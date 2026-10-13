"""trace_unpack 가상 장면 갱신 (#306 E 리뷰). Isaac·ROS·덤프 없이."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_unpack as tu  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ITEMS = json.loads((REPO / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]


def _obj(oid, cls, x, y, top_z, yaw=0.0, occluded_by=()):
    return {"id": oid, "class": cls, "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
            "top_z": top_z, "occluded_by": list(occluded_by)}


def _stack():
    """캐러멜 위 차키 (차키 top_z 52.8 mm — E 리뷰 반례 높이)."""
    car = _obj("caramel_box#1", "caramel_box", 0.09, 0.20, 0.037, occluded_by=["car_key#1"])
    key = _obj("car_key#1", "car_key", 0.09, 0.20, 0.0528)
    return {"target": None, "candidates": [car, key]}


def test_unstack_updates_height_and_relations():
    """make_room unstack 으로 쌓인 차키를 바닥 빈 자리에 놓으면 다음 가상 인식의 top_z 는 단품 높이, 캐러멜 가림 관계도 빠짐."""
    sc = tu.Scene(_stack(), "drawer_top", ITEMS)
    sc.unstack("car_key#1", {"position": [0.06, 0.08, 0.0], "yaw": 0.0})
    res = sc.scan("caramel_box")
    key = next(o for o in res["candidates"] if o["id"] == "car_key#1")
    assert abs(key["top_z"] - ITEMS["car_key"]["size_m"][2]) < 1e-4          # 52.8 mm 가 남지 않음
    assert key["pose"]["position"][:2] == [0.06, 0.08]
    assert res["target"]["occluded_by"] == []
    assert "car_key#1" in sc.placed


def test_move_alone_keeps_height_but_tracks_place():
    """평면 넛지·sweep(move)는 높이를 바꾸지 않되, 옮긴 자리는 추적함."""
    sc = tu.Scene(_stack(), "drawer_top", ITEMS)
    sc.move("caramel_box#1", {"position": [0.12, 0.20, 0.0], "yaw": 0.0})
    assert sc.placed["caramel_box#1"] == (0.12, 0.20)


def _merge_after_dump(sc, dump_res, search="eraser"):
    return tu.merge_dump(sc, copy.deepcopy(dump_res), search)


def test_moved_object_keeps_sim_place_on_next_dump():
    """넛지로 옮긴 물체는 다음 실물 덤프가 원래 자리를 보여도 시뮬 자리로 합침 (E 리뷰 2 반례: x 29 → 다음 덤프 80)."""
    first = {"target": _obj("eraser#1", "eraser", 0.109, 0.127, 0.0115),
             "candidates": [_obj("lip_balm#1", "lip_balm", 0.080, 0.125, 0.020)]}
    sc = tu.Scene(first, "drawer_bottom", ITEMS)
    sc.move("lip_balm#1", {"position": [0.029, 0.125, 0.0], "yaw": 0.0})
    res, off = _merge_after_dump(sc, first)
    lip = next(o for o in res["candidates"] if o["id"] == "lip_balm#1")
    assert off == ["lip_balm#1"] and abs(lip["pose"]["position"][0] - 0.029) < 1e-6


def test_set_pose_keeps_place_on_next_dump():
    """--set-pose 로 바꾼 배치(scene.placed 로 추적)도 다음 실물 덤프에서 원래 자리로 돌아가지 않음."""
    orig = {"target": _obj("eraser#1", "eraser", 0.109, 0.127, 0.0115),
            "candidates": [_obj("lip_balm#1", "lip_balm", 0.080, 0.125, 0.020)]}
    edited = copy.deepcopy(orig)
    edited["candidates"][0]["pose"]["position"] = [0.038, 0.062, 0.0]
    sc = tu.Scene(edited, "drawer_bottom", ITEMS)
    sc.placed["lip_balm#1"] = (0.038, 0.062)                                 # main() 이 --set-pose 뒤 하는 것과 같음
    res, off = _merge_after_dump(sc, orig)
    lip = next(o for o in res["candidates"] if o["id"] == "lip_balm#1")
    assert off == ["lip_balm#1"] and lip["pose"]["position"][:2] == [0.038, 0.062]


def test_untouched_objects_use_dump():
    """손대지 않은 물체는 실물 인식 그대로 (합칠 것 없음)."""
    first = {"target": _obj("eraser#1", "eraser", 0.109, 0.127, 0.0115), "candidates": []}
    sc = tu.Scene(first, "drawer_bottom", ITEMS)
    res, off = _merge_after_dump(sc, first)
    assert off == [] and res["target"]["pose"]["position"][0] == 0.109
