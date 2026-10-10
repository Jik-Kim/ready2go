"""E 로컬 비동기 상세 증빙. 파일 실패/정체는 음성·취소 경로와 분리합니다."""
import json
import os
from pathlib import Path
import queue
import re
import threading
import time


def redact(value, secrets=None):
    secrets = secrets if secrets is not None else [v for k, v in os.environ.items()
        if v and re.search(r'KEY|TOKEN|SECRET|PASSWORD', k, re.I)]
    if isinstance(value, dict):
        return {k: '[REDACTED]' if re.search(r'api.?key|authorization|access.?token|secret|password', k, re.I)
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)(?:bearer\s+|sk-(?:proj-)?)[A-Za-z0-9_\-]{8,}', '[REDACTED]', value)
        value = re.sub(r"""(?i)((?:api[_ -]?key|token|password|secret|authorization)["']?\s*[=:]\s*["']?(?:bearer\s+)?)[^\s,;"']+""", r"\1[REDACTED]", value)
        value = re.sub(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})', '[REDACTED]', value)
    return value


class DiagnosticFile:
    def __init__(self, cfg, warning):
        self.path = Path(cfg['diagnostic_file']).expanduser()
        self.max_bytes = cfg['diagnostic_max_bytes']
        self.backups = cfg['diagnostic_backups']
        self.warning = warning
        self.queue = queue.Queue(maxsize=cfg['diagnostic_queue_size'])
        self.stop = threading.Event()
        self.failed = False
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()

    def _warn(self, message):
        try:
            self.warning(message)
        except Exception:
            pass  # 로그 경고 실패도 음성·취소로 전파하지 않음.

    def emit(self, doc):
        if self.stop.is_set():
            return
        try:
            # 직렬화/필터 실패도 호출 경로로 전파하지 않습니다.
            raw = json.dumps(redact(dict(doc, logged_unix=time.time(), logged_monotonic=time.monotonic())), ensure_ascii=False)
            self.queue.put_nowait(raw)
        except queue.Full:
            self._warn('상세 진단 큐가 가득 차 증빙을 저장하지 못했습니다.')
        except Exception as exc:
            self._warn('상세 진단 직렬화/필터 실패: ' + type(exc).__name__)

    def _append(self, raw):
        data = (raw + '\n').encode('utf-8')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size + len(data) > self.max_bytes:
            oldest = self.path.with_name(self.path.name + f'.{self.backups}')
            if oldest.exists():
                oldest.unlink()
            for n in range(self.backups - 1, 0, -1):
                source = self.path.with_name(self.path.name + f'.{n}')
                if source.exists():
                    source.replace(self.path.with_name(self.path.name + f'.{n + 1}'))
            self.path.replace(self.path.with_name(self.path.name + '.1'))
        # One oversized original record is kept intact, then rotated by the next record.
        with self.path.open('ab') as f:
            f.write(data)

    def _work(self):
        while not self.stop.is_set() or not self.queue.empty():
            try:
                raw = self.queue.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                self._append(raw)
                self.failed = False
            except Exception as exc:
                if not self.failed:
                    self._warn('상세 진단 파일 저장 실패: ' + type(exc).__name__)
                self.failed = True
            finally:
                self.queue.task_done()

    def close(self):
        self.stop.set()
        self.worker.join(timeout=1)
        if self.worker.is_alive():
            self._warn('상세 진단 종료 대기 초과: 일부 증빙 저장 미확인')
