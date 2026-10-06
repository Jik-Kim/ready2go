"""시간 초과 결과를 버리는 단일 호출 슬롯. 늦은 결과는 발행하지 않습니다."""
import threading
import queue


class DeadlineCall:
    def __init__(self):
        self._lock = threading.Lock()

    def call(self, fn, timeout):
        if timeout <= 0:
            raise TimeoutError('예산 소진')
        if not self._lock.acquire(blocking=False):
            raise TimeoutError('이전 호출 정리 중')
        results = queue.Queue(maxsize=1)

        def run():
            try:
                results.put((True, fn()))
            except Exception as exc:
                results.put((False, exc))
            finally:
                self._lock.release()

        try:
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
        except Exception:
            self._lock.release()
            raise
        try:
            ok, value = results.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('호출 시간 초과') from None
        if not ok:
            raise value
        return value
