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

DOMAIN_IDS = itertools.count(220)       # 파일마다 Domain ID 범위를 나눔 (runner_node 200, mock_backend 180)
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
                skills_up=True):
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


def test_cancel_stops_running_task_and_locks(slow_system):
    runner, voice = slow_system
    voice.say(intent())
    assert voice.wait(lambda s: s["phase"] == "running" and s["current_step"] not in (None, "s1"))
    voice.say(intent("cancel", targets=(), confidence=0.5))
    assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "ABORTED"), voice.status
    assert voice.status["phase"] == "halted" and voice.status["halt_code"] == "HALTED"
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
        voice.say(EXAMPLE)
        assert voice.wait(lambda s: (s["last"] or {}).get("overall_status") == "COMPLETED"), voice.status
    finally:
        close()
