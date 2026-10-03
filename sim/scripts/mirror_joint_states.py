"""T2 미러링 (담당 A): /dsr01/joint_states 를 구독해 트윈의 M0609 관절을 그대로 따라가게 한다.

실행(GUI):  ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/mirror_joint_states.py
실행(헤드리스 시험):  ... mirror_joint_states.py --headless --duration 30 --topic /test/joint_states

- 입력: sensor_msgs/JointState. 이름 joint_1~joint_6, 단위 라디안, 약 100 Hz  [실측 10/03, 에뮬레이터]
- 처리: 이름으로 트윈 관절에 매핑(없는 이름은 무시), 위치를 그대로 설정(텔레포트) + 구동 목표도 같은 값으로 설정.
- 통계: 수신 주기, 메시지 지연(수신 시각 - header.stamp), 설정 후 읽은 위치와 받은 값의 차이(추종 오차).
- 시험 모드(--duration)는 메시지를 한 건도 못 받았거나 추종 오차가 크면 마지막 줄에 `[mirror] 결과: 실패`를 출력한다.
  판정은 이 결과 줄로 한다 — SimulationApp.close() 가 프로세스를 끝내서 뒤의 sys.exit 이 실행되지 않으므로 종료 코드는 항상 0 이다 [실측 10/03].
그리퍼: 토픽에 그리퍼 관절이 없으므로 `finger_joint`는 매 스텝 열림(0°) 목표로 붙잡는다. 이렇게 하지 않으면 팔을 계속 순간이동시키는 동안 손가락이
  서서히 닫힌다 [실측 10/03: 4초 만에 42.6°, 붙잡으면 0.1° 이내]. 실물 그리퍼 폭 연동(`/gripper/state`)은 후속.
이 스크립트는 로봇에 어떤 명령도 보내지 않는다(구독만).
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
from isaacsim import SimulationApp

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--scene", default=str(ROOT / "sim/scenes/ready2go_t1.usd"))
ap.add_argument("--topic", default="/dsr01/joint_states")
ap.add_argument("--headless", action="store_true", help="창 없이 실행(시험용)")
ap.add_argument("--duration", type=float, default=0.0, help="초. 0이면 창을 닫거나 Ctrl+C 할 때까지")
ap.add_argument("--report", type=float, default=2.0, help="통계 출력 간격(초)")
ap.add_argument("--max-finger-deg", type=float, default=2.0, help="시험 모드에서 허용하는 그리퍼(finger_joint)의 열림 이탈 각도(도)")
ap.add_argument("--max-err-rad", type=float, default=0.02, help="시험 모드에서 허용하는 최대 추종 오차(rad)")
args = ap.parse_args()

app = SimulationApp({"headless": args.headless})

import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import SingleArticulation  # noqa: E402
from isaacsim.core.utils.extensions import enable_extension  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from pxr import UsdPhysics  # noqa: E402

enable_extension("isaacsim.ros2.bridge")
app.update()
import rclpy  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402

omni.usd.get_context().open_stage(args.scene)
for _ in range(10):
    app.update()
stage = omni.usd.get_context().get_stage()

root_path = None
for prim in stage.Traverse():
    if str(prim.GetPath()).startswith("/World/m0609") and prim.HasAPI(UsdPhysics.ArticulationRootAPI):
        root_path = str(prim.GetPath())
        break
if root_path is None:
    print("[mirror] ArticulationRoot 를 찾지 못했습니다", flush=True)
    app.close()
    sys.exit(1)

world = World(stage_units_in_meters=1.0, physics_dt=1 / 120.0, rendering_dt=1 / 60.0)
world.reset()
robot = SingleArticulation(prim_path=root_path, name="m0609")
robot.initialize()
dof_names = list(robot.dof_names)
print(f"[mirror] 관절 루트 {root_path}, DOF {len(dof_names)}개: {dof_names}", flush=True)
finger = dof_names.index("finger_joint") if "finger_joint" in dof_names else None
if finger is None:
    print("[mirror] finger_joint 가 없어 그리퍼는 붙잡지 않습니다", flush=True)
finger_dev = []   # 열림(0°)에서 벗어난 각도 기록

rclpy.init()
node = rclpy.create_node("ready2go_twin_mirror")
state = {"msg": None, "recv_ns": 0, "count": 0, "new": False}


def on_msg(msg):
    state["msg"] = msg
    state["recv_ns"] = node.get_clock().now().nanoseconds
    state["count"] += 1
    state["new"] = True


node.create_subscription(JointState, args.topic, on_msg, 10)
print(f"[mirror] 구독 시작: {args.topic} (ROS_DOMAIN_ID 와 DDS 설정은 sim/isaac_env.sh)", flush=True)

lat_ms, errs = [], []
unmapped = set()
t_start = time.time()
t_report = t_start
count_at_report = 0
warned_silent = False

try:
    while app.is_running():
        rclpy.spin_once(node, timeout_sec=0.0)
        if state["new"]:
            state["new"] = False
            msg = state["msg"]
            idx, pos = [], []
            for n, p in zip(msg.name, msg.position):
                if n in dof_names:
                    idx.append(dof_names.index(n))
                    pos.append(p)
                else:
                    unmapped.add(n)
            if idx:
                pos = np.array(pos, dtype=float)
                idx = np.array(idx, dtype=int)
                robot.set_joint_positions(pos, joint_indices=idx)                       # 위치를 그대로 설정
                robot.set_joint_velocities(np.zeros(len(idx)), joint_indices=idx)
                # 구동 목표도 같은 값. 그리퍼는 열림(0)으로 함께 지정해 팔 순간이동 중 손가락이 닫히지 않게 한다
                a_idx, a_pos = (np.append(idx, finger), np.append(pos, 0.0)) if finger is not None else (idx, pos)
                robot.apply_action(ArticulationAction(joint_positions=a_pos, joint_indices=a_idx))
                stamp_ns = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
                if stamp_ns > 0:
                    lat_ms.append((state["recv_ns"] - stamp_ns) / 1e6)
                last = (idx, pos)
        world.step(render=not args.headless)
        if state["count"] and "last" in dir():
            idx, pos = last
            got = np.asarray(robot.get_joint_positions())[idx]
            errs.append(float(np.max(np.abs(got - pos))))
            if finger is not None:
                finger_dev.append(abs(float(np.degrees(np.asarray(robot.get_joint_positions())[finger]))))

        now = time.time()
        if now - t_report >= args.report:
            n_new = state["count"] - count_at_report
            rate = n_new / (now - t_report)
            lat = f"{np.mean(lat_ms[-200:]):.1f} ms" if lat_ms else "stamp 없음"
            err = f"{np.max(errs[-200:]) * 1000:.2f} mrad" if errs else "-"
            print(f"[mirror] 수신 {rate:.0f} Hz, 지연 {lat}, 추종 오차(최대) {err}, 누적 {state['count']}건", flush=True)
            t_report, count_at_report = now, state["count"]
        if not warned_silent and state["count"] == 0 and now - t_start > 10:
            print(f"[mirror] 10초 동안 {args.topic} 메시지가 없습니다. 드라이버가 떠 있는지, ROS_DOMAIN_ID/CYCLONEDDS_URI가 같은지 확인하세요.", flush=True)
            warned_silent = True
        if args.duration and now - t_start >= args.duration:
            break
except KeyboardInterrupt:
    pass

ok = True
if args.duration:
    n = state["count"]
    max_err = max(errs) if errs else float("nan")
    print(f"[mirror] 요약: 수신 {n}건, 평균 지연 {np.mean(lat_ms):.1f} ms" if lat_ms else f"[mirror] 요약: 수신 {n}건", flush=True)
    print(f"[mirror] 요약: 최대 추종 오차 {max_err * 1000:.2f} mrad ({np.degrees(max_err):.3f}°), 매핑 안 된 이름: {sorted(unmapped) or '없음'}", flush=True)
    fmax = max(finger_dev) if finger_dev else 0.0
    print(f"[mirror] 요약: 그리퍼(finger_joint) 열림에서 벗어난 최대 각도 {fmax:.2f}°", flush=True)
    ok = n > 0 and max_err < args.max_err_rad and fmax < args.max_finger_deg
    print(f"[mirror] 결과: {'통과' if ok else '실패'}", flush=True)

node.destroy_node()
rclpy.shutdown()
app.close()
sys.exit(0 if ok else 1)
