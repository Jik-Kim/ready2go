"""B 스킬 서버 (BACKEND=real): Runner 의 원자 동작을 `/skills/<동작>` Skill 액션으로 받는다 (#10·#13·#15).

이름·형식은 docs/interfaces.md·runner.md 7.1 과 C 의 mock_backend.py 와 같다 → Runner 코드는 그대로, 백엔드만 바뀜.
공통 (core/skill_flow.py):
  - 취소 요청 → MoveStop → 멈출 때까지 기다림 → canceled (그리퍼는 그대로, 잡은 물건을 떨어뜨리지 않음)
  - 안전·비상정지 상태 → error_code ESTOP
  - 움직이기 전 펜던트 TCP·툴 확인 → 다르면 TOOL_NOT_SET (motion_guard, calibration_meta.yaml 기준)
구현 상태:
  - move_to_named_pose: 완료 (poses.yaml 관절각으로 movej, 도착 확인)
  - drawer_control·nudge_object·pick_object·place_object: TODO(B) 10/06 실측 후 — 지금은 움직이지 않고 NOT_IMPLEMENTED

실행 (PC2, DSR 드라이버 실행 중):
    ros2 run ready2go_skills skill_server
    ros2 run ready2go_skills skill_server --ros-args -p joint_vel_deg_s:=10.0   # 처음은 저속 (safety.md 11)
"""
import json
import os
from pathlib import Path

import rclpy
import yaml
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from ready2go_interfaces.action import Skill
from ready2go_skills.adapters.dsr import Dsr
from ready2go_skills.core import motion_guard, skill_flow as sf

ACTIONS = ("move_to_named_pose", "drawer_control", "nudge_object", "pick_object", "place_object")


def find_config_dir():
    env = os.environ.get("READY2GO_CONFIG_DIR")
    if env:
        return Path(env)
    for d in Path(__file__).resolve().parents:
        if (d / "config" / "poses.yaml").exists():
            return d / "config"
    return Path.home() / "ready2go" / "config"


class SkillServer(Node):
    def __init__(self):
        super().__init__("skill_server")
        self.joint_vel = float(self.declare_parameter("joint_vel_deg_s", 20.0).value)   # [팀 확정 필요] 저속 → 정상
        self.joint_acc = float(self.declare_parameter("joint_acc_deg_s2", 20.0).value)
        self.move_timeout = float(self.declare_parameter("move_timeout_s", 30.0).value)  # 서버 쪽 안전 상한
        self.reach_tol = float(self.declare_parameter("reach_tol_deg", 0.5).value)
        cfg = Path(self.declare_parameter("config_dir", str(find_config_dir())).value)
        self.cfg_dir = cfg
        meta = yaml.safe_load((cfg / "calibration" / "calibration_meta.yaml").read_text(encoding="utf-8"))
        self.expected_tcp, self.expected_tool = motion_guard.expected_tool(meta)
        self.robot = Dsr(self, self.declare_parameter("dsr_prefix", "/dsr01/dsr_controller2").value)
        group = ReentrantCallbackGroup()
        self._servers = [ActionServer(self, Skill, f"/skills/{a}", self._execute_for(a), callback_group=group,
                                      cancel_callback=lambda _: CancelResponse.ACCEPT) for a in ACTIONS]
        self.get_logger().info(f"스킬 서버 준비: /skills/{{{','.join(ACTIONS)}}} (관절 {self.joint_vel}°/s, "
                               f"기대 TCP {self.expected_tcp}·툴 {self.expected_tool}, config {cfg})")

    def poses(self):
        """매 호출마다 다시 읽음 — 교시값을 고친 뒤 서버를 재시작하지 않아도 되게."""
        return yaml.safe_load((self.cfg_dir / "poses.yaml").read_text(encoding="utf-8"))

    def _execute_for(self, action):
        handler = getattr(self, f"_do_{action}", None)

        def execute(goal):
            try:
                params = json.loads(goal.request.params_json or "{}")
            except json.JSONDecodeError as e:
                return self._finish(goal, action, sf.Outcome(False, sf.BAD_PARAMS, reason=str(e)))
            self.get_logger().info(f"[{action}] {params}")
            if handler is None:
                return self._finish(goal, action, sf.Outcome(False, sf.NOT_IMPLEMENTED,
                                                             reason="10/06 실측 후 구현 (로봇 동작 없음)"))
            err = motion_guard.check_tool(*self.robot.tool_names(), self.expected_tcp, self.expected_tool)
            if err:
                return self._finish(goal, action, sf.Outcome(False, err.error_code, reason=err.reason))
            try:
                outcome, output = handler(goal, params)
            except Exception as e:          # 예외로 끝나도 로봇은 멈추고 실패로 돌려줌 (움직인 뒤일 수 있어 SKILL_EXCEPTION)
                self.robot.stop()
                self.get_logger().error(f"[{action}] 예외: {e!r}")
                outcome, output = sf.Outcome(False, sf.SKILL_EXCEPTION, reason=repr(e)), None
            return self._finish(goal, action, outcome, output)
        return execute

    def _finish(self, goal, action, outcome, output=None):
        if outcome.canceled:
            goal.canceled()
        elif outcome.success:
            goal.succeed()
        else:
            goal.abort()
        log = self.get_logger().info if outcome.success else self.get_logger().warning
        log(f"[{action}] {'성공' if outcome.success else outcome.error_code}: {outcome.reason}")
        return Skill.Result(success=outcome.success, error_code=outcome.error_code,
                            output_json="" if output is None else json.dumps(output, ensure_ascii=False))

    # --- 동작 ---
    def _do_move_to_named_pose(self, goal, params):
        joints, err = sf.pose_joints(self.poses(), params.get("pose_name", ""), params.get("drawer_id"))
        if err:
            return err, None
        goal.publish_feedback(Skill.Feedback(stage="auto_mode"))
        if not self.robot.auto():
            return self._rejected("자동 모드로 바꾸지 못함"), None
        goal.publish_feedback(Skill.Feedback(stage="moving"))
        if not self.robot.movej_async(joints, self.joint_vel, self.joint_acc):
            return self._rejected("movej 거부"), None
        done = sf.wait_motion(get_state=self.robot.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout)
        if not done.success:
            return done, None
        return sf.check_reached(joints, self.robot.posj(), self.reach_tol), None

    def _rejected(self, why):
        state = self.robot.state()
        if sf.stopped_by_estop(state):
            return sf.Outcome(False, sf.ESTOP, reason=f"{why} — 로봇 상태 {state}")
        return sf.Outcome(False, sf.MOVE_REJECTED, reason=f"{why} — 로봇 상태 {state}")


def main():
    rclpy.init()
    node = SkillServer()
    if not node.robot.ready():
        node.get_logger().error("DSR 서비스가 없음 — 드라이버가 실행 중인지 확인")
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:                                 # 실행 중인 goal 은 executor 가 멈추며 끊김 — 로봇 정지는 펜던트·Runner 취소로
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
