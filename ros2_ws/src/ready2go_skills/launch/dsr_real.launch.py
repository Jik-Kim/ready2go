"""DSR 드라이버 실물(real) 기동 — RViz·에뮬레이터 없이 컨테이너에서 실행 (#4).

강의 포크(ROKEY-SPARK/doosan-robot2_jazzy)의 dsr_bringup2_rviz.launch.py에서
real 모드에 필요한 노드만 남김: ros2_control_node, robot_state_publisher,
joint_state_broadcaster → dsr_controller2 spawner. (포크의 해당 launch는 RViz를 항상 띄워 화면 없는 컨테이너에서 쓸 수 없음)

    ros2 launch ready2go_skills dsr_real.launch.py              # host = 환경변수 ROBOT_HOST
    ros2 launch ready2go_skills dsr_real.launch.py host:=<제어기 IP>
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.substitutions import (Command, EnvironmentVariable, FindExecutable, LaunchConfiguration,
                                  PathJoinSubstitution)
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from dsr_bringup2.utils import read_update_rate

# 실물 제어기 접속(OPEN CONNECTION → RT stream)이 끝나기 전에 spawner 기본 대기(10 s)가 끝나
# joint_state_broadcaster가 실패한 적 있음 [실측 10/03, 컨테이너] → 대기를 늘림
SPAWNER_WAIT = ["--controller-manager-timeout", "60", "--service-call-timeout", "60"]


def generate_launch_description():
    name = LaunchConfiguration("name")
    args = [
        DeclareLaunchArgument("name", default_value="dsr01", description="네임스페이스"),
        DeclareLaunchArgument("host", default_value=EnvironmentVariable("ROBOT_HOST", default_value=""),
                              description="실물 제어기 IP [팀 확정 필요] — .env의 ROBOT_HOST"),
        DeclareLaunchArgument("port", default_value="12345"),
        DeclareLaunchArgument("rt_host", default_value="192.168.137.50"),
        DeclareLaunchArgument("model", default_value="m0609"),
    ]

    robot_description = Command([
        PathJoinSubstitution([FindExecutable(name="xacro")]), " ",
        PathJoinSubstitution([FindPackageShare("dsr_description2"), "xacro", LaunchConfiguration("model")]),
        ".urdf.xacro",
        " name:=", name,
        " host:=", LaunchConfiguration("host"),
        " rt_host:=", LaunchConfiguration("rt_host"),
        " port:=", LaunchConfiguration("port"),
        " mode:=real",
        " model:=", LaunchConfiguration("model"),
        " update_rate:=", str(int(read_update_rate())),
    ])
    controllers = PathJoinSubstitution([FindPackageShare("dsr_controller2"), "config", "dsr_controller2.yaml"])

    control_node = Node(
        package="controller_manager", executable="ros2_control_node", namespace=name,
        parameters=[{"robot_description": robot_description}, controllers], output="both",
    )
    robot_state_pub = Node(
        package="robot_state_publisher", executable="robot_state_publisher", namespace=name,
        parameters=[{"robot_description": robot_description}], output="both",
    )
    jsb_spawner = Node(
        package="controller_manager", executable="spawner", namespace=name,
        arguments=["joint_state_broadcaster", "-c", "controller_manager", *SPAWNER_WAIT],
    )
    ctrl_spawner = Node(
        package="controller_manager", executable="spawner", namespace=name,
        arguments=["dsr_controller2", "-c", "controller_manager", *SPAWNER_WAIT],
    )
    after_jsb = RegisterEventHandler(OnProcessExit(target_action=jsb_spawner, on_exit=[ctrl_spawner]))

    return LaunchDescription(args + [control_node, robot_state_pub, jsb_spawner, after_jsb])
