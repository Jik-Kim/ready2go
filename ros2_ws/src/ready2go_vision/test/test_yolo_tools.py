"""tools/yolo 의 클래스 번호 고정 회귀 테스트 (PR #45 리뷰). CI 에는 cv2·PyYAML 이 없어도 돌도록 build_dataset 쪽은 순수 파이썬만 쓴다."""
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[4] / "tools/yolo"
sys.path.insert(0, str(TOOLS))


import build_dataset as bd  # noqa: E402  (make_synthetic 이 import 하는 것과 같은 모듈 객체여야 ONTOLOGY 를 함께 바꿀 수 있다)


def make_ontology(tmp_path, split=False, items=("a", "b", "c")):
    world = {"world": {"items": {i: {"class": "Item"} for i in items}}}
    entry = tmp_path / "robot_ontology.jsonld"
    if split:
        (tmp_path / "world.jsonld").write_text(json.dumps(world), encoding="utf-8")
        entry.write_text(json.dumps({"sources": {"world": "world.jsonld"}}), encoding="utf-8")
    else:
        entry.write_text(json.dumps(world), encoding="utf-8")
    return entry


def make_sessions(tmp_path, cls=1):
    for s in ("s1", "s2"):
        (tmp_path / "labeled" / s / "images").mkdir(parents=True)
        (tmp_path / "labeled" / s / "labels").mkdir(parents=True)
        (tmp_path / "labeled" / s / "images" / "x.png").write_bytes(b"")
        (tmp_path / "labeled" / s / "labels" / "x.txt").write_text(f"{cls} 0.5 0.5 0.1 0.1\n", encoding="utf-8")


def run_main(monkeypatch, tmp_path, ontology, *extra):
    monkeypatch.setattr(bd, "ONTOLOGY", ontology)
    monkeypatch.setattr(sys, "argv", ["build_dataset", "--labeled", str(tmp_path / "labeled"), "--out", str(tmp_path / "out"),
                                      "--classes", str(tmp_path / "classes.txt"), "--val", "s2", *extra])
    return bd.main()


def test_ontology_items_reads_both_formats(tmp_path):
    single = tmp_path / "single"; single.mkdir()
    split = tmp_path / "split"; split.mkdir()
    assert bd.ontology_items(make_ontology(single)) == ["a", "b", "c"]
    assert bd.ontology_items(make_ontology(split, split=True)) == ["a", "b", "c"]


def test_missing_classes_file_fails_when_sessions_exist(tmp_path, monkeypatch):
    onto = make_ontology(tmp_path); make_sessions(tmp_path)
    assert run_main(monkeypatch, tmp_path, onto) == 1
    assert not (tmp_path / "out" / "dataset.yaml").exists()


def test_allow_ontology_order_is_explicit(tmp_path, monkeypatch):
    onto = make_ontology(tmp_path); make_sessions(tmp_path)
    assert run_main(monkeypatch, tmp_path, onto, "--allow-ontology-order") == 0
    assert (tmp_path / "out" / "dataset.yaml").exists()


def test_pinned_order_is_followed_even_if_ontology_changes(tmp_path, monkeypatch):
    onto = make_ontology(tmp_path); make_sessions(tmp_path)
    (tmp_path / "classes.txt").write_text("c\nb\na\n", encoding="utf-8")
    assert run_main(monkeypatch, tmp_path, onto) == 0
    assert (tmp_path / "out" / "classes.txt").read_text(encoding="utf-8").split() == ["c", "b", "a"]
    onto2 = make_ontology(tmp_path, items=("z", "a", "b", "c"))   # 온톨로지에 물품이 앞에 추가돼도 번호는 그대로
    assert run_main(monkeypatch, tmp_path, onto2) == 0
    assert (tmp_path / "out" / "classes.txt").read_text(encoding="utf-8").split() == ["c", "b", "a"]


def test_unknown_class_name_fails(tmp_path, monkeypatch):
    onto = make_ontology(tmp_path); make_sessions(tmp_path)
    (tmp_path / "classes.txt").write_text("a\nbanana\n", encoding="utf-8")
    assert run_main(monkeypatch, tmp_path, onto) == 1


def test_synthetic_generator_uses_the_pinned_list(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    onto = make_ontology(tmp_path)   # 항목 3개
    monkeypatch.setattr(bd, "ONTOLOGY", onto)
    (tmp_path / "classes.txt").write_text("b\na\n", encoding="utf-8")   # 고정 목록은 2개
    import make_synthetic as ms
    monkeypatch.setattr(sys, "argv", ["make_synthetic", "--out", str(tmp_path / "syn"), "--sessions", "1", "--per-session", "5",
                                      "--classes", str(tmp_path / "classes.txt")])
    ms.main()
    ids = {int(l.split()[0]) for f in (tmp_path / "syn").rglob("*.txt") for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
    assert ids and max(ids) <= 1, "합성 라벨이 고정 목록(2개)이 아니라 온톨로지(3개) 번호를 썼음"
