"""mock 장면: 여러 물체가 겹친 서랍 (ROS 비의존) — Unpacking 태스크를 로봇 없이 끝까지 시험 (FR-ACT-04, #109·#120).

MockSkills(scene=...) 가 inspect_region·pick_object·place_object·nudge_object 를 이 장면으로 답한다.
- 인식: 남아 있는 물체 전부. 목표는 search_target 과 같은 class, 나머지는 candidates(top_z 높은 순).
  각 물체에 occluded_by(그 물체 위에 얹힌 물체 id)·visible_area_m2(덮였으면 절반) — #169 계약 모양.
  id 는 촬영마다 "<class>#1" (첫 시연은 class 당 1개, #109).
- 집기: 위에 다른 물체가 얹혀 있으면 GRASP_FAILED(순서가 틀린 태스크를 잡기 위함), 이미 쥐었으면 HOLDING_OBJECT.
- 놓기: handover_zone 이면 전달(장면에서 빠짐). 서랍이면 slot 또는 pose 자리에 바닥으로 놓음 — 다른 물체와
  PLACE_GAP_M 보다 가까우면 움직이기 전 PLACE_BLOCKED(blocked_by), scan 없으면 BAD_PARAMS (#166 계약).
  placed_pose = 명령한 자리. 실물의 놓기 오차·미끄러짐은 PLACE_JITTER_M 만큼 흉내.
- 끌기: 장면 물체는 벽에서 떨어져 있으므로 끌지 않음(pushed false).
실물 B·A 동작(지지면·얹힌 물체 집기 NOT_ON_FLOOR 등)과 다를 수 있다 — 흐름 시험용.
"""
from __future__ import annotations

import copy
import math

PLACE_GAP_M = 0.05                      # mock 놓기 검사: 다른 물체 중심과 이보다 가까우면 막힘
PLACE_JITTER_M = 0.003                  # mock 놓기 오차 (다시 찍으면 명령한 자리에서 이만큼 어긋나 보임)

# 고정 빈 자리 (B #120: aside_1·aside_2, 실물 값은 B 교시 places.yaml) — mock 값
SLOTS = {"aside_1": [0.045, 0.045], "aside_2": [0.045, 0.25]}

# 장면: class → 서랍 좌표 x·y(m), yaw, 윗면 높이 top_z, 물체 자체 높이 height(바닥에 놓으면 top_z = height),
# 다 보일 때 면적 area(m², visible_area_m2 — 덮였으면 절반), 아래 물체 on. 높이는 world size_m[2] 근처 mock 값
SCENES = {
    # E #109 위 서랍 배치안: 목표 렌치를 망치가 일부 덮고, 차키가 망치 일부를 덮음 → 차키 → 망치 → 렌치
    "occluded_top": {
        "toy_wrench": {"xy": [0.12, 0.13], "yaw": 0.0, "top_z": 0.0185, "height": 0.0185, "area": 0.0104, "on": []},
        "toy_hammer": {"xy": [0.12, 0.16], "yaw": 0.0, "top_z": 0.0435, "height": 0.025, "area": 0.0135,
                       "on": ["toy_wrench"]},
        "car_key": {"xy": [0.12, 0.19], "yaw": 0.0, "top_z": 0.059, "height": 0.0158, "area": 0.0027,
                    "on": ["toy_hammer"]},
    },
    # E #109 아래 서랍 배치안 모양 (위 서랍에서 시험): 덮개 판이 지우개를 덮고, 립밤은 떨어진 곳
    "plate_over_eraser": {
        "eraser": {"xy": [0.12, 0.12], "yaw": 0.0, "top_z": 0.0115, "height": 0.0115, "area": 0.0012, "on": []},
        "cover_plate": {"xy": [0.12, 0.13], "yaw": 0.0, "top_z": 0.052, "height": 0.0405, "area": 0.0073,
                        "on": ["eraser"]},
        "lip_balm": {"xy": [0.15, 0.26], "yaw": 0.0, "top_z": 0.02, "height": 0.02, "area": 0.0014, "on": []},
    },
}


class MockScene:
    def __init__(self, name: str, region: str = "drawer_top"):
        if name not in SCENES:
            raise ValueError(f"mock 장면 이름: {sorted(SCENES)} 중 하나 — 받은 값 {name!r}")
        self.name, self.region = name, region
        self.objects = copy.deepcopy(SCENES[name])
        self.held: str | None = None
        self.delivered: list[str] = []

    # ---- 인식 ----
    def inspect(self, region: str, search_target: str) -> dict:
        def view(cls: str) -> dict:
            o = self.objects[cls]
            above = [f"{c}#1" for c, other in self.objects.items() if cls in other["on"]]
            return {"id": f"{cls}#1", "class": cls, "top_z": o["top_z"],
                    "pose": {"frame": region, "position": [o["xy"][0], o["xy"][1], 0.0], "yaw": o["yaw"],
                             "yaw_valid": not above},                  # 일부만 보이면 yaw 를 못 믿음 (A #120)
                    "occluded_by": above, "visible_area_m2": round(o["area"] * (0.5 if above else 1.0), 5)}
        seen = [view(c) for c in self.objects]
        target = next((v for v in seen if v["class"] == search_target), None) if search_target else None
        candidates = sorted((v for v in seen if v is not target), key=lambda v: -v["top_z"])
        return {"target_found": target is not None, "target": target, "candidates": candidates,
                "visible_count": len(seen)}

    # ---- 동작 ----
    def pick(self, params: dict) -> tuple[bool, str, dict | None]:
        target = params.get("target") if isinstance(params.get("target"), dict) else {}
        cls = target.get("class") or str(target.get("id", "")).split("#")[0]
        if self.held:
            return False, "HOLDING_OBJECT", None
        if cls not in self.objects:
            return False, "GRASP_FAILED", None
        if any(cls in o["on"] for o in self.objects.values()):   # 위에 얹힌 물체가 있음 → 순서가 틀림
            return False, "GRASP_FAILED", None
        self.held = cls
        self._held_info = self.objects.pop(cls)
        return True, "", {"object_id": f"{cls}#1", "class": cls, "pick_pose_drawer_frame": None, "grasp_ok": True}

    def place(self, params: dict) -> tuple[bool, str, dict | None]:
        if not self.held:
            return False, "NOT_HOLDING", {"slot": None, "placed_pose": None}
        location = params.get("location")
        if location == "handover_zone":
            self.delivered.append(self.held)
            self.held = None
            return True, "", {"slot": "handover_zone_1",
                              "placed_pose": {"frame": "handover_zone", "position": [0.0225, 0.045, 0.0]}}
        if not isinstance(params.get("scan"), dict) or ("slot" in params) == ("pose" in params):
            return False, "BAD_PARAMS", {"slot": None, "placed_pose": None}
        if "slot" in params:
            if params["slot"] not in SLOTS:
                return False, "PLACE_NOT_CONFIGURED", {"slot": None, "placed_pose": None}
            xy, yaw = list(SLOTS[params["slot"]]), 0.0
        else:
            pose = params["pose"] or {}
            xy, yaw = list(pose.get("position", [0, 0])[:2]), float(pose.get("yaw") or 0.0)
        for cls, o in self.objects.items():                       # 움직이기 전 이웃 검사
            if math.dist(xy, o["xy"]) < PLACE_GAP_M:
                return False, "PLACE_BLOCKED", {"slot": None, "placed_pose": None, "blocked_by": f"{cls}#1"}
        info = self._held_info                                   # 바닥에 놓음 (지지면 = 바닥만, B 첫 구현 #166)
        self.objects[self.held] = {**info, "xy": [round(xy[0] + PLACE_JITTER_M, 4), xy[1]], "yaw": yaw,
                                   "top_z": info["height"], "on": []}
        self.held = None
        placed = {"frame": location, "position": [xy[0], xy[1], 0.0], "yaw": yaw}
        return True, "", {"slot": params.get("slot"), "placed_pose": placed}

    def nudge(self, params: dict) -> tuple[bool, str, dict]:
        target = params.get("target") if isinstance(params.get("target"), dict) else None
        return True, "", {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": target}

