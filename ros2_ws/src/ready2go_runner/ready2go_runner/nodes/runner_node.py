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
from ..core import intent_router, planner, step_console
from ..core.start_gate import BUSY as GATE_BUSY, CANCELED_BEFORE_START, STARTED, StartGate
from ..core.interpreter import RunResult, Runner
from ..core.log_records import new_run_id, utc_iso
from ..core.request_memory import RequestMemory
from ..core.logstore import FallbackLogStore, JsonlLogStore, MongoLogStore
from ..core.runner_status import build_status

PUBLISH_PERIOD_SEC = 0.5                # 상태가 바뀌었는지 확인하는 주기 (바뀐 경우에만 발행)
BOOT_MISMATCH = "BOOT_MISMATCH"         # 계약 W3: 다른 Runner 기동(boot_id)에 대한 제어 인텐트
NOTHING_TO_END = "NOTHING_TO_END"       # end_task 대상(그 run_id 의 실행·보존 작업)이 없음
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
        # 플래너 계획 스텝 제한 시간 (스킬=초). [팀 확정 필요] tasks/find_item.json 과 같은 값 (#150)
        self.plan_timeouts = _parse_timeouts(param(
            "plan_timeouts", "open_drawer=60,close_drawer=60,pick=70,place=60,move_to_named_pose=60"))
        # 플래너 지원 범위 (스킬.파라미터=값|값). 기본 = 현재 실물 [문서: B skill_server.py 10/08, 팀 확정 필요]:
        # 서랍 drawer_top 만(drawer_bottom 교시 전), 집기는 서랍에서만, 놓기는 handover_zone 만. 빈 문자열 = 제한 없음(mock)
        self.plan_limits = planner.parse_limits(param(
            "plan_limits", "open_drawer.drawer_id=drawer_top,close_drawer.drawer_id=drawer_top,"
                           "pick.from=drawer_top,place.to=handover_zone"))

        with open(schema_file, encoding="utf-8") as f:
            schema = json.load(f)
        onto = ontology.load(ontology_file)
        self.onto = onto                        # 플래너가 스킬 pre·effect·world 를 씀 (#150)
        self.log_store = _make_log_store(log_dir, self.get_logger())
        self.runner = Runner(None, schema=schema, ontology=onto, log_store=self.log_store)
        self.ros_clients = RosClients(self, stopping=lambda: self.runner.stop_requested)
        self.runner.on_halt = self.ros_clients.cancel_all   # /runner/estop → 진행 중인 goal 즉시 취소
        self.runner.on_step = self._on_step                  # 스텝 진행 콘솔 (#98)
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
        self.gate = StartGate()                 # 실행 중 여부 + "멈춰"와 시작이 엇갈리지 않게 (#187)
        self._refused: str | None = None        # 마지막 시작 거절 이유 (BUSY / CANCELED_BEFORE_START)
        self._task_id: str | None = None
        self._last: RunResult | None = None
        self._state_reset_at: str | None = None   # 마지막 /runner/reset_state 시각 (UTC)
        self._last_task_id: str | None = None
        self._last_intent: dict | None = None   # 마지막으로 받은 인텐트와 처리 결과 (시연 화면 #59)
        self._sent = {"status": None, "state": None}
        self._seq = 0                           # /runner/status 발행 번호 (같은 boot_id 안에서 +1, 큰 것이 최신 — 계약 W4)
        # 발행 잠금: 상태를 만들고 보내는 동안, 그리고 결정을 last_intent 에 넣고 보내는 동안 다른 콜백(status·cancel·주기 발행)이
        # 끼어들지 않게 — 각 요청 자신의 결정이 적어도 한 번 발행됨 (#249 E 리뷰). 짧게만 잡음 (정지 경로가 기다리지 않게)
        self._pub_lock = threading.RLock()
        self._end_requested: str | None = None   # end_task 로 정지를 요청한 run_id (끝난 뒤 보존됐으면 폐기)
        self.requests = RequestMemory()          # 계약07: 이번 기동 동안 request_id → 첫 결정 (재기동하면 빔)
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
        return self.gate.busy

    def start_task(self, task: dict, inputs: dict | None = None, meta: dict | None = None,
                   token: int | None = None, run_id: str | None = None) -> bool:
        """작업 스레드에서 태스크 실행. 이미 실행 중이면 거절(False). 중단 잠김 상태면 Runner 가 ABORTED 로 거절.
        meta: 실행 기록 헤더에 덧붙일 값 (음성 인텐트 원문 등). token: 인텐트를 받은 순간의 gate.token() —
        그 뒤로 "멈춰"가 왔으면 시작하지 않음 (#187). run_id: 수락할 때 정한 실행 ID (계약07)."""
        with self._lock:
            outcome = self.gate.try_start(token)
            if outcome != STARTED:
                self._refused = outcome
                self.get_logger().warning(f"{'실행 중' if outcome == GATE_BUSY else '시작 전 멈춤 요청'}이라 거절: "
                                          f"{task.get('task_id')}")
                return False
            self._task_id = task.get("task_id")
            threading.Thread(target=self._run, args=(task, inputs, meta, run_id), daemon=True).start()
        return True

    def _run(self, task: dict, inputs: dict | None, meta: dict | None, run_id: str | None = None) -> None:
        self.get_logger().info(f"태스크 시작: {self._task_id}")
        try:
            result = self.runner.run(task, inputs, meta={**(meta or {}), "backend": os.environ.get("BACKEND", "mock")},
                                     run_id=run_id)
        finally:
            self.gate.finish()
        self._last, self._last_task_id = result, self._task_id
        if self._end_requested == result.run_id:     # end_task 로 멈춘 실행이 보존됐으면 폐기 (재개 모드일 때)
            self._end_requested = None
            suspended = self.runner.suspended
            if suspended and suspended["run_id"] == result.run_id:
                self._last = self.runner.discard_suspended() or result
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

    def _on_step(self, event: str, record: dict, info: dict) -> None:
        """스텝 시작·끝 한 줄 (#98). 문구는 run_report 와 같음. 콘솔은 보기용 — 저장 확인은 run_id 로 DB 조회."""
        if event == "start":
            line = step_console.start_line(info["run_id"], record, info["finally"], info.get("params"))
            if line:
                self.get_logger().info(line)
            return
        level, line = step_console.end_line(info["run_id"], record, info["finally"])
        # rclpy 는 같은 호출 위치에서 로그 등급이 바뀌면 ValueError → 등급별로 다른 줄에서 호출 (PR #74 리뷰)
        if level == step_console.INFO:
            self.get_logger().info(line)
        elif level == step_console.WARN:
            self.get_logger().warning(line)
        else:
            self.get_logger().error(line)

    def _plan(self, decision: intent_router.Decision) -> intent_router.Decision:
        """achieve_goal → 현재 상태로 플래너 (#150). 계획되면 run, 이미 만족·계획 불가면 hold (로봇 동작 없음)."""
        result = planner.plan(self.runner.state, self.onto, decision.goals, limits=self.plan_limits or None)
        lines = planner.describe(result)
        for line in lines:
            self.get_logger().info(f"[plan] {line}")
        if result.status == planner.PLANNED:
            first = decision.goals[0]
            task_id = f"plan_{first['subject']}_{first['value']}".lower()
            task = intent_router.add_accept_speak(planner.to_task(result, task_id, self.plan_timeouts), decision.inputs)
            return intent_router.Decision(intent_router.RUN, task=task, inputs=decision.inputs, intent=decision.intent,
                                          plan=lines)
        reason = intent_router.PLAN_SATISFIED if result.status == planner.SATISFIED else intent_router.UNPLANNABLE
        return intent_router.Decision(intent_router.HOLD, reason, intent=decision.intent, plan=lines)

    def _on_intent(self, msg: String) -> None:
        """/voice/intent (#17). 판단은 core/intent_router, 여기서는 실행·정지·발행만.
        계약07: request_id 가 있는 실행 요청은 이번 기동 동안 첫 결정을 기억 — 재전송·충돌은 다시 판단·실행하지 않음."""
        token = self.gate.token()               # 이 인텐트 이후 "멈춰"가 오면 시작하지 않음 (#187)
        request_id, fingerprint = self.requests.key(msg.data)
        if request_id is None:
            self._decide_intent(msg.data, token)
            return
        with self.requests.lock:
            seen = self.requests.lookup(request_id)
            if seen is None:                    # 이 요청 자신의 결정을 기억 — 공유 _last_intent 는 그 사이 동시
                summary = self._decide_intent(msg.data, token)   # status·cancel 콜백이 바꿀 수 있음 (#249 E 리뷰 P2)
                self.requests.remember(request_id, fingerprint, summary)
                return
        if seen.fingerprint == fingerprint:
            self.get_logger().info(f"/voice/intent 재전송 {request_id}: 첫 결정 그대로 다시 발행 (재실행 없음)")
        else:
            self.get_logger().warning(f"/voice/intent 충돌 {request_id}: 같은 ID 에 다른 내용 — 첫 결정 유지, 새 내용 실행 안 함")
        self._announce(seen.summary, force=True)   # 바뀐 것이 없어도 다시 발행 (E 가 결정을 다시 받게)

    def _decide_intent(self, text: str, token: int | None) -> dict:
        """판단·실행·발행. 돌려주는 값 = 이 요청의 결정 요약 (계약07 기억용)."""
        decision = self.intents.decide(text, running=self.running, locked=self.runner.halted)
        if decision.kind == intent_router.CANCEL:   # 판단·정지를 시작과 같은 잠금 안에서 (NOT_RUNNING 으로 새지 않게)
            was_running = self.gate.cancel()
            decision = intent_router.Decision(intent_router.CANCEL, None if was_running else intent_router.NOT_RUNNING,
                                              intent=decision.intent)
        if decision.kind == intent_router.END:
            decision = self._end_task(decision)
        if decision.kind == intent_router.PLAN:
            decision = self._plan(decision)
        missing = self.missing_servers(decision.task) if decision.kind == intent_router.RUN else []
        if missing:                             # 기동 직후 스킬 서버가 아직 없음 → 움직이기 전에 거절 (#108 D P1)
            self.get_logger().warning(f"스킬 서버 준비 전이라 거절: {missing}")
            decision = intent_router.Decision(intent_router.REJECT, intent_router.NOT_READY, intent=decision.intent)
        elif decision.kind == intent_router.RUN:
            decision.run_id = new_run_id()      # 계약07: 수락할 때 정하고 바꾸지 않음 (빠른 완료에도 같은 값)
            if not self.start_task(decision.task, decision.inputs,
                                   {"intent": decision.intent, **({"plan": decision.plan} if decision.plan else {})},
                                   token, run_id=decision.run_id):
                reason = (intent_router.STOPPED_BEFORE_START if self._refused == CANCELED_BEFORE_START
                          else intent_router.BUSY)
                decision = intent_router.Decision(intent_router.REJECT, reason, intent=decision.intent)
        if decision.kind == intent_router.CANCEL and decision.reason is None:
            self.runner.halt(source="voice")    # /runner/estop 과 같음: 진행 중 goal 취소, 사람 확인 전 새 태스크 거절
        summary = decision.summary()
        text = f"/voice/intent: {summary}"
        if decision.kind in (intent_router.RUN, intent_router.STATUS):
            self.get_logger().info(text)
        elif decision.kind == intent_router.CANCEL:
            self.get_logger().error(text + (" → 중단. 사람이 상태를 확인한 뒤 재개해야 합니다"
                                            if decision.reason is None else ""))
        else:
            self.get_logger().warning(text)
        self._announce(summary, force=decision.kind == intent_router.STATUS)   # status: 바뀐 것이 없어도 ("지금 뭐 해?")
        return summary

    def _end_task(self, decision: intent_router.Decision) -> intent_router.Decision:
        """계약 W3 end_task (#152·#271, E3): 같은 기동·지금 작업일 때만. 실행 중이면 cancel 과 같은 정지(정지 확인은
        halt.stop) → 끝난 뒤 보존됐으면 폐기, 이미 보존(재개 대기) 중이면 바로 폐기(ABORTED, finally 비동작만).
        잠금은 풀지 않고 새 작업도 허용하지 않는다. 대상이 없으면 NOTHING_TO_END, 다른 기동이면 BOOT_MISMATCH."""
        intent = decision.intent or {}
        if intent.get("boot_id") != self.runner.boot_id:
            return intent_router.Decision(intent_router.REJECT, BOOT_MISMATCH, intent=intent)
        target = intent.get("run_id")
        suspended = self.runner.suspended
        with self._lock:
            running = self.running and self.runner.active_run_id == target
            if running:
                self._end_requested = target
                self.gate.cancel()
        if running:
            self.runner.halt(source="voice")     # cancel 과 같은 경로: 진행 중 goal 취소, 잠금
            return intent_router.Decision(intent_router.END, intent=intent)
        if suspended and suspended["run_id"] == target:
            result = self.runner.discard_suspended()
            if result is not None:
                self._last, self._last_task_id = result, suspended["task_id"]
            return intent_router.Decision(intent_router.END, intent=intent)
        return intent_router.Decision(intent_router.REJECT, NOTHING_TO_END, intent=intent)

    def _announce(self, summary: dict, force: bool = False) -> None:
        """이 결정을 last_intent 에 넣고 바로 발행 — 사이에 다른 콜백이 last_intent 를 바꿔 이 결정이 안 나가는 일 없게."""
        with self._pub_lock:
            self._last_intent = summary
            if force:
                self._sent["status"] = None
            self.publish()

    def _estop(self, request, response):
        self.runner.halt(source="service")      # on_halt → 진행 중인 goal 에 취소 요청
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
                              self.runner.current_step, self._last, self._last_task_id, degraded,
                              halt=self.runner.halt_summary)
        status["last_intent"] = self._last_intent
        status["state_reset_at"] = self._state_reset_at   # 마지막 상태 초기화 시각 (UTC, 없으면 null)
        status["boot_id"] = self.runner.boot_id          # 계약 W4 (#271): 이 Runner 기동 — 재기동하면 새 값
        return status

    def publish(self) -> None:
        """바뀐 경우에만 발행 (늦게 구독한 쪽은 TRANSIENT_LOCAL 로 마지막 값을 받음). 만들기·보내기를 한 잠금 안에서 —
        주기 발행이 앞서 만든 옛 상태를 새 결정 뒤에 보내 덮지 않게."""
        with self._pub_lock:
            for key, pub, value in (("status", self.status_pub, self.status()),
                                    ("state", self.state_pub, self.runner.state)):
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
                if text != self._sent[key]:
                    out = text
                    if key == "status":         # 계약 W4: 바뀐 내용을 보낼 때만 seq +1·stamp (비교에는 넣지 않음 — 주기 발행이 매번 새 값이 되지 않게)
                        self._seq += 1
                        out = json.dumps({**value, "seq": self._seq, "stamp": utc_iso()}, ensure_ascii=False, sort_keys=True)
                    pub.publish(String(data=out))
                    self._sent[key] = text


def _parse_timeouts(text: str) -> dict[str, float]:
    """"pick=60,place=60" → {"pick": 60.0, ...} (플래너 계획 스텝 timeout_sec)."""
    result = {}
    for entry in filter(None, (part.strip() for part in text.split(","))):
        name, _, value = entry.partition("=")
        result[name.strip()] = float(value)
    return result


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
