"""스킬 서버에 동작 하나 보내기 (b_flow.sh 가 부름). 끌기 결과 target_after 를 저장했다가 집기에 넘긴다.
지우개 위치는 10/07 실측(위 서랍, 세로, 손잡이 쪽 오른쪽 모서리, 3번 수직 터치). 10/06 값 [0.1769, 0.2895] 은 #22 stub 과 같음."""
import json
import math
import os
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.signals import SignalHandlerOptions

from ready2go_interfaces.action import Skill

ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,          # 10/07: 손잡이 쪽 오른쪽 모서리, 세로 [실측 B 3번 터치]
          "pose": {"frame": "drawer_top", "position": [0.0275, 0.2904, 0.0], "yaw": 0.0, "yaw_valid": True}}
TRAY_FILE = "/tmp/r2g_skill_tray.json"
HELD_FILE = "/tmp/r2g_skill_held.json"   # 스킬 서버 쥔 물체 기록 (skill_server held_file 기본값) — B free 가 실제 폭·긴 변 쥠을 씀   # 스킬 서버 트레이 쓴 칸 기록 (skill_server tray_file 기본값)
AFTER = "/tmp/b_target_after.json"       # 끌기 결과 — 하나만 (pick 은 서랍 인자가 없음, target 의 frame 이 곧 서랍)
TMP = "/tmp"                              # scan(인식) 결과 target 은 서랍마다 따로 scan_file() — 있으면 nudge 가 이걸 씀, 없으면 위 고정값(stub)
DRAWER = "drawer_top"                     # 두 번째 인자로 고름 (서랍 필요한 동작은 필수): B open top|bottom|drawer_top|drawer_bottom [사용자 10/08]
DRAWER_ALIASES = {"top": "drawer_top", "bottom": "drawer_bottom", "drawer_top": "drawer_top", "drawer_bottom": "drawer_bottom"}
NEEDS_DRAWER = {"ready", "open", "opened", "close", "view", "scan", "rescan", "nudge", "all", "dragtest", "find", "clear",
                "free", "plan", "unpack"}   # home·pick·place 는 서랍 없음


def scan_file():
    """서랍마다 따로 — 위 칸 인식 결과로 아래 칸을 끌지 않게 (#181 E 리뷰)."""
    return f"{TMP}/b_target_scan_{DRAWER}.json"


def picked_file():
    """B pick 이 보낸 집기 요청(target + scan) — B putback 이 그 자리로 되돌릴 때 씀 [사용자 10/11]."""
    return f"{TMP}/b_picked.json"


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
    if cmd == "plan":                                  # 공간 만들기 다음 동작만 보기 — 움직이지 않음 (make_room + check_only) [사용자 10/12]
        action, params = goal_for("clear")
        return action, dict(params, check_only=True)
    if cmd == "clear":                                 # 파지 공간 만들기 한 단계 (nudge_object make_room) [제안 10/11 B, 계약 승인 전]
        params = with_scan({"drawer_id": DRAWER, "target": target(), "make_room": True}, DRAWER)
        if "scan" not in params:
            sys.exit(f"{DRAWER} 인식 결과 없음 — B scan {DRAWER.removeprefix('drawer_')} 먼저 (보내지 않음)")
        return "nudge_object", params
    if cmd == "pick":                                  # 가장 최근 좌표: 끌기 결과·다시 보기(target_after) 또는 그냥 B scan [사용자 10/10 넛지 없이 집기]
        srcs = [p for p in (AFTER, f"{TMP}/b_target_scan_drawer_top.json", f"{TMP}/b_target_scan_drawer_bottom.json") if os.path.exists(p)]
        if not srcs:
            sys.exit("집을 좌표 없음 — B scan <서랍> 먼저 (보내지 않음)")
        src = max(srcs, key=os.path.getmtime)
        with open(src) as f:
            t = json.load(f)
        print(f"집을 좌표: {src}")
        params = with_scan({"target": t, "approach_offset": [0, 0, 0.1]}, (t.get("pose") or {}).get("frame"))
        with open(picked_file(), "w") as f:                # B putback 용 — 집기 전 자리와 그때 본 scan (쥔 물체가 scan 에 있어야 서랍 안 놓기가 받음)
            json.dump(params, f, ensure_ascii=False)
        return "pick_object", params
    if cmd == "putback":                               # 파지만 시험: 집은 물체를 집기 전 그 자리·각도로 되돌려 놓음 [사용자 10/11]
        try:
            with open(picked_file()) as f:
                p = json.load(f)
        except (OSError, ValueError):
            sys.exit("되돌릴 자리 없음 — B pick 으로 집은 뒤에 (보내지 않음)")
        t = p["target"]
        pose = {k: t["pose"][k] for k in ("frame", "position", "yaw")}   # 서랍 안 놓기 pose 는 yaw_valid 없음 (계약 #120 ②)
        params = {"location": pose["frame"], "pose": pose}
        if p.get("scan"):
            params["scan"] = p["scan"]
        else:
            params["scan"] = {"target_found": True, "target": t, "candidates": [], "visible_count": 1}   # 옆 물체 모름 — 쥔 물체만
        print(f"되돌릴 자리: {pose['frame']} ({pose['position'][0] * 1000:.1f}, {pose['position'][1] * 1000:.1f}) mm, yaw {pose['yaw']:.3f}")
        return "place_object", params
    if cmd == "place":
        return "place_object", {"location": "handover_zone"}
    if cmd == "home":
        return "move_to_named_pose", {"pose_name": "home"}
    if cmd == "trayview":                              # 트레이 탑뷰 (poses.yaml tray_view, 놓은 뒤 비전 확인 자세) [사용자 10/11]
        return "move_to_named_pose", {"pose_name": "tray_view"}
    if cmd == "view":
        return "move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": DRAWER}
    sys.exit(USAGE)


USAGE = ("사용: B <동작> [서랍] [물체]  서랍 = top | bottom (= drawer_top | drawer_bottom), 물체 = 지우개·캐러멜·차키·립밤… (안 쓰면 마지막에 고른 것)\n"
         "  서랍 필요: ready open opened close view scan rescan nudge all dragtest find clear free plan\n"
         "  서랍 없음: home pick place putback trayview trayclear\n"
         "  putback = 파지만 시험 — B pick 으로 집은 물체를 집기 전 그 자리·각도로 되돌려 놓음\n"
         "  trayclear = 트레이를 손으로 다 비운 뒤 — 스킬 서버의 쓴 칸 기억을 지움(다음 놓기부터 1번 칸, 로봇 안 움직임)\n"
         "  plan = (B scan 뒤) 공간 만들기가 다음에 할 동작만 출력, 로봇 안 움직임 — B clear 전에 미리 보기\n"
         "  free = 쥔 물체를 그 서랍 빈 자리에 — 고정 aside 대신 집을 때 본 인식 결과로 빈 곳을 골라 놓음 (B scan → B pick → B free top)\n"
         "  find = (서랍은 손으로 열고 B opened 뒤) 탑뷰 → 인식 → 넛지 → 다시 인식 → 집기(잡을 때까지 다시) → 트레이 → 홈\n"
         "  clear = (서랍 열고 B opened 뒤) 파지 공간 만들기: 탑뷰 → 인식 → 한 동작(위에 얹힌 것·막는 것 빈 자리로 / 목표 넛지 /\n"
         "          좌우 밀기 / 벽 넛지) → 다시 인식 … 집을 수 있게 되면 집기 → 트레이 → 홈 [제안 10/11, 계약 승인 전]\n"
         "  rescan = 끌기 뒤 다시 인식, 찾은 좌표로 B pick (scan 은 확인·끌기용)\n"
         "  unpack = (서랍 닫힘·빈손·홈에서) Runner find_with_unpack 과 같은 순서 한 번에: 열기 → 탑뷰 → 인식 → 위에 덮은 것부터\n"
         "           서랍 빈 자리(free)로 최대 2개 → 목표 트레이 → 옮긴 것 역순으로 원래 자리(막히면 다시 빈 자리) → 복구 오차 출력 → 닫기·홈\n"
         "           예: B unpack top 몽키 (쌓기 해체) / B unpack bottom 지우개 (가림막 빼기)")


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


def print_seen(res):
    """보인 물체 전부 한 줄씩: 위치·윗면 높이·yaw 믿음·위에 얹힌 물체(occluded_by, 분할 모델일 때만) [사용자 10/11 쌓기 확인]."""
    objs = ([res["target"]] if res.get("target") else []) + list(res.get("candidates") or [])
    for o in objs:
        p = (o.get("pose") or {})
        rel = f"  위에 얹힘 {o['occluded_by']}" if "occluded_by" in o else ""
        print(f"  - {o.get('id')}  위치 {[round(v * 1000, 1) for v in (p.get('position') or [0, 0])[:2]]} mm  윗면 {round((o.get('top_z') or 0) * 1000, 1)} mm"
              f"  yaw {round(p.get('yaw') or 0, 3)}{'' if p.get('yaw_valid') else ' (믿을 수 없음)'}{rel}")


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
    f = c.call_async(InspectRegion.Request(region=DRAWER, search_target=TARGET))
    rclpy.spin_until_future_complete(node, f, timeout_sec=30.0)
    r = f.result()
    if r is None or not r.success:
        print(f"인식 실패: {getattr(r, 'error_code', '응답 없음')}")
        return False
    res = json.loads(r.result_json or "{}")
    print_seen(res)
    if not res.get("target_found"):
        seen = [f"{c['class']} {[round(v, 4) for v in c['pose']['position'][:2]]}" for c in res.get("candidates") or []]
        print(f"{TARGET} 못 찾음 — 보인 것 {len(seen)}개: {', '.join(seen) or '없음'} "
              f"(서랍 밖으로 걸러진 건 비전 창 'skip' 줄)")
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


TARGET = "eraser"                          # 찾을 물체 (B <동작> <서랍> <물체>) [사용자 10/10 다른 물체도]
TARGET_FILE = f"{TMP}/b_target_class.txt"   # 마지막에 고른 물체 — 다음 B 명령도 같은 물체


def repo_file(*rel):
    """저장소 파일 — 소스에서 돌리면 스크립트 기준, 설치본이면 ~/ready2go."""
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", *rel)
    return f if os.path.exists(f) else os.path.expanduser(os.path.join("~/ready2go", *rel))


def parse_target(arg):
    """물체 이름(클래스 키 또는 한국어 이름·별칭) → 클래스 키. 없으면 마지막에 고른 물체(없으면 지우개)."""
    world = json.load(open(repo_file("knowledge", "world.jsonld"), encoding="utf-8"))["world"]["items"]
    if arg is None:
        try:
            with open(TARGET_FILE) as f:
                return f.read().strip() or "eraser"
        except OSError:
            return "eraser"
    extra = {"몽키": "toy_wrench", "몽키스패너": "toy_wrench", "캐러멜박스": "caramel_box", "카라멜박스": "caramel_box",
             "가림막": "cover_plate", "덮개": "cover_plate"}   # 우리가 부르는 이름 [사용자 10/11] — 온톨로지 별칭에 없는 것
    a = arg.replace(" ", "")
    for cand in (a, arg.split()[0]):                   # 여러 단어("장난감 스패너")는 붙여서, 안 되면 첫 단어
        for k, v in world.items():
            names = [k, v.get("name_ko", "")] + list(v.get("aliases_ko") or [])
            if cand in [n.replace(" ", "") for n in names] or extra.get(cand) == k:
                with open(TARGET_FILE, "w") as f:
                    f.write(k)
                return k
    sys.exit(f"모르는 물체: {arg} — 쓸 수 있는 것: " + ", ".join(f"{k}({v.get('name_ko')})" for k, v in world.items()))


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
    global TARGET
    TARGET = parse_target(" ".join(sys.argv[3:]) if len(sys.argv) > 3 else None)
    if cmd == "trayclear":                         # 트레이를 사람이 비움 → 서버 기억 지우기 (서버가 매 놓기마다 이 파일을 읽음) [사용자 10/11]
        try:
            os.remove(TRAY_FILE)
            print(f"트레이 비움 알림: {TRAY_FILE} 지움 — 다음 놓기부터 1번 칸 (로봇 동작 없음)")
        except FileNotFoundError:
            print("트레이 기억이 이미 비어 있음 — 다음 놓기는 1번 칸 (로봇 동작 없음)")
        return
    if cmd in ("scan", "rescan", "find", "all", "dragtest", "clear", "unpack"):
        print(f"찾을 물체: {TARGET}")
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
    if cmd == "clear":
        try:
            clear(node)
        finally:
            report()
        return
    if cmd == "free":
        free(node)
        return
    if cmd == "unpack":
        try:
            unpack(node)
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
    """손잡이 앞 → 열기 → (find 와 같음: 탑뷰 → 인식 → 넛지 → 다시 보기 → 집기, 아직 못 잡는 자리면 다시 넛지 반복) → 트레이 → 닫기 → 홈.
    예전엔 넛지 한 번 뒤 집기 거부(WALL_TOO_CLOSE)면 멈춤 — 손잡이 쪽 벽까지 밀어 눕힌 뒤 옆벽 y 넛지가 한 번 더 필요 [사용자 10/11 PC2]."""
    for i, step in enumerate(("ready", "open"), 1):
        print(f"\n===== {i}. {step} =====")
        if not timed(step, lambda: run(node, step)):
            sys.exit(f"{step} 실패 — 여기서 멈춤 (뒤 단계 안 보냄). 터미널 1 로그 확인")
    find(node)
    for step in ("close", "home"):
        print(f"\n===== {step} =====")
        if not timed(step, lambda: run(node, step)):
            sys.exit(f"{step} 실패 — 여기서 멈춤. 터미널 1 로그 확인")
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
             "NO_FREE_SPACE": "치울 물체를 놓을 빈 자리가 서랍에 없음 — 사람이 몇 개 빼기",
             "OCCLUSION_UNKNOWN": "위에 얹힌 관계를 모름(분할 모델 아님·occluded_by null) — 비전 가중치 확인, 물체 조금 띄우고 다시",
             "JOINT_LIMIT": "관절 제한 — 자세·위치 확인",
             "SENSOR_INVALID": "그리퍼 폭·힘을 못 읽음 — 그리퍼에 물체가 있는지 보고 RG2 박스·케이블 확인 뒤 스킬 서버 재시작"}


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


FREE_TRIES = 15                             # B free: 빈 자리 후보를 이만큼까지 보냄 (거부는 움직이기 전이라 바로 다음 후보)
FREE_RETRY = {"PLACE_BLOCKED", "WALL_TOO_CLOSE"}   # 서랍 안 놓기의 "움직임 없음" 거부 (#166) — 다음 후보로


def free_poses(drawer):
    """B pick 으로 쥔 물체를 그 서랍 빈 자리에 놓을 후보 pose (점수 순) [사용자 10/11 "aside 말고 빈 공간 찾아 놓기"].
    집을 때 본 scan(옆 물체 전부) + 온톨로지 크기로 core/clear_plan.free_poses: 벽에 붙여 큰 빈 곳을 남기고,
    쥔 물체가 얹혀 있던 받침(다음에 꺼낼 것)에서는 25 mm 띄움. 아래 칸은 손 닿는 깊이(drawer_reach_x_mm) 안만.
    진짜로 놓을 수 있는지는 스킬 서버 서랍 안 놓기 검사가 봄(안 되면 움직이기 전 거부 → 다음 후보)."""
    import yaml
    pkg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")   # 소스에서 돌리면 ROS 설치 없이도 core 를 찾게 (PC2 B 명령)
    if os.path.isdir(os.path.join(pkg, "ready2go_skills")) and pkg not in sys.path:
        sys.path.insert(0, pkg)
    from ready2go_skills.core import clear_plan as cp, place_plan as plp
    try:
        with open(picked_file()) as f:
            p = json.load(f)
    except (OSError, ValueError):
        sys.exit("쥔 물체 정보 없음 — B scan → B pick 으로 집은 뒤에 (보내지 않음)")
    held, scan_ = p.get("target") or {}, p.get("scan")
    try:                                                   # 집은 뒤 다시 본 결과(B view → B scan)가 더 새것이면 그걸로 — 그사이 옮긴 물체 반영 [PC2 10/12]
        if os.path.getmtime(full_scan_file(drawer)) > os.path.getmtime(picked_file()):
            with open(full_scan_file(drawer)) as f:
                scan_ = json.load(f)
            print(f"집은 뒤 다시 본 인식 결과로 빈 자리 고름 ({full_scan_file(drawer)})")
    except (OSError, ValueError):
        pass
    if scan_ and held.get("id") and held["id"] not in {o.get("id") for o in ([scan_.get("target")] if scan_.get("target") else [])
                                                      + list(scan_.get("candidates") or [])}:
        scan_ = dict(scan_, candidates=list(scan_.get("candidates") or []) + [held])   # 서버는 쥔 물체가 scan 에 있어야 받음(#166) — 이웃 검사에선 빠짐
    if (held.get("pose") or {}).get("frame") != drawer:
        sys.exit(f"쥔 물체는 {(held.get('pose') or {}).get('frame')} 에서 집음 — B free {drawer.removeprefix('drawer_')} 가 아님 (보내지 않음)")
    if not scan_:
        sys.exit("집을 때 본 인식 결과 전체(scan)가 없음 — B scan 뒤 B pick 으로 다시 (옆 물체를 몰라 빈 자리를 못 고름)")
    world = json.load(open(repo_file("knowledge", "world.jsonld"), encoding="utf-8"))["world"]["items"]
    places = yaml.safe_load(open(repo_file("config", "places.yaml"), encoding="utf-8"))
    prm = yaml.safe_load(open(repo_file("ros2_ws", "src", "ready2go_skills", "params", "skills.yaml"), encoding="utf-8"))
    default = prm["place"]["default_obstacle_size_m"]

    def size_of(cls):
        return (world.get(cls) or {}).get("size_m") or default
    objs = [dict(o, occluded_by=list(o.get("occluded_by") or [])) for o in ([scan_["target"]] if scan_.get("target") else []) + list(scan_.get("candidates") or [])]
    if held.get("id") not in {o["id"] for o in objs}:
        objs.append(dict(held, occluded_by=[]))
    bases = [o for o in objs if held.get("id") in o["occluded_by"]]
    reach = (prm.get("drawer_reach_x_mm") or {}).get(drawer)
    interior, size = places[drawer]["interior_m"], size_of(held["class"])
    # 스킬 서버 서랍 안 놓기와 같은 겹침·벽 검사(core/place_plan.check_place)로 먼저 거름 — 벽에 붙인 후보는 벌린 손가락이
    # 벽에 걸려 대부분 거부됨 [P2 시뮬레이션 10/11: 앞 15개 중 통과 10배치에 2~3]. 쥔 폭은 온톨로지 잡는 폭(없으면 짧은 변)
    grasp = (yaml.safe_load(open(repo_file("config", "item_grasp.yaml"), encoding="utf-8")) or {}).get(held["class"]) or {}
    width, long_held = grasp.get("grasp_width_m") or size[1], False
    try:                                                   # 서버가 기억하는 쥔 상태 — 실제 닫은 폭·긴 변으로 쥐었는지 [PC2 10/12: 긴 변 차키 15개 다 거부]
        with open(HELD_FILE) as f:
            h = json.load(f)
        if h.get("id") == held["id"]:
            width, long_held = h.get("width_m") or width, bool(h.get("long_side"))
    except (OSError, ValueError):
        pass
    open_mm = width * 1000.0 + prm["place"]["release_extra_mm"]
    # 벽 여유를 더 둠 — 손가락 바깥 관절 표(gripper.wall_clearance_mm.across, 위 칸 10/05)로 4.3 mm 남는다던 자리에서 아래 칸 왼벽에
    # 닿음 [사용자 10/12 PC2: 립밤 긴 변 쥠 (20, 60) mm 90°, 내려가다가]. 표를 아래 칸에서 다시 재기 전 임시
    g = dict(prm["gripper"], wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(drawer),
             wall_margin_mm=prm["gripper"]["wall_margin_mm"] + float(prm["place"].get("free_wall_extra_mm", 0.0)))
    others = [o for o in objs if o["id"] not in {b["id"] for b in bases}] + bases
    held_state = {"class": held["class"], "id": held["id"], "width_m": width, "drawer_id": drawer, "long_side": long_held,
                  "tcp_above_floor_m": size[2] * prm["pick"].get("grip_height_ratio", 0.5)}
    dry = _dry_checks(drawer, held_state, places[drawer])
    out, later = [], []
    for c in cp.free_poses(objs, held["id"], size_of, interior, drawer, avoid=bases):
        pose = cp.as_pose(c)
        if reach is not None and pose["position"][0] * 1000.0 > reach:
            continue
        # 긴 변 양끝을 쥐었으면 손가락이 긴 변 끝에 있음 → 90° 돌린 물체로 확인 (서버 _place_in_drawer 와 같음)
        pc, sc = ((dict(pose, yaw=pose["yaw"] + math.pi / 2), [size[1], size[0]] + list(size[2:])) if long_held else (pose, size))
        if plp.check_place(pose=pc, held_id=held["id"], held_size_m=sc, open_mm=open_mm, objects=others, size_of=size_of,
                           interior_m=interior, g=g, place=prm["place"]) is not None:
            continue
        if dry is None:
            out.append(pose)
            continue
        # 스킬 서버의 실제 놓기·집기 사전 검사(움직이지 않음)로 — 놓을 수 있고, 놓은 뒤 다시 집을 수 있는 자리만
        # [사용자 10/12 PC2 "free 로 놓은 뒤 다시 집으려니 너무 가깝다고 안 됨"]
        if not dry["place"](scan_, pose):
            continue
        (out if dry["repick"](objs, held["id"], pose, size_of) else later).append(pose)
        if len(out) >= FREE_TRIES:
            break
    # 가로(긴 변이 손잡이 벽과 나란, 서랍 y 방향)로 눕힌 후보 먼저 — 서랍이 옆으로 넓어 앞·뒤 벽 쪽에 가로로 두면 가운데가 남음 [사용자 10/12]
    out.sort(key=lambda q: abs(math.sin(q["yaw"])) < 0.7)
    if dry is not None and not out and later:
        print("다시 바로 집을 수 있는 빈 자리는 없음 — 놓을 수만 있는 자리로 (다시 꺼낼 땐 넛지·공간 만들기 필요할 수 있음)")
        out = later
    return out, scan_


def _dry_checks(drawer, held_state, place):
    """스킬 서버 코드를 이 프로세스에서 판단 전용으로 (움직이는 메서드는 막힘, 스킬 서버 DryOracle 과 같은 방식) —
    place(scan, pose): 서랍 안 놓기 사전 검사, repick(objs, id, pose, size_of): 그 자리에 놓은 뒤 집기 사전 검사.
    가져오지 못하면 None (그땐 place_plan 검사만, 서버가 다시 확인)."""
    try:
        from pathlib import Path
        from ready2go_skills.nodes import skill_server as ss
        srv = object.__new__(ss.SkillServer)
        srv.cfg_dir, srv.params_file = Path(repo_file("config")), Path(repo_file("ros2_ws", "src", "ready2go_skills", "params", "skills.yaml"))
        srv.rg2_ip, srv.robot, srv.hold_unknown, srv._held = "", None, None, None
        srv.disp = {drawer: place.get("tf_at_travel_m")}
        srv.get_logger = lambda: ss._QUIET
    except Exception as e:                                      # noqa: BLE001 — ROS 없는 환경 등
        print(f"(스킬 서버 검사 못 불러옴 — 놓기 겹침·벽만 봄: {e!r:.80})")
        return None
    goal = ss._DRY_GOAL

    def place_ok(scan_, pose):
        dry = ss._Dry(srv, held=held_state)
        ok, code, _ = ss._dry_call(lambda: dry._place_in_drawer(goal, {"location": drawer, "pose": pose, "scan": scan_}, drawer))
        return ok

    def repick_ok(objs, held_id, pose, size_of):
        after = []
        for o in objs:
            if o["id"] == held_id:
                after.append(dict(o, pose=dict(pose, yaw_valid=True), occluded_by=[], top_z=size_of(o["class"])[2]))
            else:
                after.append(dict(o, occluded_by=[x for x in o.get("occluded_by") or [] if x != held_id]))
        t = next(o for o in after if o["id"] == held_id)
        sc = {"target_found": True, "target": t, "candidates": [o for o in after if o["id"] != held_id], "visible_count": len(after)}
        dry = ss._Dry(srv)
        ok, code, _ = ss._dry_call(lambda: dry._do_pick_object(goal, {"target": t, "approach_offset": [0, 0, 0.1], "scan": sc}))
        return ok or code == ss.sf.SKILL_EXCEPTION                 # 계산 예외는 걸러내지 않음 (서버가 다시 봄)
    return {"place": place_ok, "repick": repick_ok}


def free(node):
    """쥔 물체를 그 서랍 빈 자리에 (고정 aside 자리 대신): 후보를 차례로 place_object(pose) — 움직이기 전 거부면 다음 후보."""
    cands, scan_ = free_poses(DRAWER)
    for i, pose in enumerate(cands[:FREE_TRIES], 1):
        print(f"\n----- 빈 자리 후보 {i}: ({pose['position'][0] * 1000:.0f}, {pose['position'][1] * 1000:.0f}) mm, yaw {pose['yaw']:.2f} -----")
        if run(node, "free", ("place_object", {"location": DRAWER, "pose": pose, "scan": scan_})):
            print(f"빈 자리에 놓음 — 다시 꺼낼 땐 B scan {DRAWER.removeprefix('drawer_')} 부터")
            return True
        if last["code"] not in FREE_RETRY:
            sys.exit(f"free {last['code']} — 움직였거나 다시 해도 같은 실패라 멈춤 (물체를 든 채일 수 있음, 터미널 1 로그 확인)")
    sys.exit(f"빈 자리 후보 {min(len(cands), FREE_TRIES)}개가 모두 거부됨 — 서랍이 꽉 참 (사람이 자리 만들기)")


UNPACK_MAX = 2                              # 치울 물체 최대 — Runner find_with_unpack s7 max_iter 2
UNPACK_PICK_RETRY = 1                       # 목표 집기 다시 — 태스크 s8.t1 on_failure retry 1
REID_TOL_M = 0.02                           # 옮긴 물체 다시 찾기 거리 — 태스크 inputs.reid_tol_m [팀 확정 필요]
RESTORE_CHECK_TOL_M = 0.10                  # 마지막 확인에서 원래 자리 물체로 볼 거리 — 태스크 inputs.restore_check_tol_m (판정은 기록표 3 cm)


def _runner_unpack():
    """Runner 의 Unpacking 판단(select_obstacle·find_moved, ROS 비의존)을 그대로 씀 — 태스크와 같은 물체를 고르게."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    for pkg in ("ready2go_runner", "ready2go_knowledge"):
        d = os.path.join(src, pkg)
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    from ready2go_runner.core import unpack as up
    return up


def inspect_all(node, search):
    """탑뷰로 가서 /vision/inspect_region 결과 전체(목표를 못 찾아도). 못 가거나 인식 실패면 None."""
    from ready2go_interfaces.srv import InspectRegion
    if not timed("view", lambda: run(node, "view")):
        if last["code"] in STOP_CODES or not timed("view", lambda: run(node, "view")):
            sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
    c = node.create_client(InspectRegion, "/vision/inspect_region")
    if not c.wait_for_service(timeout_sec=2.0):
        sys.exit("비전 서비스 안 보임 — 비전 노드를 켜고 다시 (unpack 은 실제 인식이 필요)")
    f = c.call_async(InspectRegion.Request(region=DRAWER, search_target=search))
    rclpy.spin_until_future_complete(node, f, timeout_sec=30.0)
    r = f.result()
    if r is None or not r.success:
        print(f"인식 실패: {getattr(r, 'error_code', '응답 없음')}")
        return None
    res = json.loads(r.result_json or "{}")
    print_seen(res)
    with open(full_scan_file(DRAWER), "w") as fp:          # B plan·B free 등 다음 B 명령도 이 결과를 씀
        json.dump(res, fp)
    return res


def _pick(node, obj, scan_):
    return timed("pick", lambda: run(node, "pick", ("pick_object", {"target": obj, "approach_offset": [0, 0, 0.1], "scan": scan_})))


def _pick_retry(node, obj, res, search):
    """목표 집기 — 태스크 s8.t1 공통 pick 스킬(탑뷰 → 찾기 → 넛지 → 다시 보기 → 집기, retry 1)과 같게: 아직 못 잡는 자리
    (WALL_TOO_CLOSE)면 넛지 → 다시 보기 → 다시, 잡기 실패(RETRY_PICK)면 다시 보기 → 다시. 치울 물체는 태스크가 pick_object 만 쓰므로 안 씀.
    돌려줌 (성공, 마지막 인식 결과, 마지막 물체)."""
    for n in range(UNPACK_PICK_RETRY + 1):
        print(f"\n----- {obj['id']} 집기{f' (다시 {n})' if n else ''} -----")
        if _pick(node, obj, res):
            return True, res, obj
        if last["code"] in STOP_CODES:
            sys.exit(f"pick {last['code']} — 멈춤 (복구 안 함, 사람 확인)")
        if last["code"] not in RETRY_PICK | REGRAB_CODES or n == UNPACK_PICK_RETRY:
            return False, res, obj
        if last["code"] in REGRAB_CODES:                     # 벽에 붙어 아직 못 잡는 자리 → 넛지 뒤 다시 보기 (공통 pick 과 같음)
            print("\n----- 아직 못 잡는 자리 → 넛지 → 다시 보기 -----")
            if not timed("nudge", lambda: run(node, "nudge", ("nudge_object", {"drawer_id": DRAWER, "target": obj, "scan": res}))):
                if last["code"] in STOP_CODES:
                    sys.exit(f"nudge {last['code']} — 멈춤 (복구 안 함, 사람 확인)")
                if last["code"] not in RETRY_NUDGE:
                    return False, res, obj
        res = inspect_all(node, search)
        same = [o for o in ([res["target"]] if (res or {}).get("target") else []) + list((res or {}).get("candidates") or [])
                if o.get("class") == obj["class"]]
        if len(same) != 1:
            print(f"다시 보니 {obj['class']} {len(same)}개 — 멈춤")
            return False, res, obj
        obj = same[0]
    return False, res, obj


def _xy_yaw(pose):
    return [pose["position"][0], pose["position"][1]], float(pose.get("yaw") or 0.0)


def unpack(node):
    """[사용자 10/12 "문서 그대로 풀로"] Runner tasks/find_with_unpack.json(C feat/c-unpack-task)과 같은 순서를 B 명령으로:
    손잡이 앞 → 열기 → 탑뷰 → 인식 → select_obstacle(덮은 것 맨 위부터, 옮긴 것 제외, 관계 모르면 한 번 다시 찍기) →
    집기 → 서랍 빈 자리(slot free) → 기록 → 다시 보기 … 최대 2개 → 목표가 다 보이면 집기 → 트레이 →
    (쥔 게 없을 때) 옮긴 것을 역순으로: 다시 보기 → find_moved → 집기 → 원래 자리(막히면 다시 빈 자리 + 안내) →
    치운 물체는 고정 aside 대신 늘 빈 자리(free) [사용자 10/13 "free 가 상위호환, aside 다 지움"] — 서버가 집는 물체 자리는 빈 것으로 보고,
    목표(scan.target) 둘레를 비우고, 놓은 뒤 다시 집을 수 있는 곳을 고름. 빈 자리가 없으면 든 채 멈춤 (Runner 태스크는 집기 전에 판단, #250).
    마지막 다시 보기로 복구 오차(위치 mm·각도 °) 출력 → 닫기·홈. 판정(3 cm)은 기록표 — 자로 잰 값과 같이 적기."""
    up = _runner_unpack()
    world = {"items": json.load(open(repo_file("knowledge", "world.jsonld"), encoding="utf-8"))["world"]["items"]}
    for step in ("ready", "open"):
        print(f"\n===== {step} =====")
        if not timed(step, lambda: run(node, step)) and last["code"] != "DRAWER_ALREADY_OPEN":
            sys.exit(f"{step} {last['code']} — 여기서 멈춤 (서랍 닫힘·빈손·홈에서 시작, 이미 열었으면 B opened {DRAWER.removeprefix('drawer_')} 뒤 다시)")

    def select(res):
        r = up.select_obstacle({"scan": res, "moved": stack, "tol_m": REID_TOL_M}, world)
        return r.output if r.success else {"obstacle": None, "reason": "bad_scan"}

    def look_select():
        """탑뷰·인식·고르기 — 태스크 s4·s6·s6r(s7.6~s7.9)와 똑같이: 관계 모름(occlusion_unknown)일 때만 한 번 다시 찍기.
        B 명령이 태스크보다 더 해 주면(관계 고치기·더 다시 찍기) 시연(Runner)에서 다르게 나옴 [사용자 10/12 "unpack 은 스킬 짜깁기 — 고치지 말 것"]."""
        res = inspect_all(node, TARGET)
        sel = select(res) if res else {"obstacle": None, "reason": "no_scan"}
        if sel["reason"] == "occlusion_unknown":
            print("\n----- 가림 관계 모름 → 한 번 다시 찍기 (태스크 s6r·s7.9) -----")
            res2 = inspect_all(node, TARGET)
            if res2:
                res, sel = res2, select(res2)
        return res, sel

    stack, left_free, restore_failed, delivered, failed = [], [], [], False, ""
    res, sel = look_select()
    while sel.get("obstacle") and len(stack) < UNPACK_MAX:
        ob = sel["obstacle"]
        print(f"\n===== 치우기 {len(stack) + 1}: {ob['id']} ({sel['reason']}) =====")
        if not _pick(node, ob, res):                          # 태스크 s7.1 pick_object 그대로 (넛지·다시 하기 없음 — 실패면 복구로)
            if last["code"] in STOP_CODES:
                sys.exit(f"pick {last['code']} — 멈춤 (복구 안 함, 사람 확인)")
            failed = f"치울 {ob['id']} 집기 {last['code']}"
            break
        params = {"location": DRAWER, "slot": "free", "scan": res}
        if not timed("free", lambda: run(node, "free", ("place_object", params))):
            sys.exit(f"빈 자리 놓기 {last['code']} — {ob['id']} 를 든 채 멈춤 (사람이 회수, 복구 안 함)")
        out = last.get("out") or {}
        stack.append({"class": ob["class"], "id": ob["id"], "origin": {k: ob["pose"][k] for k in ("frame", "position", "yaw")},
                      "placed": out.get("placed_pose"), "slot": out.get("slot")})
        print(f"\n----- {ob['id']} → {stack[-1]['slot']} 끝 → 다시 보고 다음 (태스크 s7.6~s7.9) -----")
        res, sel = look_select()
    t = (res or {}).get("target") if (res or {}).get("target_found") else None
    if not failed and t is not None and sel.get("reason") == "target_clear":
        print(f"\n===== 목표 {t['id']} =====")
        ok, res, t = _pick_retry(node, t, res, TARGET)
        if not ok:
            failed = f"목표 집기 {last['code']}"
        if not failed:
            print("\n===== 트레이 =====")
            if not timed("place", lambda: run(node, "place")):
                sys.exit(f"트레이 놓기 {last['code']} — 목표를 든 채 멈춤 (복구 안 함)")
            delivered = True
    elif not failed:
        failed = f"목표 {'못 찾음' if t is None else '아직 가려짐'} ({sel.get('reason')})"
    print(f"\n>>> {'목표를 트레이에 놓았어요' if delivered else '목표를 꺼내지 못했어요 — ' + failed}"
          + ("" if delivered or not stack else " → 옮긴 것 원위치로"))

    for item in reversed(stack):                             # 역순 복구 (태스크 finally fr)
        print(f"\n===== 원위치 {item['id']} =====")
        rescan = inspect_all(node, item["class"])
        found = up.find_moved({"scan": rescan, "record": item, "tol_m": REID_TOL_M}, world).output if rescan else None
        if not found or found.get("status") != "found":
            print(f"  {item['id']} 다시 못 찾음 ({(found or {}).get('status', '인식 실패')}) — 남은 것 계속 (태스크 fr.x)")
            restore_failed.append(item)
            continue
        if not _pick(node, found["object"], rescan):
            if last["code"] in STOP_CODES:
                sys.exit(f"pick {last['code']} — 멈춤 (사람 확인)")
            print(f"  {item['id']} 집기 {last['code']} — 남은 것 계속 (태스크 fr.x)")
            restore_failed.append(item)
            continue
        if timed("restore", lambda: run(node, "restore", ("place_object", {"location": DRAWER, "pose": item["origin"], "scan": rescan}))):
            continue
        if last["code"] not in FREE_RETRY:
            sys.exit(f"원래 자리 놓기 {last['code']} — {item['id']} 를 든 채 멈춤 (사람이 회수)")
        if not item.get("slot") or not timed("restore", lambda: run(node, "restore", ("place_object", {"location": DRAWER, "slot": item["slot"], "scan": rescan}))):
            sys.exit(f"원래 자리·꺼냈던 자리 둘 다 안 됨 — {item['id']} 를 든 채 멈춤 (사람이 회수)")
        left_free.append(item)
        print(f">>> {item['id']} 는 원래 자리 대신 옆 빈 자리({item['slot']})에 뒀어요")

    if restore_failed:                                       # 태스크 fn·fe: 하나라도 못 돌려놓으면 안내 + FAILED RESTORE_INCOMPLETE
        print(f"\n>>> 옮긴 물건 일부를 원래 자리로 못 돌려놨어요. 사람이 확인해 주세요 ({', '.join(i['id'] for i in restore_failed)}) — RESTORE_INCOMPLETE")
    if stack:                                                # 마지막 확인 (태스크 fv) — 판정 아님, 자로 잰 값과 같이 기록
        final = inspect_all(node, TARGET)
        print("\n===== 복구 오차 (비전, 판정 아님 — 합격선 3 cm 은 기록표) =====")
        for item in stack:
            rec = dict(item, placed=item["origin"])
            fm = up.find_moved({"scan": final, "record": rec, "tol_m": RESTORE_CHECK_TOL_M}, world).output if final else {}
            o = (fm or {}).get("object")
            if item in left_free:
                print(f"  {item['id']}: 원래 자리 대신 {item['slot']}")
            elif not o:
                print(f"  {item['id']}: 원래 자리 근처에 안 보임 ({(fm or {}).get('status', '인식 실패')})")
            else:
                (x0, y0), w0 = _xy_yaw(item["origin"])
                (x1, y1), w1 = _xy_yaw(o["pose"])
                dw = math.degrees((w1 - w0 + math.pi / 2) % math.pi - math.pi / 2)
                print(f"  {item['id']}: 위치 {math.dist((x0, y0), (x1, y1)) * 1000:.1f} mm (x {(x1 - x0) * 1000:+.1f}, y {(y1 - y0) * 1000:+.1f}), 각도 {dw:+.1f}°")
    print("\n===== close (닫고 홈) =====")
    if not timed("close", lambda: run(node, "close")):
        sys.exit(f"close {last['code']} — 멈춤")
    print(f"\nunpack 끝: 전달 {'O' if delivered else 'X'}, 치움 {len(stack)}개, 원래 자리 대신 빈 자리 {len(left_free)}개"
          + (f", 못 돌려놓음 {len(restore_failed)}개 (RESTORE_INCOMPLETE)" if restore_failed else ""))
    return delivered and not restore_failed


CLEAR_STEPS = 12                            # B clear: 다시 보기 사이 동작 최대 수 (넘으면 멈춤 — 같은 동작을 되풀이하지 않게) [제안]


def clear(node):
    """파지 공간 만들기 [사용자 10/11]: 탑뷰 → 인식 → (nudge_object make_room: 스킬 서버가 동작 하나 고르고 실행) → 탑뷰 → 다시 인식 …
    서버가 ready_to_pick 이면 그 인식 좌표로 집기 → 트레이 → 홈. 집기가 다시 보면 풀리는 실패(RETRY_PICK·REGRAB)면 다시 보고 다시."""
    def look():
        if not timed("view", lambda: run(node, "view")):
            if last["code"] in STOP_CODES or not timed("view", lambda: run(node, "view")):
                sys.exit(f"탑뷰로 못 감 {last['code']} — 멈춤")
        if not timed("scan", lambda: scan(node)):
            sys.exit("목표를 못 찾음 — 어디 있는지 몰라 멈춤 (서랍 안 확인)")

    look()
    for n in range(1, CLEAR_STEPS + 1):
        print(f"\n===== {n}. clear (공간 만들기) =====")
        ok = timed("clear", lambda: run(node, "clear"))
        mr = last.get("make_room") or {}
        if not ok:
            if last["code"] in STOP_CODES:
                sys.exit(f"clear {last['code']} — 다시 할 수 없는 상태라 멈춤 (펜던트·터미널 확인)")
            if last["code"] not in RETRY_NUDGE | RETRY_PICK | {"OCCLUSION_UNKNOWN"}:   # 가림 관계 모름 → 다시 찍으면 풀릴 수 있음
                _stop_unrecoverable("clear")
            print(f"\n----- clear {last['code']} → 탑뷰 → 다시 인식 → 다시 -----")
            look()
            continue
        if not mr.get("ready_to_pick"):
            print(f"\n----- {mr.get('action')} {mr.get('moved_id')} 끝 → 탑뷰에서 다시 확인 -----")
            look()
            continue
        print("\n----- 집을 수 있음 → 집기 -----")
        if timed("pick", lambda: run(node, "pick")):
            break
        if last["code"] in STOP_CODES or last["code"] not in RETRY_PICK | REGRAB_CODES:
            _stop_unrecoverable("pick")
        print(f"\n----- pick {last['code']} → 탑뷰 → 다시 인식 → 다시 -----")
        look()
    else:
        sys.exit(f"{CLEAR_STEPS}번 동작해도 아직 못 잡음 — 멈춤 (서랍 안 확인, 사람이 띄우기)")
    print("\n===== place =====")
    if not timed("place", lambda: run(node, "place")):
        sys.exit(f"place 실패 {last['code']} — 물체를 든 채라 멈춤")
    timed("home", lambda: run(node, "home"))
    print("\nclear 성공 (트레이까지)")


def run(node, cmd, goal=None, retried=False):
    """동작 하나 보내고 끝날 때까지. 성공이면 True. goal = (action, params) 를 주면 그걸 보냄."""
    action, params = goal or goal_for(cmd)
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
    last["out"] = out
    if cmd == "opened" and r.error_code == "DRAWER_ALREADY_OPEN":
        print("결과: 서버에 '끝까지 열림(226 mm)'으로 알림 — 로봇 동작 없음")
    else:
        print("결과:", "성공" if r.success else f"실패 {r.error_code} (이유는 터미널 1 로그)")
    if out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    if cmd == "nudge" and out:
        last["pushed"] = out.get("pushed")
    last["make_room"] = (out or {}).get("make_room") if cmd == "clear" else None
    if cmd == "nudge" and r.success and out and out.get("target_after"):
        with open(AFTER, "w") as f:
            json.dump(out["target_after"], f)
        print("target_after 저장 → pick 에서 씀")
    if r.error_code == "DRAWER_NOT_AT_TRAVEL" and not retried and sys.stdin.isatty():
        # 서버를 다시 켜면 서랍 상태를 잊음(닫힘으로 시작) → 매번 B opened 를 잊어 멈춤 [사용자 10/10]. 사람이 열림을 확인해 주면 알리고 한 번 다시
        d = params.get("drawer_id") or ((params.get("target") or {}).get("pose") or {}).get("frame")
        if d and input(f"\n서버가 {d} 열림을 모름 (서버를 다시 켰나요?) — 서랍이 끝까지 열려 있으면 y 엔터: ").strip().lower() == "y":
            run(node, "opened", ("drawer_control", {"drawer_id": d, "state": "open", "displacement": 0.226}), retried=True)
            print(f"\n----- {cmd} 다시 -----")
            return run(node, cmd, goal=(action, params), retried=True)
    return r.success


if __name__ == "__main__":
    main()
