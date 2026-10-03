"""ready2go 통합 launch.

BACKEND(real|sim|mock)는 compose의 환경변수로 전달됨 (docs/docker.md).
고정 TF: config/ 의 담당 파일을 읽어 static_transform_publisher 로 발행 (결정 #23, ready2go_bringup.static_tf).
config_dir 기본값은 컨테이너 마운트 경로 /config. 호스트에서는 config_dir:=<저장소>/config 로 지정.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

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
    # TODO(C 이영훈): runner, skills, vision, voice 노드 추가
    return LaunchDescription([
        DeclareLaunchArgument("config_dir", default_value="/config",
                              description="장비·실측값 폴더 (컨테이너 /config, 호스트는 저장소 config/)"),
        OpaqueFunction(function=_static_tf_nodes),
    ])
