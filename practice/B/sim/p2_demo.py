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
    pa = lambda c: placed(Pa, c["place 가림막 → aside_1"])           # 실제로 놓은 자리 (aside 맞춤으로 옮겨질 수 있음)
    first, second = ((L, "립밤", E), (E, "지우개", L)) if lip_first else ((E, "지우개", L), (L, "립밤", E))
    steps = common_open(drawer) + [
        ("pick 가림막", "pick_object", {"target": P, "approach_offset": [0, 0, 0.1], "scan": s1}),
        ("place 가림막 → aside_1", "place_object", {"location": drawer, "slot": "aside_1", "scan": s1}),
        (f"pick {first[1]}", "pick_object", lambda c: {"target": first[0], "approach_offset": [0, 0, 0.1], "scan": scan(first[0], pa(c), first[2])}),
        (f"place {first[1]} → 트레이", "place_object", {"location": "handover_zone"}),
        (f"pick {second[1]}", "pick_object", lambda c: {"target": second[0], "approach_offset": [0, 0, 0.1], "scan": scan(second[0], pa(c))}),
        (f"place {second[1]} → 트레이", "place_object", {"location": "handover_zone"}),
        ("pick 가림막 (복구)", "pick_object", lambda c: {"target": pa(c), "approach_offset": [0, 0, 0.1], "scan": scan(pa(c))}),
        ("place 가림막 → 원래 자리", "place_object", lambda c: {"location": drawer, "pose": {"frame": drawer, "position": list(cp[:2]) + [0.0], "yaw": cp[2]},
                                                        "scan": scan(pa(c))}),
    ] + common_close(drawer)
    return run_scenario("가림막 치우고 " + ("립밤→지우개" if lip_first else "지우개→립밤") + " → 트레이 → 가림막 복구", drawer, steps)


def stack_scenario(drawer, at=(0.105, 0.150), yaw_w=0.0, yaw_c=0.0, yaw_k=0.2):
    W = obj("toy_wrench#1", "toy_wrench", at[0], at[1], yaw_w, 0.0185, drawer)
    C = obj("caramel_box#1", "caramel_box", at[0], at[1], yaw_c, 0.0185 + 0.0185, drawer)
    K = obj("car_key#1", "car_key", at[0], at[1], yaw_k, 0.037 + 0.0158, drawer)
    ka = lambda c: placed(slot(drawer, "aside_1", "car_key#1", "car_key", 0.0158), c["place 차키 → aside_1"])
    ca = lambda c: placed(slot(drawer, "aside_2", "caramel_box#1", "caramel_box", 0.0185), c["place 캐러멜 → aside_2"])
    s1 = scan(W, K, C)
    steps = common_open(drawer) + [
        ("pick 차키 (맨 위)", "pick_object", {"target": K, "approach_offset": [0, 0, 0.1], "scan": s1}),
        ("place 차키 → aside_1", "place_object", {"location": drawer, "slot": "aside_1", "scan": s1}),
        ("pick 캐러멜", "pick_object", lambda c: {"target": C, "approach_offset": [0, 0, 0.1], "scan": scan(W, ka(c), C)}),
        ("place 캐러멜 → aside_2", "place_object", lambda c: {"location": drawer, "slot": "aside_2", "scan": scan(W, ka(c), C)}),
        ("pick 몽키", "pick_object", lambda c: {"target": W, "approach_offset": [0, 0, 0.1], "scan": scan(W, ka(c), ca(c))}),
        ("place 몽키 → 트레이", "place_object", {"location": "handover_zone"}),
    ] + common_close(drawer)
    return run_scenario("몽키·캐러멜·차키 쌓기 → 몽키 꺼내기", drawer, steps)


def stack_restore_scenario(drawer, at=(0.105, 0.170), yaw_w=0.0, yaw_c=0.0, yaw_k=0.1):
    """쌓기 → 몽키 꺼내기 → 치운 것 원위치(LIFO: 캐러멜 → 차키). 받침(몽키)이 없어졌으니 바닥에 — 차키는 캐러멜 위였던 자리."""
    W = obj("toy_wrench#1", "toy_wrench", at[0], at[1], yaw_w, 0.0185, drawer)
    C = obj("caramel_box#1", "caramel_box", at[0], at[1], yaw_c, 0.037, drawer)
    K = obj("car_key#1", "car_key", at[0], at[1], yaw_k, 0.0528, drawer)
    ka = lambda c: placed(slot(drawer, "aside_1", "car_key#1", "car_key", 0.0158), c["place 차키 → aside_1"])
    ca = lambda c: placed(slot(drawer, "aside_2", "caramel_box#1", "caramel_box", 0.0185), c["place 캐러멜 → aside_2"])
    Cf = obj("caramel_box#1", "caramel_box", at[0], at[1], yaw_c, 0.0185, drawer)     # 원위치(바닥)에 놓인 캐러멜
    steps = common_open(drawer) + [
        ("pick 차키 (맨 위)", "pick_object", {"target": K, "approach_offset": [0, 0, 0.1], "scan": scan(W, K, C)}),
        ("place 차키 → aside_1", "place_object", {"location": drawer, "slot": "aside_1", "scan": scan(W, K, C)}),
        ("pick 캐러멜", "pick_object", lambda c: {"target": C, "approach_offset": [0, 0, 0.1], "scan": scan(W, ka(c), C)}),
        ("place 캐러멜 → aside_2", "place_object", lambda c: {"location": drawer, "slot": "aside_2", "scan": scan(W, ka(c), C)}),
        ("pick 몽키", "pick_object", lambda c: {"target": W, "approach_offset": [0, 0, 0.1], "scan": scan(W, ka(c), ca(c))}),
        ("place 몽키 → 트레이", "place_object", {"location": "handover_zone"}),
        ("복구: pick 캐러멜", "pick_object", lambda c: {"target": ca(c), "approach_offset": [0, 0, 0.1], "scan": scan(ca(c), ka(c))}),
        ("복구: place 캐러멜 → 원래 x·y", "place_object", lambda c: {"location": drawer, "pose": {"frame": drawer, "position": [at[0], at[1], 0.0], "yaw": yaw_c},
                                                           "scan": scan(ca(c), ka(c))}),
        ("복구: pick 차키", "pick_object", lambda c: {"target": ka(c), "approach_offset": [0, 0, 0.1], "scan": scan(ka(c), Cf)}),
        ("복구: place 차키 → 원래 x·y (캐러멜 위였음)", "place_object", lambda c: {"location": drawer, "pose": {"frame": drawer, "position": [at[0], at[1], 0.0], "yaw": yaw_k},
                                                                 "scan": scan(ka(c), Cf)}),
    ] + common_close(drawer)
    return run_scenario("쌓기 → 몽키 꺼내기 → LIFO 복구", drawer, steps)


if __name__ == "__main__":
    for d in ("drawer_top", "drawer_bottom"):
        cover_scenario(d)
        cover_scenario(d, lip_first=True)
        stack_scenario(d)
