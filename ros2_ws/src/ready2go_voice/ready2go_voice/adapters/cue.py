"""기존 PCM 출력·출력장치·lock을 공유하는 미리 준비된 로컬 알림음."""
import io
import math
import struct
import wave
from .tts import PCMTTS


class WakeCue(PCMTTS):
    def __init__(self, cfg, lock):
        super().__init__(cfg)
        self.lock = lock
        flow = cfg['voice_flow']; rate = flow['cue_rate_hz']
        pcm = bytearray()
        for frequency in flow['cue_tones_hz']:
            count = int(rate*flow['cue_tone_sec'])
            for n in range(count):
                envelope = math.sin(math.pi*n/max(1,count-1))**2
                pcm.extend(struct.pack('<h',int(32767*flow['cue_gain']*envelope*math.sin(2*math.pi*frequency*n/rate))))
            self.audible_samples = len(pcm)//2
            pcm.extend(b'\0\0'*int(rate*flow['cue_gap_sec']))
        output = io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(pcm)
        self.audio = output.getvalue()

    def _synthesize(self, text, deadline, cancel):
        return self.audio

    def play(self, cancel=None, on_start=None):
        timing = {}
        stamp = self.speak('', cancel=cancel, on_start=on_start,
            timeout=self.cfg['voice_flow']['cue_timeout_sec'], on_timing=timing.update)
        if (stamp.get('tts_mock') is not False or stamp.get('tts_start_basis') != 'portaudio_first_dac'
                or timing.get('playback_end_basis') != 'portaudio_finished_callback'):
            raise RuntimeError('CUE_PLAYBACK_UNCONFIRMED')
        timing['cue_audible_ended_monotonic'] = stamp['tts_started_monotonic'] + self.audible_samples/self.cfg['voice_flow']['cue_rate_hz']
        return stamp, timing
