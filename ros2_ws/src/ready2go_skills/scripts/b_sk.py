"""스킬 서버에 동작 하나 보내기 (b_flow.sh 가 부름). 끌기 결과 target_after 를 저장했다가 집기에 넘긴다.
지우개 위치는 10/06 실측(위 서랍, 세로, 서동권 쪽 오른쪽 모서리) — #22 점검 stub 과 같은 값."""
import json
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.signals import SignalHandlerOptions

from ready2go_interfaces.action import Skill

ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.1769, 0.2895, 0.0], "yaw": 0.0, "yaw_valid": True}}
AFTER = "/tmp/b_target_after.json"


def goal_for(cmd):
    if cmd == "open":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "open"}
    if cmd == "opened":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "open", "displacement": 0.226}
    if cmd == "close":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "close"}
    if cmd == "nudge":
        return "nudge_object", {"drawer_id": "drawer_top", "target": ERASER}
    if cmd == "pick":
        with open(AFTER) as f:
            return "pick_object", {"target": json.load(f), "approach_offset": [0, 0, 0.1]}
    if cmd == "place":
        return "place_object", {"location": "handover_zone"}
    if cmd == "home":
        return "move_to_named_pose", {"pose_name": "home"}
    sys.exit("동작: all | open | opened | nudge | pick | place | close | home")


STEPS = ("open", "nudge", "pick", "place", "close", "home")   # all: 열기 → 끌기 → 집기 → 놓기 → 닫기 → 홈


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node("b_sk")
    if cmd != "all":
        run(node, cmd)
        return
    for i, step in enumerate(STEPS, 1):
        print(f"\n===== {i}/{len(STEPS)} {step} =====")
        if not run(node, step):
            sys.exit(f"{step} 실패 — 여기서 멈춤 (뒤 단계 안 보냄). 터미널 1 로그 확인")
    print("\n전체 흐름 성공")


def run(node, cmd):
    """동작 하나 보내고 끝날 때까지. 성공이면 True."""
    action, params = goal_for(cmd)
    client = ActionClient(node, Skill, f"/skills/{action}")
    if not client.wait_for_server(timeout_sec=5.0):
        sys.exit("스킬 서버 없음 — 터미널 1 확인")
    print(f"보냄: {action} {json.dumps(params, ensure_ascii=False)}")
    sent = client.send_goal_async(Skill.Goal(params_json=json.dumps(params)),
                                  feedback_callback=lambda f: print("  단계:", f.feedback.stage))
    rclpy.spin_until_future_complete(node, sent)
    handle = sent.result()
    if not handle.accepted:
        print("거절됨 (다른 동작 실행 중?)")
        return False
    result = handle.get_result_async()
    try:
        rclpy.spin_until_future_complete(node, result)
    except KeyboardInterrupt:
        print("취소 요청 보냄 — 서버가 정지를 확인할 때까지 기다림")
        rclpy.spin_until_future_complete(node, handle.cancel_goal_async(), timeout_sec=3.0)
        rclpy.spin_until_future_complete(node, result, timeout_sec=10.0)
    if not result.done():
        print("결과 못 받음 — 터미널 1 로그 확인")
        return False
    r = result.result().result
    out = json.loads(r.output_json) if r.output_json else None
    if cmd == "opened" and r.error_code == "DRAWER_ALREADY_OPEN":
        print("결과: 서버에 '끝까지 열림(226 mm)'으로 알림 — 로봇 동작 없음")
    else:
        print("결과:", "성공" if r.success else f"실패 {r.error_code} (이유는 터미널 1 로그)")
    if out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    if cmd == "nudge" and r.success and out and out.get("target_after"):
        with open(AFTER, "w") as f:
            json.dump(out["target_after"], f)
        print("target_after 저장 → pick 에서 씀")
    return r.success


if __name__ == "__main__":
    main()
