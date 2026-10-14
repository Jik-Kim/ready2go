"""작업 실패 원인 안내 문장 (ROS 비의존) — E #196 10/14 요청: 실패가 정해진 뒤 서랍 정리(복구·닫기·홈) 전에 기존 speak 로 원인을 먼저.

Runner 가 finally 시작 때 블랙보드 run_failure = {code, step, action, text} 를 넣고(sequence 가 StepFailed 로 끝났을 때만 —
정지·취소(Halted)·성공이면 None), 태스크 finally 첫머리가 text 를 그대로 speak 한다. 문구는 E 가 대조 [팀 확정 필요].
코드가 확인한 원인·실패 동작만 말한다 — 일반 TIMEOUT 은 실패 동작과 함께, 근거 없이 카메라 단절·넛지 불필요라고 하지 않음.
안내 자체(speak)가 실패한 경우는 다시 말하지 않음(None).
"""
from __future__ import annotations

from .variables import attach_particle

# 원인을 코드만으로 아는 것 (비전·좌표 — inspect_region 이 돌려준 코드)
BY_CODE = {
    "CAMERA_TIMEOUT": "카메라 영상이 제때 오지 않아서 멈췄어요",
    "DEPTH_INVALID": "깊이 영상을 확인하지 못해서 멈췄어요",
    "TF_UNAVAILABLE": "서랍 위치를 계산하지 못해서 멈췄어요",
    "REGION_NOT_VISIBLE": "서랍 안이 카메라에 보이지 않아서 멈췄어요",
}
# 동작 이름 (원자 동작·스킬) — TIMEOUT 과 그 밖의 실패 문장에 씀
ACTION_KO = {
    "pick_object": "물건 집기", "pick": "물건 집기",
    "place_object": "물건 놓기", "place": "물건 놓기",
    "nudge_object": "물건 끌어오기",
    "drawer_control": "서랍 여닫기", "open_drawer": "서랍 열기", "close_drawer": "서랍 닫기",
    "move_to_named_pose": "로봇 자세 이동",
    "inspect_region": "서랍 촬영",
    "select_obstacle": "치울 물건 고르기", "find_moved": "옮긴 물건 다시 찾기",
    "query_ontology": "물건 기록 확인",
}
GENERIC = "작업 중 문제가 생겨서 멈췄어요"
SILENT_ACTIONS = {"speak"}


def text(code: str | None, action: str | None) -> str | None:
    """원인 안내 한 문장. 말하지 않을 경우 None."""
    if action in SILENT_ACTIONS:
        return None
    if code in BY_CODE:
        return BY_CODE[code]
    name = ACTION_KO.get(action or "")
    if not name:
        return GENERIC
    if code == "TIMEOUT":
        return f"{attach_particle(name, '이')} 제한 시간 안에 끝나지 않아서 멈췄어요"
    return f"{name}에 실패해서 멈췄어요"
