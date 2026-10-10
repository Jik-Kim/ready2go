"""스킬 서버에 동작 하나 보내기 (b_flow.sh 가 부름). 끌기 결과 target_after 를 저장했다가 집기에 넘긴다.
지우개 위치는 10/07 실측(위 서랍, 세로, 손잡이 쪽 오른쪽 모서리, 3번 수직 터치). 10/06 값 [0.1769, 0.2895] 은 #22 stub 과 같음."""
import json
import os
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.signals import SignalHandlerOptions

from ready2go_interfaces.action import Skill

ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,          # 10/07: 손잡이 쪽 오른쪽 모서리, 세로 [실측 B 3번 터치]
          "pose": {"frame": "drawer_top", "position": [0.0275, 0.2904, 0.0], "yaw": 0.0, "yaw_valid": True}}
AFTER = "/tmp/b_target_after.json"       # 끌기 결과 — 하나만 (pick 은 서랍 인자가 없음, target 의 frame 이 곧 서랍)
TMP = "/tmp"                              # scan(인식) 결과 target 은 서랍마다 따로 scan_file() — 있으면 nudge 가 이걸 씀, 없으면 위 고정값(stub)
DRAWER = "drawer_top"                     # 두 번째 인자로 고름 (서랍 필요한 동작은 필수): B open top|bottom|drawer_top|drawer_bottom [사용자 10/08]
DRAWER_ALIASES = {"top": "drawer_top", "bottom": "drawer_bottom", "drawer_top": "drawer_top", "drawer_bottom": "drawer_bottom"}
NEEDS_DRAWER = {"ready", "open", "opened", "close", "view", "scan", "rescan", "nudge", "all", "dragtest", "find"}   # home·pick·place 는 서랍 없음


def scan_file():
    """서랍마다 따로 — 위 칸 인식 결과로 아래 칸을 끌지 않게 (#181 E 리뷰)."""
    return f"{TMP}/b_target_scan_{DRAWER}.json"


def full_scan_file(drawer):
    """인식 결과 전체(target + candidates) — 집기·넛지에 scan 으로 넘겨 옆 물체 확인 [사용자 10/09 랜덤 배치]."""
    return f"{TMP}/b_target_fullscan_{drawer}.json"


def with_scan(params, drawer):
    """그 서랍 인식 결과 전체가 있으면 params 에 scan 으로 붙임 (없으면 그대로 — 스킬 서버는 옆 물체 확인 안 함)."""
    try:
        with open(full_scan_file(drawer)) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return params
    objs = ([s["target"]] if s.get("target") else []) + list(s.get("candidates") or [])
    if objs and all((o.get("pose") or {}).get("frame") == drawer for o in objs):
        return dict(params, scan=s)
    return params


def _load_target(path):
    """저장된 target 중 지금 서랍(pose.frame == DRAWER) 것만. 없거나 다른 칸이면 None."""
    try:
        with open(path) as f:
            t = json.load(f)
    except (OSError, ValueError):
        return None
    return t if isinstance(t, dict) and (t.get("pose") or {}).get("frame") == DRAWER else None


def target():
    t = _load_target(scan_file())
    if t:
        return t
    if ERASER["pose"]["frame"] == DRAWER:                 # 고정값(stub)은 위 칸 실측
        return ERASER
    sys.exit(f"{DRAWER} 인식 결과 없음 — B scan {DRAWER.removeprefix('drawer_')} 먼저 (보내지 않음)")


def goal_for(cmd):
    if cmd == "ready":                                 # 손잡이 앞 — Runner open_drawer 1단계 (열기 노드는 여기서만 시작, #168)
        return "move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": DRAWER}
    if cmd == "open":
        return "drawer_control", {"drawer_id": DRAWER, "state": "open"}
    if cmd == "opened":
        return "drawer_control", {"drawer_id": DRAWER, "state": "open", "displacement": 0.226}
    if cmd == "close":
        return "drawer_control", {"drawer_id": DRAWER, "state": "close", "then_home": True}   # 닫고 홈까지 한 동작 [사용자 10/10]
    if cmd == "nudge":
        return "nudge_object", with_scan({"drawer_id": DRAWER, "target": target()}, DRAWER)
    if cmd == "pick":                                  # 가장 최근 좌표: 끌기 결과·다시 보기(target_after) 또는 그냥 B scan [사용자 10/10 넛지 없이 집기]
        srcs = [p for p in (AFTER, f"{TMP}/b_target_scan_drawer_top.json", f"{TMP}/b_target_scan_drawer_bottom.json") if os.path.exists(p)]
        if not srcs:
            sys.exit("집을 좌표 없음 — B scan <서랍> 먼저 (보내지 않음)")
        src = max(srcs, key=os.path.getmtime)
        with open(src) as f:
            t = json.load(f)
        print(f"집을 좌표: {src}")
        return "pick_object", with_scan({"target": t, "approach_offset": [0, 0, 0.1]}, (t.get("pose") or {}).get("frame"))
    if cmd == "place":
        return "place_object", {"location": "handover_zone"}
    if cmd == "home":
        return "move_to_named_pose", {"pose_name": "home"}
    if cmd == "view":
        return "move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": DRAWER}
    sys.exit(USAGE)


USAGE = ("사용: B <동작> [서랍]  서랍 = top | bottom (= drawer_top | drawer_bottom)\n"
         "  서랍 필요: ready open opened close view scan rescan nudge all dragtest find   서랍 없음: home pick place\n"
         "  find = (서랍은 손으로 열고 B opened 뒤) 탑뷰 → 인식 → 넛지 → 다시 인식 → 집기(잡을 때까지 다시) → 트레이 → 홈\n"
         "  rescan = 끌기 뒤 다시 인식, 찾은 좌표로 B pick (scan 은 확인·끌기용)")


STEPS = ("ready", "open", "view", "scan", "nudge", "view", "rescan", "pick", "place", "close", "home")
# all: 손잡이 앞 → 열기 → 탑뷰 → 인식 → 끌기 → 탑뷰 → 다시 인식(그 좌표로 집기) → 집기 → 놓기 → 닫기 → 홈 [사용자 10/07]
DRAG_TEST = ("home", "ready", "open", "view", "scan", "nudge", "pick", "place")         # dragtest: 끌기 단위 시험 [사용자 10/07] (집기 전 탑뷰·다시 인식)
# 서랍 안 일(끌기·집기)에서 무엇이든 이상하면 멈추지 않고 탑뷰 → 인식(지금은 시늉, 비전 연동 때 실제) → 다시 들어감 [사용자 10/07].
# 다시 할 수 없는 것만 멈춘다: 비상정지, 정지·이동 미확인(서버 잠김), 취소, 결과 못 받음, 거절(다른 동작 중).
STOP_CODES = {"ESTOP", "STOP_UNCONFIRMED", "MOVE_UNCONFIRMED", "CANCELED", "NO_RESULT", "REJECTED"}
RETRIES = 2                                # 탑뷰로 돌아가 다시 들어가는 최대 횟수 (제 제안)
last = {"code": ""}
TIMES = []                                 # (단계, 걸린 s, 성공) — 끝에 구간별 시간표 (C 요청 10/07: pick 60초 예산 판단)


def timed(label, fn):
    t0 = time.monotonic()
    ok = fn()
    TIMES.append((label, time.monotonic() - t0, ok))
    return ok


def report():
    """구간별 시간표. 공통 pick 구간 = 첫 탑뷰 이동부터 마지막 집기 끝까지 (탑뷰 → 촬영 → 끌기 → 탑뷰 → 다시 촬영 → 집기)."""
    if not TIMES:
        return
    print("\n===== 구간별 시간 =====")
    for label, sec, ok in TIMES:
        print(f"  {label:<8} {sec:6.1f} s{'' if ok else '  (실패)'}")
    labels = [x[0] for x in TIMES]
    if "view" in labels and "pick" in labels:
        a, b = labels.index("view"), len(labels) - 1 - labels[::-1].index("pick")
        if a < b:
            print(f"  pick 구간 합계 (첫 탑뷰 ~ 집기): {sum(x[1] for x in TIMES[a:b + 1]):.1f} s")
    print(f"  전체 합계: {sum(x[1] for x in TIMES):.1f} s")


def scan(node, for_pick=False):
    """탑뷰에서 /vision/inspect_region (A 비전). 찾으면 target 저장, 서비스가 없으면 고정값(stub)으로 진행.
    for_pick: 끌기 뒤 다시 보기 — 찾으면 그 좌표로 집기 (끌기 예상 위치 target_after 와 비교 출력) [사용자 10/07: 끌고 나서
    탑뷰로 다시 가서 위치 재확인 후 집기]. 비전이 없으면 target_after 그대로."""
    from ready2go_interfaces.srv import InspectRegion
    c = node.create_client(InspectRegion, "/vision/inspect_region")
    if not c.wait_for_service(timeout_sec=2.0):
        if for_pick:
            if not _load_target(AFTER):               # 다른 칸 끌기 결과로 집지 않음
                print(f"비전 서비스 안 보임 — {DRAWER} 끌기 결과(target_after) 없음, 비전 노드를 켜고 다시")
                return False
            print("비전 서비스 안 보임 — 끌기 예상 위치(target_after)로 집기")
        elif _load_target(scan_file()):           # 다른 터미널(비전과 같은 통신 설정)에서 미리 scan 한 같은 칸 결과
            print(f"비전 서비스 안 보임 — 저장된 인식 결과 사용 ({scan_file()})")
        elif ERASER["pose"]["frame"] != DRAWER:      # 고정 좌표는 위 칸 실측 — 아래 칸은 비전 필요 (다른 칸 결과는 안 씀)
            print(f"비전 서비스 안 보임 — {DRAWER} 고정 좌표 없음, 비전 노드를 켜고 다시")
            return False
        else:
            print("비전 서비스 안 보임 — 고정 지우개 좌표(stub)로 진행")
        return True
    f = c.call_async(InspectRegion.Request(region=DRAWER, search_target="eraser"))
    rclpy.spin_until_future_complete(node, f, timeout_sec=30.0)
    r = f.result()
    if r is None or not r.success:
        print(f"인식 실패: {getattr(r, 'error_code', '응답 없음')}")
        return False
    res = json.loads(r.result_json or "{}")
    if not res.get("target_found"):
        print("지우개 못 찾음")
        return False
    with open(scan_file(), "w") as fp:
        json.dump(res["target"], fp)
    with open(full_scan_file(DRAWER), "w") as fp:
        json.dump(res, fp)
    print(f"인식: {json.dumps(res['target'], ensure_ascii=False)}")
    if for_pick:
        try:
            with open(AFTER) as f:
                exp = json.load(f)["pose"]["position"]
            got = res["target"]["pose"]["position"]
            print(f"끌기 예상 {[round(v, 4) for v in exp[:2]]} vs 다시 본 위치 {[round(v, 4) for v in got[:2]]} "
                  f"→ 차이 {[round((g - e) * 1000, 1) for g, e in zip(got[:2], exp[:2])]} mm (다시 본 위치로 집음)")
        except (OSError, ValueError, KeyError, TypeError):
            pass
        with open(AFTER, "w") as f:
            json.dump(res["target"], f)
    return True


def parse_drawer(cmd, arg):
    """서랍이 필요한 동작은 서랍을 꼭 받음 — 빼먹으면 엉뚱한 칸으로 가지 않게 움직이기 전에 멈춤 [사용자 10/08]."""
    if cmd in NEEDS_DRAWER:
        if arg not in DRAWER_ALIASES:
            sys.exit(f"{cmd} 은 서랍을 써야 함: B {cmd} top | bottom\n{USAGE}")
        return DRAWER_ALIASES[arg]
    if arg is not None:
        sys.exit(f"{cmd} 은 서랍을 받지 않음: B {cmd}\n{USAGE}")
    return DRAWER


def main():
    global DRAWER
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    DRAWER = parse_drawer(cmd, sys.argv[2] if len(sys.argv) > 2 else None)
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node("b_sk")
    if cmd == "scan":
        scan(node)
        return
    if cmd == "rescan":                            # 끌기 뒤 다시 인식 — 찾은 좌표를 집기(B pick)에 넘김 (all 의 rescan 과 같음, #181 E 리뷰)
        scan(node, for_pick=True)
        return
    if cmd == "find":
        try:
            find(node)
        finally:
            report()
        return
    if cmd == "dragtest":
        try:
            drag_test(node)
        finally:                                   # 중간에 멈춰도(sys.exit) 시간표는 찍음
            report()
        return
    if cmd != "all":
        run(node, cmd)                              # close 는 노드가 홈까지 (then_home) [사용자 10/10]
        return
    try:
        run_all(node)
    finally:
        report()


def run_all(node):
    for i, step in enumerate(STEPS, 1):
        print(f"\n===== {i}/{len(STEPS)} {step} =====")
        ok = timed(step, lambda: scan(node) if step == "scan" else scan(node, for_pick=True) if step == "rescan"
                   else run(node, step))
        if not ok:
            sys.exit(f"{step} 실패 — 여기서 멈춤 (뒤 단계 안 보냄). 터미널 1 로그 확인")
    print("\n전체 흐름 성공")


def drag_test(node):
    """홈 → 열기 → 탑뷰 → 인식 → 끌기 → 집기 → 트레이. 끌기·집기가 실패하면 탑뷰 → 인식 → 실패한 단계부터 다시 (최대 RETRIES 번).
    집기를 다시 할 때 좌표는 끌기 결과(target_after) — stub 은 늘 처음 좌표라 다시 끌면 안 됨. 비전 연동 때는 인식 결과로."""
    for i, step in enumerate(("home", "ready", "open", "view", "scan"), 1):
        print(f"\n===== {i}/{len(DRAG_TEST)} {step} =====")
        if not timed(step, lambda: scan(node) if step == "scan" else run(node, step)):
            sys.exit(f"{step} 실패 {last['code']} — 여기서 멈춤 (서랍 안에 들어가기 전). 터미널 로그 확인")
    step, tries = "nudge", 0
    while step != "place":
        print(f"\n===== {DRAG_TEST.index(step) + 1}/{len(DRAG_TEST)} {step} =====")
        if timed(step, lambda: run(node, step)):
            if step == "nudge":                         # 끌고 나서 탑뷰로 가서 위치 다시 확인 → 그 좌표로 집기 [사용자 10/07]
                print("\n----- 끌기 끝 → 탑뷰에서 지우개 위치 다시 확인 -----")
                if not timed("view", lambda: run(node, "view")):
                    sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
                if not timed("rescan", lambda: scan(node, for_pick=True)):
                    tries += 1
                    if tries > RETRIES:
                        sys.exit("다시 인식 실패 — 멈춤")
                    continue                            # 못 찾으면 끌기부터 다시 (지우개가 어디 있는지 모름)
            step = "pick" if step == "nudge" else "place"
            continue
        if last["code"] in STOP_CODES:
            sys.exit(f"{step} {last['code']} — 다시 할 수 없는 상태라 멈춤 (펜던트·터미널 확인)")
        if tries >= RETRIES:
            sys.exit(f"{step} {last['code']} — {RETRIES}번 다시 해도 실패해 멈춤")
        tries += 1
        print(f"\n----- {step} {last['code']} → 탑뷰로 가서 다시 확인 ({tries}/{RETRIES}) -----")
        if not timed("view", lambda: run(node, "view") or (last["code"] not in STOP_CODES and run(node, "view"))):   # 탑뷰 가기도 한 번 더
            sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
        timed("rescan" if step == "pick" else "scan", lambda: scan(node, for_pick=(step == "pick")))
    print(f"\n===== {len(DRAG_TEST)}/{len(DRAG_TEST)} place =====")
    if not timed("place", lambda: run(node, "place")):
        sys.exit(f"place 실패 {last['code']} — 물체를 든 채라 멈춤")
    print("\n끌기 시험 성공 (트레이까지)")


REGRAB_CODES = {"WALL_TOO_CLOSE"}           # 집기가 움직이기 전에 "아직 못 잡는 자리"로 거부 → 다시 넛지 [사용자 10/08]
# find 에서 다시 보면 풀릴 수 있는 실패만 반복 (#191 E 리뷰): 물체가 움직였거나 접촉·도착이 어긋난 경우.
# 나머지(입력·설정·서랍 상태·툴 등)는 다시 봐도 같으므로 원인과 사람 할 일을 출력하고 멈춤.
RETRY_NUDGE = {"PUSH_BLOCKED", "NO_OBJECT_CONTACT", "NOT_REACHED", "PUSH_LIMIT", "YAW_INVALID"}
RETRY_PICK = {"GRASP_FAILED", "NOT_REACHED", "YAW_INVALID"}
HUMAN_FIX = {"DRAWER_NOT_AT_TRAVEL": "서랍을 끝까지 열고 B opened <서랍>",
             "DRAWER_STATE_UNKNOWN": "B opened <서랍> 로 열림 알리기",
             "DRAWER_NOT_CONFIGURED": "서랍 교시값(places.yaml tf·interior_m) 확인",
             "BAD_PARAMS": "인식 결과·서랍 이름 확인 (rm -f /tmp/b_target_*.json 뒤 다시)",
             "TOOL_NOT_SET": "펜던트 TCP GripperDA_v1·툴 tool_weight 선택",
             "NOT_ON_FLOOR": "쌓인 높이가 서랍 테두리에 너무 가까움(또는 top_z 이상) — 위 물체를 사람이 내려놓기",
             "NEIGHBOR_TOO_CLOSE": "옆 물체가 손가락·끄는 길에 걸림 — 두 물체를 3~4 cm 띄우기",
             "HOLDING_OBJECT": "그리퍼에 든 물체를 빼고 서버 재시작",
             "NO_PUSH_ACCESS": "끌어도 잡을 수 없는 자리 — 사람이 옮기기",
             "JOINT_LIMIT": "관절 제한 — 자세·위치 확인"}


def _stop_unrecoverable(step):
    """다시 봐도 안 풀리는 실패 → 원인·사람 할 일 출력하고 멈춤."""
    code = last["code"]
    sys.exit(f"{step} {code} — 다시 봐도 같은 실패라 멈춤. 할 일: {HUMAN_FIX.get(code, '스킬 서버 터미널 로그 확인')}")


def find(node):
    """서랍은 사람이 열어 둔 상태(B opened)에서: 탑뷰 → 인식 → 넛지 → 탑뷰 → 다시 인식 → 집기 → 트레이 → 홈 [사용자 10/08].
    잡을 때까지 다시 (횟수 제한 없음 [사용자 10/08 "잡을 때까지"]): 넛지 실패(RETRY_NUDGE)·집기 전 거부(REGRAB_CODES)면 탑뷰 → 인식 → 다시 넛지,
    집기 실패(RETRY_PICK)면 탑뷰 → 다시 인식 → 다시 집기. 멈추는 것: STOP_CODES, 다시 봐도 안 풀리는 코드(입력·설정·서랍 상태 — 원인·할 일 출력),
    못 찾음(어디 있는지 모름), 놓기 실패(든 채)."""
    def look(for_pick):
        if not timed("view", lambda: run(node, "view")):
            if last["code"] in STOP_CODES or not timed("view", lambda: run(node, "view")):   # 탑뷰 가기는 한 번 더
                sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
        if not timed("rescan" if for_pick else "scan", lambda: scan(node, for_pick=for_pick)):
            sys.exit("목표를 못 찾음 — 어디 있는지 몰라 멈춤 (서랍 안 확인)")

    look(False)
    step, n = "nudge", 0
    while True:
        n += 1
        print(f"\n===== {n}. {step} =====")
        if timed(step, lambda: run(node, step)):
            if step == "pick":
                break
            if last.get("pushed") is False:                # 넛지 필요 없는 자리 — 끌지 않았으니 다시 보지 않고 바로 집기 [사용자 10/10]
                print("\n----- 넛지 필요 없음 → 바로 집기 -----")
            else:
                print("\n----- 넛지 끝 → 탑뷰에서 다시 확인 → 그 좌표로 집기 -----")
                look(True)
            step = "pick"
            continue
        if last["code"] in STOP_CODES:
            sys.exit(f"{step} {last['code']} — 다시 할 수 없는 상태라 멈춤 (펜던트·터미널 확인)")
        if last["code"] not in (RETRY_NUDGE if step == "nudge" else RETRY_PICK | REGRAB_CODES):
            _stop_unrecoverable(step)
        if step == "nudge" or last["code"] in REGRAB_CODES:
            print(f"\n----- {step} {last['code']} → 탑뷰 → 인식 → 다시 넛지 -----")
            look(False)
            step = "nudge"
        else:
            print(f"\n----- pick {last['code']} → 탑뷰 → 다시 인식 → 다시 집기 -----")
            look(True)
    print("\n===== place =====")
    if not timed("place", lambda: run(node, "place")):
        sys.exit(f"place 실패 {last['code']} — 물체를 든 채라 멈춤")
    timed("home", lambda: run(node, "home"))
    print("\nfind 성공 (트레이까지)")


def run(node, cmd):
    """동작 하나 보내고 끝날 때까지. 성공이면 True."""
    action, params = goal_for(cmd)
    client = ActionClient(node, Skill, f"/skills/{action}")
    if not client.wait_for_server(timeout_sec=5.0):
        sys.exit("스킬 서버 없음 — 터미널 1 확인")
    print(f"보냄: {action} {json.dumps(params, ensure_ascii=False)}")
    t = {"last": time.monotonic()}

    def fb(f):                                             # 단계 사이 걸린 시간 — 어디서 멈추는지 보기 [10/07]
        now = time.monotonic()
        print(f"  단계: {f.feedback.stage}  (+{now - t['last']:.1f} s)")
        t["last"] = now
    sent = client.send_goal_async(Skill.Goal(params_json=json.dumps(params)), feedback_callback=fb)
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
    last["pushed"] = None
    print(f"  끝  (+{time.monotonic() - t['last']:.1f} s)")
    out = json.loads(r.output_json) if r.output_json else None
    if cmd == "opened" and r.error_code == "DRAWER_ALREADY_OPEN":
        print("결과: 서버에 '끝까지 열림(226 mm)'으로 알림 — 로봇 동작 없음")
    else:
        print("결과:", "성공" if r.success else f"실패 {r.error_code} (이유는 터미널 1 로그)")
    if out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    if cmd == "nudge" and out:
        last["pushed"] = out.get("pushed")
    if cmd == "nudge" and r.success and out and out.get("target_after"):
        with open(AFTER, "w") as f:
            json.dump(out["target_after"], f)
        print("target_after 저장 → pick 에서 씀")
    return r.success


if __name__ == "__main__":
    main()
