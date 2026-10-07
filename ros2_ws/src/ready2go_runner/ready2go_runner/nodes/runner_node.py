"""Runner 노드 (#10) — 태스크 실행기를 ROS 에 연결한다 (docs/interfaces.md 5장, docs/runner.md).

- 시작: 스키마(contracts/)·온톨로지(knowledge/, 초기 상태 포함)·실행 이력 저장(MongoDB → JSONL 폴백) 준비
- 원자 동작: core/backend.RosBackend + adapters/ros_clients → /skills/*, /voice/speak, /vision/inspect_region
  (BACKEND 가 mock·real·sim 어느 쪽이든 같은 이름이므로 이 노드는 그대로)
- 발행: /runner/status (phase·현재 스텝·마지막 결과), /robot_state (온톨로지 상태). 늦게 구독해도 마지막 값을 받음
- 서비스: /runner/estop (std_srvs/Trigger) → Runner.halt(). 재개(resume) 통로는 ICD 에 없어 E 합의 후 추가
  /runner/reset_state (std_srvs/Trigger) → 온톨로지 상태를 시작 상태로 (#23·#107). 사람이 물품·서랍·그리퍼
  원위치를 확인한 뒤 부른다. 실행 중이면 거절, 중단 잠김은 풀지 않음
- 태스크 실행: /voice/intent (#17, core/intent_router) — trigger.intent 가 맞는 태스크를 inputs.target = targets[0] 로.
  cancel → halt(), status → 상태 다시 발행, 모호·미지원·저신뢰·미등록 물품은 보류, 실행 중·잠김이면 거절.
  시험용으로 task_file 파라미터를 주면 시작할 때 한 번 실행

Runner.run() 은 블로킹이므로 작업 스레드에서 돌리고, 노드는 MultiThreadedExecutor 가 돌린다
(실행 중에도 /runner/estop·액션 응답을 처리).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger

from ready2go_knowledge.core import ontology

from ..adapters.ros_clients import RosClients
from ..core.backend import RosBackend, skill_servers
from ..core import intent_router
from ..core.interpreter import RunResult, Runner
from ..core.log_records import utc_iso
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
        intent_schema_file = param("intent_schema_file", "/contracts/intent.schema.json")
        tasks_dir = param("tasks_dir", "/tasks")
        intent_tasks = param("intent_tasks", "")   # 인텐트=태스크파일 (trigger 대신, 예: 시연 find_item=/tasks/p1_demo_eraser.json)
        min_confidence = param("min_confidence", 0.6)   # [추정, E 확정 필요] E 음성 노드 임계값과 같게

        with open(schema_file, encoding="utf-8") as f:
            schema = json.load(f)
        onto = ontology.load(ontology_file)
        self.log_store = _make_log_store(log_dir, self.get_logger())
        self.runner = Runner(None, schema=schema, ontology=onto, log_store=self.log_store)
        self.ros_clients = RosClients(self, stopping=lambda: self.runner.stop_requested)
        self.runner.on_halt = self.ros_clients.cancel_all   # /runner/estop → 진행 중인 goal 즉시 취소
        self.runner.execute = RosBackend(self.ros_clients.call_action, self.ros_clients.call_service,
                                         lambda: self.runner.state, onto.get("world", {}))
        tasks = _load_tasks(tasks_dir, intent_tasks)
        with open(intent_schema_file, encoding="utf-8") as f:
            self.intents = intent_router.IntentRouter(json.load(f), tasks, onto.get("world", {}).get("items", {}),
                                                      min_confidence)

        group = ReentrantCallbackGroup()
        self.status_pub = self.create_publisher(String, "/runner/status", LATCHED)
        self.state_pub = self.create_publisher(String, "/robot_state", LATCHED)
        self.create_service(Trigger, "/runner/estop", self._estop, callback_group=group)
        self.create_service(Trigger, "/runner/reset_state", self._reset_state, callback_group=group)
        self.create_subscription(String, "/voice/intent", self._on_intent, 10, callback_group=group)
        self.create_timer(PUBLISH_PERIOD_SEC, self.publish, callback_group=group)

        self._lock = threading.Lock()
        self._busy = False                      # 실행 중 (스레드 생존과 별개: 끝난 직후 발행할 때 이미 False)
        self._task_id: str | None = None
        self._last: RunResult | None = None
        self._state_reset_at: str | None = None   # 마지막 /runner/reset_state 시각 (UTC)
        self._last_task_id: str | None = None
        self._last_intent: dict | None = None   # 마지막으로 받은 인텐트와 처리 결과 (시연 화면 #59)
        self._sent = {"status": None, "state": None}
        self.get_logger().info(f"Runner 준비: 스키마 {schema_file}, 온톨로지 {ontology_file}, "
                               f"백엔드 {os.environ.get('BACKEND', 'mock')}, 예비 기록 {log_dir}, "
                               f"인텐트 {({k: v.get('task_id') for k, v in tasks.items()})}")
        self.publish()
        if task_file:
            with open(task_file, encoding="utf-8") as f:
                task = json.load(f)
            self._ready_timer = self.create_timer(1.0, lambda: self._start_when_ready(task), callback_group=group)

    def missing_servers(self, task: dict) -> list[str]:
        """태스크가 쓸 /skills/* 서버 중 아직 안 뜬 것."""
        return self.ros_clients.missing_actions(skill_servers(task, self.runner.skills))

    def _start_when_ready(self, task: dict) -> None:
        """RUNNER_TASK_FILE(시험용): 스킬 서버가 다 뜬 뒤 한 번 실행 (real 은 드라이버·스킬 서버가 늦게 뜸, #108)."""
        missing = self.missing_servers(task)
        if missing:
            self.get_logger().info(f"task_file: 스킬 서버 기다리는 중 {missing}", throttle_duration_sec=5.0)
            return
        self._ready_timer.cancel()
        self.start_task(task)

    @property
    def running(self) -> bool:
        return self._busy

    def start_task(self, task: dict, inputs: dict | None = None, meta: dict | None = None) -> bool:
        """작업 스레드에서 태스크 실행. 이미 실행 중이면 거절(False). 중단 잠김 상태면 Runner 가 ABORTED 로 거절.
        meta: 실행 기록 헤더에 덧붙일 값 (음성 인텐트 원문 등)."""
        with self._lock:
            if self.running:
                self.get_logger().warning(f"실행 중이라 거절: {task.get('task_id')}")
                return False
            self._busy, self._task_id = True, task.get("task_id")
            threading.Thread(target=self._run, args=(task, inputs, meta), daemon=True).start()
        return True

    def _run(self, task: dict, inputs: dict | None, meta: dict | None) -> None:
        self.get_logger().info(f"태스크 시작: {self._task_id}")
        try:
            result = self.runner.run(task, inputs, meta={**(meta or {}), "backend": os.environ.get("BACKEND", "mock")})
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

    def _on_intent(self, msg: String) -> None:
        """/voice/intent (#17). 판단은 core/intent_router, 여기서는 실행·정지·발행만."""
        decision = self.intents.decide(msg.data, running=self.running, locked=self.runner.halted)
        missing = self.missing_servers(decision.task) if decision.kind == intent_router.RUN else []
        if missing:                             # 기동 직후 스킬 서버가 아직 없음 → 움직이기 전에 거절 (#108 D P1)
            self.get_logger().warning(f"스킬 서버 준비 전이라 거절: {missing}")
            decision = intent_router.Decision(intent_router.REJECT, intent_router.NOT_READY, intent=decision.intent)
        elif decision.kind == intent_router.RUN and not self.start_task(
                decision.task, decision.inputs, {"intent": decision.intent}):
            decision = intent_router.Decision(intent_router.REJECT, intent_router.BUSY, intent=decision.intent)
        if decision.kind == intent_router.CANCEL and decision.reason is None:
            self.runner.halt()                  # /runner/estop 과 같음: 진행 중 goal 취소, 사람 확인 전 새 태스크 거절
        self._last_intent = decision.summary()
        text = f"/voice/intent: {self._last_intent}"
        if decision.kind in (intent_router.RUN, intent_router.STATUS):
            self.get_logger().info(text)
        elif decision.kind == intent_router.CANCEL:
            self.get_logger().error(text + (" → 중단. 사람이 상태를 확인한 뒤 재개해야 합니다"
                                            if decision.reason is None else ""))
        else:
            self.get_logger().warning(text)
        if decision.kind == intent_router.STATUS:
            self._sent["status"] = None         # 바뀐 것이 없어도 다시 발행 ("지금 뭐 해?")
        self.publish()

    def _estop(self, request, response):
        self.runner.halt()                      # on_halt → 진행 중인 goal 에 취소 요청
        self.get_logger().error("/runner/estop: 중단. 사람이 상태를 확인한 뒤 재개해야 합니다")
        response.success = True
        response.message = "halted: 진행 중 동작 취소는 백엔드 책임, 재개 전까지 새 태스크 거절"
        self.publish()
        return response

    def _reset_state(self, request, response):
        """/runner/reset_state: 사람이 원위치를 확인한 뒤 상태를 시작 상태로. 실행 중이면 거절 (start_task 와 같은 잠금)."""
        with self._lock:
            if self.running:
                response.success = False
                response.message = f"실행 중({self._task_id}) — 끝난 뒤 원위치 확인 후 다시 요청"
                self.get_logger().warning(f"/runner/reset_state: 거절 — {response.message}")
                return response
            self.runner.reset_state()
            self._state_reset_at = utc_iso()
        locked = self.runner.halted
        response.success = True
        response.message = "상태를 시작 상태로 되돌림" + (" (중단 잠김은 그대로 — 재개는 별도)" if locked else "")
        self.get_logger().info(f"/runner/reset_state: {response.message}")
        self.publish()
        return response

    def status(self) -> dict:
        degraded = getattr(self.log_store, "degraded", False)
        status = build_status(self.running, self.runner.halted, self.runner.halt_code, self._task_id,
                              self.runner.current_step, self._last, self._last_task_id, degraded)
        status["last_intent"] = self._last_intent
        status["state_reset_at"] = self._state_reset_at   # 마지막 상태 초기화 시각 (UTC, 없으면 null)
        return status

    def publish(self) -> None:
        """바뀐 경우에만 발행 (늦게 구독한 쪽은 TRANSIENT_LOCAL 로 마지막 값을 받음)."""
        for key, pub, value in (("status", self.status_pub, self.status()),
                                ("state", self.state_pub, self.runner.state)):
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if text != self._sent[key]:
                pub.publish(String(data=text))
                self._sent[key] = text


def _load_tasks(tasks_dir: str, intent_tasks: str) -> dict[str, dict]:
    """인텐트 → 태스크. tasks_dir 의 trigger.intent, intent_tasks 로 지정한 파일이 우선."""
    def read(path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    tasks = [read(p) for p in sorted(Path(tasks_dir).glob("*.json"))] if Path(tasks_dir).is_dir() else []
    overrides = {name: read(path) for name, path in intent_router.parse_overrides(intent_tasks).items()}
    return intent_router.tasks_by_intent(tasks, overrides)


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
