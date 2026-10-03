"""서랍장을 씬에 만들 수 있는지 판단 (build_scene.py 와 verify_scene.py 가 같은 규칙을 쓴다). Isaac Sim 에 의존하지 않는다.

값이 하나라도 비어 있으면(null) 서랍장은 만들지 않고, 그 이유를 목록으로 돌려준다.
- 형상 치수: sim/drawer_dimensions.yaml
- 서랍 내부 치수·최대 인출 거리: config/places.yaml (정본)
"""

# build_scene.py 의 서랍장 형상 코드가 지원하는 단 수. 새 서랍(2단)은 아직 형상 코드가 없다.
SUPPORTED_TIERS = 3


def cabinet_missing(dim: dict, places: dict) -> list[str]:
    """서랍장을 만들기 위해 아직 필요한 항목(사람이 읽는 이름)의 목록. 비어 있으면 만들 수 있다."""
    u = dim.get("drawer_unit") or {}
    top = dim.get("drawer_top") or {}
    pv = dim.get("plan_view_cm") or {}
    pt = places.get("drawer_top") or {}
    need = {
        "drawer_unit.width_cm": u.get("width_cm"),
        "drawer_unit.depth_cm": u.get("depth_cm"),
        "drawer_unit.total_height_cm": u.get("total_height_cm"),
        "drawer_unit.seat_top_vs_table_surface_cm": u.get("seat_top_vs_table_surface_cm"),
        "drawer_top.front_bottom_height_above_seat_cm": top.get("front_bottom_height_above_seat_cm"),
        "plan_view_cm.drawer_right_edge_to_table_right": pv.get("drawer_right_edge_to_table_right"),
        "plan_view_cm.drawer_left_edge_to_table_left": pv.get("drawer_left_edge_to_table_left"),
        "plan_view_cm.drawer_front_to_table_edge_gap": pv.get("drawer_front_to_table_edge_gap"),
        "places.yaml drawer_top.interior_m": pt.get("interior_m"),
        "places.yaml drawer_top.max_travel_m": pt.get("max_travel_m"),
    }
    missing = [k for k, v in need.items() if v is None]
    tiers = u.get("tiers")
    if tiers is not None and tiers != SUPPORTED_TIERS:
        missing.append(f"build_scene.py 의 서랍장 형상 코드가 {tiers}단 서랍장을 아직 지원하지 않음 ({SUPPORTED_TIERS}단만 지원)")
    return missing
