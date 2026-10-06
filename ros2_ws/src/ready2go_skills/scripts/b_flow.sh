#!/usr/bin/env bash
# B 시연 흐름 시험 — PC2 호스트에서 스킬 서버를 소스 그대로 돌리고 동작을 하나씩 보낸다 (10/06 #22 점검 전 확인용).
# 전제: 호스트 DSR 드라이버(roboton) 실행 중, 컨테이너 ros2-core 멈춤, r2gjog 꺼짐(같이 명령하지 않게).
#   bash b_flow.sh build      메시지 패키지(ready2go_interfaces)만 호스트에 빌드 — 처음 한 번
#   bash b_flow.sh server     스킬 서버 (터미널 1, 계속 켜 둠)
#   bash b_flow.sh all        터미널 2: 열기 → 끌기 → 집기 → 놓기 → 닫기 → 홈 (실패하면 거기서 멈춤)
#   bash b_flow.sh <동작>     하나만: open | opened | nudge | pick | place | close | home
#     opened = 서랍을 손으로 끝까지 연 것으로 서버에 알림 (로봇 동작 없음)
R="$HOME/ready2go"
ros_env() {
    source /opt/ros/jazzy/setup.bash
    source "$HOME/cobot2_ws/install/setup.bash"
    if [ -f "$R/ros2_ws/install/setup.bash" ]; then source "$R/ros2_ws/install/setup.bash"; fi
}
case "$1" in
    build)
        source /opt/ros/jazzy/setup.bash
        cd "$R/ros2_ws" && colcon build --packages-select ready2go_interfaces ;;
    server)
        ros_env
        cd "$R/ros2_ws/src/ready2go_skills" && RG2_HOST="${RG2_HOST:-192.168.1.1}" exec python3 -m ready2go_skills.nodes.skill_server \
            --ros-args -p joint_vel_deg_s:="${VEL:-10.0}" -p config_dir:="$R/config" ;;
    "")
        sed -n '2,10p' "$0" ;;
    *)
        ros_env
        exec python3 "$(dirname "$0")/b_sk.py" "$@" ;;
esac
