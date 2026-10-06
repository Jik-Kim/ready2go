import json
from pathlib import Path
import pytest
from ready2go_voice.core.config import load_config
from ready2go_knowledge.core.ontology import load

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    return load_config(PACKAGE / 'params/voice.yaml')


@pytest.fixture
def ontology():
    return load(ROOT / 'knowledge/robot_ontology.jsonld')


@pytest.fixture
def schema():
    return json.loads((ROOT / 'contracts/intent.schema.json').read_text())
