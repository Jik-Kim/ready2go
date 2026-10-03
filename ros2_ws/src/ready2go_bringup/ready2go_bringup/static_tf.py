"""고정 TF 목록 읽기 (ROS 비의존) — 결정 #23, docs/interfaces.md TF 표.

bringup 이 각 담당 파일을 직접 읽는다 (이슈 #3 합의):
- 손목 카메라: config/calibration/calibration_meta.yaml 의 derived_tf (A)
- 서랍·트레이: config/places.yaml 의 항목별 tf 블록 (B·E, 이슈 #6)
TF 블록 키: parent, child, translation_m [x, y, z], quaternion_xyzw [x, y, z, w]
tf 블록이 없거나 translation_m·quaternion_xyzw 가 둘 다 null 인 장소는 아직 측정 전이므로 건너뛰고 사유를 돌려준다.
한쪽만 채워진 블록은 입력 실수로 보고 StaticTfError.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

CALIBRATION_FILE = "calibration/calibration_meta.yaml"
PLACES_FILE = "places.yaml"
QUATERNION_TOLERANCE = 1e-3              # 단위 쿼터니언 허용 오차


@dataclass(frozen=True)
class StaticTf:
    parent: str
    child: str
    translation_m: tuple[float, float, float]
    quaternion_xyzw: tuple[float, float, float, float]
    source: str                          # 값이 나온 파일·항목 (로그용)


class StaticTfError(ValueError):
    """TF 블록 형식이 틀림. 잘못된 좌표로 로봇이 움직이지 않도록 bringup 을 멈춘다."""


def _numbers(value, count: int, what: str, source: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != count \
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        raise StaticTfError(f"{source}: {what} 는 숫자 {count}개여야 함: {value!r}")
    if not all(math.isfinite(v) for v in value):   # YAML .nan·.inf 도 float 라 위 검사를 통과함
        raise StaticTfError(f"{source}: {what} 에 NaN·무한대가 있음 (tf2 가 버려 TF 가 사라짐): {value!r}")
    return tuple(float(v) for v in value)


def parse_tf(block: dict, source: str) -> StaticTf:
    """TF 블록 하나를 검사해 StaticTf 로 만든다."""
    if not isinstance(block, dict):
        raise StaticTfError(f"{source}: TF 블록이 객체가 아님")
    for key in ("parent", "child"):
        if not isinstance(block.get(key), str) or not block[key]:
            raise StaticTfError(f"{source}: {key} 가 비어 있음")
    translation = _numbers(block.get("translation_m"), 3, "translation_m", source)
    quaternion = _numbers(block.get("quaternion_xyzw"), 4, "quaternion_xyzw", source)
    norm = math.sqrt(sum(q * q for q in quaternion))
    if abs(norm - 1.0) > QUATERNION_TOLERANCE:
        raise StaticTfError(f"{source}: quaternion_xyzw 가 단위 쿼터니언이 아님 (크기 {norm:.4f})")
    return StaticTf(block["parent"], block["child"], translation, quaternion, source)


def _not_measured(block) -> bool:
    return isinstance(block, dict) and block.get("translation_m") is None \
        and block.get("quaternion_xyzw") is None


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_static_tfs(config_dir: str | Path) -> tuple[list[StaticTf], list[str]]:
    """(발행할 TF 목록, 건너뛴 항목 사유) 를 돌려준다. 형식 오류는 StaticTfError."""
    config_dir = Path(config_dir)
    tfs: list[StaticTf] = []
    skipped: list[str] = []

    calib = config_dir / CALIBRATION_FILE
    if calib.exists():
        block = _load_yaml(calib).get("derived_tf")
        if block is None or _not_measured(block):
            skipped.append(f"{CALIBRATION_FILE}: derived_tf 없음 (캘리브레이션 전)")
        else:
            tfs.append(parse_tf(block, f"{CALIBRATION_FILE}:derived_tf"))
    else:
        skipped.append(f"{CALIBRATION_FILE}: 파일 없음")

    places = config_dir / PLACES_FILE
    for name, entry in (_load_yaml(places) if places.exists() else {}).items():
        block = entry.get("tf") if isinstance(entry, dict) else None
        if block is None:
            skipped.append(f"{PLACES_FILE}:{name}: tf 블록 없음 (측정 전, 이슈 #6)")
            continue
        if _not_measured(block):
            skipped.append(f"{PLACES_FILE}:{name}: tf 값 null (측정 전, #6)")
            continue
        tfs.append(parse_tf(block, f"{PLACES_FILE}:{name}.tf"))

    children = [tf.child for tf in tfs]
    duplicated = sorted({c for c in children if children.count(c) > 1})
    if duplicated:                       # TF 에서 한 프레임은 부모를 하나만 가질 수 있음
        raise StaticTfError(f"같은 child 프레임을 두 곳에서 발행: {duplicated}")
    return tfs, skipped
