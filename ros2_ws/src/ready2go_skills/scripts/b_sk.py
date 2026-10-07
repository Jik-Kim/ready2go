"""스킬 서버에 동작 하나 보내기 (b_flow.sh 가 부름). 끌기 결과 target_after 를 저장했다가 집기에 넘긴다.
지우개 위치는 10/07 실측(위 서랍, 세로, 손잡이 쪽 오른쪽 모서리, 3번 수직 터치). 10/06 값 [0.1769, 0.2895] 은 #22 stub 과 같음."""
import json
import sys

import rclpy
from rclpy.action import ActionClient
from rclpy.signals import SignalHandlerOptions

from ready2go_interfaces.action import Skill

ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,          # 10/07: 손잡이 쪽 오른쪽 모서리, 세로 [실측 B 3번 터치]
          "pose": {"frame": "drawer_top", "position": [0.0275, 0.2904, 0.0], "yaw": 0.0, "yaw_valid": True}}
AFTER = "/tmp/b_target_after.json"
SCAN = "/tmp/b_target_scan.json"          # scan(인식) 결과 target — 있으면 nudge 가 이걸 씀, 없으면 위 고정값(stub)


def target():
    try:
        with open(SCAN) as f:
            return json.load(f)
    except (OSError, ValueError):
        return ERASER


def goal_for(cmd):
    if cmd == "open":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "open"}
    if cmd == "opened":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "open", "displacement": 0.226}
    if cmd == "close":
        return "drawer_control", {"drawer_id": "drawer_top", "state": "close"}
    if cmd == "nudge":
        return "nudge_object", {"drawer_id": "drawer_top", "target": target()}
    if cmd == "pick":
        with open(AFTER) as f:
            return "pick_object", {"target": json.load(f), "approach_offset": [0, 0, 0.1]}
    if cmd == "place":
        return "place_object", {"location": "handover_zone"}
    if cmd == "home":
        return "move_to_named_pose", {"pose_name": "home"}
    if cmd == "view":
        return "move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"}
    sys.exit("동작: all | dragtest | open | opened | view | scan | nudge | pick | place | close | home")


STEPS = ("open", "view", "scan", "nudge", "pick", "place", "close", "home")   # all: 열기 → 탑뷰 → 인식 → 끌기 → 집기 → 놓기 → 닫기 → 홈
DRAG_TEST = ("home", "open", "view", "scan", "nudge", "pick", "place")         # dragtest: 끌기 단위 시험 [사용자 10/07]
# 서랍 안 일(끌기·집기)에서 무엇이든 이상하면 멈추지 않고 탑뷰 → 인식(지금은 시늉, 비전 연동 때 실제) → 다시 들어감 [사용자 10/07].
# 다시 할 수 없는 것만 멈춘다: 비상정지, 정지·이동 미확인(서버 잠김), 취소, 결과 못 받음, 거절(다른 동작 중).
STOP_CODES = {"ESTOP", "STOP_UNCONFIRMED", "MOVE_UNCONFIRMED", "CANCELED", "NO_RESULT", "REJECTED"}
RETRIES = 2                                # 탑뷰로 돌아가 다시 들어가는 최대 횟수 (제 제안)
last = {"code": ""}


def scan(node):
    """탑뷰에서 /vision/inspect_region (A 비전). 찾으면 target 저장, 서비스가 없으면 고정값(stub)으로 진행."""
    from ready2go_interfaces.srv import InspectRegion
    c = node.create_client(InspectRegion, "/vision/inspect_region")
    if not c.wait_for_service(timeout_sec=5.0):
        import os
        if os.path.exists(SCAN):                  # 다른 터미널(비전과 같은 통신 설정)에서 미리 scan 한 결과
            print(f"비전 서비스 안 보임 — 저장된 인식 결과 사용 ({SCAN})")
        else:
            print("비전 서비스 안 보임 — 고정 지우개 좌표(stub)로 진행")
        return True
    f = c.call_async(InspectRegion.Request(region="drawer_top", search_target="eraser"))
    rclpy.spin_until_future_complete(node, f, timeout_sec=30.0)
    r = f.result()
    if r is None or not r.success:
        print(f"인식 실패: {getattr(r, 'error_code', '응답 없음')}")
        return False
    res = json.loads(r.result_json or "{}")
    if not res.get("target_found"):
        print("지우개 못 찾음")
        return False
    with open(SCAN, "w") as fp:
        json.dump(res["target"], fp)
    print(f"인식: {json.dumps(res['target'], ensure_ascii=False)}")
    return True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node("b_sk")
    if cmd == "scan":
        scan(node)
        return
    if cmd == "dragtest":
        drag_test(node)
        return
    if cmd != "all":
        run(node, cmd)
        return
    for i, step in enumerate(STEPS, 1):
        print(f"\n===== {i}/{len(STEPS)} {step} =====")
        if not (scan(node) if step == "scan" else run(node, step)):
            sys.exit(f"{step} 실패 — 여기서 멈춤 (뒤 단계 안 보냄). 터미널 1 로그 확인")
    print("\n전체 흐름 성공")


def drag_test(node):
    """홈 → 열기 → 탑뷰 → 인식 → 끌기 → 집기 → 트레이. 끌기·집기가 실패하면 탑뷰 → 인식 → 실패한 단계부터 다시 (최대 RETRIES 번).
    집기를 다시 할 때 좌표는 끌기 결과(target_after) — stub 은 늘 처음 좌표라 다시 끌면 안 됨. 비전 연동 때는 인식 결과로."""
    for i, step in enumerate(("home", "open", "view", "scan"), 1):
        print(f"\n===== {i}/{len(DRAG_TEST)} {step} =====")
        if not (scan(node) if step == "scan" else run(node, step)):
            sys.exit(f"{step} 실패 {last['code']} — 여기서 멈춤 (서랍 안에 들어가기 전). 터미널 로그 확인")
    step, tries = "nudge", 0
    while step != "place":
        print(f"\n===== {DRAG_TEST.index(step) + 1}/{len(DRAG_TEST)} {step} =====")
        if run(node, step):
            step = "pick" if step == "nudge" else "place"
            continue
        if last["code"] in STOP_CODES:
            sys.exit(f"{step} {last['code']} — 다시 할 수 없는 상태라 멈춤 (펜던트·터미널 확인)")
        if tries >= RETRIES:
            sys.exit(f"{step} {last['code']} — {RETRIES}번 다시 해도 실패해 멈춤")
        tries += 1
        print(f"\n----- {step} {last['code']} → 탑뷰로 가서 다시 확인 ({tries}/{RETRIES}) -----")
        if not (run(node, "view") or (last["code"] not in STOP_CODES and run(node, "view"))):   # 탑뷰 가기도 한 번 더
            sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
        scan(node)
    print(f"\n===== {len(DRAG_TEST)}/{len(DRAG_TEST)} place =====")
    if not run(node, "place"):
        sys.exit(f"place 실패 {last['code']} — 물체를 든 채라 멈춤")
    print("\n끌기 시험 성공 (트레이까지)")


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
        last["code"] = "REJECTED"
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
        last["code"] = "NO_RESULT"
        return False
    r = result.result().result
    last["code"] = r.error_code
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
