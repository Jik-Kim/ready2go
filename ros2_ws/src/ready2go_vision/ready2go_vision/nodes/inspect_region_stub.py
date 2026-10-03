"""/vision/inspect_region stub 노드. 설정 파일의 좌표를 그대로 응답한다 (카메라·YOLO 미사용)."""
import yaml
import rclpy
from rclpy.node import Node
from ready2go_interfaces.srv import InspectRegion

from ready2go_vision.core.stub_inspect import inspect


class InspectRegionStub(Node):
    def __init__(self):
        super().__init__("inspect_region_stub")
        self.declare_parameter("config_path", "/config/vision_stub.yaml")
        path = self.get_parameter("config_path").value
        with open(path, encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        self.create_service(InspectRegion, "/vision/inspect_region", self._handle)
        self.get_logger().info(f"inspect_region stub 시작 (좌표: {path})")
        if self._config.get("ready") is not True:
            self.get_logger().warn("설정의 ready 가 true 가 아닙니다. 모든 요청이 STUB_NOT_READY 로 실패합니다 (자리표시자 좌표 차단).")

    def _handle(self, req, res):
        res.success, res.error_code, res.result_json = inspect(self._config, req.region, req.search_target)
        return res


def main():
    rclpy.init()
    node = InspectRegionStub()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
