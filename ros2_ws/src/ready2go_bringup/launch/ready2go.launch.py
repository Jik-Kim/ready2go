"""ready2go 통합 launch.

BACKEND(real|sim|mock)는 compose의 환경변수로 전달됨 (docs/docker.md).
- real: DSR 드라이버(ready2go_skills/dsr_real.launch.py, 제어기 = ROBOT_HOST) + RG2 /gripper/state (RG2 = RG2_HOST)
"""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    is_real = IfCondition(PythonExpression(
        ["'", EnvironmentVariable("BACKEND", default_value="mock"), "' == 'real'"]))

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

    # TODO(C 이영훈): runner, vision, voice 노드 추가
    return LaunchDescription([dsr_real, gripper_state])
