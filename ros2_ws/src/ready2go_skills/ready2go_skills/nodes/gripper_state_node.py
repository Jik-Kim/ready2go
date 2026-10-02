"""RG2 상태를 /gripper/state(std_msgs/String, JSON)로 주기 발행 (ICD 5장, #4).

실행 (ROS source 후, 빌드 없이):
    cd ros2_ws/src/ready2go_skills
    python3 -m ready2go_skills.nodes.gripper_state_node --ros-args -p rg2_ip:=<RG2 IP>
확인: ros2 topic echo /gripper/state
"""
import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ready2go_skills.adapters.rg2 import Rg2
from ready2go_skills.core import rg2_protocol as proto


class GripperStateNode(Node):
    def __init__(self):
        super().__init__("gripper_state")
        ip = self.declare_parameter("rg2_ip", "").value          # [팀 확정 필요] 코드에 고정하지 않음
        port = self.declare_parameter("rg2_port", 502).value
        rate_hz = self.declare_parameter("rate_hz", 10.0).value
        if not ip:
            raise ValueError("rg2_ip 파라미터가 필요함 (--ros-args -p rg2_ip:=<IP>)")
        self._rg2 = Rg2(ip, port)
        self._pub = self.create_publisher(String, "/gripper/state", 10)
        self.create_timer(1.0 / rate_hz, self._tick)
        self.get_logger().info(f"RG2 {ip}:{port} 연결, /gripper/state {rate_hz} Hz 발행")

    def _tick(self):
        try:
            st = self._rg2.status()
        except IOError as e:
            self.get_logger().warning(f"RG2 상태 읽기 실패: {e}", throttle_duration_sec=2.0)
            return
        if st.safety_error:
            self.get_logger().error("RG2 safety error", throttle_duration_sec=2.0)
        self._pub.publish(String(data=json.dumps(proto.gripper_state_payload(st))))

    def destroy_node(self):
        self._rg2.close()
        super().destroy_node()


def main():
    rclpy.init()
    node = GripperStateNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
