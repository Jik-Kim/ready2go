"""inspect_region N회 호출 응답 시간(s) + 늦게 붙은 구독자로 /vision/inspect_overlay 마지막 한 장 저장. 사용: call_and_grab.py <out.jpg> <N> [호출 간격 s, 기본 0.5 — 0 이면 연속 호출]"""
import sys, time, rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage
from ready2go_interfaces.srv import InspectRegion
rclpy.init(); n = Node("grab")
cl = n.create_client(InspectRegion, "/vision/inspect_region"); cl.wait_for_service(timeout_sec=180)
ts = []
for i in range(int(sys.argv[2])):
    t0 = time.monotonic(); f = cl.call_async(InspectRegion.Request(region="drawer_top", search_target="toy_wrench"))
    rclpy.spin_until_future_complete(n, f, timeout_sec=30); r = f.result(); ts.append(time.monotonic() - t0)
    time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 0.5)
print("응답(s):", " ".join(f"{t:.3f}" for t in ts), "| 첫 호출 제외 중앙값", sorted(ts[1:])[len(ts[1:]) // 2], flush=True)
time.sleep(1.5); got = []
qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST, depth=1)
n.create_subscription(CompressedImage, "/vision/inspect_overlay", lambda m: got.append(m), qos)
end = time.monotonic() + 4
while time.monotonic() < end: rclpy.spin_once(n, timeout_sec=0.2)
print("late subscriber got", len(got))
if got:
    m = got[-1]; open(sys.argv[1], "wb").write(bytes(m.data)); print("format", m.format, "frame", m.header.frame_id, len(m.data) // 1024, "KB")
