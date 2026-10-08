"""CPU/한국어 전용 로컬 합성 프로세스. stdout은 E 내부 JSON pipe입니다."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import wave


def cache_key(identity, text):
    return hashlib.sha256(json.dumps([identity, text], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    cfg = json.loads(sys.stdin.readline())
    assets = Path(cfg['assets'])
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import nltk
            nltk.data.find('corpora/cmudict.zip')
            import mecab  # g2pkk의 런타임 자동 설치를 방지하는 사전 확인
            sys.path.insert(0, str(assets / 'source'))
            import numpy as np
            import torch
            torch.set_num_threads(cfg['tts_melotts_threads'])
            manifest = json.loads((assets / 'model_manifest.json').read_text())
            os.environ['MELOTTS_BERT_PATH'] = manifest['kykim/bert-kor-base']['path']
            from melo.api import TTS
            kr = Path(manifest['myshell-ai/MeloTTS-Korean']['path'])
            model = TTS(language='KR', device='cpu', config_path=str(kr / 'config.json'),
                        ckpt_path=str(kr / 'checkpoint.pth'))
            speaker = model.hps.data.spk2id[cfg['tts_melotts_speaker']]
            cache = assets / 'wav_cache'
            cache.mkdir(exist_ok=True)
            def digest(path):
                h = hashlib.sha256()
                with path.open('rb') as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b''):
                        h.update(chunk)
                return h.hexdigest()
            identity = {'models': manifest, 'source_revision': '209145371cff8fc3bd60d7be902ea69cbdb7965a',
                        'speaker': cfg['tts_melotts_speaker'], 'speed': cfg['tts_melotts_speed'],
                        'threads': cfg['tts_melotts_threads'],
                        'dependencies': (assets / 'requirements.lock').read_text(),
                        'worker': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            identity['model_hashes'] = {repo: {p.name: digest(p) for p in Path(record['path']).iterdir() if p.is_file()}
                                        for repo, record in manifest.items()}
            # Private source compatibility patches also participate in cache validity.
            identity['source_hashes'] = {str(p.relative_to(assets / 'source')): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in (assets / 'source/melo').rglob('*.py')}
            def synth(text):
                key = cache_key(identity, text)
                path = cache / (key + '.wav')
                if path.exists():
                    return path.read_bytes(), True
                audio = model.tts_to_file(text, speaker, speed=cfg['tts_melotts_speed'], quiet=True)
                pcm = (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()
                data = io.BytesIO()
                with wave.open(data, 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(model.hps.data.sampling_rate)
                    wav.writeframes(pcm)
                raw = data.getvalue()
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(raw)
                temporary.replace(path)
                return raw, False
            synth(cfg['tts_melotts_warmup_text'])
            for text in dict.fromkeys(cfg.get('prefill_texts', [])):
                synth(text)
        print(json.dumps({'ready': True}), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                start = time.monotonic()
                with contextlib.redirect_stdout(sys.stderr):
                    raw, hit = synth(request['text'])
                print(json.dumps({'wav': base64.b64encode(raw).decode('ascii'), 'cache_hit': hit,
                                  'synth_sec': time.monotonic() - start}), flush=True)
            except Exception as exc:
                print(json.dumps({'error': type(exc).__name__}), flush=True)
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__}), flush=True)
        raise


if __name__ == '__main__':
    main()
