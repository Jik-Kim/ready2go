"""이슈 #348 웹 촬영 사진 캐시의 정렬·격리·동시성 경계를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from ready2go_web.core.overlay_cache import OverlayCache


# 모든 시험이 같은 절대 시각을 사용해 나이와 ISO 문자열을 결정적으로 검증한다.
BASE_TIME = datetime(2026, 10, 14, 6, 30, tzinfo=timezone.utc)


def make_cache() -> OverlayCache:
    """기본 수신 시각을 고정한 새 캐시를 만든다."""
    # received_at을 생략하는 시험도 실제 시스템 시각에 의존하지 않게 한다.
    return OverlayCache(utcnow=lambda: BASE_TIME)


def test_initial_cache_has_no_image_or_binary_metadata() -> None:
    """촬영 전 상태는 이미지 없음과 고정된 JSON 구조를 반환한다."""
    cache = make_cache()

    # 사진이 한 번도 기록되지 않은 조회와 메타데이터를 확인한다.
    latest = cache.get_latest()
    metadata = cache.get_metadata(BASE_TIME)

    # 이미지 API는 None으로 404를 판단하고 상태 API는 revision 0을 사용할 수 있어야 한다.
    assert latest is None
    assert metadata["image_available"] is False
    assert metadata["revision"] == 0
    assert metadata["captured_at"] is None
    # 상태 JSON에 큰 JPEG나 다른 bytes 값이 섞이지 않았는지도 함께 보장한다.
    assert not any(isinstance(value, bytes) for value in metadata.values())


def test_first_image_is_copied_and_returned_as_an_immutable_snapshot() -> None:
    """호출자가 원본 버퍼를 바꿔도 저장된 JPEG와 스냅샷은 변하지 않는다."""
    cache = make_cache()
    # 변경 가능한 bytearray를 사용해 캐시가 저장 전에 bytes 복사를 하는지 확인한다.
    original = bytearray(b"jpeg-first")

    # 최초 사진은 revision 1로 정상 저장돼야 한다.
    stored = cache.update(original, 1_760_422_200, 123_456_789, BASE_TIME, "camera_color")
    original[:] = b"changed-out"
    first = cache.get_latest()
    second = cache.get_latest()

    assert stored is True
    assert first is not None
    assert first.jpeg == b"jpeg-first"
    assert first.revision == 1
    # 조회마다 같은 내부 객체를 직접 내보내지 않고 값이 같은 새 스냅샷을 반환한다.
    assert second == first
    assert second is not first
    # frozen dataclass이므로 Flask 쪽 코드도 캐시 값을 실수로 수정할 수 없다.
    with pytest.raises(FrozenInstanceError):
        first.revision = 99  # type: ignore[misc]


def test_newer_capture_replaces_image_and_increments_revision() -> None:
    """수신 간격이 아니라 촬영 stamp가 더 최신일 때만 사진을 교체한다."""
    cache = make_cache()
    cache.update(b"jpeg-1", 100, 900, BASE_TIME, "camera_color")

    # 초가 같아도 nanosec이 큰 두 번째 촬영은 더 최신이다.
    stored = cache.update(b"jpeg-2", 100, 901, BASE_TIME + timedelta(seconds=3), "camera_color")
    latest = cache.get_latest()

    assert stored is True
    assert latest is not None
    assert latest.jpeg == b"jpeg-2"
    assert latest.captured_stamp_nanosec == 901
    assert latest.received_at == BASE_TIME + timedelta(seconds=3)
    assert latest.revision == 2


@pytest.mark.parametrize("sec,nanosec", [(99, 999_999_999), (100, 899), (100, 900)])
def test_older_or_duplicate_capture_does_not_replace_latest(sec: int, nanosec: int) -> None:
    """늦게 도착한 과거 사진과 같은 촬영의 중복 메시지를 무시한다."""
    cache = make_cache()
    cache.update(b"current", 100, 900, BASE_TIME, "camera_color")

    # 더 늦게 수신됐더라도 촬영 stamp가 이전 값 이하이면 저장하지 않는다.
    stored = cache.update(b"late", sec, nanosec, BASE_TIME + timedelta(minutes=1), "camera_color")
    latest = cache.get_latest()

    assert stored is False
    assert latest is not None
    assert latest.jpeg == b"current"
    assert latest.received_at == BASE_TIME
    assert latest.revision == 1


def test_empty_jpeg_is_ignored_without_erasing_current_image() -> None:
    """빈 payload가 기존 정상 촬영 사진을 지우지 않는다."""
    cache = make_cache()
    cache.update(b"current", 100, 0, BASE_TIME, "camera_color")

    # stamp가 더 최신이어도 표시할 JPEG가 없으면 갱신으로 인정하지 않는다.
    stored = cache.update(b"", 101, 0, BASE_TIME + timedelta(seconds=1), "camera_color")
    latest = cache.get_latest()

    assert stored is False
    assert latest is not None
    assert latest.jpeg == b"current"
    assert latest.revision == 1


def test_metadata_separates_capture_time_from_web_receipt_time() -> None:
    """늦게 받은 과거 촬영을 방금 촬영한 사진처럼 표시하지 않는다."""
    cache = make_cache()
    # 촬영은 20분 전이고 웹 수신은 3초 전인 상황을 만든다.
    captured_at = BASE_TIME - timedelta(minutes=20)
    received_at = BASE_TIME - timedelta(seconds=3)
    cache.update(
        b"jpeg",
        int(captured_at.timestamp()),
        500_000_000,
        received_at,
        "wrist_cam_color_optical_frame",
    )

    # 합의 전 기본값 None과 임시 10분 기준을 각각 조회한다.
    undecided = cache.get_metadata(BASE_TIME, capture_time_is_utc=True)
    decided = cache.get_metadata(BASE_TIME, stale_after_sec=600, capture_time_is_utc=True)

    assert undecided["image_available"] is True
    assert undecided["capture_age_sec"] == pytest.approx(1_199.5)
    assert undecided["receive_age_sec"] == pytest.approx(3.0)
    assert undecided["stale_after_sec"] is None
    assert undecided["stale"] is False
    assert decided["stale_after_sec"] == 600.0
    assert decided["stale"] is True
    assert decided["received_at"] == "2026-10-14T06:29:57Z"
    assert decided["captured_stamp"] == {
        "sec": int(captured_at.timestamp()),
        "nanosec": 500_000_000,
    }
    # JSON 메타데이터에는 JPEG 본문을 넣지 않는다.
    assert "jpeg" not in decided


def test_non_utc_capture_clock_does_not_create_misleading_wall_time_or_age() -> None:
    """sim stamp를 1970년 UTC나 매우 오래된 사진으로 잘못 표시하지 않는다."""
    cache = make_cache()
    cache.update(b"sim-jpeg", 15, 0, BASE_TIME, "camera_color")

    metadata = cache.get_metadata(BASE_TIME, stale_after_sec=10)

    assert metadata["captured_stamp"] == {"sec": 15, "nanosec": 0}
    assert metadata["captured_at"] is None
    assert metadata["capture_age_sec"] is None
    assert metadata["receive_age_sec"] == pytest.approx(0.0)
    assert metadata["stale"] is False


def test_lower_capture_stamp_never_replaces_current_image() -> None:
    """publisher 기동과 관계없이 UTC 촬영 시각이 과거이면 현재 사진을 유지한다."""
    cache = make_cache()
    cache.update(b"current", 100, 0, BASE_TIME, "camera_color")

    stored = cache.update(
        b"late-old-capture",
        1,
        0,
        BASE_TIME + timedelta(seconds=1),
        "camera_color",
    )
    latest = cache.get_latest()

    assert stored is False
    assert latest is not None
    assert latest.jpeg == b"current"
    assert latest.captured_stamp_sec == 100
    assert latest.revision == 1


def test_clear_removes_image_without_reusing_revision() -> None:
    """Runtime 종료용 초기화가 사진을 비우고 다음 URL revision은 새 값으로 만든다."""
    cache = make_cache()
    cache.update(b"before-restart", 100, 0, BASE_TIME, "camera_color")

    cache.clear()

    assert cache.get_latest() is None
    assert cache.get_metadata(BASE_TIME)["image_available"] is False
    assert cache.update(b"after-restart", 101, 0, BASE_TIME, "camera_color") is True
    assert cache.get_latest().revision == 2


def test_concurrent_updates_keep_the_newest_capture_stamp() -> None:
    """여러 ROS 콜백이 겹쳐도 가장 최신 촬영 한 장만 남긴다."""
    cache = make_cache()

    def update(sequence: int) -> bool:
        """각 worker가 서로 다른 촬영 stamp와 JPEG를 기록한다."""
        return cache.update(
            f"jpeg-{sequence}".encode(),
            sequence,
            sequence,
            BASE_TIME + timedelta(seconds=sequence),
            "camera_color",
        )

    # 완료 순서를 보장하지 않는 실제 스레드에서 1부터 100까지 동시에 갱신한다.
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(update, range(1, 101)))

    latest = cache.get_latest()
    assert latest is not None
    assert latest.captured_stamp_sec == 100
    assert latest.captured_stamp_nanosec == 100
    assert latest.jpeg == b"jpeg-100"


@pytest.mark.parametrize(
    "sec,nanosec,error_type",
    [(True, 0, TypeError), (1, True, TypeError), (1, -1, ValueError), (1, 1_000_000_000, ValueError)],
)
def test_invalid_capture_stamp_is_rejected(
    sec: object,
    nanosec: object,
    error_type: type[Exception],
) -> None:
    """잘못된 촬영 stamp가 최신 사진 정렬 기준에 들어가지 않게 한다."""
    cache = make_cache()

    with pytest.raises(error_type):
        cache.update(b"jpeg", sec, nanosec, BASE_TIME, "camera_color")  # type: ignore[arg-type]


def test_naive_time_and_invalid_stale_threshold_are_rejected() -> None:
    """시간대가 불명확한 시각과 잘못된 오래됨 기준을 조용히 수용하지 않는다."""
    cache = make_cache()

    with pytest.raises(ValueError, match="timezone-aware"):
        cache.update(b"jpeg", 100, 0, datetime(2026, 10, 14, 6, 30), "camera_color")
    with pytest.raises(ValueError, match="0보다 커야"):
        cache.get_metadata(BASE_TIME, stale_after_sec=0)
