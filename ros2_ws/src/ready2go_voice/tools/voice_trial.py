#!/usr/bin/env python3
"""명시 prepare/live 실행. 원본 local·기존 로그를 보존하는 E 시험 도구."""
import argparse
import contextlib
import codecs
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import yaml
from ready2go_voice.core.config import load_config
from ready2go_voice.core.diagnostics import redact
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_knowledge.core.ontology import load

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[2]
REQUIRED = ('dialogue_timeout_sec','resume_admission_window_sec','resume_stt_result_timeout_sec',
    'resume_independent_request_timeout_sec','place_admission_window_sec','place_stt_result_timeout_sec',
    'place_max_reasks','p2_goal_catalog')


def trial_config(original, folder, *, silence=False, auto_complete=False):
    raw = yaml.safe_load(Path(original).read_text())
    cfg = load_config(original)
    base = yaml.safe_load((PACKAGE/'params/voice.yaml').read_text())
    for key in REQUIRED:
        if key not in raw:
            cfg[key] = base.get(key)
        if cfg.get(key) is None:
            raise ValueError('TRIAL_CONFIG_UNCONFIRMED')
    for env, key, default in (('E_VOICE_CUE','wake_cue_enabled','1'),
                             ('E_VOICE_SAVE_WAV','capture_save_wav','1'),('E_VOICE_TRIM','capture_trim','0')):
        value = os.environ.get(env,default)
        if value not in ('0','1'):
            raise ValueError('TRIAL_SWITCH_INVALID')
        cfg['voice_flow'][key] = value == '1'
    for env in ('E_VOICE_SILENCE','E_VOICE_AUTO_COMPLETE'):
        if os.environ.get(env,'0') not in ('0','1'):
            raise ValueError('TRIAL_SWITCH_INVALID')
    hint = os.environ.get('E_VOICE_STT_HINT','')
    if hint not in ('','0','1'):
        raise ValueError('TRIAL_SWITCH_INVALID')
    if hint:
        cfg['voice_flow']['stt_context_hint_enabled'] = hint == '1'
    cfg['voice_flow']['cue_gain'] = base['voice_flow']['cue_gain']
    cfg['tts_prefill_max_texts'] = base['tts_prefill_max_texts']
    cfg['cancel_phrases'] = base['cancel_phrases']
    cfg['voice_flow']['dummy_auto_complete'] = auto_complete or os.environ.get('E_VOICE_AUTO_COMPLETE','0') == '1'
    if silence or os.environ.get('E_VOICE_SILENCE','0') == '1':
        cfg['recording_mode'] = 'silence'
    if cfg['voice_flow']['capture_save_wav']:
        cfg['voice_flow']['capture_dir'] = str(folder/'captures')
    cfg['diagnostic_detail'] = True
    cfg['diagnostic_file'] = str(folder/'diagnostic.jsonl')
    target = folder/'voice.local.yaml'
    with target.open('x',encoding='utf-8') as stream:
        yaml.safe_dump(cfg,stream,allow_unicode=True)
    return target,load_config(target)


def selected_texts(cfg):
    ontology = load(cfg['ontology_file'])
    return prefill_texts(cfg,ontology['world']['items'].values(),reference_state=ontology['state'],
        places=ontology['world']['places'],item_names={k:v['name_ko'] for k,v in ontology['world']['items'].items()})


def preparation_identity(cfg, texts):
    # 노드가 다시 실제 worker/cache identity를 검사합니다. 이 receipt는 성공 선행 확인용입니다.
    value = {key:item for key,item in cfg.items() if key.startswith('tts_') and key != 'tts_melotts_startup_timeout_sec'}
    value['texts'] = texts
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def require_prepared(run_root, identity):
    receipts = list(Path(run_root).glob('voice_prepare_*/result.json'))
    if not receipts:
        raise ValueError('PREPARE_REQUIRED')
    latest = max(receipts,key=lambda path:path.parent.stat().st_mtime_ns)
    result = json.loads(latest.read_text())
    if result.get('success') is not True or result.get('identity') != identity:
        raise ValueError('PREPARE_FAILED_OR_CONFIG_CHANGED')
    return latest.parent


class PipeOutput:
    def __init__(self, fd):self.fd = fd
    def write(self, value):
        data = value.encode('utf-8')
        while data:
            written = os.write(self.fd,data);data = data[written:]
        return len(value)
    def flush(self):pass
    def fileno(self):return self.fd
    encoding = 'utf-8'
    errors = 'replace'
    def isatty(self):return False


@contextlib.contextmanager
def console_capture(output):
    """Python/ROS/native fd1·2를 한 번만 로컬 저장하며 stdin은 변경하지 않습니다."""
    sys.stdout.flush();sys.stderr.flush()
    saved = (os.dup(1),os.dup(2))
    reader,writer = os.pipe()
    errors = []
    def pump():
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        pending = ''
        def line(value):
            clean = redact(value)
            data = clean.encode('utf-8')
            while data:
                written = os.write(saved[0],data);data = data[written:]
            output.write(clean);output.flush()
        try:
            while True:
                chunk = os.read(reader,4096)
                if not chunk:break
                pending += decoder.decode(chunk)
                while '\n' in pending:
                    value,pending = pending.split('\n',1);line(value+'\n')
            pending += decoder.decode(b'',final=True)
            if pending:line(pending)
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            os.close(reader)
    worker = threading.Thread(target=pump,daemon=True);worker.start()
    os.dup2(writer,1);os.dup2(writer,2)
    try:
        with contextlib.redirect_stdout(PipeOutput(writer)), contextlib.redirect_stderr(PipeOutput(writer)):
            yield
    finally:
        os.dup2(saved[0],1);os.dup2(saved[1],2);os.close(writer)
        worker.join()
        os.close(saved[0]);os.close(saved[1])
        if errors:raise RuntimeError('CONSOLE_CAPTURE_FAILED')


def prepare(cfg):
    from ready2go_voice.adapters.melotts import MeloTTS
    if cfg['tts_engine'] != 'melotts':
        raise ValueError('MELOTTS_REQUIRED')
    cfg = dict(cfg)
    cfg['tts_melotts_startup_timeout_sec'] = 120.0  # 기존 명시 prepare 전용 상한; 일반 node60 불변
    def progress(data):
        print(json.dumps({key:data[key] for key in ('event','done','total','cache_hit','elapsed_sec') if key in data},ensure_ascii=False),flush=True)
    cfg['_tts_progress'] = progress
    tts = MeloTTS(cfg)
    try:
        tts.prepare()  # 합성/캐시 준비만. speak/마이크/API/live는 호출하지 않습니다.
    finally:
        tts.close()


def live(config_file, *, auto_complete):
    from p2_voice_dummy import serve_live
    serve_live(config_file,auto_complete=auto_complete)


def run(mode, original, run_root, *, silence=False, auto_complete=False, prepare_fn=prepare, live_fn=live):
    Path(run_root).mkdir(parents=True,exist_ok=True)
    label = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')
    folder = Path(run_root)/f'voice_{mode}_{label}_{uuid.uuid4().hex[:8]}'
    folder.mkdir()
    receipt = folder/'result.json'
    result = {'mode':mode,'success':False}
    receipt.write_text(json.dumps(result))  # 최신 실패도 과거 준비 성공을 대신 사용하지 않습니다.
    code = 1
    with (folder/'console.log').open('x',encoding='utf-8') as output:
        with console_capture(output):
            print('시험 로그:',folder,flush=True)
            try:
                path,cfg = trial_config(original,folder,silence=silence,auto_complete=auto_complete)
                cfg['_tts_prefill_texts'] = texts = selected_texts(cfg)
                result['identity'] = preparation_identity(cfg,texts)
                print('시험 설정:',path,'문장+warmup:',len(texts)+1,'상한:',cfg['tts_prefill_max_texts'],
                      'cue_gain:',cfg['voice_flow']['cue_gain'],'일반startup:',cfg['tts_melotts_startup_timeout_sec'],flush=True)
                if mode == 'prepare':
                    prepare_fn(cfg)
                    print('캐시 준비 완료. live는 별도 명령으로 실행해 주세요.',flush=True)
                elif mode == 'live':
                    print('준비 성공 기록:',require_prepared(run_root,result['identity']),flush=True)
                    live_fn(path,auto_complete=cfg['voice_flow']['dummy_auto_complete'])
                else:
                    raise ValueError('TRIAL_MODE_INVALID')
                result['success'] = True
                code = 0
            except KeyboardInterrupt:
                print('사용자 중단: 이번 실행을 종료합니다.',flush=True)
                code = 130
            except Exception as exc:
                known = {'TRIAL_CONFIG_UNCONFIRMED','TRIAL_SWITCH_INVALID','PREPARE_REQUIRED',
                    'PREPARE_FAILED_OR_CONFIG_CHANGED','MELOTTS_REQUIRED','TRIAL_MODE_INVALID'}
                reason = str(exc) if str(exc) in known else type(exc).__name__
                print('시험 시작/실행 실패:',reason,'자동 재시도·live 시작 없음',flush=True)
            finally:
                result['exit_code'] = code
                receipt.write_text(json.dumps(result,ensure_ascii=False))
    return code,folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','live'))
    parser.add_argument('--config-file',type=Path,default=ROOT/'logs/voice_eval/voice.local.yaml')
    parser.add_argument('--run-root',type=Path,default=ROOT/'logs/voice_eval')
    parser.add_argument('--silence',action='store_true',help='시험 복사본의 일반 녹음만 무음 종료로 비교')
    parser.add_argument('--auto-complete',action='store_true',help='현재 더미 수락TTS/첫동작 뒤에만 모의 완료')
    args = parser.parse_args()
    os.chdir(ROOT)
    code,_ = run(args.mode,args.config_file,args.run_root,silence=args.silence,auto_complete=args.auto_complete)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
