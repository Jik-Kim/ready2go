import sys, math, json, yaml, collections
R = str(__import__("pathlib").Path(__file__).resolve().parents[3])
sys.path.insert(0, R + "/ros2_ws/src/ready2go_skills")
from ready2go_skills.core import motion_plan as mp
R = str(__import__("pathlib").Path(__file__).resolve().parents[3])
prm = yaml.safe_load(open(f"{R}/ros2_ws/src/ready2go_skills/params/skills.yaml"))
pl = yaml.safe_load(open(f"{R}/config/places.yaml"))
world = json.load(open(f"{R}/knowledge/world.jsonld"))
SIZES = {}
def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, dict) and "size_m" in v: SIZES[k] = v["size_m"]
            walk(v)
    elif isinstance(o, list):
        for x in o: walk(x)
walk(world)
ROUND = prm["pick"].get("round_classes") or []

def gws(drawer, cls):
    gw = dict(prm["gripper"], wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(drawer),
              reach_x_max_mm=(prm.get("drawer_reach_x_mm") or {}).get(drawer),
              max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
              axis_grasp=bool(prm["pick"].get("axis_grasp")), front_tilt_within_mm=prm["pick"].get("front_tilt_within_mm"),
              round=cls in ROUND and bool(prm["pick"].get("round_wall")))
    gd = dict(gw, wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(drawer))
    return gw, gd

def decide(t, S, I, gw, gd):
    yaw = t["pose"]["yaw"]
    if gw["axis_grasp"] and not gw["round"] and mp.axis_grasp_fits(S, gw) and mp.is_crosswise(yaw):
        ag = mp.plan_axis_grasp(target=t, size_m=S, interior_m=I, g=gd, drag=prm["drag"])
        if ag.drag is None: return ("LONG_TILT" if ag.tilt_dir else "LONG"), None
        return ("NUDGE", ag.drag) if ag.drag.needed else ("STOP", ag.drag.reason)
    wall = mp.wall_blocks_grasp(target=t, size_m=S, interior_m=I, g=gw)
    rs = mp.round_edge_dir(target=t, size_m=S, interior_m=I, g=gw) if gw["round"] else None
    if rs is not None: return "LONG_TILT_SIDE", None
    if gw["round"] and mp.long_side_ok(target=t, size_m=S, interior_m=I, g=gw):
        return ("LONG_TILT" if mp.front_tilt_x_mm(target=t, size_m=S, interior_m=I, g=gw) is not None else "LONG"), None
    if not wall: return "SHORT", None
    dp = mp.plan_drag(target=t, size_m=S, interior_m=I, g=gd, drag=prm["drag"])
    if dp.needed: return "NUDGE", dp
    if dp.error_code is None and mp.long_side_ok(target=t, size_m=S, interior_m=I, g=gw):
        return ("LONG_TILT" if mp.front_tilt_x_mm(target=t, size_m=S, interior_m=I, g=gw) is not None else "LONG"), None
    return "STOP", dp.reason or wall

def inside(x, y, yaw, S, I):
    c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
    hx, hy = (S[0]*c + S[1]*s)/2, (S[0]*s + S[1]*c)/2
    return x - hx >= -0.0005 and x + hx <= I[0] + 0.0005 and y - hy >= -0.0005 and y + hy <= I[1] + 0.0005

def run(drawer, cls, step=0.005, ystep=10):
    S = SIZES[cls]; I = pl[drawer]["interior_m"]; gw, gd = gws(drawer, cls)
    res = collections.Counter(); stops = collections.defaultdict(list); roll = 0; tot = 0; maxn = collections.Counter()
    yaws = [0] if abs(S[0] - S[1]) < 1e-6 else range(-90 + ystep, 91, ystep)
    for yd in yaws:
        yaw = math.radians(yd); x = 0.0
        while x <= I[0]:
            y = 0.0
            while y <= I[1]:
                if inside(x, y, yaw, S, I):
                    tot += 1
                    t = {"pose": {"position": [x, y, 0.0], "yaw": yaw}}; n = 0
                    for k in range(5):
                        kind, info = decide(t, S, I, gw, gd)
                        if kind != "NUDGE": break
                        n += 1
                        if cls in ROUND:
                            ax = (math.cos(t["pose"]["yaw"]), math.sin(t["pose"]["yaw"]))
                            v = (info.shift_x_m, info.shift_y_m); L = math.hypot(*v)
                            if L and abs(ax[0]*v[0] + ax[1]*v[1]) / L < math.cos(math.radians(30)) and "벽까지" not in info.reason: roll += 1
                        ny = t["pose"]["yaw"]
                        if "원통형이 손잡이 쪽 벽에 비스듬히" in info.reason:
                            ny = math.pi / 2
                        elif "원통형이 옆벽에 비스듬히" in info.reason:
                            ny = 0.0
                        elif "벽까지" in info.reason:
                            ny = math.pi / 2 if mp.is_crosswise(ny) else 0.0
                        p = t["pose"]["position"]
                        t = {"pose": {"position": [p[0] + info.shift_x_m, p[1] + info.shift_y_m, 0.0], "yaw": ny}}
                    else:
                        kind, info = "LOOP", "넛지 5번 넘음"
                    res[kind] += 1; maxn[n] += 1
                    if kind in ("STOP", "LOOP"):
                        stops[str(info)[:60]].append((round(x*1000), round(y*1000), yd))
                y += step
            x += step
    out = f"{cls:12s} {drawer[7:]:6s} {tot:6d}곳 | " + " ".join(f"{k} {100*v/tot:.1f}%" for k, v in sorted(res.items(), key=lambda kv: -kv[1]))
    out += f" | 넛지 0/1/2/3+: {maxn[0]*100//tot}/{maxn[1]*100//tot}/{maxn[2]*100//tot}/{sum(v for k,v in maxn.items() if k>=3)*100//tot}%"
    if cls in ROUND: out += f" | 굴릴 넛지 {roll}"
    print(out)
    for r, lst in sorted(stops.items(), key=lambda kv: -len(kv[1]))[:4]:
        xs = [a[0] for a in lst]; ys = [a[1] for a in lst]; yws = sorted(set(a[2] for a in lst))
        print(f"     멈춤 {len(lst):5d} ({100*len(lst)/tot:.1f}%) {r} | x {min(xs)}~{max(xs)} y {min(ys)}~{max(ys)} yaw {yws[:3]}..{yws[-3:]}")

if __name__ == "__main__":
    for cls in ["lip_balm"] if len(sys.argv) > 1 else ["caramel_box", "car_key", "lip_balm", "toy_wrench", "toy_hammer", "cover_plate", "airpods_case", "toy_car", "masking_tape", "eraser"]:
        for d in ("drawer_top", "drawer_bottom"):
            run(d, cls)
