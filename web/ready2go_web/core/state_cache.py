"""ROS 콜백과 Flask 요청 사이에서 최신 상태를 안전하게 공유한다.

이 캐시는 장치 전체의 정상 여부를 추론하지 않는다. ROS 그래프에서 확인한
publisher 존재, 메시지 수신/해석 결과, 마지막 수신 시각과 오류를 분리해
저장하고 REST 응답용 스냅샷을 만든다. 주기 토픽만 명시적인 freshness timeout을
등록하며, Runner 상태처럼 오래됐다는 이유만으로 끊김으로 판단하면 안 되는
소스는 timeout 없이 등록한다. 기준: GitHub issue #267.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, Mapping


# REST와 UI가 공유할 연결 상태 문자열이다. ROS enum이나 새 공개 계약은 아니다.
UNKNOWN = "unknown"
WAITING = "waiting"
RECEIVING = "receiving"
DISCONNECTED = "disconnected"
ERROR = "error"


def _utc_now() -> datetime:
    """API에 표시할 timezone-aware UTC 현재 시각을 만든다."""
    # 로컬 시간대에 따라 응답이 달라지지 않도록 처음부터 UTC로 생성한다.
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    """datetime을 JSON에서 쓰기 쉬운 UTC ISO 8601 문자열로 바꾼다."""
    # 아직 한 번도 수신하지 않은 상태는 시각도 없으므로 null을 유지한다.
    if value is None:
        return None
    # +00:00 대신 브라우저가 바로 이해하는 Z 접미사를 사용한다.
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_aware(value: datetime) -> datetime:
    """시간대가 빠진 시각이 캐시에 섞이지 않도록 입력을 검사한다."""
    # naive datetime은 PC별 로컬 시간대로 다르게 해석될 수 있으므로 거절한다.
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at은 timezone-aware datetime이어야 합니다")
    return value


@dataclass
class _SourceState:
    """한 ROS 데이터 소스의 내부 상태다. 외부에는 snapshot 복사본만 공개한다."""

    freshness_timeout_sec: float | None  # 주기 토픽의 무수신 한계. None이면 나이 판정 안 함.
    publisher_present: bool | None = None  # True/False는 확인 결과, None은 아직 그래프 미확인.
    message_received: bool = False  # 정상 여부와 관계없이 메시지를 한 번이라도 받았는지.
    message_valid: bool = False  # 가장 최근에 받은/처리한 메시지를 정상 해석했는지.
    last_received_at: datetime | None = None  # 정상·비정상 포함 마지막 메시지의 표시용 UTC 시각.
    last_valid_received_at: datetime | None = None  # 마지막 정상 메시지의 표시용 UTC 시각.
    last_received_monotonic: float | None = None  # 시스템 시계 변경에 영향받지 않는 수신 나이 계산값.
    last_valid_monotonic: float | None = None  # stale 판정에 사용할 마지막 정상 메시지 기준값.
    message_error: str | None = None  # 최신 메시지의 JSON 형식·내용 해석 오류.
    bridge_error: str | None = None  # executor나 ROS 그래프처럼 메시지 외부의 브리지 오류.
    data: Any = None  # 마지막 정상 메시지. 비정상 메시지가 와도 진단을 위해 보존한다.
    message_revision: int = 0  # 정상·비정상 메시지 콜백이 처리될 때마다 증가하는 내부 세대 표식.


class StateCache:
    """토픽별 최신 상태를 잠금으로 보호하고 일관된 복사본을 반환한다.

    ``sources``는 ``{이름: freshness_timeout_sec}`` 매핑이다. timeout이 ``None``인
    소스는 메시지가 오래돼도 stale로 판정하지 않는다. 시간 함수 주입은 sleep
    없는 결정적 시험을 위한 것이다.
    """

    def __init__(
        self,
        sources: Mapping[str, float | None] | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = _utc_now,
    ) -> None:
        # ROS executor 콜백과 Flask 요청 스레드가 같은 캐시에 동시에 접근한다.
        # 내부 메서드가 잠금 안에서 다른 내부 메서드를 호출할 수 있어 RLock을 쓴다.
        self._lock = threading.RLock()
        # monotonic은 timeout 계산 전용이며 운영 코드에서는 time.monotonic을 사용한다.
        self._monotonic = monotonic
        # utcnow는 사용자에게 보여줄 절대 수신 시각을 만드는 함수다.
        self._utcnow = utcnow
        # 키는 runner, robot_state, camera처럼 브리지가 정한 내부 source 이름이다.
        self._sources: dict[str, _SourceState] = {}
        # 생성 시 받은 설정도 register_source의 동일한 검증 절차를 통과시킨다.
        for name, timeout in (sources or {}).items():
            self.register_source(name, freshness_timeout_sec=timeout)

    def register_source(self, name: str, *, freshness_timeout_sec: float | None = None) -> None:
        """새 상태 소스를 등록한다. 이름 중복과 잘못된 timeout은 거절한다."""
        # 빈 키는 REST 응답에서 식별할 수 없고 오타를 숨기므로 허용하지 않는다.
        if not isinstance(name, str) or not name.strip():
            raise ValueError("source 이름은 비어 있지 않은 문자열이어야 합니다")
        # Runner처럼 event/latched 성격인 소스는 None, 카메라처럼 주기적인 소스만 양수를 쓴다.
        if freshness_timeout_sec is not None:
            # bool은 int의 하위 타입이라 True가 1초로 잘못 들어오는 경우도 명시적으로 막는다.
            if isinstance(freshness_timeout_sec, bool) or freshness_timeout_sec <= 0:
                raise ValueError("freshness_timeout_sec은 0보다 커야 합니다")
            # JSON 직렬화와 계산 결과를 일정하게 유지하도록 숫자를 float로 정규화한다.
            freshness_timeout_sec = float(freshness_timeout_sec)
        # 등록과 조회가 동시에 일어나도 sources 사전이 중간 상태로 노출되지 않게 한다.
        with self._lock:
            # 같은 이름을 덮어쓰면 이전 수신 기록이 조용히 사라지므로 오류로 처리한다.
            if name in self._sources:
                raise ValueError(f"이미 등록된 source입니다: {name}")
            # 새 소스는 publisher 확인 전, 메시지 미수신 상태에서 시작한다.
            self._sources[name] = _SourceState(freshness_timeout_sec)

    def set_publisher_present(self, name: str, present: bool) -> None:
        """ROS 그래프의 publisher 여부를 기록하고 새 세대의 수신 상태를 분리한다."""
        # 0/1이나 문자열을 허용하면 확인 전 상태와 실제 bool이 섞이므로 엄격히 검사한다.
        if not isinstance(present, bool):
            raise TypeError("present는 bool이어야 합니다")
        # publisher가 사라진 동안에는 마지막 정상 데이터를 진단용으로 보존한다.
        with self._lock:
            source = self._source(name)
            # 사라졌던 publisher가 다시 발견되면 이전 endpoint/boot의 상태를 현재값으로
            # 재사용하지 않는다. 새 메시지가 도착할 때까지 snapshot은 waiting을 반환한다.
            if present and source.publisher_present is False:
                self._clear_message_state(source)
            # 메시지 콜백이 먼저 새 값을 기록한 경우 publisher_present가 이미 True이므로
            # 뒤늦은 graph poll이 그 새 메시지를 지우지 않는다.
            source.publisher_present = present

    def message_revision(self, name: str) -> int:
        """graph 관찰 사이에 새 메시지가 처리됐는지 비교할 내부 revision을 반환한다."""
        # REST 공개 필드가 아니라 publisher endpoint 교체와 콜백 경합을 구분하는 용도다.
        with self._lock:
            return self._source(name).message_revision

    def reset_for_publisher_change(self, name: str, *, expected_revision: int) -> bool:
        """endpoint 집합이 바뀌었고 이후 메시지가 없을 때만 이전 payload를 지운다."""
        # graph 조회보다 먼저 새 publisher의 콜백이 도착할 수 있으므로, 이전 graph
        # 관찰 당시 revision과 현재 revision이 같을 때만 오래된 세대로 확정한다.
        with self._lock:
            source = self._source(name)
            if source.message_revision != expected_revision:
                return False
            self._clear_message_state(source)
            return True

    @staticmethod
    def _clear_message_state(source: _SourceState) -> None:
        """publisher 세대가 바뀔 때 이전 세대의 메시지 관련 필드만 초기화한다."""
        # publisher 존재와 graph 오류는 호출자가 별도로 갱신하므로 여기서 바꾸지 않는다.
        source.message_received = False
        source.message_valid = False
        source.last_received_at = None
        source.last_valid_received_at = None
        source.last_received_monotonic = None
        source.last_valid_monotonic = None
        source.message_error = None
        source.data = None

    def record_message(
        self,
        name: str,
        data: Any,
        *,
        received_at: datetime | None = None,
    ) -> None:
        """정상 해석한 메시지를 기록하고 앞선 오류를 해제한다."""
        # wall clock은 REST 표시용이고 timezone-aware인지 즉시 확인한다.
        wall_time = _require_aware(received_at or self._utcnow())
        # monotonic clock은 NTP나 수동 시간 변경과 무관한 timeout 계산에 사용한다.
        monotonic_time = self._monotonic()
        # 콜백 호출자가 나중에 원본 dict를 수정해도 캐시가 바뀌지 않게 입력을 복사한다.
        copied = copy.deepcopy(data)
        # 관련 필드를 한 잠금 구간에서 함께 바꿔 Flask가 부분 갱신 상태를 보지 않게 한다.
        with self._lock:
            source = self._source(name)
            source.publisher_present = True  # 메시지 자체가 publisher 존재의 직접 증거다.
            source.message_received = True  # 수신 여부와 유효 여부는 별도 필드로 유지한다.
            source.message_valid = True  # 이번 메시지는 정상 파싱을 통과했다.
            source.last_received_at = wall_time  # 모든 수신 중 가장 최근 표시 시각이다.
            source.last_valid_received_at = wall_time  # 정상 수신 시각도 함께 전진한다.
            source.last_received_monotonic = monotonic_time  # 전체 수신 나이의 기준이다.
            source.last_valid_monotonic = monotonic_time  # freshness 판정의 기준이다.
            source.message_error = None  # 새 정상 메시지는 앞선 메시지 파싱 오류를 회복시킨다.
            # 그래프 조회 오류는 별도 경로가 성공해야 회복되므로 여기서 지우지 않는다.
            source.data = copied  # REST가 읽을 마지막 정상 payload를 교체한다.
            source.message_revision += 1  # graph 관찰과 콜백 순서를 비교할 내부 revision을 전진시킨다.

    def record_invalid_message(
        self,
        name: str,
        error: str,
        *,
        received_at: datetime | None = None,
    ) -> None:
        """수신했지만 해석하지 못한 메시지를 기록하고 마지막 정상 데이터는 보존한다."""
        # 빈 오류 문자열은 UI와 로그에서 원인을 설명할 수 없으므로 거절한다.
        error = self._validate_error(error)
        # 비정상 메시지도 실제 수신된 사건이므로 마지막 전체 수신 시각은 갱신한다.
        wall_time = _require_aware(received_at or self._utcnow())
        monotonic_time = self._monotonic()
        # 정상 데이터와 오류 플래그가 엇갈리지 않도록 한 번에 갱신한다.
        with self._lock:
            source = self._source(name)
            source.publisher_present = True  # 비정상 내용이어도 메시지를 보낸 publisher는 존재한다.
            source.message_received = True  # 메시지 수신 자체는 성공했다.
            source.message_valid = False  # 다만 브리지가 사용할 상태로 해석하지 못했다.
            source.last_received_at = wall_time  # 비정상 메시지 수신 시각을 진단에 남긴다.
            source.last_received_monotonic = monotonic_time  # age_sec은 마지막 전체 수신을 가리킨다.
            source.message_error = error  # REST/UI가 구체적인 파싱 실패를 표시할 수 있게 한다.
            # data와 last_valid_*는 마지막 정상 값을 보존하므로 여기서 수정하지 않는다.
            source.message_revision += 1  # 비정상 메시지도 새 publisher가 보낸 수신 사건으로 센다.

    def record_bridge_error(self, name: str, error: str) -> None:
        """executor/브리지 오류를 메시지 수신 시각과 섞지 않고 기록한다."""
        # executor 정지처럼 메시지와 무관한 오류도 빈 원인으로 기록하지 않는다.
        error = self._validate_error(error)
        # 오류 플래그만 바꾸고 마지막 ROS 수신 시각은 그대로 둔다.
        with self._lock:
            source = self._source(name)
            source.bridge_error = error  # 메시지 오류와 독립적으로 원인을 보존한다.

    def clear_bridge_error(self, name: str) -> None:
        """정상 그래프 확인 뒤 bridge 종류의 오류만 해제한다."""
        # JSON 파싱 실패(message)는 새 정상 메시지를 받아야만 회복된 것으로 처리한다.
        with self._lock:
            source = self._source(name)
            source.bridge_error = None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """REST 응답에서 수정해도 내부 상태가 변하지 않는 전체 복사본을 반환한다."""
        # 모든 source가 같은 기준 시각으로 age를 계산하도록 한 번만 읽는다.
        now = self._monotonic()
        # 전체 source를 한 잠금 구간에서 복사해 서로 다른 갱신 시점이 섞이지 않게 한다.
        with self._lock:
            return {
                name: self._snapshot_source(source, now)
                for name, source in self._sources.items()
            }

    def _snapshot_source(self, source: _SourceState, now: float) -> dict[str, Any]:
        """내부 source 상태 하나에 나이와 연결 판정을 더해 직렬화 가능한 dict로 만든다."""
        # age_sec은 정상 여부와 관계없이 마지막으로 무언가 받은 뒤 지난 시간이다.
        age_sec = None
        if source.last_received_monotonic is not None:
            # 주입된 시험 시계가 역행해도 음수 나이를 외부에 내보내지 않는다.
            age_sec = max(0.0, now - source.last_received_monotonic)

        # valid_age_sec은 마지막으로 화면에 쓸 수 있는 정상 데이터를 받은 뒤 지난 시간이다.
        valid_age_sec = None
        if source.last_valid_monotonic is not None:
            valid_age_sec = max(0.0, now - source.last_valid_monotonic)

        # timeout을 등록한 주기 소스만 마지막 정상 데이터의 freshness를 판정한다.
        stale = bool(
            source.freshness_timeout_sec is not None
            and valid_age_sec is not None
            and valid_age_sec > source.freshness_timeout_sec
        )

        # 연결 상태는 세부 원본 필드를 요약한 UI 편의 값이다.
        # 원본 publisher/message/error 필드는 응답에 함께 남겨 상태 원인을 구분한다.
        # 두 오류가 동시에 있으면 현재 브리지 통신 자체를 막는 bridge 오류를 대표값으로 쓴다.
        # 각 상세 오류도 별도 필드로 반환해 한쪽을 잃지 않는다.
        last_error = source.bridge_error or source.message_error
        last_error_kind = "bridge" if source.bridge_error else "message" if source.message_error else None

        if source.publisher_present is None:
            # ROS 그래프를 아직 확인하지 않았으면 연결 여부를 추정하지 않는다.
            connection_state = UNKNOWN
        elif not source.publisher_present:
            # 캐시 데이터가 남아 있어도 현재 publisher가 없다는 사실을 우선 표시한다.
            connection_state = DISCONNECTED
        elif last_error is not None or not source.message_valid and source.message_received:
            # publisher가 있어도 JSON 파싱 또는 브리지 오류면 정상 수신으로 보지 않는다.
            connection_state = ERROR
        elif not source.message_received:
            # publisher만 발견했고 아직 콜백이 오지 않은 상태다.
            connection_state = WAITING
        elif stale:
            # 카메라처럼 주기적인 소스가 timeout을 넘기면 무수신 단절로 표시한다.
            connection_state = DISCONNECTED
        else:
            # publisher와 정상 메시지가 있고 설정된 freshness 조건도 만족한다.
            connection_state = RECEIVING

        # datetime은 문자열로, payload는 깊은 복사로 바꿔 REST 직렬화와 내부 격리를 보장한다.
        return {
            "publisher_present": source.publisher_present,  # ROS 그래프 확인 결과.
            "message_received": source.message_received,  # 한 번이라도 콜백이 있었는지.
            "message_valid": source.message_valid,  # 최신 처리 결과가 유효한지.
            "last_received_at": _isoformat(source.last_received_at),  # 모든 메시지의 마지막 UTC 시각.
            "last_valid_received_at": _isoformat(source.last_valid_received_at),  # 정상 메시지의 마지막 UTC 시각.
            "age_sec": age_sec,  # 마지막 전체 수신 뒤 경과 초.
            "valid_age_sec": valid_age_sec,  # 마지막 정상 수신 뒤 경과 초.
            "freshness_timeout_sec": source.freshness_timeout_sec,  # 이 source에 적용한 무수신 한계.
            "stale": stale,  # 정상 데이터가 설정된 한계를 넘겼는지.
            "connection_state": connection_state,  # UI용 요약 상태.
            "last_error": last_error,  # UI에서 우선 표시할 파싱/executor 오류.
            "last_error_kind": last_error_kind,  # 대표 오류의 message 또는 bridge 분류.
            "message_error": source.message_error,  # 메시지 해석 오류를 독립 보존한다.
            "bridge_error": source.bridge_error,  # executor/그래프 오류를 독립 보존한다.
            "data": copy.deepcopy(source.data),  # 호출자가 수정 가능한 격리된 정상 payload 복사본.
        }

    def _source(self, name: str) -> _SourceState:
        """등록된 source를 반환하고 오타나 미등록 접근은 즉시 실패시킨다."""
        try:
            return self._sources[name]
        except KeyError as exc:
            # 원래 KeyError를 연결해 디버깅 정보는 보존하되 사용자에게 source 이름을 알려준다.
            raise KeyError(f"등록되지 않은 source입니다: {name}") from exc

    @staticmethod
    def _validate_error(error: str) -> str:
        """REST에 표시할 오류가 설명 가능한 비어 있지 않은 문자열인지 확인한다."""
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error는 비어 있지 않은 문자열이어야 합니다")
        # 앞뒤 공백은 진단 값의 불필요한 차이를 만들므로 제거한다.
        return error.strip()
