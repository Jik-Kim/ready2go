"""실행 시작과 음성 "멈춰"가 엇갈리지 않게 (ROS 비의존) — #187 C.

/voice/intent 콜백은 동시에 여러 개 돌 수 있다(ReentrantCallbackGroup). 예전에는 "지우개 찾아줘"를 처리하는
도중(특히 플래너 계산 중)에 "멈춰"가 오면, cancel 판단 때는 아직 실행 전이라 NOT_RUNNING 으로 끝나고 그 직후
태스크가 시작될 수 있었다. 그래서:
- 인텐트를 받는 순간 token() 으로 지금까지의 "멈춰" 횟수를 기억하고,
- 실행을 시작할 때 try_start(token) 이 그 뒤로 "멈춰"가 있었으면 시작하지 않는다(CANCELED_BEFORE_START).
- cancel() 은 횟수를 올리고, 그 순간 실행 중이었는지를 같은 잠금 안에서 돌려준다(실행 중이면 호출 쪽이 halt).
"멈춰" 뒤에 새로 받은 요청은 영향을 받지 않는다(그 요청의 token 이 이미 새 횟수).
"""
from __future__ import annotations

import threading

STARTED, BUSY, CANCELED_BEFORE_START = "started", "busy", "canceled_before_start"


class StartGate:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancels = 0
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def token(self) -> int:
        with self._lock:
            return self._cancels

    def cancel(self) -> bool:
        """'멈춰'를 받음. 그 순간 실행 중이었으면 True (호출 쪽이 Runner.halt)."""
        with self._lock:
            self._cancels += 1
            return self._busy

    def try_start(self, token: int | None = None) -> str:
        """token 이후 '멈춰'가 있었으면 시작 안 함. token 없음 = 지금 시점(시험용 RUNNER_TASK_FILE 등)."""
        with self._lock:
            if self._busy:
                return BUSY
            if token is not None and token != self._cancels:
                return CANCELED_BEFORE_START
            self._busy = True
            return STARTED

    def finish(self) -> None:
        with self._lock:
            self._busy = False
