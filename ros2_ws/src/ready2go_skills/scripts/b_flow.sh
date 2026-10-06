#!/usr/bin/env bash
# B 시연 흐름 시험 — PC2 호스트에서 스킬 서버를 소스 그대로 돌리고 동작을 하나씩 보낸다 (10/06 #22 점검 전 확인용).
# 전제: 호스트 DSR 드라이버(roboton) 실행 중, 컨테이너 ros2-core 멈춤, r2gjog 꺼짐(같이 명령하지 않게).
#   bash b_flow.sh demo [go|N]  10/06 시연 흐름 (사용자 지정 순서·좌표, 단계마다 Enter / go = 끝까지 / N = N단계부터)
#   bash b_flow.sh build      메시지 패키지(ready2go_interfaces)만 호스트에 빌드 — 처음 한 번
#   bash b_flow.sh server     스킬 서버 (터미널 1, 계속 켜 둠)
#   bash b_flow.sh all        터미널 2: 홈에서 열기 → 끌기 → 집기 → 놓기 → 닫기 → 홈 (실패하면 거기서 멈춤)
#   bash b_flow.sh <동작>     하나만: open | opened | nudge | pick | place | close | home
#     opened = 서랍을 손으로 끝까지 연 것으로 서버에 알림 (로봇 동작 없음)
#   bash b_flow.sh route1     들고 나오기 시험: 경유점 1(서랍 안)으로 관절 이동 (스킬 서버 없이)
#   bash b_flow.sh route      경유점 1 → movesj 2·3·4 → 트레이 첫 칸 위 직선
#   bash b_flow.sh mvl X Y Z A B C   툴 확인 후 직선 이동
#   bash b_flow.sh movej J1 J2 J3 J4 J5 J6   툴 확인 후 관절 이동 (J5 133° 넘으면 거부)
#   bash b_flow.sh press      지금 자세로 z 최대 9 mm 내려가며 툴 힘 z 2 N 되면 정지 (5 mm/s, 직전 0점)
#   bash b_flow.sh view       drawer_top_view 로 관절 이동 하나만 (경유 없음)
R="$HOME/ready2go"
H="$HOME/r2g_host"      # 호스트 빌드 결과 — 저장소 ros2_ws/install 은 컨테이너가 만든 것(경로가 /opt/dsr_ws 등)이라 쓰지 않음
ros_env() {
    source /opt/ros/jazzy/setup.bash
    source "$HOME/cobot2_ws/install/setup.bash"
    if [ ! -f "$H/install/setup.bash" ]; then echo "먼저: bash $0 build"; exit 1; fi
    source "$H/install/setup.bash"
}
case "$1" in
    build)
        source /opt/ros/jazzy/setup.bash
        cd "$R/ros2_ws" && colcon --log-base "$H/log" build --packages-select ready2go_interfaces \
            --build-base "$H/build" --install-base "$H/install" ;;
    server)
        ros_env
        cd "$R/ros2_ws/src/ready2go_skills" && RG2_HOST="${RG2_HOST:-192.168.1.1}" exec python3 -m ready2go_skills.nodes.skill_server \
            --ros-args -p joint_vel_deg_s:="$(python3 -c "print(float('${VEL:-20}'))")" -p config_dir:="$R/config" ;;
    demo)
        ros_env
        shift
        exec python3 "$(dirname "$0")/b_demo.py" "$@" ;;
    view|route1|route|mvl|movej|press)
        ros_env
        exec python3 "$(dirname "$0")/b_route.py" "$@" ;;
    "")
        sed -n '2,17p' "$0" ;;
    *)
        ros_env
        exec python3 "$(dirname "$0")/b_sk.py" "$@" ;;
esac
