"""TCP 3점 터치 → 장소 좌표계 static TF (`config/places.yaml`의 `tf` 블록 값) (#6).

ROS·numpy 비의존 (pytest 대상). 회전(ZYZ)은 쓰지 않고 세 점의 위치만 쓴다.
  P1 = 원점, P2 = x축 위의 점(멀수록 정확), P3 = xy 평면 위의 점(y가 +인 쪽)
  x = norm(P2 − P1), z = norm(x × (P3 − P1)), y = z × x  → 오른손 좌표계
축 방향(어느 모서리를 원점으로 할지)은 [팀 확정 필요]: z가 위(base +z)를 향하도록 P3을 고른다.
z가 아래를 향하면 경고한다 — P3을 반대쪽 모서리로 찍은 경우.

손끝 보정: 펜던트 좌표는 TCP(`GripperDA_v1`, 손가락 패드 부근) 위치라, 닫힌 손끝으로 찍으면
손끝이 TCP보다 약 10 mm 아래에 있다 [실측 B 10/03, #7]. 그대로 넣으면 좌표계가 그만큼 위로 뜨므로
`tip_offset_mm`(손끝 돌출량)을 세 점의 z에서 뺀다. **툴이 수직 아래(base −z)를 향한 자세로 찍는다고 가정**한다.

단독 실행 (펜던트 베이스 좌표 X·Y·Z mm 그대로):
    python3 touch_frame.py --child drawer_top \\
        --origin 400.1 -120.3 150.2 --x-point 600.0 -121.0 150.0 --xy-point 401.0 150.5 150.4 \\
        --tip-offset-mm 10
"""
import argparse
import math
import sys
from dataclasses import dataclass

MIN_SPAN_MM = 50.0          # P1–P2, P1–P3 최소 거리. 가까우면 축 방향 오차가 커진다 [추정]
MAX_PLANE_SKEW_DEG = 5.0    # P1P2 와 P1P3 사이 각이 90°에서 이만큼 벗어나면 경고 [추정]


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return [v / n for v in a]


def quaternion_xyzw(x_axis, y_axis, z_axis) -> list:
    """열벡터가 x·y·z 축인 회전행렬 → 쿼터니언 [x, y, z, w], w ≥ 0 (calibration_meta.yaml 규약)."""
    m = [[x_axis[r], y_axis[r], z_axis[r]] for r in range(3)]
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = [0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = [(m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s]
    q = [v / math.sqrt(sum(c * c for c in q)) for v in q]
    return [-v for v in q] if q[3] < 0 else q


@dataclass(frozen=True)
class TouchFrame:
    translation_m: list        # base_link 기준 원점 [m]
    quaternion_xyzw: list      # base_link → 장소 좌표계 회전, w ≥ 0
    x_axis: list
    y_axis: list
    z_axis: list
    plane_angle_deg: float     # P1P2 와 P1P3 사이 각 (직각 모서리면 약 90)
    warnings: list


def frame_from_touch(origin_mm, x_point_mm, xy_point_mm, *, tip_offset_mm: float = 0.0) -> TouchFrame:
    """세 점(mm, base_link, 펜던트 TCP 좌표) → 장소 좌표계. 점이 너무 가깝거나 한 직선 위면 ValueError.

    `tip_offset_mm`: 닫힌 손끝이 TCP보다 아래로 나온 길이 [팀 확정 필요, 측정 당일 자로 실측].
    세 점에 똑같이 적용되므로 회전은 그대로이고 원점 z만 내려간다.
    """
    if tip_offset_mm < 0:
        raise ValueError(f"tip_offset_mm는 0 이상: {tip_offset_mm}")
    origin_mm, x_point_mm, xy_point_mm = (
        [p[0], p[1], p[2] - tip_offset_mm] for p in (origin_mm, x_point_mm, xy_point_mm))
    v1 = _sub(x_point_mm, origin_mm)
    v2 = _sub(xy_point_mm, origin_mm)
    if _norm(v1) < MIN_SPAN_MM or _norm(v2) < MIN_SPAN_MM:
        raise ValueError(f"P1에서 P2·P3까지 {MIN_SPAN_MM} mm 이상 떨어져야 함: "
                         f"{_norm(v1):.1f}, {_norm(v2):.1f} mm")
    x = _unit(v1)
    zc = _cross(x, v2)
    if _norm(zc) / _norm(v2) < math.sin(math.radians(10)):
        raise ValueError("세 점이 거의 한 직선 위에 있음 (P1P2–P1P3 각 10° 미만)")
    z = _unit(zc)
    y = _cross(z, x)

    angle = math.degrees(math.acos(max(-1.0, min(1.0, _dot(v1, v2) / (_norm(v1) * _norm(v2))))))
    warnings = []
    if abs(angle - 90.0) > MAX_PLANE_SKEW_DEG:
        warnings.append(f"P1P2–P1P3 각 {angle:.1f}° (직각 모서리면 약 90°) — 찍은 점 확인")
    if z[2] < 0:
        warnings.append("z축이 아래(base −z)를 향함 — P3을 x축의 반대쪽에서 찍었는지 확인")
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, abs(z[2])))))
    if tilt > MAX_PLANE_SKEW_DEG:
        warnings.append(f"평면이 수평에서 {tilt:.1f}° 기울어 있음 — 서랍 설치·찍은 점 확인")

    return TouchFrame(
        translation_m=[v / 1000.0 for v in origin_mm],
        quaternion_xyzw=quaternion_xyzw(x, y, z),
        x_axis=x, y_axis=y, z_axis=z,
        plane_angle_deg=angle,
        warnings=warnings,
    )


def places_tf_line(child: str, frame: TouchFrame, parent: str = "base_link") -> str:
    """places.yaml 에 그대로 붙일 tf 한 줄."""
    t = ", ".join(f"{v:.5f}" for v in frame.translation_m)
    q = ", ".join(f"{v:.6f}" for v in frame.quaternion_xyzw)
    return (f"tf: {{parent: {parent}, child: {child}, "
            f"translation_m: [{t}], quaternion_xyzw: [{q}]}}")


def main() -> int:
    ap = argparse.ArgumentParser(description="TCP 3점 터치(mm) → places.yaml tf 블록")
    ap.add_argument("--child", required=True, help="장소 이름 (drawer_top, staging_tray, ...)")
    ap.add_argument("--origin", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"))
    ap.add_argument("--x-point", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"))
    ap.add_argument("--xy-point", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"))
    ap.add_argument("--tip-offset-mm", type=float, required=True,
                    help="닫힌 손끝이 TCP보다 아래로 나온 길이 mm (툴 수직 아래 가정). 보정하지 않으려면 0")
    args = ap.parse_args()
    try:
        f = frame_from_touch(args.origin, args.x_point, args.xy_point, tip_offset_mm=args.tip_offset_mm)
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    print(places_tf_line(args.child, f))
    print(f"# x축 {[round(v, 4) for v in f.x_axis]}, y축 {[round(v, 4) for v in f.y_axis]}, "
          f"z축 {[round(v, 4) for v in f.z_axis]}, P1P2–P1P3 각 {f.plane_angle_deg:.1f}°")
    for w in f.warnings:
        print(f"경고: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
