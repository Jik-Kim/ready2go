"""이슈 #267 웹 상태 캐시의 연결 의미와 동시성 경계를 검증한다.

실제 ROS나 Flask를 시작하지 않고 core만 시험한다. 가짜 시계를 주입해 sleep 없이
2초 무수신 경계와 장기 idle 동작을 결정적으로 확인한다.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ready2go_web.core.state_cache import StateCache


class FakeClock:
    """표시용 UTC 시각과 timeout용 monotonic 시각을 함께 전진시키는 시험 시계."""

    def __init__(self) -> None:
        # monotonic 값은 절대 시각 의미가 없으므로 계산하기 쉬운 100초에서 시작한다.
        self.elapsed = 100.0
        # REST 응답 문자열을 고정 검증할 수 있도록 UTC 기준 시각도 고정한다.
        self.wall = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        """StateCache가 수신 나이와 timeout을 계산할 때 읽는 값."""
        return self.elapsed

    def utcnow(self) -> datetime:
        """StateCache가 사용자 표시용 수신 시각을 기록할 때 읽는 값."""
        return self.wall

    def advance(self, seconds: float) -> None:
        """sleep 없이 두 종류의 시험 시계를 같은 시간만큼 전진시킨다."""
        self.elapsed += seconds
        self.wall += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    """각 시험이 다른 시험의 시간 진행에 영향을 받지 않도록 새 시계를 제공한다."""
    return FakeClock()


def make_cache(clock: FakeClock, **sources: float | None) -> StateCache:
    """키워드 인자를 source 설정으로 바꾸고 같은 가짜 시계를 주입한다."""
    return StateCache(sources, monotonic=clock.monotonic, utcnow=clock.utcnow)


def test_initial_state_separates_unknown_publisher_from_message_receipt(clock: FakeClock) -> None:
    """그래프 미확인과 메시지 미수신을 같은 값으로 합치지 않는다."""
    # Runner는 메시지 나이 timeout을 사용하지 않으므로 None으로 등록한다.
    cache = make_cache(clock, runner=None)

    # 등록 직후 아무 ROS 관측도 하지 않은 초기 스냅샷을 읽는다.
    state = cache.snapshot()["runner"]

    # publisher 미확인, 메시지 미수신, 시각 없음이 각각 독립적으로 유지돼야 한다.
    assert state["publisher_present"] is None
    assert state["message_received"] is False
    assert state["message_valid"] is False
    assert state["connection_state"] == "unknown"
    assert state["last_received_at"] is None


def test_publisher_without_message_is_waiting(clock: FakeClock) -> None:
    """publisher 발견만으로 유효 상태 수신 완료라고 표시하지 않는다."""
    cache = make_cache(clock, runner=None)

    # ROS 그래프에서는 publisher를 봤지만 구독 콜백은 아직 오지 않은 상황이다.
    cache.set_publisher_present("runner", True)

    # UI 요약 상태는 receiving이 아니라 waiting이어야 한다.
    state = cache.snapshot()["runner"]
    assert state["publisher_present"] is True
    assert state["connection_state"] == "waiting"


def test_valid_message_is_copied_on_write_and_snapshot(clock: FakeClock) -> None:
    """호출자와 REST 응답의 변경이 내부 캐시 payload를 훼손하지 않는다."""
    cache = make_cache(clock, runner=None)
    # 중첩 객체까지 복사되는지 보기 위해 last.run_id를 포함한다.
    payload = {"phase": "running", "last": {"run_id": "run-1"}}

    # 정상 메시지를 기록한 뒤 원본 객체와 첫 스냅샷을 의도적으로 수정한다.
    cache.record_message("runner", payload)
    payload["last"]["run_id"] = "changed-outside"
    first = cache.snapshot()
    first["runner"]["data"]["last"]["run_id"] = "changed-snapshot"
    # 두 외부 수정 뒤 새 스냅샷을 만들어 내부 값이 보존됐는지 확인한다.
    second = cache.snapshot()["runner"]

    # 정상 메시지는 publisher 직접 증거이며 receiving 상태와 고정 UTC 시각을 만든다.
    assert second["publisher_present"] is True
    assert second["message_valid"] is True
    assert second["connection_state"] == "receiving"
    assert second["last_received_at"] == "2026-10-13T04:00:00Z"
    assert second["data"]["last"]["run_id"] == "run-1"


def test_invalid_message_reports_error_and_preserves_last_valid_data(clock: FakeClock) -> None:
    """잘못된 JSON은 오류로 표시하되 마지막 정상 상태를 진단용으로 보존한다."""
    cache = make_cache(clock, runner=None)
    # 먼저 화면에 쓸 수 있는 정상 idle 상태를 기록한다.
    cache.record_message("runner", {"phase": "idle"})
    # 다음 비정상 메시지의 수신 시각을 구분하기 위해 1초 전진한다.
    clock.advance(1.0)

    # ROS 메시지는 도착했지만 JSON 해석이 실패한 상황을 기록한다.
    cache.record_invalid_message("runner", "JSON decode failed")

    # 최신 메시지는 invalid/error이고 정상 데이터와 정상 수신 시각은 이전 값이어야 한다.
    state = cache.snapshot()["runner"]
    assert state["message_received"] is True
    assert state["message_valid"] is False
    assert state["connection_state"] == "error"
    assert state["last_error"] == "JSON decode failed"
    assert state["last_received_at"] == "2026-10-13T04:00:01Z"
    assert state["last_valid_received_at"] == "2026-10-13T04:00:00Z"
    assert state["data"] == {"phase": "idle"}


def test_periodic_source_becomes_stale_after_configured_timeout(clock: FakeClock) -> None:
    """카메라 같은 주기 토픽은 설정한 무수신 경계를 넘은 뒤 끊김이 된다."""
    # 이슈 #267의 카메라 기준처럼 2초 timeout을 설정한다.
    cache = make_cache(clock, camera=2.0)
    cache.record_message("camera", {"frame_id": "wrist_cam"})

    # 경계와 정확히 같은 2초는 아직 허용한다.
    clock.advance(2.0)
    assert cache.snapshot()["camera"]["connection_state"] == "receiving"

    # 경계를 1ms 넘긴 순간 stale과 disconnected가 함께 표시돼야 한다.
    clock.advance(0.001)
    state = cache.snapshot()["camera"]
    assert state["stale"] is True
    assert state["connection_state"] == "disconnected"
    assert state["valid_age_sec"] == pytest.approx(2.001)


def test_source_without_timeout_is_not_disconnected_only_because_message_is_old(clock: FakeClock) -> None:
    """Runner 상태는 장시간 변화가 없어도 메시지 나이만으로 끊김 처리하지 않는다."""
    cache = make_cache(clock, runner=None)
    cache.record_message("runner", {"phase": "idle"})

    # 하루 동안 새 상태 변경이 없는 장기 idle을 모의한다.
    clock.advance(24 * 60 * 60)

    # timeout을 등록하지 않았으므로 오래됐다는 이유만으로 stale/disconnected가 되면 안 된다.
    state = cache.snapshot()["runner"]
    assert state["stale"] is False
    assert state["connection_state"] == "receiving"


def test_publisher_disappearance_is_distinct_from_cached_data(clock: FakeClock) -> None:
    """publisher가 사라져도 마지막 정상 데이터 자체는 진단용으로 남긴다."""
    cache = make_cache(clock, runner=None)
    cache.record_message("runner", {"phase": "idle"})

    # 정상 상태를 받은 뒤 ROS 그래프에서 publisher가 사라진 상황이다.
    cache.set_publisher_present("runner", False)

    # 연결은 끊김이지만 마지막 데이터와 당시 유효성은 별도 필드로 보존한다.
    state = cache.snapshot()["runner"]
    assert state["connection_state"] == "disconnected"
    assert state["message_valid"] is True
    assert state["data"] == {"phase": "idle"}


def test_bridge_error_does_not_change_last_received_time(clock: FakeClock) -> None:
    """executor 오류를 ROS 메시지 수신 사건으로 잘못 기록하지 않는다."""
    cache = make_cache(clock, robot_state=None)
    cache.record_message("robot_state", {"drawer": "closed"})
    # 오류 전 실제 ROS 수신 시각을 비교 기준으로 저장한다.
    before = cache.snapshot()["robot_state"]["last_received_at"]
    clock.advance(5.0)

    # 5초 뒤 executor 오류가 났지만 새 ROS 메시지가 도착한 것은 아니다.
    cache.record_bridge_error("robot_state", "executor stopped")

    # 오류는 보이되 last_received_at은 정상 메시지 시각 그대로여야 한다.
    state = cache.snapshot()["robot_state"]
    assert state["connection_state"] == "error"
    assert state["last_error"] == "executor stopped"
    assert state["last_error_kind"] == "bridge"
    assert state["last_received_at"] == before


def test_graph_recovery_clears_only_bridge_error(clock: FakeClock) -> None:
    """그래프 조회 성공은 executor 오류만 해제하고 JSON 파싱 오류는 보존한다."""
    cache = make_cache(clock, runner=None)
    cache.record_message("runner", {"phase": "idle"})

    # executor 오류는 다음 정상 그래프 확인으로 회복 가능한 bridge 오류다.
    cache.record_bridge_error("runner", "graph query failed")
    cache.clear_bridge_error("runner")
    assert cache.snapshot()["runner"]["last_error"] is None

    # 잘못된 JSON은 그래프가 정상이어도 새 정상 메시지를 받기 전까지 남아야 한다.
    cache.record_invalid_message("runner", "JSON decode failed")
    cache.clear_bridge_error("runner")
    state = cache.snapshot()["runner"]
    assert state["last_error"] == "JSON decode failed"
    assert state["last_error_kind"] == "message"


def test_concurrent_updates_and_snapshots_never_expose_torn_payload(clock: FakeClock) -> None:
    """ROS 쓰기와 REST 읽기가 겹쳐도 서로 다른 갱신의 필드가 섞이지 않는다."""
    cache = make_cache(clock, runner=None)
    # sequence와 mirror는 항상 같은 값으로 한 메시지에서 함께 기록한다.
    cache.record_message("runner", {"sequence": 0, "mirror": 0})

    def write_messages() -> None:
        """ROS 콜백 역할로 연속된 정상 메시지를 캐시에 쓴다."""
        for sequence in range(1, 500):
            cache.record_message("runner", {"sequence": sequence, "mirror": sequence})

    def read_snapshots() -> None:
        """Flask 요청 역할로 스냅샷을 반복 조회하고 찢어진 payload를 찾는다."""
        for _ in range(500):
            payload = cache.snapshot()["runner"]["data"]
            # 잠금이 없다면 두 필드가 서로 다른 갱신에서 보일 수 있다.
            assert payload["sequence"] == payload["mirror"]

    # 쓰기 1개와 읽기 3개를 실제 스레드에서 동시에 실행한다.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(write_messages)]
        futures.extend(executor.submit(read_snapshots) for _ in range(3))
        # worker 안의 assertion 실패도 메인 시험에서 반드시 다시 발생시킨다.
        for future in futures:
            future.result()


@pytest.mark.parametrize("timeout", [0, -1, True])
def test_invalid_timeout_is_rejected(timeout: object) -> None:
    """0·음수·bool이 실수로 유효한 timeout 설정이 되는 것을 막는다."""
    # 설정 오류는 실행 뒤 잘못된 연결 판정보다 시작 시 명시적 실패가 안전하다.
    with pytest.raises(ValueError, match="0보다 커야"):
        StateCache({"camera": timeout})  # type: ignore[arg-type]


def test_unknown_source_is_rejected(clock: FakeClock) -> None:
    """source 이름 오타가 새 캐시 항목을 조용히 만들지 않게 한다."""
    cache = make_cache(clock, runner=None)

    # camera를 등록하지 않았으므로 기록 시 즉시 KeyError가 나야 한다.
    with pytest.raises(KeyError, match="등록되지 않은 source"):
        cache.record_message("camera", {})


def test_naive_received_time_is_rejected(clock: FakeClock) -> None:
    """시간대가 없는 datetime이 PC마다 다르게 해석되는 것을 막는다."""
    cache = make_cache(clock, runner=None)

    # tzinfo가 없는 시각은 UTC인지 로컬인지 알 수 없으므로 기록하지 않는다.
    with pytest.raises(ValueError, match="timezone-aware"):
        cache.record_message("runner", {}, received_at=datetime(2026, 10, 13, 4, 0))


@pytest.mark.parametrize("name", ["", "   ", 1])
def test_invalid_source_name_is_rejected(name: object) -> None:
    """빈 문자열·공백·문자열이 아닌 source 이름을 등록하지 않는다."""
    cache = StateCache()

    # 잘못된 키가 REST 응답 구조에 들어가기 전에 등록 단계에서 실패해야 한다.
    with pytest.raises(ValueError, match="비어 있지 않은 문자열"):
        cache.register_source(name)  # type: ignore[arg-type]


def test_duplicate_source_registration_is_rejected(clock: FakeClock) -> None:
    """같은 source 재등록으로 기존 수신 데이터가 조용히 초기화되지 않게 한다."""
    cache = make_cache(clock, runner=None)

    # 이미 등록된 runner를 다시 등록하면 명시적인 설정 오류가 발생해야 한다.
    with pytest.raises(ValueError, match="이미 등록된 source"):
        cache.register_source("runner")


def test_publisher_presence_requires_real_bool(clock: FakeClock) -> None:
    """정수나 문자열이 publisher 확인 결과로 섞이는 것을 거절한다."""
    cache = make_cache(clock, runner=None)

    # bool과 값이 비슷한 정수 1도 허용하지 않아 API 형식을 일정하게 유지한다.
    with pytest.raises(TypeError, match="bool"):
        cache.set_publisher_present("runner", 1)  # type: ignore[arg-type]


@pytest.mark.parametrize("error", ["", "   ", None])
def test_empty_error_description_is_rejected(clock: FakeClock, error: object) -> None:
    """UI에 원인을 설명할 수 없는 빈 오류 기록을 만들지 않는다."""
    cache = make_cache(clock, runner=None)

    # message와 bridge 오류가 공통 validator를 사용하므로 한 공개 경로로 검증한다.
    with pytest.raises(ValueError, match="비어 있지 않은 문자열"):
        cache.record_bridge_error("runner", error)  # type: ignore[arg-type]
