"""ready2go 통합 launch (TODO: 노드가 생기면 추가).

BACKEND(real|sim|mock)는 compose의 환경변수로 전달됨 (docs/docker.md).
"""
from launch import LaunchDescription


def generate_launch_description():
    # TODO(C 이영훈): runner, skills, vision, voice 노드 추가
    return LaunchDescription([])
