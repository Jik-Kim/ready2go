"""덤프(inspect_*.npz) 한 장의 컬러·뎁스·K 를 손목 카메라 토픽으로 계속 발행 + base_link→광학 프레임 static TF — 오버레이 노드 시험용 (tools/dev/overlay_node_check.sh)."""
import json, sys
import numpy as np, rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import TransformStamped
from tf2_ros import StaticTransformBroadcaster
z = np.load(sys.argv[1]); meta = json.loads(str(z["meta"])); K = meta["K"]
rclpy.init(); n = Node("fake_cam")
pc = n.create_publisher(Image, "/wrist_cam/color/image_raw", qos_profile_sensor_data)
pd = n.create_publisher(Image, "/wrist_cam/aligned_depth_to_color/image_raw", qos_profile_sensor_data)
pi = n.create_publisher(CameraInfo, "/wrist_cam/color/camera_info", qos_profile_sensor_data)
T = z["T_base_cam"]; tb = StaticTransformBroadcaster(n); ts = TransformStamped()
ts.header.frame_id, ts.child_frame_id = "base_link", "wrist_cam_color_optical_frame"
ts.transform.translation.x, ts.transform.translation.y, ts.transform.translation.z = map(float, T[:3, 3])
def quat(M):
    w = np.sqrt(max(0.0, 1 + M[0,0] + M[1,1] + M[2,2])) / 2
    x = np.sqrt(max(0.0, 1 + M[0,0] - M[1,1] - M[2,2])) / 2 * np.sign(M[2,1] - M[1,2] or 1)
    y = np.sqrt(max(0.0, 1 - M[0,0] + M[1,1] - M[2,2])) / 2 * np.sign(M[0,2] - M[2,0] or 1)
    zq = np.sqrt(max(0.0, 1 - M[0,0] - M[1,1] + M[2,2])) / 2 * np.sign(M[1,0] - M[0,1] or 1)
    return [x, y, zq, w]
q = quat(T[:3, :3]); ts.transform.rotation.x, ts.transform.rotation.y, ts.transform.rotation.z, ts.transform.rotation.w = map(float, q)
ts.header.stamp = n.get_clock().now().to_msg(); tb.sendTransform(ts)
col = z["color"]; dep = (z["depth_m"] * 1000).astype(np.uint16)
def tick():
    st = n.get_clock().now().to_msg()
    c = Image(); c.header.stamp, c.header.frame_id = st, "wrist_cam_color_optical_frame"; c.height, c.width = col.shape[:2]
    c.encoding, c.step, c.data = "bgr8", col.shape[1] * 3, col.tobytes()
    d = Image(); d.header = c.header; d.height, d.width = dep.shape; d.encoding, d.step, d.data = "16UC1", dep.shape[1] * 2, dep.tobytes()
    i = CameraInfo(); i.header = c.header; i.height, i.width = col.shape[:2]; i.k = [K[0], 0.0, K[2], 0.0, K[1], K[3], 0.0, 0.0, 1.0]
    pc.publish(c); pd.publish(d); pi.publish(i)
n.create_timer(0.2, tick); rclpy.spin(n)
