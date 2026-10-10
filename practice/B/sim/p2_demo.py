import sys, math, yaml
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from demo_sim import run_scenario, obj
PL = yaml.safe_load(open(str(__import__("pathlib").Path(__file__).resolve().parents[3] / "config/places.yaml")))

def slot(drawer, name, oid, cls, top_z):
    s = PL[drawer]["place_slots"][name]
    return obj(oid, cls, s["position"][0], s["position"][1], s["yaw"], top_z, drawer)

def placed(o, data):
    pp = (data or {}).get("placed_pose") or o["pose"]
    return dict(o, pose={"frame": pp["frame"], "position": list(pp["position"]), "yaw": pp["yaw"], "yaw_valid": True})

def scan(target, *others):
    return {"target_found": target is not None, "target": target, "candidates": list(others), "visible_count": 1 + len(others)}

def common_open(drawer):
    return [("drawer_approach", "move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": drawer}),
            ("open", "drawer_control", {"drawer_id": drawer, "state": "open"})]

def common_close(drawer):
    return [("close", "drawer_control", {"drawer_id": drawer, "state": "close", "then_home": True})]

def cover_scenario(drawer, cp=(0.110, 0.200, 0.0), er=(0.095, 0.182, 0.0), lb=(0.120, 0.218, 0.0), lip_first=False):
    P = obj("cover_plate#1", "cover_plate", *cp, 0.0405, drawer)
    E = obj("eraser#1", "eraser", *er, 0.0115, drawer)
    L = obj("lip_balm#1", "lip_balm", *lb, 0.020, drawer)
    Pa = slot(drawer, "aside_1", "cover_plate#1", "cover_plate", 0.0405)
    s1 = scan(P, E, L)
    s2 = scan(E, Pa, L)
    s3 = scan(L, Pa)
    s4 = scan(Pa)
    steps = common_open(drawer) + [
        ("pick 가림막", "pick_object", {"target": P, "approach_offset": [0, 0, 0.1], "scan": s1}),
        ("place 가림막 → aside_1", "place_object", {"location": drawer, "slot": "aside_1", "scan": s1}),
    ] + ([
        ("pick 립밤", "pick_object", {"target": L, "approach_offset": [0, 0, 0.1], "scan": scan(L, Pa, E)}),
        ("place 립밤 → 트레이", "place_object", {"location": "handover_zone"}),
        ("pick 지우개", "pick_object", {"target": E, "approach_offset": [0, 0, 0.1], "scan": scan(E, Pa)}),
        ("place 지우개 → 트레이", "place_object", {"location": "handover_zone"}),
    ] if lip_first else [
        ("pick 지우개", "pick_object", {"target": E, "approach_offset": [0, 0, 0.1], "scan": s2}),
        ("place 지우개 → 트레이", "place_object", {"location": "handover_zone"}),
        ("pick 립밤", "pick_object", {"target": L, "approach_offset": [0, 0, 0.1], "scan": s3}),
        ("place 립밤 → 트레이", "place_object", {"location": "handover_zone"}),
    ]) + [
        ("pick 가림막 (복구)", "pick_object", lambda c: {"target": placed(Pa, c["place 가림막 → aside_1"]), "approach_offset": [0, 0, 0.1],
                                                       "scan": scan(placed(Pa, c["place 가림막 → aside_1"]))}),
        ("place 가림막 → 원래 자리", "place_object", lambda c: {"location": drawer, "pose": {"frame": drawer, "position": list(cp[:2]) + [0.0], "yaw": cp[2]},
                                                        "scan": scan(placed(Pa, c["place 가림막 → aside_1"]))}),
    ] + common_close(drawer)
    return run_scenario("가림막 치우고 " + ("립밤→지우개" if lip_first else "지우개→립밤") + " → 트레이 → 가림막 복구", drawer, steps)

def stack_scenario(drawer, at=(0.105, 0.150), yaw_w=0.0, yaw_c=0.0, yaw_k=0.2):
    W = obj("toy_wrench#1", "toy_wrench", at[0], at[1], yaw_w, 0.0185, drawer)
    C = obj("caramel_box#1", "caramel_box", at[0], at[1], yaw_c, 0.0185 + 0.0185, drawer)
    K = obj("car_key#1", "car_key", at[0], at[1], yaw_k, 0.037 + 0.0158, drawer)
    Ka = slot(drawer, "aside_1", "car_key#1", "car_key", 0.0158)
    Ca = slot(drawer, "aside_2", "caramel_box#1", "caramel_box", 0.0185)
    s1 = scan(W, K, C)
    steps = common_open(drawer) + [
        ("pick 차키 (맨 위)", "pick_object", {"target": K, "approach_offset": [0, 0, 0.1], "scan": s1}),
        ("place 차키 → aside_1", "place_object", {"location": drawer, "slot": "aside_1", "scan": s1}),
        ("pick 캐러멜", "pick_object", {"target": C, "approach_offset": [0, 0, 0.1], "scan": scan(W, Ka, C)}),
        ("place 캐러멜 → aside_2", "place_object", {"location": drawer, "slot": "aside_2", "scan": scan(W, Ka, C)}),
        ("pick 몽키", "pick_object", {"target": W, "approach_offset": [0, 0, 0.1], "scan": scan(W, Ka, Ca)}),
        ("place 몽키 → 트레이", "place_object", {"location": "handover_zone"}),
    ] + common_close(drawer)
    return run_scenario("몽키·캐러멜·차키 쌓기 → 몽키 꺼내기", drawer, steps)

if __name__ == "__main__":
    for d in ("drawer_top", "drawer_bottom"):
        cover_scenario(d)
        cover_scenario(d, lip_first=True)
        stack_scenario(d)
