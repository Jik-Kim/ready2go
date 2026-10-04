"""Runner 노드 (#10) — 태스크 실행기를 ROS 에 연결한다 (docs/interfaces.md 5장, docs/runner.md).

- 시작: 스키마(contracts/)·온톨로지(knowledge/, 초기 상태 포함)·실행 이력 저장(MongoDB → JSONL 폴백) 준비
- 원자 동작: core/backend.RosBackend + adapters/ros_clients → /skills/*, /voice/speak, /vision/inspect_region
  (BACKEND 가 mock·real·sim 어느 쪽이든 같은 이름이므로 이 노드는 그대로)
- 발행: /runner/status (phase·현재 스텝·마지막 결과), /robot_state (온톨로지 상태). 늦게 구독해도 마지막 값을 받음
- 서비스: /runner/estop (std_srvs/Trigger) → Runner.halt(). 재개(resume) 통로는 ICD 에 없어 E 합의 후 추가
- 태스크 실행: 정식 통로는 /voice/intent (#17). 지금은 시험용으로 task_file 파라미터를 주면 시작할 때 한 번 실행

Runner.run() 은 블로킹이므로 작업 스레드에서 돌리고, 노드는 MultiThreadedExecutor 가 돌린다
(실행 중에도 /runner/estop·액션 응답을 처리).
"""
from __future__ import annotations

import json
import os
import threading

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger

from ready2go_knowledge.core import ontology

from ..adapters.ros_clients import RosClients
from ..core.backend import RosBackend
from ..core.interpreter import RunResult, Runner
from ..core.logstore import FallbackLogStore, JsonlLogStore, MongoLogStore
from ..core.runner_status import build_status

PUBLISH_PERIOD_SEC = 0.5                # 상태가 바뀌었는지 확인하는 주기 (바뀐 경우에만 발행)
LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)


class RunnerNode(Node):
    def __init__(self, **node_kwargs):
        super().__init__("runner", **node_kwargs)
        param = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        schema_file = param("schema_file", "/contracts/task.schema.json")
        ontology_file = param("ontology_file", "/knowledge/robot_ontology.jsonld")
        log_dir = param("log_dir", "/logs")
        task_file = param("task_file", "")

        with open(schema_file, encoding="utf-8") as f:
            schema = json.load(f)
        onto = ontology.load(ontology_file)
        self.log_store = _make_log_store(log_dir, self.get_logger())
        self.runner = Runner(None, schema=schema, ontology=onto, log_store=self.log_store)
        self.ros_clients = RosClients(self, stopping=lambda: self.runner.halted)
        self.runner.on_halt = self.ros_clients.cancel_all   # /runner/estop → 진행 중인 goal 즉시 취소
        self.runner.execute = RosBackend(self.ros_clients.call_action, self.ros_clients.call_service,
                                         lambda: self.runner.state, onto.get("world", {}))

        group = ReentrantCallbackGroup()
        self.status_pub = self.create_publisher(String, "/runner/status", LATCHED)
        self.state_pub = self.create_publisher(String, "/robot_state", LATCHED)
        self.create_service(Trigger, "/runner/estop", self._estop, callback_group=group)
        self.create_timer(PUBLISH_PERIOD_SEC, self.publish, callback_group=group)

        self._lock = threading.Lock()
        self._busy = False                      # 실행 중 (스레드 생존과 별개: 끝난 직후 발행할 때 이미 False)
        self._task_id: str | None = None
        self._last: RunResult | None = None
        self._last_task_id: str | None = None
        self._sent = {"status": None, "state": None}
        self.get_logger().info(f"Runner 준비: 스키마 {schema_file}, 온톨로지 {ontology_file}, "
                               f"백엔드 {os.environ.get('BACKEND', 'mock')}, 예비 기록 {log_dir}")
        self.publish()
        if task_file:
            with open(task_file, encoding="utf-8") as f:
                self.start_task(json.load(f))

    @property
    def running(self) -> bool:
        return self._busy

    def start_task(self, task: dict, inputs: dict | None = None) -> bool:
        """작업 스레드에서 태스크 실행. 이미 실행 중이면 거절(False). 중단 잠김 상태면 Runner 가 ABORTED 로 거절."""
        with self._lock:
            if self.running:
                self.get_logger().warning(f"실행 중이라 거절: {task.get('task_id')}")
                return False
            self._busy, self._task_id = True, task.get("task_id")
            threading.Thread(target=self._run, args=(task, inputs), daemon=True).start()
        return True

    def _run(self, task: dict, inputs: dict | None) -> None:
        self.get_logger().info(f"태스크 시작: {self._task_id}")
        try:
            result = self.runner.run(task, inputs, meta={"backend": os.environ.get("BACKEND", "mock")})
        finally:
            self._busy = False
        self._last, self._last_task_id = result, self._task_id
        message = (f"태스크 끝: {self._task_id} → {result.overall_status}"
                   + (f" ({result.error_code} @ {result.failed_step})" if result.error_code else "")
                   + (f" 거절 이유: {result.problems}" if result.problems else "")
                   + f" run_id={result.run_id}")
        # rclpy 는 같은 호출 위치에서 로그 등급이 바뀌면 ValueError → 등급별로 다른 줄에서 호출 (PR #74 리뷰)
        if result.overall_status == "COMPLETED":
            self.get_logger().info(message)
        else:
            self.get_logger().warning(message)
        self.publish()

    def _estop(self, request, response):
        self.runner.halt()                      # on_halt → 진행 중인 goal 에 취소 요청
        self.get_logger().error("/runner/estop: 중단. 사람이 상태를 확인한 뒤 재개해야 합니다")
        response.success = True
        response.message = "halted: 진행 중 동작 취소는 백엔드 책임, 재개 전까지 새 태스크 거절"
        self.publish()
        return response

    def status(self) -> dict:
        degraded = getattr(self.log_store, "degraded", False)
        return build_status(self.running, self.runner.halted, self.runner.halt_code, self._task_id,
                            self.runner.current_step, self._last, self._last_task_id, degraded)

    def publish(self) -> None:
        """바뀐 경우에만 발행 (늦게 구독한 쪽은 TRANSIENT_LOCAL 로 마지막 값을 받음)."""
        for key, pub, value in (("status", self.status_pub, self.status()),
                                ("state", self.state_pub, self.runner.state)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if text != self._sent[key]:
                pub.publish(String(data=text))
                self._sent[key] = text


def _make_log_store(log_dir: str, logger):
    """MongoDB(cobot2) → 실패 시 JSONL. pymongo 가 없으면 JSONL 만 (NFR-DB-01)."""
    try:
        return FallbackLogStore(MongoLogStore(), JsonlLogStore(log_dir))
    except ImportError:
        logger.warning(f"pymongo 없음 → 실행 기록은 {log_dir} JSONL 에만 저장")
        return JsonlLogStore(log_dir)


def main():
    rclpy.init()
    node = RunnerNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
