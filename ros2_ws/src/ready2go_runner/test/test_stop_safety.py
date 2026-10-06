"""PR #74 리뷰: /runner/estop·시간 초과가 진행 중 로봇 동작의 정지로 이어지고, 정지 확인 전에는 다음 동작을 보내지 않음.
실제 ROS 액션으로 시험 (rclpy·ready2go_interfaces 필요 → 호스트 pytest 는 건너뜀, ros2-core 컨테이너·colcon test 에서 실행).
ICD 고정 이름(/skills/*)을 쓰므로 별도 Domain ID 에서 돌린다."""
import itertools
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ready2go_interfaces")

from rclpy.action import ActionServer, CancelResponse  # noqa: E402
from rclpy.callback_groups import ReentrantCallbackGroup  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402

from ready2go_interfaces.action import Skill  # noqa: E402
from ready2go_runner.adapters.ros_clients import RosClients  # noqa: E402
from ready2go_runner.core.backend import RosBackend  # noqa: E402
from ready2go_runner.core.interpreter import Runner  # noqa: E402

# 시험마다 다른 Domain ID (파일마다 범위를 나눠, 앞 시험의 남은 서버와 섞이지 않게)
DOMAIN_IDS = itertools.count(150)
TASK = {"task_id": "stop", "sequence": [
    {"id": "s1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}}],
    "finally": [{"id": "f1", "action": "speak", "params": {"text": "멈췄습니다"}},
                {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]}


class Robot:
    """느린 drawer_control. mode: "stops"(취소 받으면 cancel_delay 뒤 멈춤) / "ignores"(취소를 무시하고 끝까지) /
    "unconfirmed"(취소 받으면 끝내지만 최종 결과가 STOP_UNCONFIRMED — B #73 서버의 정지 확인 실패)."""

    def __init__(self, node, mode, duration=3.0, cancel_delay=0.4):
        self.mode, self.duration, self.cancel_delay = mode, duration, cancel_delay
        self.events: list[tuple[str, float]] = []
        self.started = threading.Event()
        group = ReentrantCallbackGroup()
        accept = lambda _: CancelResponse.ACCEPT  # noqa: E731
        ActionServer(node, Skill, "/skills/drawer_control", self._drawer, callback_group=group, cancel_callback=accept)
        for name in ("/skills/move_to_named_pose", "/voice/speak"):
            ActionServer(node, Skill, name, self._quick(name), callback_group=group, cancel_callback=accept)

    def _mark(self, what):
        self.events.append((what, time.monotonic()))

    def _drawer(self, goal):
        self._mark("drawer_start")
        self.started.set()
        end = time.monotonic() + self.duration
        while time.monotonic() < end:
            if goal.is_cancel_requested and self.mode in ("stops", "unconfirmed"):
                time.sleep(self.cancel_delay)           # 실제 로봇처럼 멈추는 데 시간이 걸림
                self._mark("drawer_end")
                goal.canceled()
                code = "CANCELED" if self.mode == "stops" else "STOP_UNCONFIRMED"
                return Skill.Result(success=False, error_code=code)
            time.sleep(0.02)
        self._mark("drawer_end")
        goal.succeed()
        return Skill.Result(success=True)

    def _quick(self, name):
        def execute(goal):
            self._mark(name.rsplit("/", 1)[-1] + "_start")
            goal.succeed()
            return Skill.Result(success=True)
        return execute

    def time_of(self, what):
        return next(t for w, t in self.events if w == what)

    def names(self):
        return [w for w, _ in self.events]


def run_case(mode, halt_after=None, timeout_sec=None, cancel_confirm_sec=3.0):
    context = rclpy.Context()
    rclpy.init(context=context, domain_id=next(DOMAIN_IDS))
    server_node, client_node = rclpy.create_node("robot", context=context), rclpy.create_node("runner", context=context)
    robot = Robot(server_node, mode)
    executor = MultiThreadedExecutor(context=context)
    executor.add_node(server_node)
    executor.add_node(client_node)
    threading.Thread(target=executor.spin, daemon=True).start()
    try:
        runner = Runner(None)
        clients = RosClients(client_node, server_wait_sec=3.0, cancel_confirm_sec=cancel_confirm_sec,
                             stopping=lambda: runner.stop_requested)
        runner.execute = RosBackend(clients.call_action, clients.call_service, lambda: runner.state, {})
        runner.on_halt = clients.cancel_all
        task = {**TASK, "sequence": [{**TASK["sequence"][0], **({"timeout_sec": timeout_sec} if timeout_sec else {})}]}
        if halt_after is not None:                             # 동작이 시작된 뒤 /runner/estop 이 다른 스레드에서 들어옴
            threading.Thread(target=lambda: robot.started.wait(10) and time.sleep(halt_after) or runner.halt(),
                             daemon=True).start()
        result = runner.run(task)
        returned = time.monotonic()
        time.sleep(0.2)
        return runner, robot, result, returned
    finally:
        executor.shutdown()
        rclpy.shutdown(context=context)


def test_estop_cancels_running_action_before_finally():
    runner, robot, result, _ = run_case("stops", halt_after=0.5)
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1")
    assert result.steps[0]["error_code"] == "CANCELED"
    assert robot.time_of("drawer_end") - robot.time_of("drawer_start") < 2.0        # 3초 동작을 끝까지 하지 않음
    assert robot.time_of("drawer_end") <= robot.time_of("speak_start")             # 정지 확인 뒤에 finally
    assert "move_to_named_pose_start" not in robot.names()                          # 중단 뒤 로봇 동작 없음
    assert runner.halted


def test_timeout_waits_for_stop_before_finally_motion():
    runner, robot, result, returned = run_case("stops", timeout_sec=0.3)
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert robot.time_of("drawer_end") <= returned
    assert robot.time_of("drawer_end") <= robot.time_of("move_to_named_pose_start")  # 홈 이동이 겹치지 않음
    assert not runner.halted


def test_stop_not_confirmed_locks_runner():
    runner, robot, result, _ = run_case("ignores", timeout_sec=0.3, cancel_confirm_sec=0.5)
    assert (result.overall_status, result.error_code) == ("ABORTED", "STOP_UNCONFIRMED")
    assert runner.halted and runner.halt_code == "STOP_UNCONFIRMED"
    assert "move_to_named_pose_start" not in robot.names()                          # 사람 확인 전 새 동작 없음


def test_unconfirmed_stop_result_after_timeout_locks_runner():
    # PR #74 E 리뷰: 시간 초과 뒤 최종 결과가 STOP_UNCONFIRMED 면 TIMEOUT 이 아니라 잠금, finally 로봇 동작 없음
    runner, robot, result, _ = run_case("unconfirmed", timeout_sec=0.3)
    assert (result.overall_status, result.error_code) == ("ABORTED", "STOP_UNCONFIRMED")
    assert runner.halted
    assert "move_to_named_pose_start" not in robot.names()
