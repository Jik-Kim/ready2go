"""layout_cases.json 형식 확인 — 관계·전략 이름, B 거부 코드가 실제 스킬 서버에 있는지.

저장소 루트에서: python3 practice/B/ontology/check_cases.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
DATA = pathlib.Path(__file__).with_name("layout_cases.json")
SKILLS = ROOT / "ros2_ws/src/ready2go_skills/ready2go_skills"
STATUS = {"verified_real", "unconfirmed", "sim_only", "layout_rule"}


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    rel, traits, strat = d["relations"], d["item_traits"], d["strategies"]
    src = "\n".join(p.read_text(encoding="utf-8") for p in SKILLS.rglob("*.py"))
    bad, ids = [], set()
    for c in d["cases"]:
        cid = c["id"]
        if cid in ids:
            bad.append(f"{cid}: id 중복")
        ids.add(cid)
        for w in c["when"]:
            m = re.match(r"(\w+)\(", w)
            if m and m.group(1) not in rel:
                bad.append(f"{cid}: 모르는 관계 {m.group(1)}")
            m = re.match(r"trait (\w+)", w)
            if m and m.group(1) not in traits:
                bad.append(f"{cid}: 모르는 성질 {m.group(1)}")
        for k in ("strategy", "then"):
            if k in c and c[k] not in strat:
                bad.append(f"{cid}: 모르는 전략 {c[k]}")
        code = c.get("b_code")
        if code and f'"{code}"' not in src and f"'{code}'" not in src:
            bad.append(f"{cid}: B 코드에 없는 거부 코드 {code}")
        if c["strategy"] == "impossible" and not c.get("reason"):
            bad.append(f"{cid}: impossible 인데 reason 없음")
        if c["status"] not in STATUS:
            bad.append(f"{cid}: 모르는 status {c['status']}")
        if not (c["evidence"]["real"] or c["evidence"]["sim"]):
            bad.append(f"{cid}: 근거 없음")
    by = {}
    for c in d["cases"]:
        by[c["strategy"]] = by.get(c["strategy"], 0) + 1
    print(f"난제 {len(d['cases'])}개 · 관계 {len(rel)}개 · 전략별 {by}")
    for b in bad:
        print("  ✗", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
