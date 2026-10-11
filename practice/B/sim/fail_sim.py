"""중간 실패·복구 시뮬레이션 — 실패를 일부러 넣고(빈손 닫힘·옮기다 놓침·끌다 걸림·서버 재시작), 그 자리에서 다음 스킬(다시 집기·닫기·놓기)이
그대로 되는지. 단계마다 추정 시간 [s] (사다리꼴 속도 + 멈춤 + 그리퍼 0.8 s) [추정].
  python3 practice/B/sim/fail_sim.py"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sim
from demo_sim import run_scenario, obj
from p2_demo import PL, scan, common_open, common_close


def setv(**kv):
    def f(robot, srv):
        for k, v in kv.items():
            setattr(robot, k, v)
    return f


def drop(robot, srv):
    robot.ss.Rg2.width = 0.9                      # 그리퍼가 빈손 닫힘으로 (옮기다 놓침)


def restart(keep_holding):
    def f(robot, srv):
        ss = robot.ss
        srv.held_file = Path("/tmp/claude-0/fail_sim_held.json")
        srv.held = dict(srv.held) if srv.held else None   # 파일에 저장
        new = object.__new__(ss.SkillServer)
        new.__dict__.update({k: v for k, v in srv.__dict__.items() if k != "_held"})
        if not keep_holding:
            ss.Rg2.width = 99.0                   # 재시작 사이에 놓쳐 활짝 열림
        new.get_logger = lambda: __import__("types").SimpleNamespace(info=lambda m: None, warning=lambda m: None, warn=lambda m: None)
        new._held = new._restore_held()
        print(f"      재시작: 쥔 물체 복원 {(new._held or {}).get('id')}")
        return new
    return f


def flows(drawer):
    I = PL[drawer]["interior_m"]
    E = obj("eraser#1", "eraser", 0.110, 0.200, 0.0, 0.0115, drawer)
    Ew = obj("eraser#1", "eraser", 0.110, I[1] - 0.016, 0.0, 0.0115, drawer)          # 오른쪽 벽에 세로로 붙음 → 넛지
    pick = lambda T, lab="pick 지우개": (lab, "pick_object", {"target": T, "approach_offset": [0, 0, 0.1], "scan": scan(T)})
    tray = lambda lab="place 지우개 → 트레이": (lab, "place_object", {"location": "handover_zone"})
    yield "빈손 닫힘 → 다시 집기", common_open(drawer) + [
        ("주입: 빈손 닫힘 1번", "_do", setv(fail_grasp=1)), pick(E, "!pick 지우개 (빈손)"), pick(E, "pick 지우개 (다시)"), tray()] + common_close(drawer)
    yield "옮기다 놓침 → 서랍 닫기", common_open(drawer) + [
        pick(E), ("주입: 놓침", "_do", drop), tray("!place 지우개 → 트레이 (놓침)")] + common_close(drawer)
    yield "쥔 채 서버 재시작 → 놓기", common_open(drawer) + [
        pick(E), ("주입: 서버 재시작 (쥔 채)", "_do", restart(True)), tray()] + common_close(drawer)
    yield "재시작 사이 놓침 → 놓기 거부 → 닫기", common_open(drawer) + [
        pick(E), ("주입: 서버 재시작 (놓침)", "_do", restart(False)), tray("!place 지우개 → 트레이 (NOT_HOLDING)")] + common_close(drawer)
    yield "끌다 걸림 → 다시 넛지·집기", common_open(drawer) + [
        ("주입: 끌기 걸림 1번", "_do", setv(block_drag=1)), pick(Ew, "!pick 지우개 (넛지 걸림)"), pick(Ew, "pick 지우개 (다시)"), tray()] + common_close(drawer)


if __name__ == "__main__":
    res = []
    for d in ("drawer_top", "drawer_bottom"):
        for name, steps in flows(d):
            ok, robot, srv = run_scenario(name, d, steps)
            res.append((d, name, ok))
    print()
    for d, name, ok in res:
        print(f"{'OK ' if ok else 'FAIL'} {d} {name}")
    tot = collections.defaultdict(list)
    for sc, d, lab, t in demo_sim.TIMES:
        if lab.startswith("pick") or lab.startswith("place"):
            tot[lab.split()[0]].append(t)
    for k, v in tot.items():
        print(f"{k}: 추정 {min(v):.1f}~{max(v):.1f} s")
