"""StartGate (#187): 실행 시작과 음성 "멈춰"가 엇갈리지 않게."""
import threading

from ready2go_runner.core.start_gate import BUSY, CANCELED_BEFORE_START, STARTED, StartGate


def test_stop_while_request_is_being_handled_blocks_its_start():
    """'지우개 찾아줘' 처리 중(플래너 계산 등) '멈춰' → 그 요청은 시작하지 않음."""
    gate = StartGate()
    token = gate.token()                       # 요청을 받은 순간
    assert gate.cancel() is False              # 아직 실행 전 → 멈출 실행은 없음 (NOT_RUNNING)
    assert gate.try_start(token) == CANCELED_BEFORE_START and gate.busy is False


def test_new_request_after_stop_starts_normally():
    gate = StartGate()
    gate.cancel()
    assert gate.try_start(gate.token()) == STARTED and gate.busy


def test_stop_during_run_reports_running_and_second_start_is_busy():
    gate = StartGate()
    assert gate.try_start(gate.token()) == STARTED
    assert gate.cancel() is True               # 실행 중 → 호출 쪽이 halt
    assert gate.try_start(gate.token()) == BUSY
    gate.finish()
    assert gate.try_start(gate.token()) == STARTED


def test_concurrent_stop_and_start_never_both_miss():
    """동시에 들어와도 '멈춰가 실행을 못 봄(False) + 그 요청이 시작됨' 조합은 생기지 않음."""
    for _ in range(300):
        gate, seen = StartGate(), {}
        token = gate.token()
        barrier = threading.Barrier(2)

        def stop():
            barrier.wait()
            seen["was_running"] = gate.cancel()

        def start():
            barrier.wait()
            seen["start"] = gate.try_start(token)
        threads = [threading.Thread(target=stop), threading.Thread(target=start)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not (seen["was_running"] is False and seen["start"] == STARTED)
