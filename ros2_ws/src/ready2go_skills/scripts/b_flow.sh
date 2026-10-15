#!/usr/bin/env bash
# B 시연 흐름 시험 — PC2 호스트에서 스킬 서버를 소스 그대로 돌리고 동작을 하나씩 보낸다 (10/06 #22 점검 전 확인용).
# 전제: 호스트 DSR 드라이버(roboton) 실행 중, 컨테이너 ros2-core 멈춤, r2gjog 꺼짐(같이 명령하지 않게).
#   bash b_flow.sh demo [go|N]  10/06 시연 흐름 (사용자 지정 순서·좌표, 단계마다 Enter / go = 끝까지 / N = N단계부터)
#   bash b_flow.sh build      메시지 패키지(ready2go_interfaces)만 호스트에 빌드 — 처음 한 번
#   bash b_flow.sh server     스킬 서버 (터미널 1, 계속 켜 둠). 관절 속도 VEL=60 JACC=40 기본, 느리게 보려면 VEL=20 JACC=20
#   bash b_flow.sh <동작> [서랍] [물체]  b_sk.py 로 동작 하나 (B <동작>) — 서랍 = top | bottom, 목록은 인자 없이 b_sk.py
#     opened = 서랍을 손으로 끝까지 연 것으로 서버에 알림 (로봇 동작 없음)
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
            --ros-args -p joint_vel_deg_s:="$(python3 -c "print(float('${VEL:-80}'))")" \
            -p joint_acc_deg_s2:="$(python3 -c "print(float('${JACC:-60}'))")" -p config_dir:="$R/config" ;;   # 10/06 저녁 2배 (30·20 → 60·40) → 10/11 80·60 [사용자 "이동 답답"]
    demo)
        ros_env
        shift
        exec python3 "$(dirname "$0")/b_demo.py" "$@" ;;
    "")
        sed -n '2,8p' "$0" ;;
    *)
        ros_env
        exec python3 "$(dirname "$0")/b_sk.py" "$@" ;;
esac
