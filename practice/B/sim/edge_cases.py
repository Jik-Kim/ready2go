"""가장자리 동작 기구학 확인: 기울여 잡기(손잡이 쪽 가로·립밤 네 벽·아래 칸 깊은 곳), 벽까지 밀기 넛지, 들고 나오기. 위·아래 칸."""
import sys, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ros2_ws/src/ready2go_skills"))
import p2_demo as d
from demo_sim import obj

CASES = [  # (이름, 클래스, x, y, yaw, top_z, 넛지 먼저)
    ("지우개 손잡이 쪽 가로 → 기울여 긴 변", "eraser", 0.012, 0.15, math.pi / 2, 0.0115, False),
    ("지우개 손잡이 쪽 비스듬 → 벽까지 밀기", "eraser", 0.031, 0.12, -1.0102, 0.0115, True),
    ("지우개 오른쪽 벽 가로 → y 넛지", "eraser", 0.10, 0.282, math.pi / 2, 0.0115, True),
    ("지우개 안쪽 벽 세로 → x 넛지", "eraser", 0.183, 0.15, 0.0, 0.0115, True),
    ("립밤 왼벽 → 기울여", "lip_balm", 0.10, 0.011, 0.0, 0.020, False),
    ("립밤 오른벽 → 기울여", "lip_balm", 0.10, 0.278, 0.0, 0.020, False),
    ("립밤 손잡이 쪽 가로 → 기울여", "lip_balm", 0.011, 0.15, math.pi / 2, 0.020, False),
    ("립밤 안쪽 벽 가로 → 기울여", "lip_balm", 0.198, 0.15, math.pi / 2, 0.020, False),
    ("립밤 왼벽 근처 45° → 벽까지 밀기", "lip_balm", 0.10, 0.035, math.radians(45), 0.020, True),
    ("캐러멜 가로 가운데 → 긴 변", "caramel_box", 0.10, 0.15, math.pi / 2, 0.0185, False),
    ("차키 가로 가운데 → 긴 변", "car_key", 0.10, 0.15, math.pi / 2, 0.0158, False),
]

for drawer in ("drawer_top", "drawer_bottom"):
    for name, cls, x, y, yaw, tz, nudge in CASES:
        T = obj(f"{cls}#1", cls, x, y, yaw, tz, drawer)
        steps = d.common_open(drawer)
        if nudge:
            steps.append(("nudge", "nudge_object", {"drawer_id": drawer, "target": T}))
            steps.append(("pick (넛지 뒤)", "pick_object", lambda c, T=T: {"target": c["nudge"]["target_after"] or T, "approach_offset": [0, 0, 0.1]}))
        else:
            steps.append(("pick", "pick_object", {"target": T, "approach_offset": [0, 0, 0.1]}))
        steps += [("place → 트레이", "place_object", {"location": "handover_zone"})] + d.common_close(drawer)
        d.run_scenario(name, drawer, steps)
