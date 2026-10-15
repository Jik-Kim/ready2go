"""이슈 #348 촬영 결과 JPEG 한 장을 스레드 안전하게 보관한다.

이 모듈은 ROS 메시지와 Flask 응답을 알지 못한다. ROS 콜백은 메시지에서 꺼낸
JPEG와 촬영 시각을 기록하고, Flask 요청은 불변 스냅샷이나 JSON용 메타데이터를
읽는다. 수신 순서가 뒤바뀌어도 과거 촬영이 최신 사진을 덮지 않도록 촬영 시각을
정렬 기준으로 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import threading
from typing import Callable


def _utc_now() -> datetime:
    """운영 코드에서 웹 수신 시각으로 사용할 UTC 현재 시각을 만든다."""
    # 로컬 시간대가 달라도 같은 절대 시각을 기록하도록 timezone-aware UTC를 쓴다.
    return datetime.now(timezone.utc)


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    """PC마다 다르게 해석될 수 있는 timezone-naive 시각을 거절한다."""
    # tzinfo만 있고 UTC offset을 계산하지 못하는 객체도 naive 시각과 같이 취급한다.
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}은 timezone-aware datetime이어야 합니다")
    # 캐시 내부의 절대 시각 표현을 하나로 맞춰 비교와 직렬화를 단순하게 만든다.
    return value.astimezone(timezone.utc)


def _validate_stamp(sec: int, nanosec: int) -> tuple[int, int]:
    """ROS ``builtin_interfaces/Time``과 같은 초·나노초 쌍을 검사한다."""
    # bool은 int의 하위 타입이므로 True가 1초로 들어오는 경우를 별도로 막는다.
    if isinstance(sec, bool) or not isinstance(sec, int):
        raise TypeError("captured_stamp_sec은 정수여야 합니다")
    # nanosec도 정수만 허용하고 ROS Time의 정규화 범위를 강제한다.
    if isinstance(nanosec, bool) or not isinstance(nanosec, int):
        raise TypeError("captured_stamp_nanosec은 정수여야 합니다")
    # 10억 나노초는 다음 초로 정규화돼야 하므로 이 범위 밖 값은 입력 오류다.
    if nanosec < 0 or nanosec >= 1_000_000_000:
        raise ValueError("captured_stamp_nanosec은 0 이상 1000000000 미만이어야 합니다")
    return sec, nanosec


def _stamp_as_datetime(sec: int, nanosec: int) -> datetime:
    """촬영 stamp를 API 표시용 UTC datetime으로 변환한다."""
    # datetime은 마이크로초 정밀도이므로 원본 나노초는 metadata의 stamp에 따로 보존한다.
    return datetime.fromtimestamp(sec, timezone.utc).replace(microsecond=nanosec // 1_000)


def _isoformat_utc(value: datetime) -> str:
    """브라우저가 읽기 쉬운 UTC ISO 8601 문자열을 만든다."""
    # +00:00을 동일한 의미의 짧은 Z 접미사로 바꾼다.
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class OverlaySnapshot:
    """한 번 수신한 촬영 결과의 외부 공개용 불변 스냅샷이다."""

    jpeg: bytes  # Flask 이미지 응답이 그대로 반환할 불변 JPEG 바이트다.
    captured_stamp_sec: int  # 카메라 컬러 프레임 header.stamp의 초 부분이다.
    captured_stamp_nanosec: int  # 같은 stamp의 나노초 부분이다.
    received_at: datetime  # 웹 브리지가 메시지를 받은 timezone-aware UTC 시각이다.
    frame_id: str  # 촬영에 사용한 카메라 컬러 프레임 ID다.
    revision: int  # 정상 교체 때만 증가하는 브라우저 캐시 무효화 번호다.


class OverlayCache:
    """최신 촬영 JPEG 한 장을 촬영 시각 순서로 보관한다."""

    def __init__(self, *, utcnow: Callable[[], datetime] = _utc_now) -> None:
        # ROS executor 콜백과 Flask 요청 스레드가 같은 객체에 동시에 접근한다.
        self._lock = threading.RLock()
        # 시험에서 sleep 없이 수신 시각을 고정할 수 있도록 현재 시각 함수를 주입받는다.
        self._utcnow = utcnow
        # 촬영 결과가 오기 전에는 명시적으로 None을 유지해 빈 상태를 구분한다.
        self._latest: OverlaySnapshot | None = None
        # revision은 사진이 실제로 교체된 횟수이며 최초 저장 결과는 1이 된다.
        self._revision = 0

    def update(
        self,
        jpeg: bytes | bytearray | memoryview,
        captured_stamp_sec: int,
        captured_stamp_nanosec: int,
        received_at: datetime | None,
        frame_id: str,
    ) -> bool:
        """더 최신인 촬영 결과만 저장하고 실제 교체 여부를 반환한다."""
        # bytearray와 memoryview도 받되 저장 전 bytes로 복사해 호출자의 변경을 차단한다.
        if not isinstance(jpeg, (bytes, bytearray, memoryview)):
            raise TypeError("jpeg는 bytes 계열이어야 합니다")
        jpeg_bytes = bytes(jpeg)
        # 빈 payload는 표시 가능한 사진이 아니므로 현재 정상 사진을 지우지 않고 무시한다.
        if not jpeg_bytes:
            return False

        # 잘못된 stamp는 정렬 기준을 훼손하므로 잠금을 잡기 전에 즉시 거절한다.
        stamp = _validate_stamp(captured_stamp_sec, captured_stamp_nanosec)
        # 호출자가 생략하면 수신 순간의 UTC를 사용하고, 전달값은 timezone 여부를 검사한다.
        received = _require_aware(received_at or self._utcnow(), field_name="received_at")
        # frame_id는 촬영 기준 프레임을 식별해야 하므로 빈 문자열이나 다른 타입을 허용하지 않는다.
        if not isinstance(frame_id, str) or not frame_id.strip():
            raise ValueError("frame_id는 비어 있지 않은 문자열이어야 합니다")
        with self._lock:
            # 기존 사진의 촬영 stamp를 새 stamp와 같은 튜플 형식으로 만든다.
            latest_stamp = (
                None
                if self._latest is None
                else (self._latest.captured_stamp_sec, self._latest.captured_stamp_nanosec)
            )
            # 늦게 도착한 과거 사진과 같은 촬영의 중복 메시지는 최신 사진을 덮지 않는다.
            if latest_stamp is not None and stamp <= latest_stamp:
                return False

            # 실제로 최신 사진이 교체될 때만 revision을 증가시킨다.
            self._revision += 1
            # 검증·복사가 끝난 값만 한 번에 대입해 조회자가 절반 갱신된 상태를 보지 않게 한다.
            self._latest = OverlaySnapshot(
                jpeg=jpeg_bytes,
                captured_stamp_sec=stamp[0],
                captured_stamp_nanosec=stamp[1],
                received_at=received,
                frame_id=frame_id,
                revision=self._revision,
            )
            return True

    def clear(self) -> None:
        """현재 사진을 제거하되 다음 사진의 revision은 계속 증가하게 한다."""
        with self._lock:
            # Runtime 재기동 사이에 이전 기동 사진을 제공하지 않도록 스냅샷만 비운다.
            # revision을 되돌리면 브라우저가 과거 URL의 이미지를 재사용할 수 있으므로 유지한다.
            self._latest = None

    def get_latest(self) -> OverlaySnapshot | None:
        """현재 최신 사진을 새 불변 스냅샷으로 반환한다."""
        with self._lock:
            # 빈 상태는 API의 404 판단에 사용할 수 있도록 None을 그대로 반환한다.
            if self._latest is None:
                return None
            # 내부에서 가진 인스턴스 자체를 노출하지 않고 값이 같은 새 객체를 반환한다.
            return replace(self._latest)

    def get_metadata(
        self,
        now: datetime | None = None,
        stale_after_sec: float | None = None,
        *,
        capture_time_is_utc: bool = False,
    ) -> dict[str, object]:
        """JPEG를 제외한 REST 직렬화용 촬영 메타데이터를 반환한다.

        ``now``는 웹 서버의 UTC 시각이다. 카메라 stamp도 같은 UTC wall clock이라는
        근거가 있을 때만 ``capture_time_is_utc=True``로 촬영 시각·나이를 계산한다.
        sim time처럼 기준이 다르면 원본 stamp만 제공하고 파생 시각·나이는 ``None``이다.
        오래됨 기준이 미확정이면 ``stale_after_sec=None``으로 둔다.
        """
        # 수신 나이와 촬영 나이를 같은 조회 시점에서 계산하도록 now를 한 번만 읽는다.
        current = _require_aware(now or self._utcnow(), field_name="now")
        # 0·음수·bool이 실수로 오래됨 기준으로 적용되지 않게 설정값을 검증한다.
        if stale_after_sec is not None:
            if isinstance(stale_after_sec, bool) or stale_after_sec <= 0:
                raise ValueError("stale_after_sec은 0보다 커야 합니다")
            stale_after_sec = float(stale_after_sec)
        if not isinstance(capture_time_is_utc, bool):
            raise TypeError("capture_time_is_utc는 bool이어야 합니다")

        # 잠금 구간을 짧게 유지하기 위해 불변 복사본을 얻은 뒤 시간 계산을 수행한다.
        latest = self.get_latest()
        if latest is None:
            # 빈 상태도 고정된 키를 반환해 REST와 UI가 조건마다 다른 구조를 처리하지 않게 한다.
            return {
                "image_available": False,
                "captured_stamp": None,
                "captured_at": None,
                "received_at": None,
                "capture_age_sec": None,
                "receive_age_sec": None,
                "frame_id": None,
                "revision": 0,
                "stale_after_sec": stale_after_sec,
                "stale": False,
            }

        # UTC wall clock이라는 근거가 없으면 sim stamp를 1970년 시각으로 오해하지 않는다.
        captured_at = (
            _stamp_as_datetime(latest.captured_stamp_sec, latest.captured_stamp_nanosec)
            if capture_time_is_utc
            else None
        )
        # PC 시계와 같은 기준일 때만 경과 시간을 계산하며 음수 값은 노출하지 않는다.
        capture_age_sec = (
            max(0.0, (current - captured_at).total_seconds())
            if captured_at is not None
            else None
        )
        # 웹 수신 나이는 ROS stamp가 아니라 실제 브리지 수신 시각을 기준으로 별도 계산한다.
        receive_age_sec = max(0.0, (current - latest.received_at).total_seconds())
        # 기준이 합의되지 않은 None 상태에서는 사진을 임의로 오래됐다고 판정하지 않는다.
        stale = bool(
            stale_after_sec is not None
            and capture_age_sec is not None
            and capture_age_sec > stale_after_sec
        )

        return {
            "image_available": True,
            "captured_stamp": {
                "sec": latest.captured_stamp_sec,
                "nanosec": latest.captured_stamp_nanosec,
            },
            "captured_at": _isoformat_utc(captured_at) if captured_at is not None else None,
            "received_at": _isoformat_utc(latest.received_at),
            "capture_age_sec": capture_age_sec,
            "receive_age_sec": receive_age_sec,
            "frame_id": latest.frame_id,
            "revision": latest.revision,
            "stale_after_sec": stale_after_sec,
            "stale": stale,
        }
