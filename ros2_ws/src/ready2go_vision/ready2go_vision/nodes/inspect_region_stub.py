"""/vision/inspect_region stub 노드. 설정 파일의 좌표를 그대로 응답한다 (카메라·YOLO 미사용)."""
import yaml
import rclpy
from rclpy.node import Node
from ready2go_interfaces.srv import InspectRegion

from ready2go_vision.core.stub_inspect import format_request, format_response, inspect, validate_config


class InspectRegionStub(Node):
    def __init__(self):
        super().__init__("inspect_region_stub")
        self.declare_parameter("config_path", "/config/vision_stub.yaml")
        self.declare_parameter("places_path", "/config/places.yaml")      # 서랍 내부 범위(interior_m) — 위치 검사용
        path = self.get_parameter("config_path").value
        with open(path, encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        with open(self.get_parameter("places_path").value, encoding="utf-8") as f:
            places = yaml.safe_load(f)
        self._interiors = {k: v["interior_m"][:2] for k, v in places.items() if isinstance(v, dict) and v.get("interior_m")}
        self.create_service(InspectRegion, "/vision/inspect_region", self._handle)
        self.get_logger().info(f"inspect_region stub 시작 (좌표: {path})")
        if self._config.get("ready") is not True:
            self.get_logger().warn("설정의 ready 가 true 가 아닙니다. 모든 요청이 STUB_NOT_READY 로 실패합니다 (자리표시자 좌표 차단).")
        else:
            errs = validate_config(self._config, self._interiors)
            if errs:
                self.get_logger().error("설정이 실측 규칙을 어깁니다. 모든 요청이 CONFIG_INVALID 로 실패합니다: " + "; ".join(errs))

    def _handle(self, req, res):
        log = self.get_logger()
        log.info(format_request(req.region, req.search_target))
        res.success, res.error_code, res.result_json = inspect(self._config, req.region, req.search_target, self._interiors)
        line = format_response(req.region, req.search_target, res.success, res.error_code, res.result_json)
        if res.success:                                  # 미발견도 정상 응답이라 info
            log.info(line)
        else:                                            # rclpy 는 한 호출 위치에서 심각도를 바꾸면 ValueError → 호출을 나눈다
            log.warning(line)
        return res


def main():
    rclpy.init()
    node = InspectRegionStub()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
