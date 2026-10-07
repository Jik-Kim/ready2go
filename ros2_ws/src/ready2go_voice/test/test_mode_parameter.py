"""실행 시 evaluation bool 우선순위. 실제 마이크/API/로봇 입력은 사용하지 않습니다."""
from pathlib import Path
import time
from types import SimpleNamespace
import pytest
import yaml
from ready2go_voice.core.config import load_config
from conftest import ROOT, PACKAGE


def test_package_default_execution_and_missing_yaml_key(cfg, tmp_path):
    default = load_config(PACKAGE/'params/voice.yaml')
    assert default['evaluation_mode'] is False
    assert (default['recording_mode'], default['record_duration_sec'], default['timing_mode']) == ('fixed', 5, 'commissioning')
    cfg.pop('evaluation_mode')
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    assert load_config(path)['evaluation_mode'] is False


@pytest.mark.parametrize('yaml_mode', [True, False])
@pytest.mark.parametrize('override', [True, False])
def test_effective_bool_overrides_yaml_without_other_config_changes(cfg, tmp_path, yaml_mode, override):
    cfg['evaluation_mode']=yaml_mode
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    loaded=load_config(path, evaluation_mode=override)
    assert loaded == dict(cfg, evaluation_mode=override)
    assert path.read_text() == yaml.safe_dump(cfg)


@pytest.mark.parametrize('bad', ['false', 'true', 0, 1, [], {}])
def test_invalid_mode_override_is_rejected(cfg, tmp_path, bad):
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match='evaluation_mode: bool'):
        load_config(path, evaluation_mode=bad)


@pytest.mark.parametrize('yaml_mode', [True, False])
@pytest.mark.parametrize('cli', [None, 'true', 'false'])
def test_real_ros_startup_bool_default_and_cli_priority(cfg, tmp_path, monkeypatch, yaml_mode, cli):
    rclpy=pytest.importorskip('rclpy')
    pytest.importorskip('ready2go_interfaces.action')
    from rclpy.context import Context
    import ready2go_voice.nodes.voice_node as runtime
    cfg.update(evaluation_mode=yaml_mode, audio_enabled=False,
               ontology_file=str(ROOT/'knowledge/robot_ontology.jsonld'),
               intent_schema_file=str(ROOT/'contracts/intent.schema.json'))
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    original=path.read_bytes()
    published=[]
    def speak(text, **kwargs):
        stamp={'tts_started_unix':123, 'tts_started_monotonic':time.monotonic(),
               'tts_start_basis':'mock', 'tts_mock':True}
        kwargs['on_start'](stamp)
        return stamp
    monkeypatch.setattr(runtime, 'create_tts', lambda _:SimpleNamespace(prepare=lambda:None, speak=speak, close=lambda:None))
    monkeypatch.setattr(runtime.threading, 'Thread', lambda *a, **k:SimpleNamespace(start=lambda:None, join=lambda **k:None))
    def publisher(_node, _type, topic, *args, **kwargs):
        return SimpleNamespace(publish=lambda doc: published.append(doc) if topic == '/voice/intent' else None)
    monkeypatch.setattr(runtime.VoiceNode, 'create_publisher', publisher)
    monkeypatch.setattr(runtime.VoiceNode, 'create_subscription', lambda *a, **k:None)
    monkeypatch.setattr(runtime, 'ActionServer', lambda *a, **k:SimpleNamespace(destroy=lambda:None))
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path/'ros_logs'))
    args=['--ros-args', '-p', 'config_file:='+str(path)]
    if cli is not None:args+=['-p','evaluation_mode:='+cli]
    context=Context(); node=None
    rclpy.init(args=args, context=context, domain_id=166)
    try:
        node=runtime.VoiceNode(context=context)
        expected=cli=='true'
        assert node.get_parameter('evaluation_mode').value is expected
        assert node.cfg['evaluation_mode'] is expected
        assert node.cfg is node.session.cfg is node.parser.cfg
        node.parser.llm=None
        node._deliver(node.parser.parse('지우개 찾아줘'),0)
        assert bool(published) == (not expected)
        assert path.read_bytes() == original
    finally:
        if node:node.close();node.destroy_node()
        context.shutdown()


@pytest.mark.parametrize('cli', ['1', "'false'"])
def test_real_ros_rejects_non_bool_before_runtime_creation(tmp_path, monkeypatch, cli):
    rclpy=pytest.importorskip('rclpy')
    pytest.importorskip('ready2go_interfaces.action')
    from rclpy.context import Context
    from rclpy.exceptions import InvalidParameterTypeException
    import ready2go_voice.nodes.voice_node as runtime
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path/'ros_logs'))
    monkeypatch.setattr(runtime,'load_config',lambda *a,**k:pytest.fail('invalid ROS bool reached config/session'))
    context=Context()
    rclpy.init(args=['--ros-args','-p','evaluation_mode:='+cli],context=context,domain_id=166)
    try:
        with pytest.raises(InvalidParameterTypeException):runtime.VoiceNode(context=context)
    finally:context.shutdown()
