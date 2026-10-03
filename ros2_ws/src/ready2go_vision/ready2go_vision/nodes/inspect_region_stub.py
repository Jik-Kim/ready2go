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
