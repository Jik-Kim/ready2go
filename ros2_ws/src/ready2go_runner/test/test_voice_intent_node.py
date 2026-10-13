"""#17 /voice/intent → Runner 노드: mock 백엔드와 함께 띄워 음성 인텐트로 태스크 실행·보류·중복 거절·cancel·status 확인.
E 통합 공지(#23): find_item → P1 태스크, cancel/status, 모호·미지원 요청 보류, 중복 실행 처리, 입력 명령 기록.
rclpy·ready2go_interfaces 필요 → 호스트 pytest 는 건너뛰고 ros2-core 컨테이너·colcon test 에서 실행."""
import json
import itertools
import threading
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ready2go_interfaces")

from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from std_msgs.msg import String  # noqa: E402

from ready2go_runner.nodes.mock_backend import MockBackendNode  # noqa: E402
from ready2go_runner.nodes.runner_node import LATCHED, RunnerNode  # noqa: E402

DOMAIN_IDS = itertools.count(100)       # 파일마다 Domain ID 범위를 나눔 (stop_safety 150, mock_backend 180, runner_node 200). ROS Domain ID 는 최대 232 → 220 에서 시작하면 14번째 시험이 233 으로 프로세스 종료 (#150)
ROOT = Path(__file__).resolve().parents[4]
EXAMPLE = (ROOT / "contracts/examples/intent_find_item.json").read_text(encoding="utf-8")


def intent(name="find_item", targets=("eraser",), confidence=0.9):
    return json.dumps({"intent": name, "targets": list(targets), "confidence": confidence})


class Voice:
    """E 음성 노드처럼 /voice/intent 를 발행하고 /runner/status 를 본다."""

    def __init__(self, node):
        self.status = None
        node.create_subscription(String, "/runner/status", lambda m: setattr(self, "status", json.loads(m.data)), LATCHED)
        self.pub = node.create_publisher(String, "/voice/intent", 10)

    def say(self, text):
        end = time.monotonic() + 5.0            # Runner 구독이 연결될 때까지 (처음 발행이 사라지지 않게)
        while self.pub.get_subscription_count() == 0 and time.monotonic() < end:
            time.sleep(0.05)
        self.pub.publish(String(data=text))

    def wait(self, check, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.status is not None and check(self.status):
                return True
            time.sleep(0.05)
        return False


def last_intent(s):
    return s.get("last_intent") or {}


def make_system(tmp_path, duration=0.05, ontology_file="knowledge/robot_ontology.jsonld", intent_tasks="",
                skills_up=True, plan_limits=None, extra=()):
    """skills_up=False: mock 백엔드(/skills/* 서버) 없이 시작 — 기동 직후 스킬 서버가 늦게 뜨는 상황 (#108).
    나중에 voice.start_skills() 로 띄운다."""
    context = rclpy.Context()
    rclpy.init(context=context, domain_id=next(DOMAIN_IDS))
    runner = RunnerNode(context=context, parameter_overrides=[
        Parameter("schema_file", value=str(ROOT / "contracts/task.schema.json")),
        Parameter("intent_schema_file", value=str(ROOT / "contracts/intent.schema.json")),
        Parameter("ontology_file", value=str(ROOT / ontology_file)),
        Parameter("tasks_dir", value=str(ROOT / "tasks")),
        Parameter("intent_tasks", value=intent_tasks),
        *([Parameter("plan_limits", value=plan_limits)] if plan_limits is not None else []),
        *[Parameter(k, value=v) for k, v in extra],
        Parameter("log_dir", value=str(tmp_path))])
    voice_node = rclpy.create_node("voice_test", context=context)
    voice = Voice(voice_node)
    executor = MultiThreadedExecutor(context=context)
    for node in (runner, voice_node):
        executor.add_node(node)

    def start_skills():
        executor.add_node(MockBackendNode(context=context, parameter_overrides=[Parameter("duration_sec", value=duration)]))
    voice.start_skills = start_skills
    if skills_up:
        start_skills()
    threading.Thread(target=executor.spin, daemon=True).start()

    def close():
        executor.shutdown()
        rclpy.shutdown(context=context)
    return runner, voice, close


@pytest.fixture
def system(tmp_path):
    runner, voice, close = make_system(tmp_path)
    yield runner, voice
    close()


@pytest.fixture
def slow_system(tmp_path):
    runner, voice, close = make_system(tmp_path, duration=0.4)   # 실행 중에 두 번째 인텐트를 보낼 시간
    yield runner, voice
    close()


def test_find_item_runs_p1_task_and_records_voice_input(system):
    runner, voice = system
    voice.say(EXAMPLE)                                  # "지우개 찾아줘" (contracts 예시)
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") is not None), voice.status
    assert voice.status["last"]["task_id"] == "find_item" and voice.status["last"]["overall_status"] == "COMPLETED"
    assert last_intent(voice.status)["decision"] == "run" and last_intent(voice.status)["stt_text"] == "지우개 찾아줘"
    run = runner.log_store.read_run(voice.status["last"]["run_id"])["run"]
    assert run["inputs"]["target"] == "eraser" and run["inputs"]["source"] == "voice"   # 입력 명령 기록 (FR-LOG-01)
    assert run["inputs"]["stt_text"] == "지우개 찾아줘" and run["intent"]["intent"] == "find_item"


@pytest.mark.parametrize("text, reason", [
    (intent("unknown", targets=()), "NEEDS_CLARIFY"),
    (intent(targets=("phone",)), "UNKNOWN_ITEM"),
    (intent(targets=("car_key",)), "UNSUPPORTED_ITEM"),            # 10/07 P1 은 지우개만 (E #17), 로봇 동작 전 보류
    (intent(confidence=0.2), "LOW_CONFIDENCE"),
    ("지우개 찾아줘", "BAD_INTENT"),
])
def test_unclear_request_is_held_without_running(system, text, reason):
    runner, voice = system
    voice.say(text)
    assert voice.wait(lambda s: last_intent(s).get("reason") == reason), voice.status
    assert last_intent(voice.status)["decision"] == "hold"
    time.sleep(0.3)
    assert voice.status["phase"] == "idle" and voice.status["last"] is None           # 실행 기록 없음


def test_duplicate_request_while_running_is_rejected(slow_system):
    runner, voice = slow_system
    voice.say(intent())
    assert voice.wait(lambda s: s["phase"] == "running")
    voice.say(intent())                                 # 같은 요청 중복 (P1 find_item 은 지우개만)
    assert voice.wait(lambda s: last_intent(s).get("reason") == "BUSY"), voice.status
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "COMPLETED")
    run_ids = {voice.status["last"]["run_id"]}
    time.sleep(0.5)
    assert {voice.status["last"]["run_id"]} == run_ids                               # 두 번째 요청은 실행 안 됨


@pytest.fixture
def long_action_system(tmp_path):
    """동작마다 2 s — /runner/status 는 PUBLISH_PERIOD_SEC(0.5 s)마다 발행돼 시험이 단계를 최대 0.5 s 늦게 본다.
    0.4 s 동작이면 "멈춰"가 닿을 때 그 동작이 이미 끝나 다음 스텝 경계에서 멈춤(HALTED) — 진행 중 goal 취소를 못 봄."""
    runner, voice, close = make_system(tmp_path, duration=2.0)
    yield runner, voice
    close()


def test_cancel_stops_running_task_and_locks(long_action_system):
    """진행 중인 동작(첫 안내 speak)에 "멈춰" → 그 goal 취소(CANCELED), 정지 기록, 잠김.
    #259: 음성 goal 은 취소하지만 로봇 goal 이 아니라 canceled_goals 0, halt.stop none(멈출 로봇 동작 없었음)."""
    runner, voice = long_action_system
    voice.say(intent())
    # 첫 안내 speak 가 나가 있는 동안 멈춤 (계약07 뒤 s2 는 accept_text if — 안내는 s2.1/s2.2)
    assert voice.wait(lambda s: s["phase"] == "running" and s["current_step"] in ("s2.1", "s2.2"))
    voice.say(intent("cancel", targets=(), confidence=0.5))
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "ABORTED"), voice.status
    assert voice.status["phase"] == "halted" and voice.status["halt_code"] == "HALTED"
    halt = runner.log_store.read_run(voice.status["last"]["run_id"])["run"]["halts"][0]   # #187 정지 기록
    assert halt["source"] == "voice" and halt["canceled_goals"] == 0 and halt["step_code"] == "CANCELED"
    assert (voice.status["halt"]["stop"], voice.status["halt"]["response_code"]) == ("none", None)
    voice.say(intent())                                 # 잠김: 사람이 확인하기 전 새 태스크 없음
    assert voice.wait(lambda s: last_intent(s).get("reason") == "LOCKED"), voice.status


def test_cancel_when_idle_does_not_lock(system):
    runner, voice = system
    voice.say(intent("cancel", targets=()))
    assert voice.wait(lambda s: last_intent(s).get("reason") == "NOT_RUNNING")
    assert voice.status["phase"] == "idle"


def test_status_republishes(system):
    runner, voice = system
    voice.say(intent("status", targets=()))
    assert voice.wait(lambda s: last_intent(s).get("decision") == "status"), voice.status
    assert voice.status["phase"] == "idle"


def test_demo_override_runs_wall_nudge_task(tmp_path):
    """P1 시연 조합: 공통 온톨로지 + intent_tasks 로 find_item → p1_demo_eraser (벽 배치·끌기 뒤 다시 촬영, E #122)."""
    runner, voice, close = make_system(tmp_path, ontology_file="knowledge/robot_ontology.jsonld",
                                       intent_tasks=f"find_item={ROOT / 'tasks/p1_demo_eraser.json'}")
    try:
        voice.say(EXAMPLE)
        assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") is not None), voice.status
        assert voice.status["last"]["task_id"] == "p1_demo_eraser"
        assert voice.status["last"]["overall_status"] == "COMPLETED", voice.status["last"]
    finally:
        close()


def test_request_before_skill_servers_is_rejected_without_motion(tmp_path):
    """#108 D P1: 기동 직후 스킬 서버가 아직 없으면 NOT_READY 로 거절 — BACKEND_ERROR 실행·로봇 동작 없음.
    서버가 뜬 뒤 같은 요청은 실행된다."""
    runner, voice, close = make_system(tmp_path, skills_up=False)
    try:
        voice.say(EXAMPLE)
        assert voice.wait(lambda s: last_intent(s).get("reason") == "NOT_READY"), voice.status
        assert last_intent(voice.status)["decision"] == "reject" and voice.status["last"] is None   # 실행 기록 없음
        assert voice.status["phase"] == "idle"
        voice.start_skills()
        end = time.monotonic() + 10.0
        while runner.missing_servers(runner.intents.tasks["find_item"]) and time.monotonic() < end:
            time.sleep(0.1)
        again = json.loads(EXAMPLE)                  # 사용자가 다시 말함 = E 가 새 request_id (계약07: 같은 ID 는 첫 결정 그대로)
        again["request_id"] = "example-find-07-again"
        voice.say(json.dumps(again, ensure_ascii=False))
        assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "COMPLETED"), voice.status
    finally:
        close()


# ---- #150 achieve_goal → 플래너 → 실행 (P2, FR-PLN-02) ----

def goal_intent(subject, value, predicate="located_in", stt="립밤은 아래 서랍에 넣어 둬"):
    return json.dumps({"intent": "achieve_goal", "targets": [subject], "confidence": 0.9,
                       "goals": [{"predicate": predicate, "subject": subject, "value": value}],
                       "source": {"stt_text": stt}}, ensure_ascii=False)


def test_goal_is_planned_and_run_with_plan_in_record(tmp_path):
    """립밤(위 서랍) → 아래 서랍: 플래너가 순서를 만들고(하드코딩 없음) Runner 가 실행, 계획·근거는 실행 기록에.
    서랍 간 이동은 실물 기본 지원 범위 밖이라 mock 처럼 제한 없음(plan_limits="")으로."""
    runner, voice, close = make_system(tmp_path, plan_limits="")
    try:
        _goal_run(runner, voice)
    finally:
        close()


def _goal_run(runner, voice):
    voice.say(goal_intent("lip_balm", "drawer_bottom"))
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") is not None, timeout=40), voice.status
    last = voice.status["last"]
    assert last["overall_status"] == "COMPLETED" and last["task_id"] == "plan_lip_balm_drawer_bottom", last
    assert last_intent(voice.status)["decision"] == "run"
    assert runner.runner.state["located_in"]["lip_balm"] == "drawer_bottom"
    assert runner.runner.state["open"]["drawer_bottom"] is False and runner.runner.state["open"]["drawer_top"] is False
    run = runner.log_store.read_run(last["run_id"])["run"]
    assert run["inputs"]["goals"][0]["value"] == "drawer_bottom" and run["inputs"]["stt_text"] == "립밤은 아래 서랍에 넣어 둬"
    plan = run["plan"]                                                                     # extra 는 헤더에 펼쳐 저장
    assert any("place(lip_balm, drawer_bottom)" in line and "목표" in line for line in plan)


@pytest.mark.parametrize("goal, reason", [
    (("lip_balm", "drawer_top"), "PLAN_SATISFIED"),          # 이미 그 자리
    (("handover_zone", False, "open"), "UNPLANNABLE"),        # 트레이를 닫는 스킬이 없음 → 계획 불가
])
def test_goal_satisfied_or_unplannable_is_held_without_motion(system, goal, reason):
    runner, voice = system
    voice.say(goal_intent(*goal))
    assert voice.wait(lambda s: last_intent(s).get("reason") == reason), voice.status
    assert last_intent(voice.status)["decision"] == "hold"
    time.sleep(0.3)
    assert voice.status["phase"] == "idle" and voice.status["last"] is None              # 실행 기록 없음


def test_default_real_limits_hold_plans_the_robot_cannot_do(system):
    """#154 E 리뷰 P1: 기본(실물 지원 범위)에서 '립밤을 아래 서랍에'는 실행 전에 계획 불가 — 로봇 동작·실행 기록 없음."""
    runner, voice = system
    voice.say(goal_intent("lip_balm", "drawer_bottom"))
    assert voice.wait(lambda s: last_intent(s).get("reason") == "UNPLANNABLE"), voice.status
    time.sleep(0.3)
    assert voice.status["last"] is None and runner.runner.state["located_in"]["lip_balm"] == "drawer_top"


def test_default_real_limits_still_run_p1_delivery_goal(system):
    runner, voice = system
    voice.say(goal_intent("eraser", "handover_zone", stt="지우개 트레이에 갖다 놔"))
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") is not None, timeout=40), voice.status
    assert voice.status["last"]["overall_status"] == "COMPLETED"
    assert runner.runner.state["located_in"]["eraser"] == "handover_zone"



def test_stop_while_request_is_being_handled_does_not_start_it(system):
    """#187: 요청을 처리하는 사이(플래너 계산 등) "멈춰"가 오면 그 요청은 시작하지 않음 — NOT_RUNNING 으로 새지 않게."""
    runner, voice = system
    token = runner.gate.token()                         # "지우개 찾아줘"를 받은 순간
    voice.say(intent("cancel", targets=()))             # 그 처리 중 "멈춰"
    assert voice.wait(lambda s: last_intent(s).get("reason") == "NOT_RUNNING")
    task = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
    assert runner.start_task(task, {"target": "eraser"}, token=token) is False
    time.sleep(0.3)
    assert voice.status["phase"] == "idle" and voice.status["last"] is None          # 실행 없음
    assert runner.start_task(task, {"target": "eraser"}, token=runner.gate.token())   # 멈춰 뒤 새 요청은 정상


def end_task(boot, run, request_id="end-1"):
    return json.dumps({"intent": "end_task", "targets": [], "confidence": 0.9, "request_id": request_id,
                       "boot_id": boot, "run_id": run, "source": {"stt_text": "작업 종료해"}})


def test_end_task_stops_only_the_current_run_and_keeps_lock(long_action_system):
    """계약 W3 end_task (#271, E3): 다른 run_id → NOTHING_TO_END, 다른 기동 → BOOT_MISMATCH (둘 다 실행 그대로),
    지금 실행 → cancel 과 같은 정지 → ABORTED·잠김(잠금 해제·새 작업 허용 아님), 같은 ID 재전송 → 첫 결정 재발행."""
    runner, voice = long_action_system
    boot = runner.runner.boot_id
    voice.say(intent())
    assert voice.wait(lambda s: s["phase"] == "running" and last_intent(s).get("run_id")), voice.status
    run_id = last_intent(voice.status)["run_id"]
    voice.say(end_task(boot, "2026-01-01T00:00:00Z_000000", "end-x"))
    assert voice.wait(lambda s: last_intent(s).get("reason") == "NOTHING_TO_END"), voice.status
    voice.say(end_task("other-boot", run_id, "end-y"))
    assert voice.wait(lambda s: last_intent(s).get("reason") == "BOOT_MISMATCH"), voice.status
    assert voice.status["phase"] == "running"                                     # 거절은 실행에 영향 없음
    voice.say(end_task(boot, run_id))
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "ABORTED"), voice.status
    assert voice.status["phase"] == "halted" and voice.status["last"]["run_id"] == run_id
    voice.say(intent())                                                         # 잠김 유지
    assert voice.wait(lambda s: last_intent(s).get("reason") == "LOCKED"), voice.status
    voice.say(end_task(boot, run_id))                                           # 같은 ID 재전송 → 첫 결정(end) 다시
    assert voice.wait(lambda s: last_intent(s).get("decision") == "end"
                      and last_intent(s).get("request_id") == "end-1"), voice.status
    assert voice.status["phase"] == "halted"


def test_end_task_when_idle_is_nothing_to_end(system):
    runner, voice = system
    voice.say(end_task(runner.runner.boot_id, "2026-01-01T00:00:00Z_000000"))
    assert voice.wait(lambda s: last_intent(s).get("reason") == "NOTHING_TO_END"), voice.status
    assert voice.status["phase"] == "idle"


def recover(boot, event, request_id="rec-1"):
    return json.dumps({"intent": "recover", "targets": [], "confidence": 0.9, "request_id": request_id,
                       "boot_id": boot, "event_id": event, "source": {"stt_text": "복구해"}})


def test_recover_unlocks_preserved_work_without_resuming(tmp_path):
    """계약 W3 recover (#271, FR-SAF-03): 재개 대기(resumable)에서 멈춰 → 작업 보존·잠김 → 다른 사건 recover 거절 →
    지금 사건 recover = B 조회(mock) 충족 → 잠금 해제·halt.resume.offered (재개 아님, 로봇 동작 없음) →
    보존 중 새 요청은 RESUME_PENDING → end_task 로 폐기."""
    runner, voice, close = make_system(tmp_path, duration=2.0, extra=[("resumable", True)])
    try:
        boot = runner.runner.boot_id
        voice.say(intent())
        assert voice.wait(lambda s: s["phase"] == "running" and s["current_step"] in ("s2.1", "s2.2")), voice.status
        voice.say(intent("cancel", targets=(), confidence=0.9))
        assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "SUSPENDED"), voice.status
        halt = voice.status["halt"]
        assert voice.status["phase"] == "halted" and halt["locked"] and halt["resume"]["offered"] is False
        run_id, event = voice.status["last"]["run_id"], halt["event_id"]
        voice.say(recover(boot, "h0-old", "rec-x"))
        assert voice.wait(lambda s: last_intent(s).get("reason") == "HALT_EVENT_MISMATCH"), voice.status
        voice.say(recover(boot, event))
        assert voice.wait(lambda s: last_intent(s).get("decision") == "recover" and s["phase"] == "idle"), voice.status
        resume = voice.status["halt"]["resume"]
        assert resume["offered"] and resume["from_step"] and voice.status["halt"]["locked"] is False
        voice.say(json.dumps({"intent": "find_item", "targets": ["eraser"], "confidence": 0.9}))
        assert voice.wait(lambda s: (s["last"] or {}).get("error_code") == "RESUME_PENDING"), voice.status
        voice.say(end_task(boot, run_id, "end-r"))
        assert voice.wait(lambda s: last_intent(s).get("decision") == "end"
                          and (s["last"] or {}).get("run_id") == run_id
                          and s["last"]["overall_status"] == "ABORTED"), voice.status
        assert voice.status["halt"] is None                                      # 보존 작업 없음, 잠금 없음
    finally:
        close()


def test_recover_without_b_check_keeps_the_lock(tmp_path):
    """B 상태 조회(W1) 없음(real 기본 recover_check none) → B_CHECK_UNAVAILABLE, 잠금 유지."""
    runner, voice, close = make_system(tmp_path, duration=2.0, extra=[("recover_check", "none")])
    try:
        voice.say(intent())
        assert voice.wait(lambda s: s["phase"] == "running"), voice.status
        voice.say(intent("cancel", targets=(), confidence=0.9))
        assert voice.wait(lambda s: s["phase"] == "halted" and s["halt"]), voice.status
        voice.say(recover(runner.runner.boot_id, voice.status["halt"]["event_id"]))
        assert voice.wait(lambda s: last_intent(s).get("reason") == "B_CHECK_UNAVAILABLE"), voice.status
        assert voice.status["phase"] == "halted" and runner.runner.halted
    finally:
        close()
