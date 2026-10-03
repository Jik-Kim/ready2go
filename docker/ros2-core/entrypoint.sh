#!/usr/bin/env bash
# ROS → DSR 드라이버 오버레이(/opt/dsr_ws) → 팀 워크스페이스(/colcon/install, 있으면) 순으로 source.
# set -u는 두지 않음 — ROS setup.bash가 미정의 변수를 참조함.
set -eo pipefail
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source /opt/dsr_ws/install/setup.bash
if [ -f /colcon/install/setup.bash ]; then    # 팀 워크스페이스 (Dockerfile CMD 가 /colcon 에 빌드)
    source /colcon/install/setup.bash
fi
exec "$@"
