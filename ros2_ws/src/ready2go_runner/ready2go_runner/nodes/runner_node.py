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
import time
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
from ..core import intent_router, plan_exec, planner, step_console
from ..core.start_gate import BUSY as GATE_BUSY, CANCELED_BEFORE_START, STARTED, StartGate
from ..core.interpreter import NOTHING_TO_RESUME, ResumeRejected, RunResult, Runner
from ..core.log_records import new_run_id, run_document, utc_iso
from ..core.recovery import MOCK_LIMITS, choose_check, load_limits as load_recovery_limits, mock_check, parse_check, recover_blockers
from ..core.request_memory import RequestMemory
from ..core.resume_admission import ResumeAdmission, load_limits
from ..core.logstore import FallbackLogStore, JsonlLogStore, MongoLogStore
from ..core.runner_status import build_status

PUBLISH_PERIOD_SEC = 0.5                # 상태가 바뀌었는지 확인하는 주기 (바뀐 경우에만 발행)
BOOT_MISMATCH = "BOOT_MISMATCH"         # 계약 W3: 다른 Runner 기동(boot_id)에 대한 제어 인텐트
NOTHING_TO_END = "NOTHING_TO_END"       # end_task 대상(그 run_id 의 실행·보존 작업)이 없음
STOP_NOT_CONFIRMED = "STOP_NOT_CONFIRMED"   # 보존 작업의 정지 확인이 없음(halt.stop unconfirmed) → 폐기 보류, 작업·잠금 유지
NOT_LOCKED = "NOT_LOCKED"               # recover 인데 이미 잠겨 있지 않음
HALT_EVENT_MISMATCH = "HALT_EVENT_MISMATCH"   # 지금 정지 사건이 아님 (과거·지연 요청, 그 뒤 다시 멈춤)
STOPPED_DURING_RECOVER = "STOPPED_DURING_RECOVER"   # recover 의 B 조회를 기다리는 사이 새 정지 요청 → 잠금 유지
B_RECOVER_UNAVAILABLE = "B_RECOVER_UNAVAILABLE"   # B 복구(W2) 서비스 없음·응답 없음 → 잠금 유지
B_RECOVER_FAILED = "B_RECOVER_FAILED"           # B 복구가 recovered=false 인데 code 를 안 줌
RUN_MISMATCH = "RUN_MISMATCH"           # 재개 인텐트의 run_id 가 보존 작업과 다름 (#271 D 리뷰)
REGISTERED, CLOSED = "registered", "closed"   # 재개 결정: 질문·독립 요청 등록 확인 / 질문만 닫음(작업 보존)
LATCHED = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)


class RunnerNode(Node):
    # 최근 수락(run)한 요청 {request_id, run_id, task_id} — last_intent 는 BUSY·status·cancel 결정으로 덮이므로 따로 (#376 E).
    # 클래스 기본값: __init__ 없이 만든 객체(E 음성 연결 시험의 가짜 Runner)도 지금처럼
    _accepted: dict | None = None
    # 묶음 계획(#302 2안) 칸의 클래스 기본값 — __init__ 을 거치지 않고 만든 객체(E 음성 연결 시험의 가짜 Runner)도 지금처럼 동작
    plan_composites = False
    tasks_dir = "/tasks"
    _chain_run: str | None = None
    _chain_parent: dict | None = None
    _chain_events: dict | None = None

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
        # 재개 대기(#152): 켜면 정지된 작업을 버리지 않고 보존 → recover·resume·end_task 로 처리. 기본 꺼짐(지금 동작 그대로)
        resumable = param("resumable", os.environ.get("RUNNER_RESUMABLE", "") in ("1", "true", "on"))
        # 복구 때 B 상태 조회(W1): b = B /skills/check_state (#297 제안, real·sim 기본), mock = mock 백엔드 흉내(mock 백엔드에서만),
        # none = 조회 불가 → 복구 거절. B 서비스가 없거나 응답이 없으면 조회 불가로 거절
        backend = os.environ.get("BACKEND", "mock")
        self.recover_check, warning = choose_check(param("recover_check", "mock" if backend == "mock" else "b"), backend)
        if warning:
            self.get_logger().error(warning)
        self.b_timeout_s = param("b_check_timeout_s", 2.0)   # B 조회·복구 서비스 응답 대기 [팀 확정 필요]
        # recover 때 B 복구(W2 /skills/recover)를 먼저 부를지 — B 답 10/13 "C 가 recover 처리 중 호출"(C 제안과 같음). 기본 켜짐,
        # RUNNER_RECOVER_CALL_B=0 이면 끔. recover_check 가 b 일 때만 (mock·none 은 B 서비스를 안 부름)
        self.recover_call_b = param("recover_call_b",
                                    os.environ.get("RUNNER_RECOVER_CALL_B", "1") not in ("0", "false", "off"))
        # 실물 판정 기준 (params/recovery.yaml [팀 확정 필요]) — 못 읽으면 기준 없음 → 실물 복구 거절
        recovery_file = param("recovery_params_file", _param_file("ready2go_runner", "recovery.yaml"))
        try:
            self.recover_limits = load_recovery_limits(recovery_file)
        except (OSError, TypeError, ValueError) as e:
            self.recover_limits = None
            self.get_logger().warning(f"복구 기준을 못 읽음 ({recovery_file}): {e} — 실물 복구는 거절")
        # 재개 기한: C 값(이 패키지 params/resume.yaml [팀 확정 필요]) + E 증빙 상한(voice.yaml 원본). 못 읽으면 재개 인텐트 보류
        resume_file = param("resume_params_file", _param_file("ready2go_runner", "resume.yaml"))
        voice_file = param("voice_params_file", _param_file("ready2go_voice", "voice.yaml"))
        try:
            resume_limits = load_limits(resume_file, voice_file)
        except (OSError, KeyError, TypeError, ValueError) as e:
            resume_limits = None
            self.get_logger().warning(f"재개 기한을 못 읽음 ({resume_file}, {voice_file}): {e} — 재개 인텐트는 보류")
        min_confidence = param("min_confidence", 0.6)   # [추정, E 확정 필요] E 음성 노드 임계값과 같게
        # 플래너 계획 스텝 제한 시간 (스킬=초). [팀 확정 필요] tasks/find_item.json 과 같은 값 (#150)
        self.plan_timeouts = _parse_timeouts(param(
            "plan_timeouts", "open_drawer=60,close_drawer=60,pick=70,place=60,move_to_named_pose=60"))
        # 플래너 지원 범위 (스킬.파라미터=값|값). 기본 = P2 실물 범위 planner.DEFAULT_PLAN_LIMITS [B 확인 필요]:
        # 서랍 위·아래 칸(한 번에 하나만), 집기는 서랍에서만, 놓기는 handover_zone 만. 빈 문자열 = 제한 없음(mock)
        # RUNNER_PLAN_LIMITS 로 바꿀 수 있음 (예: 위 칸만 "open_drawer.drawer_id=drawer_top,...")
        self.plan_limits = planner.parse_limits(param(
            "plan_limits", os.environ.get("RUNNER_PLAN_LIMITS") or planner.DEFAULT_PLAN_LIMITS))
        # 묶음 스킬 계획 (#302 2안): plan_effect 가 있는 composite(handover_with_unpack — 안은 find_with_unpack)도 후보 → 구간 실행.
        # 온톨로지에 plan_effect 가 없으면 지금 계획 그대로. RUNNER_PLAN_COMPOSITES=0 이면 끔
        self.plan_composites = param("plan_composites",
                                     os.environ.get("RUNNER_PLAN_COMPOSITES", "1") not in ("0", "false", "off"))
        self.tasks_dir = tasks_dir
        with open(schema_file, encoding="utf-8") as f:
            schema = json.load(f)
        onto = ontology.load(ontology_file)
        self.onto = onto                        # 플래너가 스킬 pre·effect·world 를 씀 (#150)
        self.log_store = _make_log_store(log_dir, self.get_logger())
        self.runner = Runner(None, schema=schema, ontology=onto, log_store=self.log_store, resumable=resumable,
                             **({"resume_window_sec": resume_limits["question_offer_sec"]} if resume_limits else {}))
        if resume_limits:
            self.runner.admission = ResumeAdmission(self.runner.clock, resume_limits)
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
        self.b_check_client = self.create_client(Trigger, "/skills/check_state", callback_group=group)   # W1 (#297)
        self.b_recover_client = self.create_client(Trigger, "/skills/recover", callback_group=group)    # W2 (#297)
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
        # 묶음 계획 구간 실행 (#302 C 설계·E 동의): 요청 하나 = 상위 run_id 하나. 구간(child) run_id → 상위, 정지 사건 → 상위
        self._chain_run: str | None = None       # 지금 구간 실행 중인 상위 run_id (없으면 None)
        self._chain_parent: dict[str, str] = {}  # child run_id → 상위 run_id (halt.run_id 를 상위로 내보냄)
        self._chain_events: dict[str, str] = {}  # 묶음 중 생긴 정지 사건 event_id → 상위 run_id (구간 사이 정지)
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
            if self._end_requested == result.run_id:     # end_task 로 멈춘 실행이 보존됐으면 폐기 (재개 모드일 때)
                self._end_requested = None              # 실행 문(gate)을 닫기 전에 — 폐기 중 새 실행이 끼지 않게
                result = self._discard_after_stop(result.run_id) or result
        finally:
            self.gate.finish()
        self._finished(result)

    def _run_resume(self, ctx) -> None:
        """재개: 최종 검사·시작 전이(Runner.begin_resume)를 통과한 보존 작업을 중단된 스텝부터 이어 실행."""
        self.get_logger().info(f"재개 시작: {self._task_id} run_id={ctx.doc['run_id']}")
        try:
            result = self.runner.continue_resumed(ctx)
        finally:
            self.gate.finish()
        self._finished(result)

    def _chain_steps(self, result: planner.PlanResult) -> list[dict]:
        """묶음 계획의 서버 확인용 스텝: 묶음은 그 태스크의 스텝(정리 포함), primitive 는 스킬 스텝."""
        steps = []
        for n, s in enumerate(result.steps, 1):
            if s.task:
                task = self._load_task(s.task)
                steps += [*task.get("sequence", []), *task.get("finally", [])]
            else:
                steps.append({"id": f"c{n}", "skill": s.skill, "params": dict(s.params)})
        return steps

    def _load_task(self, path: str) -> dict:
        """묶음 스킬 task 경로(저장소 기준 "tasks/find_with_unpack.json") → tasks_dir 의 같은 파일."""
        with open(Path(self.tasks_dir) / Path(path).name, encoding="utf-8") as f:
            return json.load(f)

    def start_plan(self, decision: intent_router.Decision, meta: dict, token: int | None = None) -> bool:
        """묶음 계획을 작업 스레드에서 구간 실행. 시작 규칙은 start_task 와 같음 (실행 중·시작 전 멈춤이면 거절)."""
        with self._lock:
            outcome = self.gate.try_start(token)
            if outcome != STARTED:
                self._refused = outcome
                self.get_logger().warning(f"{'실행 중' if outcome == GATE_BUSY else '시작 전 멈춤 요청'}이라 거절: "
                                          f"{decision.task.get('task_id')}")
                return False
            self._task_id, self._chain_run = decision.task.get("task_id"), decision.run_id
            threading.Thread(target=self._run_plan, args=(decision, meta), daemon=True).start()
        return True

    def _run_plan(self, decision: intent_router.Decision, meta: dict) -> None:
        """상위 run_id R 하나로 구간 실행 (#302 C 설계·E 동의): 구간 사이에도 phase running(gate), 구간 run 은 R.1, R.2 …
        (parent_run_id R) 로 따로 기록, 상위 문서 R 에 구간 목록·결과. 끝에 last 를 R 로 한 번."""
        run_id, task_id = decision.run_id, self._task_id
        extra = {**meta, "backend": os.environ.get("BACKEND", "mock"), "plan_chain": True}
        inputs = {**decision.inputs, "goals": decision.goals}
        started, t0 = utc_iso(), time.monotonic()
        self.get_logger().info(f"묶음 계획 시작: {task_id} run_id={run_id}")
        self._log_run("start_run", run_document(run_id, task_id, inputs, started, extra=extra))
        out = plan_exec.PlanRun("FAILED", "INTERNAL_ERROR", reason="구간 실행 예외")
        try:
            out = plan_exec.run_plan(self.runner, self.onto, decision.goals, self._load_task,
                                     limits=self.plan_limits or None, timeouts=self.plan_timeouts, run_id=run_id,
                                     meta={**extra, "parent_run_id": run_id},
                                     accept_text=decision.inputs.get("accept_text"))
        except Exception as e:  # noqa: BLE001 — 예외여도 상위 R 의 끝 기록·last 를 남김 (#377 E·D 리뷰 P2)
            self.get_logger().error(f"묶음 계획 구간 실행 예외: {task_id} run_id={run_id} — {e!r}")
            out = plan_exec.PlanRun("FAILED", "INTERNAL_ERROR", reason=f"구간 실행 예외: {type(e).__name__}: {e}")
        finally:
            for seg in out.segments:
                if seg.run_id:
                    self._chain_parent[seg.run_id] = run_id
            event = self.runner.halt_event_id
            if event and self.runner.halted:
                self._chain_events.setdefault(event, run_id)
            self._chain_run = None
            self.gate.finish()
        segments = [{"run_id": s.run_id, "kind": s.kind, "skills": s.skills, "overall_status": s.overall_status,
                     "error_code": s.error_code} for s in out.segments]
        failure = self._chain_failure(out, run_id)
        self._log_run("end_run", run_document(
            run_id, task_id, inputs, started, ended_at=utc_iso(), total_duration_sec=round(time.monotonic() - t0, 3),
            overall_status=out.overall_status, error_code=out.error_code, failed_step=out.failed_step,
            extra={**extra, "segments": segments, "reason": out.reason, **({"failure": failure} if failure else {})}))
        problems = [] if out.overall_status == "COMPLETED" else [out.reason]
        self._finished(RunResult(out.overall_status, {}, error_code=out.error_code, failed_step=out.failed_step,
                                 problems=problems, run_id=run_id, failure=failure))

    def _chain_failure(self, out: plan_exec.PlanRun, run_id: str) -> dict | None:
        """묶음 계획의 last.failure (#376·#377): FAILED 일 때만. 멈춘 구간이 FAILED 면 그 구간의 처음 원인(case_id 포함)을
        상위 R 로, 구간 실패가 아닌 묶음 단위 원인(PLAN_EFFECT_UNMET·PLAN_NO_PROGRESS·UNPLANNABLE·INTERNAL_ERROR)은 그 코드만."""
        if out.overall_status != "FAILED":
            return None
        last = out.segments[-1] if out.segments else None
        if last is not None and last.overall_status == "FAILED" and last.failure:
            return {**last.failure, "run_id": run_id}
        return {"run_id": run_id, "boot_id": self.runner.boot_id, "code": out.error_code, "step": out.failed_step,
                "action": None, "case_id": None, "strategy": None, "text": None}

    def _log_run(self, method: str, doc: dict) -> None:
        """상위 문서 기록 — 실패해도 실행·결과는 그대로 (Runner._log 와 같은 규칙)."""
        try:
            getattr(self.log_store, method)(doc)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"묶음 계획 기록 실패({method}): {e}")

    def _finished(self, result: RunResult) -> None:
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
        result = planner.plan(self.runner.state, self.onto, decision.goals, limits=self.plan_limits or None,
                              composites=self.plan_composites)
        lines = planner.describe(result)
        for line in lines:
            self.get_logger().info(f"[plan] {line}")
        if result.status == planner.PLANNED:
            first = decision.goals[0]
            task_id = f"plan_{first['subject']}_{first['value']}".lower()
            if any(s.task for s in result.steps):   # 묶음 스킬 — 구간 실행(core/plan_exec), 상위 run_id 하나 (#302 2안)
                check = {"task_id": task_id, "sequence": self._chain_steps(result)}   # 서버 확인·표시용 (실행 안 함)
                return intent_router.Decision(intent_router.RUN, task=check, inputs=decision.inputs, intent=decision.intent,
                                              goals=decision.goals, plan=lines, chain=True)
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
        if decision.kind == intent_router.RECOVER:
            decision = self._recover(decision)
        if decision.kind == intent_router.RESUME:
            decision = self._resume(decision, token)
        if decision.kind == intent_router.PLAN:
            decision = self._plan(decision)
        missing = self.missing_servers(decision.task) if decision.kind == intent_router.RUN else []
        if missing:                             # 기동 직후 스킬 서버가 아직 없음 → 움직이기 전에 거절 (#108 D P1)
            self.get_logger().warning(f"스킬 서버 준비 전이라 거절: {missing}")
            decision = intent_router.Decision(intent_router.REJECT, intent_router.NOT_READY, intent=decision.intent)
        elif decision.kind == intent_router.RUN:
            decision.run_id = new_run_id()      # 계약07: 수락할 때 정하고 바꾸지 않음 (빠른 완료에도 같은 값)
            meta = {"intent": decision.intent, **({"plan": decision.plan} if decision.plan else {})}
            started = (self.start_plan(decision, meta, token) if decision.chain else
                       self.start_task(decision.task, decision.inputs, meta, token, run_id=decision.run_id))
            if not started:
                reason = (intent_router.STOPPED_BEFORE_START if self._refused == CANCELED_BEFORE_START
                          else intent_router.BUSY)
                decision = intent_router.Decision(intent_router.REJECT, reason, intent=decision.intent)
            else:                               # 실제로 시작한 요청만 — last.failure 가 어느 요청의 결과인지 (#376)
                self._accepted = {"request_id": (decision.intent or {}).get("request_id"), "run_id": decision.run_id,
                                  "task_id": decision.task.get("task_id")}
        if decision.kind == intent_router.CANCEL and decision.reason is None:
            self.runner.halt(source="voice")    # /runner/estop 과 같음: 진행 중 goal 취소, 사람 확인 전 새 태스크 거절
        summary = decision.summary()
        text = f"/voice/intent: {summary}"
        if decision.kind in (intent_router.RUN, intent_router.STATUS, intent_router.RESUME, REGISTERED, CLOSED):
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
        with self._lock:                         # 대상 확인·정지를 start_task 와 같은 잠금 안에서 (#285 E 리뷰)
            if self.running and self._chain_run is not None and self._chain_run == target:
                # 묶음 계획(상위 R): 진행 중인 구간을 멈추고 잠금 — 구간 사이면 잠금만, run_plan 이 다음 구간 전에 멈춤.
                # 묶음 중엔 재개 보존을 끄므로 보존·폐기 단계 없음
                self.gate.cancel()
                self.runner.halt(source="voice")
                return intent_router.Decision(intent_router.END, intent=intent)
            if self.running and self.runner.active_run_id == target:
                self._end_requested = target
                self.gate.cancel()
                # 그 run 이 지금 실행 중일 때만 멈춤 — 확인 직후 끝났으면 멈추지 않음(새 실행은 이 잠금 때문에 아직 못 시작)
                if self.runner.halt(source="voice", run_id=target):
                    return intent_router.Decision(intent_router.END, intent=intent)
                self._end_requested = None
            suspended = self.runner.suspended
            if not (suspended and suspended["run_id"] == target):
                return intent_router.Decision(intent_router.REJECT, NOTHING_TO_END, intent=intent)
            if not self.runner.stop_settled:     # 실제 정지를 모르면 폐기 보류 — 작업·잠금 유지 (#285 E 리뷰)
                return intent_router.Decision(intent_router.REJECT, STOP_NOT_CONFIRMED, intent=intent)
            if self.gate.try_start() != STARTED:  # 폐기(finally 비동작) 중 새 실행이 끼지 않게
                return intent_router.Decision(intent_router.REJECT, intent_router.BUSY, intent=intent)
        try:
            result = self.runner.discard_suspended()
        finally:
            self.gate.finish()
        if result is not None:
            self._last, self._last_task_id = result, suspended["task_id"]
        return intent_router.Decision(intent_router.END, intent=intent)

    def _discard_after_stop(self, run_id: str) -> RunResult | None:
        """end_task 로 멈춘 실행이 보존됐으면 폐기 — 정지 확인(halt.stop confirmed·none)일 때만. 아니면 작업·잠금 유지."""
        suspended = self.runner.suspended
        if not (suspended and suspended["run_id"] == run_id):
            return None
        if not self.runner.stop_settled:
            self.get_logger().error(f"end_task: {run_id} 정지 확인 없음 — 보존 작업 폐기 보류 (사람 확인 → reset_state)")
            return None
        return self.runner.discard_suspended()

    def _b_check(self) -> tuple[dict | None, dict | None]:
        """B 상태 조회(W1)와 판정 기준. mock 백엔드만 흉내 조회·시험 기준(MOCK_LIMITS), 그 밖은 조회 불가(None).
        실물 기준(힘·신선도)은 B·팀 확정 뒤 연결 — 그 전까지 None 이라 recover_blockers 가 거절."""
        if self.recover_check == "mock" and os.environ.get("BACKEND", "mock") == "mock":
            return mock_check(self.runner.state), MOCK_LIMITS
        if self.recover_check == "b":
            reply = self._call_trigger(self.b_check_client)
            return (parse_check(*reply) if reply else None), self.recover_limits
        return None, None

    def _call_trigger(self, client) -> tuple[bool, str] | None:
        """B 서비스(std_srvs/Trigger) 호출 → (success, message). 서비스 없음·시간 초과·예외 → None (호출 쪽이 거절).
        콜백 안에서 부르므로 future 를 기다림(ReentrantCallbackGroup + MultiThreadedExecutor 라 응답 콜백이 따로 돎)."""
        if not client.service_is_ready():
            return None
        done = threading.Event()
        future = client.call_async(Trigger.Request())
        future.add_done_callback(lambda _: done.set())
        if not done.wait(self.b_timeout_s):
            future.cancel()
            return None
        try:
            reply = future.result()
        except Exception:                       # noqa: BLE001 — 서비스 쪽 예외도 조회 불가로
            return None
        return (bool(reply.success), reply.message) if reply is not None else None

    def _b_recover(self) -> str | None:
        """B 복구(W2 /skills/recover, #297): 성공이면 None, 아니면 거절 이유 (B code 그대로, 없음·응답 없음은 C 코드)."""
        reply = self._call_trigger(self.b_recover_client)
        if reply is None:
            return B_RECOVER_UNAVAILABLE
        result = parse_check(True, reply[1]) or {}
        if reply[0] and result.get("recovered") is True:
            return None
        return result.get("code") or B_RECOVER_FAILED

    def _recover(self, decision: intent_router.Decision) -> intent_router.Decision:
        """계약 W3 recover (#152·#271, FR-SAF-03): 같은 기동·지금 정지 사건이고 B 상태 조회(W1)가 모두 충족일 때만
        C 잠금 해제(Runner.resume). 해제는 재개 허가가 아님 — 보존 작업이 있으면 halt.resume.offered 로 제안만.
        불충족·모름이면 잠금 유지(이유 = 첫 차단 코드, 콘솔에 전부). 로봇 동작 없음."""
        intent = decision.intent or {}
        reject = lambda reason: intent_router.Decision(intent_router.REJECT, reason, intent=intent)  # noqa: E731
        if intent.get("boot_id") != self.runner.boot_id:
            return reject(BOOT_MISMATCH)
        if not self.runner.halted:
            return reject(NOT_LOCKED)
        if intent.get("event_id") != self.runner.halt_event_id:
            return reject(HALT_EVENT_MISMATCH)
        if self.running:                       # 아직 멈추는 중 (진행 중 동작의 최종 결과 대기)
            return reject(intent_router.BUSY)
        generation = self.runner.halt_generation   # B 조회를 기다리는 사이 새 정지가 오면 해제하지 않음 (#304 E 리뷰 P1)
        if self.recover_call_b and self.recover_check == "b":   # W2 성공 뒤 W1 (계약: B 복구가 필요한 사건이면 그 성공 뒤)
            failed = self._b_recover()
            if failed:
                self.get_logger().warning(f"recover 거절 — B 복구 실패: {failed}")
                return reject(failed)
        check, limits = self._b_check()
        blockers = recover_blockers(check, self.runner.state, limits)
        if blockers:
            self.get_logger().warning(f"recover 거절 — 잠금 유지: {blockers} (B 조회 {check})")
            return reject(blockers[0])
        if not self.runner.resume_if(generation):   # 조회 중 새 정지(잠긴 채 다시 멈춤 포함) → 잠금 유지
            self.get_logger().warning("recover 거절 — B 조회 중 새 정지 요청: 잠금 유지")
            return reject(STOPPED_DURING_RECOVER)
        self.get_logger().info(f"recover: 잠금 해제 (B 조회 {check}) — 재개 허가 아님, 보존 작업 {self.runner.suspended}")
        return intent_router.Decision(intent_router.RECOVER, intent=intent)

    def _resume(self, decision: intent_router.Decision, token: int | None) -> intent_router.Decision:
        """계약 W3 resume_register·resume_answer·resume (#152·#271, FR-SAF-03·AC-SAF-04). 접수 판단은 core/resume_admission.
        같은 기동·지금 사건·보존 작업이어야 함. 등록 = 재개 허가 아님(E 는 halt.resume.question·request 로 확인 뒤 TTS·소비).
        답 resume·독립 요청 소비가 접수되면: B 상태 다시 조회 → 재진입·pre 검사 → 통과해야 이어 실행. 거절이면 작업 보존."""
        intent = decision.intent or {}
        reject = lambda reason: intent_router.Decision(intent_router.REJECT, reason, intent=intent)  # noqa: E731
        admission = self.runner.admission
        if admission is None:                   # 재개 기한 설정을 못 읽음 → 접수하지 않음
            return intent_router.Decision(intent_router.HOLD, intent_router.UNSUPPORTED_INTENT, intent=intent)
        if intent.get("boot_id") != self.runner.boot_id:
            return reject(BOOT_MISMATCH)
        suspended = self.runner.suspended
        if suspended is None:
            return reject(NOTHING_TO_RESUME)
        if intent.get("event_id") != suspended["event_id"]:
            return reject(HALT_EVENT_MISMATCH)
        if intent.get("run_id") != suspended["run_id"]:
            return reject(RUN_MISMATCH)
        event, run, name = suspended["event_id"], suspended["run_id"], intent["intent"]
        if name == "resume_register":
            offered = bool((self.runner.resume_offer or {}).get("offered"))
            reason = admission.register_question(event, run, intent["question_id"], offered)
            return reject(reason) if reason else intent_router.Decision(REGISTERED, intent=intent)
        if name == "resume_answer":
            reason = admission.answer(event, run, intent["question_id"], intent["answer"], intent.get("evidence"))
            if reason:
                return reject(reason)
            if intent["answer"] != "resume":    # "아니"·만료: 질문만 닫고 작업 보존
                return intent_router.Decision(CLOSED, intent=intent)
        elif intent["phase"] == "register":
            reason = admission.register_request(event, run, intent["request_id"], unlocked=not self.runner.halted)
            return reject(reason) if reason else intent_router.Decision(REGISTERED, intent=intent)
        else:
            reason = admission.consume_request(event, run, intent["request_id"], intent.get("evidence"))
            if reason:
                return reject(reason)
        check, limits = self._b_check()
        observed = {"gripper": ((check or {}).get("gripper") or {}).get("state")}
        blockers = recover_blockers(check, self.runner.state, limits)
        with self._lock:                        # 최종 검사·시작 전이를 결정 발행 전에 (#291 E 리뷰) — 거절이면 그대로 결정
            outcome = self.gate.try_start(token)
            if outcome != STARTED:
                reasons = [intent_router.STOPPED_BEFORE_START if outcome == CANCELED_BEFORE_START else intent_router.BUSY]
            else:
                try:
                    ctx = self.runner.begin_resume(event, blockers, observed, window=False)
                except ResumeRejected as e:
                    self.gate.finish()
                    reasons = e.reasons
                else:
                    reasons = []
                    self._task_id = suspended["task_id"]
                    threading.Thread(target=self._run_resume, args=(ctx,), daemon=True).start()
        admission.settle(event, run, resumed=not reasons)
        if reasons:
            self.get_logger().warning(f"재개 거절 — 작업 보존: {reasons} (B 조회 {check})")
            return reject(reasons[0])
        return intent_router.Decision(intent_router.RESUME, intent=intent)

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
            suspended = self.runner.suspended
            if suspended:                       # 상태 초기화 = 보존 작업 끝 (정본 resume-admission-policy) — finally 비동작만
                self.gate.try_start()           # 폐기 중 새 실행이 끼지 않게 (실행 중이 아님은 위에서 확인)
                try:
                    self._last, self._last_task_id = self.runner.discard_suspended(), suspended["task_id"]
                finally:
                    self.gate.finish()
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
        halt = self.runner.halt_summary
        if halt is not None:                    # 묶음 계획: 구간(child)·구간 사이 정지는 상위 run_id 로 (E end_task·복구 대상이 그대로 맞게)
            parent = ((self._chain_parent or {}).get(halt.get("run_id")) or (self._chain_events or {}).get(halt.get("event_id"))
                      or (self._chain_run if halt.get("run_id") is None else None)
                      or (self._chain_run if (halt.get("run_id") or "").startswith(f"{self._chain_run}.") else None))
            if parent:
                halt = {**halt, "run_id": parent}
        status = build_status(self.running, self.runner.halted, self.runner.halt_code, self._task_id,
                              self.runner.current_step, self._last, self._last_task_id, degraded, halt=halt)
        status["last_intent"] = self._last_intent
        status["accepted"] = self._accepted              # 최근 수락 요청 (#376) — 이번 기동에 없으면 null
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



def _param_file(package: str, name: str) -> str:
    """패키지 params 파일: 설치 위치(share/<package>/params) → 마운트한 소스(/ros2_ws/src) → 이 저장소 소스 순."""
    candidates = []
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(Path(get_package_share_directory(package)) / "params" / name)
    except (ImportError, LookupError, ValueError):
        pass
    candidates += [Path("/ros2_ws/src") / package / "params" / name,
                   Path(__file__).resolve().parents[3] / package / "params" / name]
    return str(next((p for p in candidates if p.is_file()), candidates[-1]))

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
