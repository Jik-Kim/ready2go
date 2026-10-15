"""Flask와 ROS에 의존하지 않는 웹 대시보드 핵심 로직.

외부 코드는 내부 파일 위치를 알 필요 없이 이 모듈에서 공개한 클래스만 가져간다.
"""

# 촬영 JPEG 캐시와 일반 상태 캐시를 core의 공개 API로 노출한다.
from .overlay_cache import OVERLAY_REJECTION_REASONS, OverlayCache, OverlaySnapshot
from .state_cache import StateCache

# wildcard import가 내부 구현 객체를 노출하지 않도록 공개 이름을 제한한다.
__all__ = ["OVERLAY_REJECTION_REASONS", "OverlayCache", "OverlaySnapshot", "StateCache"]
