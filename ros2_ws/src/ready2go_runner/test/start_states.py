"""시험 시작 상태 — 저장소 knowledge/snapshots/initial_state.json 내용과 무관하게 시험이 직접 정한다 (#283 E 리뷰).

- P1_TOP: P1 시험 (find_item·p1_demo_eraser·플래너 기본) — 등록 물품 10종이 모두 위 칸 (#283 이전 initial_state 와 같음)
- P2_SINGLE: P2 선정 목표 — 사용자 확정 단일 배치 (위 칸 S1 toy_wrench·caramel_box·car_key, 아래 칸 S2 cover_plate·eraser·lip_balm, #283)
운영 initial_state 를 시험에 맞춰 되돌리지 않는다. 위 두 배치가 운영 파일과 달라도 시험 결과는 같다.
"""
import copy

P1_TOP = {item: "drawer_top" for item in (
    "airpods_case", "caramel_box", "car_key", "eraser", "lip_balm",
    "masking_tape", "toy_car", "toy_wrench", "toy_hammer", "cover_plate")}
P2_SINGLE = {"toy_wrench": "drawer_top", "caramel_box": "drawer_top", "car_key": "drawer_top",
             "cover_plate": "drawer_bottom", "eraser": "drawer_bottom", "lip_balm": "drawer_bottom"}


def start_state(located: dict) -> dict:
    """홈·빈손·두 서랍 닫힘·전달 트레이 열림 + 물품 위치."""
    return {"robot_pose": {"robot": "home"}, "gripper": {"robot": "empty"},
            "open": {"drawer_top": False, "drawer_bottom": False, "handover_zone": True},
            "located_in": dict(located)}


def with_state(onto: dict, located: dict) -> dict:
    """온톨로지(스킬·world 는 저장소 그대로)에 시작 상태만 바꿔 끼운 복사본."""
    out = copy.deepcopy(onto)
    out["state"] = start_state(located)
    return out
