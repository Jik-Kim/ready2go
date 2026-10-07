"""ready2go 통합 launch.

BACKEND(real|sim|mock)는 compose의 환경변수로 전달됨 (docs/docker.md).
- 모든 BACKEND: 고정 TF — config/ 의 담당 파일을 읽어 static_transform_publisher 로 발행
  (결정 #23, ready2go_bringup.static_tf). config_dir 기본값은 컨테이너 마운트 경로 /config,
  호스트에서는 config_dir:=<저장소>/config 로 지정.
- real: DSR 드라이버(ready2go_skills/dsr_real.launch.py, 제어기 = ROBOT_HOST) + RG2 /gripper/state (RG2 = RG2_HOST)
- 모든 BACKEND: Runner 노드(ready2go_runner runner) — /runner/status·/robot_state 발행, /runner/estop.
  RUNNER_TASK_FILE 을 주면 시작할 때 그 태스크를 한 번 실행 (시험용). 음성 시연 조합은
  RUNNER_ONTOLOGY_FILE·RUNNER_INTENT_TASKS (docs/docker.md)
- mock: mock 백엔드(ready2go_runner mock_backend) — /skills/*·/voice/speak·/vision/inspect_region 을
  로봇·음성·비전 없이 같은 이름으로 응답 (#10). 실패 시험은 MOCK_FAIL·MOCK_NOT_VISIBLE 환경변수
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from ready2go_bringup.static_tf import load_static_tfs


def _static_tf_nodes(context):
    config_dir = LaunchConfiguration("config_dir").perform(context)
    tfs, skipped = load_static_tfs(config_dir)       # 형식 오류면 예외로 launch 중단
    actions = [LogInfo(msg=f"[static_tf] 건너뜀: {reason}") for reason in skipped]
    for tf in tfs:
        x, y, z = tf.translation_m
        qx, qy, qz, qw = tf.quaternion_xyzw
        actions.append(LogInfo(msg=f"[static_tf] {tf.parent} -> {tf.child} ({tf.source})"))
        actions.append(Node(
            package="tf2_ros", executable="static_transform_publisher",
            name=f"static_tf_{tf.child}",
            arguments=["--x", str(x), "--y", str(y), "--z", str(z),
                       "--qx", str(qx), "--qy", str(qy), "--qz", str(qz), "--qw", str(qw),
                       "--frame-id", tf.parent, "--child-frame-id", tf.child],
        ))
    return actions


def generate_launch_description():
    is_real = IfCondition(PythonExpression(
        ["'", EnvironmentVariable("BACKEND", default_value="mock"), "' == 'real'"]))
    is_mock = IfCondition(PythonExpression(
        ["'", EnvironmentVariable("BACKEND", default_value="mock"), "' == 'mock'"]))

    dsr_real = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("ready2go_skills"), "launch", "dsr_real.launch.py"])),
        condition=is_real,
    )
    gripper_state = Node(
        package="ready2go_skills", executable="gripper_state", name="gripper_state",
        parameters=[{"rg2_ip": EnvironmentVariable("RG2_HOST", default_value="")}],
        condition=is_real, output="screen",
    )

    mock_backend = Node(
        package="ready2go_runner", executable="mock_backend", name="mock_backend",
        parameters=[{"fail": EnvironmentVariable("MOCK_FAIL", default_value=""),
                     "not_visible": EnvironmentVariable("MOCK_NOT_VISIBLE", default_value="")}],
        condition=is_mock, output="screen",
    )

    runner = Node(  # RUNNER_TASK_FILE: 시험용으로 시작할 때 한 번 실행할 태스크 (정식 통로는 /voice/intent, #17)
        package="ready2go_runner", executable="runner", name="runner", output="screen",
        parameters=[{"task_file": EnvironmentVariable("RUNNER_TASK_FILE", default_value=""),
                     "ontology_file": EnvironmentVariable("RUNNER_ONTOLOGY_FILE",
                                                          default_value="/knowledge/robot_ontology.jsonld"),
                     "intent_tasks": EnvironmentVariable("RUNNER_INTENT_TASKS", default_value="")}],
    )

    # TODO(C 이영훈): vision, voice 노드 추가
    return LaunchDescription([
        DeclareLaunchArgument("config_dir", default_value="/config",
                              description="장비·실측값 폴더 (컨테이너 /config, 호스트는 저장소 config/)"),
        OpaqueFunction(function=_static_tf_nodes),
        dsr_real,
        gripper_state,
        mock_backend,
        runner,
    ])
