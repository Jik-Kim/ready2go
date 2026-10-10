"""`vision_stub.yaml` 물체 좌표를 손끝 터치로 재기: 펜던트 base 좌표 → 서랍 좌표계 (x, y, yaw) (#6, A와 합의).

ROS·numpy 비의존 (pytest 대상). 3점 터치 원점과 같은 기준(닫힌 손끝)이라 줄자 오프셋이 섞이지 않는다.
  - 길쭉한 물체: 긴 변 양 끝(가운데 선 위) 두 점을 찍는다 → 중심 = 중점, yaw = 두 점 방향
  - 대칭 물체(위에서 본 모양이 둥글거나 정사각형, 예: masking_tape): 중심 한 점 → yaw 0
  - yaw 범위 (−π/2, π/2], −π/2는 +π/2 — ready2go_vision.core.pose_rules.normalize_yaw와 같은 규칙·같은 경계 테스트
    (패키지 사이 의존을 만들지 않으려고 import하지 않음)
  - top_z는 터치하지 않고 온톨로지 size_m[2](#8 버니어 실측)를 쓴다
측정 전: 펜던트 활성 TCP = GripperDA_v1, 툴 = tool_weight 확인, 그리퍼 닫고 수직 아래, 서랍 최대 인출.

단독 실행 (펜던트 base 좌표 X Y Z mm 그대로, 점 1개 또는 2개):
    python3 stub_measure.py --class eraser --point 380.1 -150.2 210.0 --point 420.3 -160.4 210.1
"""
import argparse
import math
import sys
from pathlib import Path
from typing import Mapping, Sequence


def normalize_yaw(yaw: float) -> float:
    """임의의 각도(rad)를 같은 직선을 나타내는 (−π/2, π/2] 값으로. −π/2 는 +π/2 로 쓴다."""
    return yaw - math.pi * math.ceil(yaw / math.pi - 0.5)


def _rot(q_xyzw):
    x, y, z, w = q_xyzw
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def base_to_frame(tf: Mapping, p_base_m: Sequence[float]) -> tuple:
    """base 점 → 자식 좌표계 (R^T (p − t))."""
    r, t = _rot(tf["quaternion_xyzw"]), tf["translation_m"]
    d = [p - o for p, o in zip(p_base_m, t)]
    return tuple(sum(r[i][j] * d[i] for i in range(3)) for j in range(3))


def measure(tf: Mapping, points_mm: Sequence[Sequence[float]], tip_offset_mm: float = 10.0) -> dict:
    """찍은 점(TCP mm, 1~2개) → {position: [x, y, 0.0], yaw, floor_gap_m}. floor_gap_m = 손끝이 서랍 바닥 위 몇 m(점검용)."""
    if len(points_mm) not in (1, 2):
        raise ValueError("점은 1개(대칭 물체) 또는 2개(긴 변 양 끝)")
    local = [base_to_frame(tf, (p[0] / 1000, p[1] / 1000, (p[2] - tip_offset_mm) / 1000)) for p in points_mm]
    cx = sum(p[0] for p in local) / len(local)
    cy = sum(p[1] for p in local) / len(local)
    yaw = 0.0
    if len(local) == 2:
        dx, dy = local[1][0] - local[0][0], local[1][1] - local[0][1]
        if math.hypot(dx, dy) < 0.005:
            raise ValueError("두 점이 5 mm 안 — 긴 변 양 끝을 찍었는지 확인")
        yaw = normalize_yaw(math.atan2(dy, dx))
    return {"position": [round(cx, 4), round(cy, 4), 0.0], "yaw": round(yaw, 4) + 0.0,   # -0.0 → 0.0
            "floor_gap_m": round(min(p[2] for p in local), 4)}


def stub_line(cls: str, m: Mapping, top_z: float) -> str:
    """vision_stub.yaml objects 한 줄."""
    return f"- {{class: {cls}, position: {m['position']}, yaw: {m['yaw']}, top_z: {top_z}}}"


def main(argv=None) -> int:
    import yaml
    root = Path(__file__).resolve().parents[5]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class", dest="cls", required=True, help="온톨로지 물품 키 (예: eraser)")
    ap.add_argument("--point", nargs=3, type=float, action="append", required=True, metavar=("X", "Y", "Z"))
    ap.add_argument("--drawer", default="drawer_top")
    ap.add_argument("--tip-offset-mm", type=float, default=10.0, help="닫힌 손끝이 TCP보다 아래인 거리 [실측 B 10/03]")
    ap.add_argument("--config-dir", default=str(root / "config"))
    ap.add_argument("--world", default=str(root / "knowledge/world.jsonld"))
    a = ap.parse_args(argv)
    places = yaml.safe_load(Path(a.config_dir, "places.yaml").read_text(encoding="utf-8"))
    world = yaml.safe_load(Path(a.world).read_text(encoding="utf-8"))
    items = world.get("world", world).get("items", {})
    if a.cls not in items:
        print(f"온톨로지에 없는 물품: {a.cls}", file=sys.stderr)
        return 1
    m = measure(places[a.drawer]["tf"], a.point, a.tip_offset_mm)
    print(stub_line(a.cls, m, items[a.cls]["size_m"][2]))
    print(f"# 손끝–바닥 {m['floor_gap_m'] * 1000:.1f} mm (물체 윗면을 찍었으면 물체 높이와 비슷해야 함), 점 {len(a.point)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
