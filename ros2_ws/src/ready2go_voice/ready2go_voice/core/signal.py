"""로컬 시험의 PCM 증빙·선택 구간 정리. 새 VAD/모델/발화 종료 추정은 하지 않습니다."""
from dataclasses import replace
from pathlib import Path
import re
import uuid
import wave
import numpy as np


def prepare(recording, cfg, request_id, emit):
    flow = cfg['voice_flow']
    samples = np.frombuffer(recording.pcm, dtype='<i2').astype(np.float64)
    emit(event='capture_signal', sample_count=len(samples), duration_sec=len(samples)/cfg['sample_rate'],
         rms=float(np.sqrt(np.mean(samples*samples))) if len(samples) else 0,
         peak=float(np.max(np.abs(samples))) if len(samples) else 0,
         recording_started_monotonic=recording.recording_started_monotonic,
         recording_ended_monotonic=recording.recording_ended_monotonic)
    if flow['capture_save_wav']:
        try:
            folder = Path(flow['capture_dir']); folder.mkdir(parents=True, exist_ok=True)
            ident = request_id if re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', request_id or '') else uuid.uuid4().hex
            path = folder / (ident + '.wav')
            with path.open('xb') as output:
                with wave.open(output, 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(cfg['sample_rate']); wav.writeframes(recording.pcm)
            emit(event='capture_saved', path=str(path), sample_count=len(samples))
        except Exception as exc:
            emit(event='capture_save_failed', error_type=type(exc).__name__)
    if flow['capture_trim'] and len(samples):
        voiced = np.flatnonzero(np.abs(samples) >= cfg['speech_rms'])
        if len(voiced):
            padding = int(flow['trim_padding_sec']*cfg['sample_rate'])
            start, end = max(0,int(voiced[0])-padding), min(len(samples),int(voiced[-1])+1+padding)
            emit(event='capture_trimmed', start_sample=start, end_sample=end, original_samples=len(samples),
                 timing_basis='original_recording_unchanged')
            return replace(recording, pcm=recording.pcm[start*2:end*2])
    return recording
