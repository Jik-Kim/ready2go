"""JSON 태스크 해석기 — docs/runner.md 7.1~7.3.

Phase 1 범위: sequence, if, set_var, retry, timeout_sec, finally, 변수($ref·{{}} 보간·조사 필터),
primitive 스킬 실행 전 pre 확인 → 실행 → 응답 성공 시 effect 반영(ready2go_knowledge.core.ontology),
스텝 로그(LogStore, 스킬의 pre_check·state_diff 는 진단용 부가 기록).
Phase 2 (구현): while(max_iter, 넘으면 LOOP_LIMIT) · for_each(as 변수는 루프 안에서만) · push/pop(restore_stack 역순
복구) · fallback(대안. 그 대안에서 팔을 움직이는 동작을 보냈으면 어떤 실패든 다음 대안을 보내지 않음). 중단(ABORTED) 뒤 finally 에서 이 블록들은 SKIPPED (복구 기록은 남김).
Phase 2 (후속): recovery · on_halt, verify 사후 관측(FR-ONT-02), 상세 상태 로그(FR-LOG-02).
Phase 3: 선언형 복합 스킬 추가(FR-PLN-03).

Runner 는 원자 동작을 직접 실행하지 않는다. 생성 시 받은 execute(action, params, timeout_sec) → ActionResult
로 위임하며, #10 에서 ROS 액션 클라이언트(real·sim·mock 백엔드)가 이 자리에 들어간다.
timeout_sec 이 지나면 동작을 취소하는 것은 백엔드 책임이고, Runner 는 걸린 시간을 재서 초과하면 TIMEOUT 으로 판정한다.

E-stop·사용자 취소(docs/runner.md 7.1, docs/safety.md): 백엔드가 ESTOP 으로 실패하거나 halt() 가 호출되면
일반 실패 처리(retry·skip·safe_home)를 건너뛰고 ABORTED 로 끝낸다. 이때 finally 는 로봇을 움직이지 않는
동작(ABORT_SAFE_ACTIONS)만 실행하고 나머지는 SKIPPED 로 기록한다.
중단 상태는 잠긴 채 유지되어, 사람이 확인하고 resume() 을 부르기 전까지 새 태스크를 로봇 동작 없이 거절한다.
재개 대기 (#152, resumable=True, 계약 승인 전 제안): sequence 중 중단되면 실행을 끝내지 않고 보존(SUSPENDED)한다.
finally 는 실행하지 않는다. resume() 으로 잠금이 풀린 뒤 같은 정지 사건 ID 로 resume_run() 하면 중단된 스텝을
처음부터 다시 실행하고 이어 간다(앞 스텝은 다시 보내지 않음, 중단된 스킬의 effect 는 반영된 적 없음).
discard_suspended() 는 보존한 실행을 지금까지처럼 ABORTED 로 끝낸다(finally 는 비동작만). 반복·fallback 안에서
멈추면 재개할 수 없으므로 보존하지 않고 바로 ABORTED.
중단과 결과 반영의 경계: 중단 요청이 결과 반영 전에 들어오면 반영하지 않는다. 스킬은 effect 직전에 확인해
상태를 바꾸지 않고, 원자 동작은 응답대로 기록하되 다음 동작을 보내지 않으며, 마지막 동작 중이어도 ABORTED.
"""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ready2go_knowledge.core import ontology

from .conditions import BadCondition, evaluate
from .log_records import new_run_id, run_document, step_document, utc_iso
from .logstore import LogStore
from .validation import TASK_INVALID, check_task
from .variables import BadFilter, VarUndefined, resolve


@dataclass
class ActionResult:
    """원자 동작 결과. ICD Skill 액션 result(success, error_code, output_json)와 같은 구성."""
    success: bool
    output: Any = None
    error_code: str | None = None


@dataclass
class RunResult:
    overall_status: str                 # COMPLETED / FAILED / ABORTED(E-stop·사용자 취소)
    blackboard: dict
    steps: list[dict] = field(default_factory=list)
    error_code: str | None = None       # FAILED·ABORTED 일 때 원인 코드
    failed_step: str | None = None      # FAILED·ABORTED 일 때 멈춘 스텝 ID
    problems: list[str] = field(default_factory=list)   # 실행하지 않은 이유 (TASK_INVALID 검사 결과, 중단 잠김)
    run_id: str | None = None           # 실행 이력(runs·steps)의 실행 ID
    log_errors: list[str] = field(default_factory=list)  # 기록 저장 실패 (실행은 멈추지 않음)


Execute = Callable[[str, dict, "float | None"], ActionResult]   # (action, params, timeout_sec)

SAFE_HOME_POSE = "home"                 # on_failure: safe_home 이 이동할 기준 포즈 (docs/runner.md 7.1)
# 이 코드로 실패하면 ABORTED·잠금 (사람 확인 전 새 동작 없음). 비상정지, 취소 후 정지 확인 실패(PR #74 리뷰),
# B 스킬 서버의 잠금 코드(PR #73: 상태 조회 실패·이동 수락 모름·서버 잠김) — 10/06 실물 확인 후 runner.md 표로 확정
# HALT_MOTION (#78 사용자 결정 10/09): 물체 놓침(OBJECT_DROPPED, 정상 관측)·그리퍼 센서 이상(SENSOR_INVALID, 보유 불확실)
# → 즉시 ABORTED·잠금. 예전엔 일반 실패라 finally 의 서랍 닫기·홈이 나갈 수 있었음. 재개 대상도 아님: 실행을 끝내고
# 사람이 물체 회수·원위치 → 상태 맞추기(/runner/reset_state 등) → 잠금 해제 → 명시적 새 요청으로 처음부터.
HALT_MOTION_CODES = {"OBJECT_DROPPED", "SENSOR_INVALID"}
HALT_CODES = {"ESTOP", "STOP_UNCONFIRMED", "STATE_UNKNOWN", "MOVE_UNCONFIRMED", "LOCKED"} | HALT_MOTION_CODES
HALTED = "HALTED"                       # halt() 로 멈춘 경우의 코드 (/runner/estop 서비스·음성 "멈춰")
# ABORTED 일 때 finally 에서도 실행해도 되는 동작 (로봇을 움직이지 않음). 허용 목록이라 새 동작은 기본 생략
# 태스크가 정리 동작(닫기·홈)을 멈추지 않고 실행 결과만 실패로 남길 때 쓰는 블랙보드 변수 {code, step}
# (예: find_with_unpack 복구 미완료 RESTORE_INCOMPLETE — 정본 requirements 137 "복구 실패면 전체 FAILED")
TASK_ERROR_VAR = "task_error"
ABORT_SAFE_ACTIONS = {"set_var", "if", "speak", "query_ontology", "update_ontology"}
# skill 스텝 (#12): 온톨로지 primitive 스킬. 로봇을 움직이므로 ABORTED 때는 건너뜀
UNKNOWN_SKILL = "UNKNOWN_SKILL"         # 온톨로지에 없거나 primitive 가 아닌 스킬 (P1 은 primitive 만)
BAD_SKILL_PARAMS = "BAD_SKILL_PARAMS"   # 스킬 정의의 params 가 빠짐
PRE_UNMET = "PRE_UNMET"                 # pre 조건 불충족 → 로봇 동작을 보내지 않음
LOOP_LIMIT = "LOOP_LIMIT"               # while 이 max_iter 번 돈 뒤에도 조건이 참 (docs/runner.md 7.1)
STACK_EMPTY = "STACK_EMPTY"             # pop 할 기록이 없음
NOT_A_LIST = "NOT_A_LIST"               # for_each 의 in·push/pop 의 stack 이 리스트가 아님
FALLBACK_FAILED = "FALLBACK_FAILED"     # fallback 대안이 하나도 없음
NOT_IN_NEXT_ON = "NOT_IN_NEXT_ON"       # fallback_stopped: 움직이지 않은 실패지만 next_on 에 없는 코드 → 다음 대안 없음 (#121)
EXPAND_BLOCKS = ("fallback", "if")      # 스킬 expand 안에서 쓸 수 있는 블록 (#121·#245 계약안)
VAR_NULL = "VAR_NULL"                   # 백엔드로 보낼 동작의 "$변수" 값이 null (예: 실패한 nudge 의 target_after, #23)
# 스킬 재시도 (P1): 앞 동작이 실행됐거나 끝났을 수 있으면 다시 보내지 않는다(PR #64 D 리뷰). 다만 백엔드가
# 로봇을 움직이지 않았음을 보장하는 실패이고, 그 시도에서 앞서 보낸 동작도 팔을 움직이지 않았으면 재시도한다.
# 원자 동작이 **움직이기 전에** 거부했음이 보장된 실패 코드, 동작별 (runner.md 7.1 "로봇 동작 공통 에러 코드"·
# nudge_object 표의 "움직이지 않음", place_object 는 #166 계약안 표 "움직임 없음" — #168 B 노드 카드가 정본이 되면 맞춤).
# [임시] place_object 줄은 #166 승인·B 구현 전 계약안 기준 (지금 스킬 서버는 서랍 안 놓기를 UNSUPPORTED_PARAMS 로
# 거부, PLACE_BLOCKED 미구현). #166 승인·#168 카드 확정 뒤 각 코드가 실제로 모션 전인지 통합 시험으로 고정 (#175 D 리뷰).
# 이 실패는 로봇이 안 움직였으므로: 스킬 재시도(그 시도에서 앞서 팔을 움직이지 않았을 때)·fallback 다음 대안 허용
PRE_MOTION_COMMON = {"TOOL_NOT_SET", "DRAWER_NOT_AT_TRAVEL", "YAW_INVALID", "NOT_ON_FLOOR", "WALL_TOO_CLOSE"}
NO_MOTION_DEFAULT = {"TOOL_NOT_SET"}    # 표에 없는 로봇 동작 (move_to_named_pose 등)
NO_MOTION_BY_ACTION = {
    # NEIGHBOR_TOO_CLOSE: scan 의 옆 물체가 벌린 손가락·끄는 길에 걸림 — B 가 움직이기 전 거부 (main 구현 10/09, runner.md 표)
    "pick_object": PRE_MOTION_COMMON | {"BAD_PARAMS", "HOLDING_OBJECT", "UNSUPPORTED_PARAMS", "NEIGHBOR_TOO_CLOSE"},
    # make_room(#226): NO_FREE_SPACE = 치울 물체 놓을 빈 자리 없음, OCCLUSION_UNKNOWN = 가림 관계 모름 → 다시 찍기 (둘 다 움직이기 전)
    "nudge_object": PRE_MOTION_COMMON | {"NO_PUSH_ACCESS", "BAD_PARAMS", "NEIGHBOR_TOO_CLOSE", "NO_FREE_SPACE",
                                         "OCCLUSION_UNKNOWN"},
    # #181 B 서랍 노드 (머지 10/08 예정): 설정·시작 자세·상태 확인은 모두 움직이기 전 (닫기 노드 안의 홈·시작 자세
    # 이동 뒤 실패는 CLOSE_NOT_CONFIRMED 등이라 여기 없음)
    "drawer_control": NO_MOTION_DEFAULT | {"NOT_AT_START_POSE", "DRAWER_NOT_CONFIGURED", "DRAWER_STATE_UNKNOWN",
                                           "DRAWER_ALREADY_OPEN", "OTHER_DRAWER_OPEN", "HOLDING_OBJECT", "BAD_PARAMS"},
    # slot "free"(B #241): NO_FREE_SPACE = 서랍 안 빈 자리 없음 (움직이기 전). check_only 는 코드와 무관하게 움직이지 않음(_moves_arm)
    "place_object": PRE_MOTION_COMMON | {"NOT_HOLDING", "UNSUPPORTED_PARAMS", "PLACE_NOT_CONFIGURED", "TRAY_FULL",
                                         "BAD_PARAMS", "PLACE_BLOCKED", "NO_FREE_SPACE"},
}
NON_MOTION_ACTIONS = ABORT_SAFE_ACTIONS | {"inspect_region", "select_obstacle", "find_moved"}   # 팔을 움직이지 않는 원자 동작


SUSPENDED = "SUSPENDED"                 # 실행 상태: 중단됐지만 재개 대기로 보존 (#152)
# 재개 거절 이유 (#152 계약안 v0 — 이름은 승인 전 제안)
RESUME_PENDING = "RESUME_PENDING"       # 재개 대기 실행이 있어 새 태스크를 받지 않음 (말없이 버리지 않음)
NOTHING_TO_RESUME = "NOTHING_TO_RESUME"
HALT_EVENT_MISMATCH = "HALT_EVENT_MISMATCH"   # 지금 정지 사건이 아님 (과거·지연 응답, 복구 뒤 다시 멈춤)
NOT_RECOVERED = "NOT_RECOVERED"         # 아직 잠김 (복구 전)
RESUME_EXPIRED = "RESUME_EXPIRED"       # 잠금이 풀린 뒤 resume_window_sec 안에 재개 요청이 없음
RESUME_UNSUPPORTED_BLOCK = "RESUME_UNSUPPORTED_BLOCK"   # 반복·fallback 안에서 중단 → 보존하지 않음
REENTRY_BLOCKED = "REENTRY_BLOCKED"     # 중단된 스텝의 재진입 조건 불충족 (B #152 스킬별 조건)
STATE_UNOBSERVED = "STATE_UNOBSERVED"   # 재진입 판단에 필요한 실제 상태(그리퍼)를 받지 못함
# 스텝을 시작한 뒤 멈췄을 때 다시 들어가도 되는 조건 (B #152 답 10/08, 계약 승인 전 [팀 확정 필요]).
# 값: None = 항상 거절(사람이 정리) / "empty"·"holding" = 관측한 그리퍼가 그 상태일 때만. 없는 스텝은 조건 없음.
# 서랍: 열림 거리 센서가 없고 손잡이를 쥔 채일 수 있음 / 집기: 빈손이 확실할 때만 처음부터 /
# 놓기: 그리퍼가 열려 있으면 놓은 것으로 봄 → 쥐고 있을 때만 처음부터 / 끌기: 누르는 중 멈춤 — B 조건 받기 전까지 거절
REENTRY_GRIPPER = {"open_drawer": None, "close_drawer": None, "drawer_control": None, "nudge_object": None,
                   "pick": "empty", "pick_object": "empty", "place": "holding", "place_object": "holding"}


class ResumeRejected(Exception):
    """resume_run() 거절. reasons: 위 코드·PRE_UNMET·호출 쪽이 넘긴 관측 검사 결과(STATE_MISMATCH 등)."""

    def __init__(self, reasons: list[str]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


@dataclass
class _Run:
    """실행 하나의 문맥. 재개 대기 때 이대로 보존한다."""
    task: dict
    blackboard: dict
    records: list[dict]
    doc: dict                           # run_document 인자 (run_id·task_id·inputs·started_at·extra)
    started: float
    halts: list[dict] = field(default_factory=list)   # 정지 사건 기록 (실행 문서 extra.halts, FR-LOG-02)
    branch_at: dict = field(default_factory=dict)       # if 위치 → 고른 분기 (재개 때 같은 분기로 들어감)
    path: list | None = None            # 중단 위치 [(인덱스, action), ...] — 바깥 → 안쪽
    step_started: bool = False          # 중단된 스텝이 이미 시작됐는지 (시작 전이면 실물에 남은 부분 동작 없음)
    error: "Halted | None" = None


class StepFailed(Exception):
    """no_retry: 동작이 어디까지 됐는지 몰라 다시 보내면 위험한 실패의 이유 (기록 retry_stopped).
    LATE_RESULT = 제한 시간 뒤 도착한 결과, TIMEOUT = 백엔드 호출이 제한 시간에 끝나지 않아 취소 요청함,
    MOTION_UNCERTAIN = 스킬 하위 동작·fallback 대안 실패 중 로봇이 움직이지 않았음이 보장되지 않음,
    RESPONSE_LOST = 팔을 움직이는 동작을 보내다 백엔드 예외 (보낸 뒤 응답이 끊겼을 수 있음, #159 E 리뷰),
    NOT_RETRYABLE = 스킬 단계의 실패가 "움직이기 전 거부"(NO_MOTION_BY_ACTION)가 아님 (PRE_UNMET 등).
    no_motion: 원자 동작이 움직이기 전에 거부했음이 보장됨 (NO_MOTION_BY_ACTION)."""

    def __init__(self, step_id: str, code: str, no_retry: str | None = None, no_motion: bool = False):
        super().__init__(f"{step_id}: {code}")
        self.step_id, self.code, self.no_retry, self.no_motion = step_id, code, no_retry, no_motion


class Halted(Exception):
    """E-stop·사용자 취소. StepFailed 와 달리 retry·skip·safe_home 을 거치지 않고 바로 위로 전달된다.
    step_code: 스텝 기록에 남길 백엔드 응답 코드 (예: 중단 요청으로 취소된 동작의 CANCELED). 없으면 code."""

    def __init__(self, step_id: str, code: str, step_code: str | None = None):
        super().__init__(f"{step_id}: {code}")
        self.step_id, self.code, self.step_code = step_id, code, step_code


class Runner:
    def __init__(self, execute: Execute, schema: dict | None = None,
                 clock: Callable[[], float] = time.monotonic, log_store: LogStore | None = None,
                 ontology: dict | None = None, resumable: bool = False, resume_window_sec: float = 30.0):
        self.execute = execute
        self.resumable = resumable              # #152: 중단 시 재개 대기로 보존 (기본 꺼짐 = 지금 동작)
        self.resume_window_sec = resume_window_sec   # 잠금이 풀린 뒤 재개를 받는 시간 [팀 확정 필요]
        self.schema = schema                    # contracts/task.schema.json 내용 (노드가 읽어서 전달)
        self.clock = clock                      # 소요 시간·timeout 측정용 (테스트에서 가짜 시계 주입)
        self.log_store = log_store              # 실행 이력 저장 (FallbackLogStore: MongoDB → JSONL), None 이면 기록 안 함
        # 온톨로지(E, knowledge/robot_ontology.jsonld): 스킬 정의는 참고만, 상태는 Runner 가 단일 관리자(docs/ontology.md 7.8)
        self.skills: dict = (ontology or {}).get("skills", {})
        self._state: dict = copy.deepcopy((ontology or {}).get("state", {}))   # 원본은 바꾸지 않음, 태스크 사이에 유지
        self._initial_state: dict = copy.deepcopy(self._state)   # reset_state() 가 되돌릴 시작 상태
        self._run_id: str | None = None
        self._records: list[dict] = []
        self._log_errors: list[str] = []
        self._halt = threading.Event()          # 중단 잠김 (다른 스레드의 ROS 서비스 콜백에서 halt() 호출)
        self._halt_lock = threading.Lock()      # halt() 와 effect 반영(중단 확인 → 상태 갱신)이 서로 끼어들지 않게
        self.on_halt: Callable[[], object] | None = None   # 처음 멈출 때 진행 중인 동작 취소 (노드가 RosClients.cancel_all 연결)
        # 스텝 시작·끝 알림 (#98 콘솔 진행 표시). (event "start"|"end", record, {"run_id", "finally"}).
        # 보기용: 예외가 나도 실행·기록·안전 처리에 영향 없음
        self.on_step: Callable[[str, dict, dict], object] | None = None
        self._in_finally = False
        self._iterations: list[int] = []        # 반복 블록 안이면 몇 번째 회차인지 (스텝 기록 iteration)
        self._motions = 0                       # 팔을 움직였을 수 있는 동작을 보낸 횟수 (fallback 이 대안마다 비교)
        # 팔이 지금 있는 이름 자세 (마지막 성공한 move_to_named_pose 의 params, 그 뒤 팔을 움직였을 수 있으면 None).
        # 같은 자세로 다시 가라면 보내지 않음 — B 는 경유점을 거쳐 다시 와서 "위아래 왕복"이 됨 (#245)
        self._at_pose: dict | None = None
        self._halt_code: str | None = None      # 처음 멈춘 이유 (HALTED / ESTOP)
        self._halt_info: dict = {}              # 처음 멈춘 요청의 시각·출처·취소 요청한 동작 수 (halts[] 기록)
        self._aborted = False                   # 이번 실행이 E-stop·취소로 중단되었는지
        self._event_seq = 0
        self._event_id: str | None = None       # 정지 사건 ID: 잠길 때마다 새로 (재개 요청이 이 사건에 대한 것인지)
        self._suspended: _Run | None = None     # 재개 대기 중인 실행
        self._offered_at: float | None = None   # 재개 대기 중 잠금이 풀린 시각 (clock)
        self._pos: list[tuple[int, str]] = []   # 지금 실행 중인 스텝 위치 (바깥 → 안쪽)
        self._branch_at: dict[tuple, str] = {}  # 지금 실행 문맥의 _Run.branch_at
        self._halt_path: list | None = None     # 중단이 처음 난 스텝 위치
        self._halt_started = False              # 그 스텝이 시작된 뒤 멈췄는지
        self._step_started = False              # 가장 최근 _run_step 이 기록을 만들었는지 (시작 전 중단 구분)

    def halt(self, code: str = HALTED, source: str = "runner") -> None:
        """실행 중인 태스크를 멈추고 resume() 전까지 잠근다. 진행 중인 동작의 취소는 백엔드 책임.
        source: 정지 요청 출처 — "service"(/runner/estop)·"voice"(음성 cancel)·"backend"(스킬 서버 ESTOP 등 중단 코드).
        정지 요청 시각·출처·취소 요청한 동작 수는 실행 기록 halts[] 에 남는다 (#187, AC-SAF-02 C 몫)."""
        with self._halt_lock:                   # effect 반영 중이면 끝날 때까지 기다림 → 반영 전/후가 분명함
            first = not self._halt.is_set()
            if first:
                self._halt_code = code
                self._event_seq += 1
                self._event_id = f"h{self._event_seq}-{utc_iso()}"
                self._offered_at = None
                self._halt_info = {"requested_at": utc_iso(), "source": source, "canceled_goals": None}
            self._halt.set()
        if first and self.on_halt is not None:  # 진행 중인 로봇 동작에 즉시 취소 요청 (기다림은 클라이언트가 함)
            canceled = self.on_halt()
            if isinstance(canceled, int) and not isinstance(canceled, bool):
                self._halt_info["canceled_goals"] = canceled

    def resume(self) -> None:
        """사람이 상태를 확인한 뒤 중단 잠김을 푼다 (docs/safety.md "비상정지 후 처리")."""
        with self._halt_lock:
            self._halt_code = None
            self._halt.clear()
            if self._suspended is not None:     # 재개 대기: 이때부터 resume_window_sec 안에 재개 요청을 받음
                self._offered_at = self.clock()

    @property
    def halted(self) -> bool:
        return self._halt.is_set()

    @property
    def stop_requested(self) -> bool:
        """중단 요청이 들어왔지만 이번 실행이 아직 중단 처리 전. 이때 새 원자 동작을 보내지 않는다(RosClients).
        중단 처리 뒤 finally 의 비동작(speak 등)은 Runner 가 골라 보내므로 막지 않는다."""
        return self._halt.is_set() and not self._aborted

    @property
    def halt_code(self) -> str | None:
        """처음 멈춘 이유 (HALTED / ESTOP). 잠기지 않았으면 None."""
        return self._halt_code if self._halt.is_set() else None

    @property
    def current_step(self) -> str | None:
        """지금(또는 마지막으로) 시작한 스텝 ID. /runner/status 표시용 (#10, 시연 화면 #59)."""
        records = self._records
        return records[-1]["id"] if records else None

    @property
    def state(self) -> dict:
        """현재 온톨로지 상태 state[predicate][subject] 의 복사본 (#10 에서 /robot_state 로 발행)."""
        return copy.deepcopy(self._state)

    def reset_state(self) -> None:
        """온톨로지 상태를 시작 상태로 되돌린다 (#23·#107). 사람이 물품·서랍·그리퍼를 원위치한 것을 확인한 뒤에만
        부른다(/runner/reset_state, 나중에 시연 화면 버튼 #59). P1 은 실행 사이 원위치를 관측으로 맞추지 못하므로
        시연 전 상태 스냅샷 복원(docs/metrics_risks.md). 실행 중에는 부르지 않는다(노드가 막음).
        중단 잠김(halt)은 풀지 않는다 — 잠금 해제는 별도 절차."""
        with self._halt_lock:                   # effect 반영과 끼어들지 않게
            self._state = copy.deepcopy(self._initial_state)

    def run(self, task: dict, inputs: dict | None = None, meta: dict | None = None) -> RunResult:
        """태스크를 실행한다. inputs 는 태스크 기본 inputs 를 덮어쓴다(음성 인텐트 바인딩).
        meta: 실행 기록 헤더에 덧붙일 값 (backend·STT 원문 등, docs/runner.md 7.4)."""
        self._aborted, self._in_finally = False, False
        self._at_pose = None                    # 실행 사이에는 사람이 팔을 옮겼을 수 있음
        blackboard = {"inputs": {**task.get("inputs", {}), **(inputs or {})}}
        ctx = _Run(task, blackboard, [], {"run_id": new_run_id(), "task_id": task.get("task_id", ""),
                                          "inputs": blackboard["inputs"], "started_at": utc_iso(), "extra": meta},
                   self.clock())
        self._run_id, self._records, self._log_errors = ctx.doc["run_id"], ctx.records, []
        self._log("start_run", run_document(**ctx.doc))

        if self._halt.is_set():                 # E-stop 뒤 resume() 전에는 로봇을 움직이지 않음
            return self._finish(ctx, RunResult("ABORTED", blackboard, [], self._halt_code,
                                               problems=["중단 상태입니다. 사람이 확인한 뒤 resume() 해야 실행합니다"]))
        if self._suspended is not None:         # 재개 대기 실행을 말없이 버리지 않음 (#152)
            return self._finish(ctx, RunResult("ABORTED", blackboard, [], RESUME_PENDING, problems=[
                f"재개 대기 중인 실행 {self._suspended.doc['run_id']} 이 있습니다. 재개하거나 버린 뒤 실행합니다"]))
        problems = check_task(task, self.schema, self.skills)
        if problems:                            # 로봇을 움직이기 전에 거절 (finally 도 실행하지 않음)
            return self._finish(ctx, RunResult("FAILED", blackboard, [], TASK_INVALID, problems=problems))
        return self._continue(ctx)

    def _continue(self, ctx: _Run, path: list | None = None) -> RunResult:
        """sequence(path 가 있으면 그 스텝부터) → finally. 재개 가능한 중단이면 finally 전에 보존하고 돌아감."""
        self._aborted, self._in_finally, self._halt_path = False, False, None
        self._branch_at = ctx.branch_at
        blackboard, records = ctx.blackboard, ctx.records
        error: StepFailed | Halted | None = None
        try:
            if path is None:
                self._run_steps(ctx.task["sequence"], blackboard, records)
            else:
                self._run_from(ctx.task["sequence"], path, blackboard, records, ())
            self._check_halt(records[-1]["id"] if records else "")   # 마지막 스텝 중 중단 요청도 ABORTED
        except StepFailed as e:
            error = e
        except Halted as e:
            error = self._abort(e)
            where = self._halt_path or [(len(ctx.task["sequence"]), "end")]       # 마지막 스텝 뒤 = 남은 sequence 없음
            stopped = None
            if self._halt_path and all(action == "if" for _, action in where[:-1]):
                stopped = _step_at(ctx, where)    # 최상위·if 안이면 그 스텝, 반복·fallback 안이면 멈춘 동작 ID 그대로
            self._note_halt(ctx, e, stopped.get("id") if stopped else None)
            if self.resumable and (self._halt_code or e.code) not in HALT_MOTION_CODES:   # 놓침·센서 이상은 보존 안 함
                if all(action == "if" for _, action in where[:-1]):
                    ctx.step_started = self._halt_started and self._halt_path is not None
                    return self._suspend(ctx, e, where)
        # finally 는 sequence 가 성공·실패 어느 쪽으로 끝나도 실행 (복구·서랍 닫기·홈 복귀)
        # ABORTED 이면 _run_step 이 로봇 동작을 건너뛴다
        return self._run_finally(ctx, error)

    def _run_finally(self, ctx: _Run, error: StepFailed | Halted | None) -> RunResult:
        blackboard, records = ctx.blackboard, ctx.records
        self._in_finally = True
        try:
            self._run_steps(ctx.task.get("finally", []), blackboard, records)
            self._check_halt(records[-1]["id"] if records else "")
        except StepFailed as e:
            error = error or e                  # 둘 다 실패하면 처음(sequence) 원인을 남김
        except Halted as e:
            if not self._aborted:               # E-stop 이 다른 실패보다 우선
                error = self._abort(e)
                self._note_halt(ctx, e)
            # 이미 중단 상태면 처음 멈춘 위치·원인을 유지
        if error is None and not self._aborted:
            error = _marked_error(blackboard)   # 태스크가 남긴 실패 (앞선 실패·중단이 있으면 그 원인이 우선)
        if self._aborted:
            return self._finish(ctx, RunResult("ABORTED", blackboard, records, error.code, error.step_id))
        if error:
            return self._finish(ctx, RunResult("FAILED", blackboard, records, error.code, error.step_id))
        return self._finish(ctx, RunResult("COMPLETED", blackboard, records))

    def _finish(self, ctx: _Run, result: RunResult) -> RunResult:
        result.run_id, result.log_errors = ctx.doc["run_id"], self._log_errors
        doc = dict(ctx.doc)
        if ctx.halts:
            doc["extra"] = {**(doc.get("extra") or {}), "halts": ctx.halts}
        self._log("end_run", run_document(
            **doc, ended_at=utc_iso(), total_duration_sec=round(self.clock() - ctx.started, 3),
            overall_status=result.overall_status, error_code=result.error_code,
            failed_step=result.failed_step, problems=result.problems))
        return result

    # ---- 재개 대기 (#152) ----
    def _suspend(self, ctx: _Run, e: Halted, path: list) -> RunResult:
        """중단된 실행을 끝내지 않고 보존. finally 는 재개·버림이 정해질 때까지 미룬다."""
        ctx.path, ctx.error = path, e                 # 정지 기록(halts[-1])은 _continue 가 이미 남김
        self._suspended, self._offered_at = ctx, None
        return self._finish(ctx, RunResult(SUSPENDED, ctx.blackboard, ctx.records, e.code, e.step_id))

    @property
    def halt_event_id(self) -> str | None:
        """지금 정지 사건 ID. 잠겨 있거나 재개 대기 중일 때만."""
        return self._event_id if self._halt.is_set() or self._suspended is not None else None

    @property
    def suspended(self) -> dict | None:
        """재개 대기 중인 실행 요약 (/runner/status 용). 없으면 None."""
        ctx = self._suspended
        if ctx is None:
            return None
        step = _step_at(ctx, ctx.path)
        return {"run_id": ctx.doc["run_id"], "task_id": ctx.doc["task_id"], "event_id": self._event_id,
                "code": ctx.error.code, "from_step": step.get("id") if step else None,
                "step_started": ctx.step_started, "needs": _reentry_need(step) if ctx.step_started else "none",
                "recovered": not self._halt.is_set()}

    def check_resume(self, event_id: str | None, blockers: list[str] = (), observed: dict | None = None) -> list[str]:
        """재개 거절 이유 목록 (비면 재개 가능). blockers: 호출 쪽 관측 검사 결과 (STATE_MISMATCH 등).
        observed: 실제 상태 {"gripper": "empty"|"holding"} — 시작된 스텝에서 멈췄으면 REENTRY_GRIPPER 로 판단."""
        ctx = self._suspended
        if ctx is None:
            return [NOTHING_TO_RESUME]
        reasons = []
        if event_id != self._event_id:
            reasons.append(HALT_EVENT_MISMATCH)
        if self._halt.is_set():
            reasons.append(NOT_RECOVERED)
        elif self._offered_at is not None and self.clock() - self._offered_at > self.resume_window_sec:
            reasons.append(RESUME_EXPIRED)
        step = _step_at(ctx, ctx.path)
        if ctx.step_started:                    # 시작 뒤 멈춤 → 실물에 부분 동작이 남았을 수 있음 (B #152)
            need = _reentry_need(step)
            seen = (observed or {}).get("gripper")
            if need is None:
                reasons.append(REENTRY_BLOCKED)
            elif need != "none" and seen is None:
                reasons.append(STATE_UNOBSERVED)
            elif need != "none" and seen != need:
                reasons.append(REENTRY_BLOCKED)
        if step is not None and "skill" in step:   # 중단된 스킬의 pre 를 지금 상태로 다시 확인 (로봇 동작 전)
            skill = self.skills.get(step["skill"]) or {}
            try:
                params = resolve(step.get("params", {}), ctx.blackboard)
            except (VarUndefined, BadFilter) as e:
                reasons.append(e.code)
            else:
                if not all(c["pass"] for c in ontology.check(self._state, skill.get("pre", []), params)):
                    reasons.append(PRE_UNMET)
        return reasons + [b for b in blockers if b not in reasons]

    def resume_run(self, event_id: str | None, blockers: list[str] = (), observed: dict | None = None) -> RunResult:
        """재개 대기 실행을 중단된 스텝부터 이어 실행. 거절이면 ResumeRejected (보존·잠금 상태 그대로)."""
        reasons = self.check_resume(event_id, blockers, observed)
        if reasons:
            raise ResumeRejected(reasons)
        ctx, self._suspended, self._offered_at = self._suspended, None, None
        ctx.halts[-1]["resumed_at"] = utc_iso()
        self._at_pose = None                    # 멈춘 동안 사람이 팔을 옮겼을 수 있음
        self._run_id, self._records = ctx.doc["run_id"], ctx.records
        return self._continue(ctx, ctx.path)

    def discard_suspended(self) -> RunResult | None:
        """재개하지 않음 ("아니"·시간 초과·상태 초기화): 지금까지처럼 ABORTED 로 끝냄. finally 는 비동작만."""
        ctx = self._suspended
        if ctx is None:
            return None
        self._suspended, self._offered_at = None, None
        ctx.halts[-1]["discarded_at"] = utc_iso()
        self._run_id, self._records = ctx.doc["run_id"], ctx.records
        self._branch_at = ctx.branch_at
        self._aborted = True                    # 로봇 동작은 건너뜀 (잠금이 풀렸어도 사람이 정리)
        return self._run_finally(ctx, ctx.error)

    def _log(self, method: str, doc: dict) -> None:
        """실행 이력 저장. 실패해도 실행은 멈추지 않고 log_errors 에 남긴다 (NFR-DB-01)."""
        if self.log_store is None:
            return
        try:
            getattr(self.log_store, method)(doc)
        except Exception as e:
            self._log_errors.append(f"{method}: {type(e).__name__}: {e}")

    def _log_step(self, record: dict) -> None:
        """스텝이 끝날 때 저장. seq 는 스텝이 시작된 순서 (if 블록은 안쪽 스텝보다 늦게 끝남)."""
        seq = next(i for i, r in enumerate(self._records) if r is record)
        self._log("write_step", step_document(self._run_id, seq, record))
        self._notify("end", record)

    def _notify(self, event: str, record: dict, params: dict | None = None) -> None:
        """on_step 알림. 콘솔 표시용이라 실패해도 무시한다 (실행·저장·중단 처리에 영향 없음).
        params: 시작 때 아직 풀지 않은 스텝 params (예: drawer_control state) — 이름 표시용."""
        if self.on_step is None:
            return
        try:
            self.on_step(event, record, {"run_id": self._run_id, "finally": self._in_finally, "params": params})
        except Exception:
            pass

    def _abort(self, e: Halted) -> Halted:
        """중단으로 전환하고 잠근다(백엔드 ESTOP 도 resume() 전까지 유지)."""
        self._aborted = True
        self.halt(e.code, source="backend")     # 이미 잠겼으면(서비스·음성 요청) 처음 요청 정보 그대로
        return e

    def _note_halt(self, ctx: _Run, e: Halted, step_id: str | None = None) -> dict:
        """정지 기록 1건 (실행 기록 halts[], #187 AC-SAF-02 C 몫): 요청 시각·출처·취소 요청한 동작 수 →
        백엔드가 돌려준 응답 코드(CANCELED·STOP_UNCONFIRMED·ESTOP 등)와 Runner 가 받은 시각."""
        entry = {"event_id": self._event_id, "code": self._halt_code or e.code,
                 "source": self._halt_info.get("source", "runner"),
                 "requested_at": self._halt_info.get("requested_at"), "at": self._halt_info.get("requested_at"),
                 "canceled_goals": self._halt_info.get("canceled_goals"),
                 "step": step_id or e.step_id, "action_step": e.step_id,
                 "step_code": e.step_code or e.code, "stopped_at": utc_iso(), "in_finally": self._in_finally}
        ctx.halts.append(entry)
        return entry

    def _check_halt(self, step_id: str) -> None:
        """중단 요청이 있으면 로봇 동작 전에 멈춘다. 스텝 시작·재시도·safe_home 직전에 확인."""
        if self._halt.is_set() and not self._aborted:
            raise Halted(step_id, self._halt_code or HALTED)

    def _run_steps(self, steps: list[dict], blackboard: dict, records: list[dict], start: int = 0) -> None:
        for idx in range(start, len(steps)):
            step = steps[idx]
            self._pos.append((idx, step.get("action", "skill")))
            try:
                self._run_step(step, blackboard, records)
            except Halted:
                if self._halt_path is None and not self._in_finally:
                    self._halt_path = list(self._pos)   # 가장 안쪽에서 처음 잡힌 위치 = 재개 지점
                    self._halt_started = self._step_started
                raise
            finally:
                self._pos.pop()

    def _run_from(self, steps: list[dict], path: list, blackboard: dict, records: list[dict], prefix: tuple) -> None:
        """재개: path 의 스텝부터 실행하고 그 뒤 형제 스텝으로 이어 감. 바깥 if 는 처음 고른 분기로 다시 들어감."""
        idx, action = path[0]
        if len(path) > 1:
            key = prefix + (idx,)
            self._pos.append((idx, action))
            try:
                self._run_from(steps[idx].get(self._branch_at[key], []), path[1:], blackboard, records, key)
            finally:
                self._pos.pop()
            idx += 1
        self._run_steps(steps, blackboard, records, start=idx)

    def _run_step(self, step: dict, blackboard: dict, records: list[dict]) -> None:
        """스텝 하나를 실행하고, 끝나면(성공·실패·건너뜀 모두) 실행 이력에 기록한다."""
        self._step_started = False
        self._check_halt(step["id"])
        self._step_started = True
        record = {"id": step["id"], "action": step.get("action", "skill"), "started_at": utc_iso()}
        if "skill" in step:
            record["skill"] = step["skill"]
        if self._iterations:
            record["iteration"] = self._iterations[-1]   # while·for_each 안: 같은 스텝 ID 가 회차마다 기록됨
        records.append(record)
        self._notify("start", record, step.get("params"))
        try:
            self._run_step_body(step, blackboard, records, record)
        finally:
            self._log_step(record)

    def _run_step_body(self, step: dict, blackboard: dict, records: list[dict], record: dict) -> None:
        """on_failure 정책(abort·retry·skip·safe_home)을 적용."""
        if self._aborted and step.get("action") not in ABORT_SAFE_ACTIONS:
            record.update(status="SKIPPED", skipped_reason="ABORTED")   # 중단 후 로봇 동작 금지
            return
        policy = step.get("on_failure", "abort")
        max_attempts = 1 + (step.get("retry", 0) if policy == "retry" else 0)
        started = self.clock()

        for attempt in range(1, max_attempts + 1):
            if attempt > 1 and self._halt.is_set() and not self._aborted:   # 실패 중 중단 요청 → 재시도 안 함
                record.update(status="FAILURE", error_code=failure.code,
                              duration_sec=round(self.clock() - started, 3))
                self._check_halt(step["id"])
            record["attempts"] = attempt
            try:
                self._dispatch(step, blackboard, record, records, self.clock())
            except StepFailed as e:
                failure = e
                if "skill" in step and e.no_retry is None and not e.no_motion:
                    e.no_retry = "NOT_RETRYABLE"    # 스킬은 로봇이 움직이지 않았음이 보장된 실패만 재시도
                if e.no_retry:                  # 결과 불확실: 동작이 실제로 끝났을 수 있어 다시 보내지 않음
                    if attempt < max_attempts:
                        record["retry_stopped"] = e.no_retry
                    break
                continue
            except Halted as e:                 # retry·skip·safe_home 을 거치지 않음
                record.update(status="FAILURE", error_code=e.step_code or e.code)
                raise
            except Exception as e:              # Runner 내부의 예상 못 한 에러도 스텝 실패로 처리해 finally 를 보장
                record["internal_error"] = f"{type(e).__name__}: {e}"
                failure = StepFailed(step["id"], "INTERNAL_ERROR")
                continue
            finally:
                record["duration_sec"] = round(self.clock() - started, 3)   # 재시도 포함 전체 시간
            record["status"] = "SUCCESS"
            return

        record.update(status="FAILURE", error_code=failure.code)
        if policy == "skip":
            record["on_failure"] = "skip"
            return
        if policy == "safe_home" and not self._aborted:      # 중단 중에는 홈 이동도 하지 않음
            self._check_halt(step["id"])
            self._safe_home(step, records)
        raise failure

    def _safe_home(self, step: dict, records: list[dict]) -> None:
        """실패 후 홈 포즈로 이동. 이동 결과도 기록하되, 실패해도 원래 실패로 중단한다."""
        params = {"pose_name": SAFE_HOME_POSE}
        record = {"id": f"{step['id']}.safe_home", "action": "move_to_named_pose",
                  "started_at": utc_iso(), "params": params}
        records.append(record)
        self._notify("start", record, params)
        try:
            self._motions += 1
            self._at_pose = None
            try:
                result = self.execute("move_to_named_pose", params, None)
            except Exception:
                result = ActionResult(False, error_code="BACKEND_ERROR")
            record["status"] = "SUCCESS" if result.success else "FAILURE"
            if not result.success:
                record["error_code"] = result.error_code or "ACTION_FAILED"
                if result.error_code in HALT_CODES:
                    raise Halted(record["id"], result.error_code)
        finally:
            self._log_step(record)

    def _check_timeout(self, step: dict, attempt_started: float) -> None:
        """결과가 온 뒤 걸린 시간을 판정. 이때는 동작이 이미 끝났을 수 있으므로 재시도하지 않는 TIMEOUT."""
        timeout = step.get("timeout_sec")
        if timeout is not None and self.clock() - attempt_started > timeout:
            again = not _moves_arm(step.get("action"), step.get("params")) and step.get("action") != "if"   # 팔 안 움직이는 원자 동작
            raise StepFailed(step["id"], "TIMEOUT", no_retry=None if again else "LATE_RESULT")

    def _dispatch(self, step: dict, blackboard: dict, record: dict, records: list[dict],
                  attempt_started: float) -> None:
        if "skill" in step:
            self._run_skill(step, blackboard, record, records, attempt_started)
            return
        action = step["action"]
        block = {"if": self._run_if, "while": self._run_while, "for_each": self._run_for_each,
                 "fallback": self._run_fallback}.get(action)
        if block is not None:
            block(step, blackboard, record, records)
            self._check_timeout(step, attempt_started)    # 블록은 취소할 수 없어 끝난 뒤 판정
            return
        try:
            params = resolve(step.get("params", {}), blackboard)
        except (VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        record["params"] = params
        if action not in ABORT_SAFE_ACTIONS and _null_refs(step.get("params", {}), params):
            raise StepFailed(step["id"], VAR_NULL)     # 빈 값으로 로봇·백엔드 동작을 보내지 않음

        if action == "set_var":
            blackboard[params["name"]] = params.get("value")
            return
        if action in ("push", "pop"):
            self._stack(step, action, params, blackboard, record)
            return

        if action == "move_to_named_pose" and params == self._at_pose:
            record["same_pose"] = True          # 이미 그 자세이고 그 뒤 팔을 움직이지 않음 → 보내지 않고 성공 (#245)
            return
        motion = _moves_arm(action, params)
        at_pose, self._at_pose = self._at_pose, (None if motion else self._at_pose)
        try:
            result = self.execute(action, params, step.get("timeout_sec"))
        except Exception as e:                  # 통신 끊김 등 백엔드 예외도 스텝 실패로 처리해 finally 를 보장
            if motion:                          # 보낸 뒤 끊겼을 수 있음 → 결과 불확실 (재시도·다음 대안 금지)
                self._motions += 1
            raise StepFailed(step["id"], "BACKEND_ERROR", no_retry="RESPONSE_LOST" if motion else None) from e
        no_motion = not result.success and (not motion or _no_motion(action, result.error_code))
        if motion and not no_motion:
            self._motions += 1                  # 움직이기 전 거부가 보장된 실패만 빼고 셈
        if not result.success:
            if result.output is not None:       # 실패 응답의 결과도 기록만 (예: 그리퍼를 연 뒤 실패한 place_object 의
                record["output"] = result.output   # placed_pose, #166). 블랙보드에는 넣지 않음 — 뒤 스텝이 성공 값으로 쓰지 않게
            if result.error_code in HALT_CODES:
                raise Halted(step["id"], result.error_code)
            if _hand_uncertain(result.output):  # #223: 실패했는데 B 가 "쥐었는지 모름·쥠"이라고 함 → 빈손으로 보지 않고
                record["hand_uncertain"] = (result.output or {}).get("hand")   # 정지·잠금(finally 비동작) — 사람 확인
                raise Halted(step["id"], result.error_code or "ACTION_FAILED")
            if self._halt.is_set() and not self._aborted:   # 중단 요청으로 취소된 동작 → 그 자리에서 중단
                raise Halted(step["id"], self._halt_code or HALTED, step_code=result.error_code or None)
            # 백엔드 TIMEOUT(제한 시간에 끝나지 않아 취소 요청)도 결과가 불확실하므로 재시도하지 않음.
            # 팔을 움직이지 않는 동작(인식 등)은 끝났어도 다시 해도 되므로 재시도 허용 (#168 인식 실패 다시 찍기)
            raise StepFailed(step["id"], result.error_code or "ACTION_FAILED",
                             no_retry="TIMEOUT" if result.error_code == "TIMEOUT" and motion else None,
                             no_motion=no_motion)
        self._check_timeout(step, attempt_started)        # 늦게 성공한 결과는 쓰지 않음
        if action == "move_to_named_pose":
            self._at_pose = dict(params)
        elif action == "nudge_object" and _stayed(result.output):
            self._at_pose = at_pose             # 밀지 않음 = 움직이지 않음 (runner.md 7.1 nudge_object)
        record["output"] = result.output
        if "output" in step:
            blackboard[step["output"]] = result.output

    def _run_if(self, step: dict, blackboard: dict, record: dict, records: list[dict]) -> None:
        """cond 가 참이면 then, 거짓이면 else 를 실행. 자식 스텝 기록은 if 기록 뒤에 이어진다."""
        try:
            taken = evaluate(step["cond"], blackboard)
        except (BadCondition, VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        branch = "then" if taken else "else"
        record["branch"] = branch
        self._branch_at[tuple(i for i, _ in self._pos)] = branch
        self._run_steps(step.get(branch, []), blackboard, records)

    def _cond(self, step: dict, blackboard: dict) -> bool:
        try:
            return bool(evaluate(step["cond"], blackboard))
        except (BadCondition, VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e

    def _loop_body(self, step: dict, n: int, blackboard: dict, records: list[dict]) -> None:
        self._iterations.append(n)
        try:
            self._run_steps(step.get("body", []), blackboard, records)
        finally:
            self._iterations.pop()

    def _run_while(self, step: dict, blackboard: dict, record: dict, records: list[dict]) -> None:
        """cond 가 참인 동안 body 반복. max_iter 번 돈 뒤에도 참이면 LOOP_LIMIT (무한 반복 금지)."""
        n = 0
        while self._cond(step, blackboard):
            if n >= step["max_iter"]:
                record["iterations"] = n
                raise StepFailed(step["id"], LOOP_LIMIT)
            n += 1
            self._loop_body(step, n, blackboard, records)
        record["iterations"] = n

    def _run_for_each(self, step: dict, blackboard: dict, record: dict, records: list[dict]) -> None:
        """in 의 리스트를 하나씩 as 변수에 넣고 body 실행 (번들 요청·역순 복구)."""
        try:
            items = resolve(step["in"], blackboard)
        except (VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        if not isinstance(items, list):
            raise StepFailed(step["id"], NOT_A_LIST)
        record["iterations"] = 0
        name = step["as"]                                 # as 변수는 루프 안에서만: 끝나면(실패 포함) 이전 값 복구
        had, before = name in blackboard, blackboard.get(name)
        try:
            for n, item in enumerate(list(items), 1):     # 복사본을 돎 (body 가 리스트를 바꿔도 회차 수 그대로)
                blackboard[name] = item
                self._loop_body(step, n, blackboard, records)
                record["iterations"] = n
        finally:
            if had:
                blackboard[name] = before
            else:
                blackboard.pop(name, None)

    def _run_fallback(self, step: dict, blackboard: dict, record: dict, records: list[dict]) -> None:
        """options 를 차례로 시도해 하나라도 끝까지 성공하면 성공. 다음 대안은 앞 대안이 로봇을 움직이지 않았음이
        확인된 실패일 때만 보낸다 — 스킬 재시도와 같은 규칙(#159 E 리뷰). 그 대안에서 팔을 움직이는 동작을 보냈으면
        (성공한 이동 뒤 인식 실패 포함) MOTION_UNCERTAIN, 결과 불확실(TIMEOUT·늦은 결과·응답 유실)이면 그 이유로 멈춤.
        중단(Halted)은 그대로 위로."""
        last: StepFailed | None = None
        for n, option in enumerate(step.get("options", []), 1):
            record["option"] = n
            motions = self._motions
            try:
                self._run_steps(option, blackboard, records)
                return
            except StepFailed as e:
                last = e
                if e.no_retry is None and self._motions != motions:
                    e.no_retry = "MOTION_UNCERTAIN"   # fallback 스텝 자체의 retry 도 막힘
                if e.no_retry:
                    record["fallback_stopped"] = e.no_retry
                    raise
                if "next_on" in step and e.code not in step["next_on"]:   # #121: 정한 코드일 때만 다음 대안
                    record["fallback_stopped"] = NOT_IN_NEXT_ON
                    raise
        raise StepFailed(step["id"], last.code if last else FALLBACK_FAILED)

    def _stack(self, step: dict, action: str, params: dict, blackboard: dict, record: dict) -> None:
        """push: params.value 를 params.stack 리스트 끝에 / pop: 끝에서 꺼내 output 에 (LIFO 역순 복구)."""
        name = params["stack"]
        stack = blackboard.setdefault(name, [])
        if not isinstance(stack, list):
            raise StepFailed(step["id"], NOT_A_LIST)
        if action == "push":
            stack.append(copy.deepcopy(params.get("value")))
            record["output"] = {"stack": name, "size": len(stack)}
            return
        if not stack:
            raise StepFailed(step["id"], STACK_EMPTY)
        value = stack.pop()
        record["output"] = value
        if "output" in step:
            blackboard[step["output"]] = value

    def _run_skill(self, step: dict, blackboard: dict, record: dict, records: list[dict],
                   attempt_started: float) -> None:
        """skill 스텝: pre 확인 → expand 원자 동작 실행 → effect 반영 (#12, docs/ontology.md 7.8).
        P1 은 동작 응답이 성공이면 effect 를 반영한다 (verify·hold 는 P2, FR-ONT-02)."""
        skill = self.skills.get(step["skill"])
        if not isinstance(skill, dict) or skill.get("kind") != "primitive":
            raise StepFailed(step["id"], UNKNOWN_SKILL)
        try:
            params = resolve(step.get("params", {}), blackboard)
        except (VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        record["params"] = params
        if any(name not in params for name in skill.get("params", {})):
            raise StepFailed(step["id"], BAD_SKILL_PARAMS)

        checks = ontology.check(self._state, skill.get("pre", []), params)
        record["pre_check"] = checks
        if not all(c["pass"] for c in checks):
            raise StepFailed(step["id"], PRE_UNMET)

        scope = {**blackboard, **params}        # expand 의 $drawer_id·$scan 등은 스킬 안에서만 보임
        moved = False                           # 이 시도에서 팔을 움직이는 동작을 이미 보냈는지
        for i, sub in enumerate(skill.get("expand", []), 1):
            motions = self._motions
            try:
                self._run_expand_item(sub, f"{step['id']}.e{i}", step, scope, records, attempt_started)
            except StepFailed as e:
                if e.no_retry is None and moved:
                    e.no_retry = "MOTION_UNCERTAIN"   # 앞서 팔을 움직였으면 어떤 실패든 스킬을 다시 보내지 않음
                raise
            moved = moved or (self._motions != motions if sub["action"] in EXPAND_BLOCKS
                              else _moves_arm(sub["action"], sub.get("params")))
        with self._halt_lock:                   # 중단 확인과 반영 사이에 halt() 가 끼어들 수 없음 (PR #64 E 리뷰)
            self._check_halt(step["id"])        # 반영 전 중단 요청 → effect 반영 안 함
            self._check_timeout(step, attempt_started)
            self._state, diff = ontology.apply(self._state, skill.get("effect", []), params)
        record["state_diff"] = diff             # 반영 뒤 들어온 중단은 다음 경계(스텝 시작·실행 끝)에서 ABORTED

    def _run_expand_item(self, sub: dict, child_id: str, step: dict, scope: dict, records: list[dict],
                         attempt_started: float) -> None:
        """스킬 expand 한 줄: 원자 동작이거나 fallback·if 블록 (#121). 하위 ID: <스텝>.e<n>.o<k>.<m> / .t<m> / .f<m>."""
        if sub.get("action") == "fallback":
            self._run_expand_fallback(sub, child_id, step, scope, records, attempt_started)
        elif sub.get("action") == "if":
            self._run_expand_if(sub, child_id, step, scope, records, attempt_started)
        else:
            self._run_expanded({**sub, "id": child_id}, step, scope, records, attempt_started)

    def _expand_block(self, block_id: str, action: str, step: dict, records: list[dict], body) -> None:
        """expand 안 블록의 기록 하나(부모 = 스킬 스텝)를 남기며 body(record) 실행."""
        record = {"id": block_id, "action": action, "parent": step["id"], "started_at": utc_iso()}
        if self._iterations:
            record["iteration"] = self._iterations[-1]
        records.append(record)
        self._notify("start", record, None)
        started = self.clock()
        try:
            body(record)
            record["status"] = "SUCCESS"
        except (StepFailed, Halted) as e:
            record.update(status="FAILURE", error_code=getattr(e, "step_code", None) or e.code)
            raise
        finally:
            record["duration_sec"] = round(self.clock() - started, 3)
            self._log_step(record)

    def _run_expand_fallback(self, sub: dict, block_id: str, step: dict, scope: dict, records: list[dict],
                             attempt_started: float) -> None:
        """expand 안 fallback: 앞 대안이 로봇을 움직이지 않았고(태스크 fallback 과 같은 규칙) 실패 코드가
        next_on 안일 때만 다음 대안. 그 밖(움직였을 수 있음·결과 불확실·정지·목록 밖 코드)은 그 실패로 멈춤."""
        next_on = set(sub.get("next_on") or ())

        def body(record):
            last = None
            for k, option in enumerate(sub.get("options", []), 1):
                record["option"] = k
                motions = self._motions
                try:
                    for m, child in enumerate(option, 1):
                        self._run_expand_item(child, f"{block_id}.o{k}.{m}", step, scope, records, attempt_started)
                    return
                except StepFailed as e:
                    last = e
                    if e.no_retry is None and self._motions != motions:
                        e.no_retry = "MOTION_UNCERTAIN"
                    if e.no_retry or e.code not in next_on:
                        record["fallback_stopped"] = e.no_retry or NOT_IN_NEXT_ON
                        raise
            raise StepFailed(step["id"], last.code if last else FALLBACK_FAILED)
        self._expand_block(block_id, "fallback", step, records, body)

    def _run_expand_if(self, sub: dict, block_id: str, step: dict, scope: dict, records: list[dict],
                       attempt_started: float) -> None:
        def body(record):
            try:
                taken = evaluate(sub["cond"], scope)
            except (BadCondition, VarUndefined, BadFilter) as e:
                raise StepFailed(step["id"], e.code) from e
            record["branch"] = "then" if taken else "else"
            mark = "t" if taken else "f"
            for m, child in enumerate(sub.get("then" if taken else "else", []), 1):
                self._run_expand_item(child, f"{block_id}.{mark}{m}", step, scope, records, attempt_started)
        self._expand_block(block_id, "if", step, records, body)

    def _run_expanded(self, child: dict, step: dict, scope: dict, records: list[dict],
                      attempt_started: float) -> None:
        """스킬이 펼친 원자 동작 하나. 재시도·실패 정책은 스킬 스텝이 맡고, 여기서는 실행과 기록만."""
        self._check_halt(child["id"])
        timeout = step.get("timeout_sec")
        if timeout is not None:                 # 스킬 전체 제한 시간 중 남은 시간을 동작에 넘김
            child["timeout_sec"] = timeout - (self.clock() - attempt_started)
            if child["timeout_sec"] <= 0:
                raise StepFailed(step["id"], "TIMEOUT")
        record = {"id": child["id"], "action": child["action"], "parent": step["id"], "started_at": utc_iso()}
        if self._iterations:
            record["iteration"] = self._iterations[-1]   # 반복 안의 스킬: 하위 동작도 몇 회차인지 (보고서 묶음)
        records.append(record)
        self._notify("start", record, child.get("params"))
        started = self.clock()
        try:
            self._dispatch(child, scope, record, records, started)
            record["status"] = "SUCCESS"
        except (StepFailed, Halted) as e:
            record.update(status="FAILURE", error_code=getattr(e, "step_code", None) or e.code)
            raise
        except Exception:                       # 스킬 스텝에서 INTERNAL_ERROR 로 처리됨
            record.update(status="FAILURE", error_code="INTERNAL_ERROR")
            raise
        finally:
            record["duration_sec"] = round(self.clock() - started, 3)
            self._log_step(record)


def _marked_error(blackboard: dict) -> StepFailed | None:
    """블랙보드 task_error = {code, step} 이 있으면 그 실패. 형식이 맞지 않으면 무시(실행 결과를 바꾸지 않음)."""
    mark = blackboard.get(TASK_ERROR_VAR)
    if isinstance(mark, dict) and isinstance(mark.get("code"), str) and mark["code"]:
        return StepFailed(str(mark.get("step") or ""), mark["code"])
    return None


def _hand_uncertain(output) -> bool:
    """B 결과 hand(#223, 결정 10): holding·unknown 이면 실패여도 손에 물건이 있을 수 있음. 지금 B 는 이 경우를
    SENSOR_INVALID·ESTOP(HALT_CODES)로 보내므로 이 검사는 다른 코드로 오는 경우의 안전장치. released·empty·없음은 그대로."""
    return isinstance(output, dict) and output.get("hand") in ("holding", "unknown")


def _moves_arm(action: str, params) -> bool:
    """팔을 움직일 수 있는 원자 동작인지. place_object check_only(B #241)는 놓기 판단만 — 성공·거부 모두 어떤 동작도
    하지 않고, 집기 전이면 집기 계획까지 판단만 해서 집기 거부 코드(NEIGHBOR_TOO_CLOSE 등)로도 실패한다(#242)."""
    if action in NON_MOTION_ACTIONS:
        return False
    return not (action == "place_object" and isinstance(params, dict) and params.get("check_only") is True)


def _stayed(output) -> bool:
    """nudge_object 결과가 "잡을 수 있는 자리라 움직이지 않음"(pushed false, make_room 아님)인지."""
    return isinstance(output, dict) and output.get("pushed") is False and not output.get("make_room")


def _no_motion(action: str, code: str | None) -> bool:
    """원자 동작 action 이 code 로 실패했을 때 움직이기 전 거부가 보장되는지."""
    if action in NON_MOTION_ACTIONS:
        return True
    return code in NO_MOTION_BY_ACTION.get(action, NO_MOTION_DEFAULT)


def _reentry_need(step: dict | None) -> str | None:
    """중단된 스텝의 재진입 조건: None = 항상 거절, "empty"/"holding" = 그리퍼 조건, "none" = 조건 없음."""
    if step is None:
        return "none"
    name = step.get("skill") or step.get("action")
    return REENTRY_GRIPPER[name] if name in REENTRY_GRIPPER else "none"


def _step_at(ctx: _Run, path: list) -> dict | None:
    """중단 위치의 스텝 (처음 고른 if 분기를 따라 내려감). 마지막 스텝 뒤면 None."""
    steps, prefix = ctx.task["sequence"], ()
    for depth, (idx, _) in enumerate(path):
        if idx >= len(steps):
            return None
        if depth == len(path) - 1:
            return steps[idx]
        prefix += (idx,)
        steps = steps[idx].get(ctx.branch_at[prefix], [])
    return None


def _null_refs(raw: dict, resolved: dict) -> list[str]:
    """params 중 값 전체가 "$변수" 참조인데 null 로 풀린 이름. 백엔드 동작에 빈 값을 보내지 않으려고 확인한다.
    (없는 변수는 VAR_UNDEFINED. null 은 "있지만 비어 있음" — 예: 실패·누락된 target_after)"""
    return [key for key, value in raw.items()
            if isinstance(value, str) and value.startswith("$") and resolved.get(key) is None]
