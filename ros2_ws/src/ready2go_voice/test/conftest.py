import json
from pathlib import Path
import pytest
from ready2go_voice.core.config import load_config
from ready2go_knowledge.core.ontology import load

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    # 기존 게이트 회귀는 평가 모드를 명시합니다. 제품 기본값은 별도 검사합니다.
    return load_config(PACKAGE / 'params/voice.yaml', evaluation_mode=True)


@pytest.fixture
def ontology():
    return load(ROOT / 'knowledge/robot_ontology.jsonld')


@pytest.fixture
def schema():
    return json.loads((ROOT / 'contracts/intent.schema.json').read_text())
