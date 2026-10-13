"""ROS 2와 웹 core를 연결하는 rclpy 노드 모음.

후속 Flask 서버는 이 모듈에서 공개한 DashboardBridge 하나만 생성하고 별도
executor에서 spin한다. REST 요청마다 새 노드를 만들지 않는다.
"""

# 외부 실행 코드가 노드 구현 파일 경로에 의존하지 않도록 공개 클래스를 모은다.
from .dashboard_bridge import BridgeTopics, DashboardBridge

# wildcard import로 테스트 helper나 내부 상수가 노출되지 않게 제한한다.
__all__ = ["BridgeTopics", "DashboardBridge"]

