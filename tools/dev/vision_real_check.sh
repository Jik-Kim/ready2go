#!/usr/bin/env bash
# 실물 카메라·TF로 inspect_region 첫 연결 시험 (담당 A, PC2에서 실행, 저장소 루트에서).
# 로봇 드라이버·bringup(고정 TF)·realsense 가 같은 PC 에서 떠 있다는 전제라 DDS 는 local. 터미널마다 이 스크립트로 실행한다.
#
#   bash tools/dev/vision_real_check.sh check                 # 카메라 토픽 주기·TF 확인 (약 20초)
#   bash tools/dev/vision_real_check.sh node                  # 비전 노드 (Ctrl+C 로 종료). 요청마다 logs/vision_dump/ 에 프레임 저장
#   bash tools/dev/vision_real_check.sh call [eraser]         # 서비스 호출 1회 (node 가 떠 있어야 함, 그 컨테이너 안에서 실행)
#   bash tools/dev/vision_real_check.sh measure X1 Y1 Z1 X2 Y2 Z2   # 펜던트 base 좌표(mm) 손끝 두 점 → 서랍 좌표 정답 (stub_measure.py)
#   bash tools/dev/vision_real_check.sh replay [파일] [X Y YAW]   # 저장한 프레임 다시 계산 (파일 생략 = 전부, 정답 주면 위치 오차)
#
# 같은 저장소의 config/places.yaml 을 비전 노드와 measure 가 함께 쓰므로 두 결과의 서랍 원점이 같다.
# stub 노드(inspect_region_stub)와 동시에 켜지 않는다 — 서비스 이름이 겹친다.
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO=$PWD
IMG=ready2go-vision:latest
NODE=vision_check
DUMP=$REPO/logs/vision_dump
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
ROSENV=(-e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/y -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-70}" -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
        -e CYCLONEDDS_URI="file:///repo/config/${DDS_PROFILE:-cyclonedds.local.xml}")
RUN=(docker run --rm --network host --user "$(id -u):$(id -g)" "${ROSENV[@]}" -v "$REPO:/repo" -v "$REPO/knowledge:/knowledge:ro"
     -v "$REPO/models:/models:ro" -w /repo)
BUILD='source /opt/ros/jazzy/setup.bash && cd /repo/ros2_ws && colcon build --build-base /tmp/build --install-base /tmp/install --packages-up-to ready2go_vision >/tmp/build.log 2>&1 || { tail -30 /tmp/build.log; exit 1; }; source /tmp/install/setup.bash'

case "${1:-}" in
  check)
    "${RUN[@]}" "$IMG" bash -lc 'source /opt/ros/jazzy/setup.bash
      echo "== 카메라 토픽 (뎁스 약 30 Hz 면 정상)"; ros2 topic list | grep wrist_cam || echo "wrist_cam 토픽 없음 — realsense 확인"
      timeout -s INT 8 ros2 topic hz /wrist_cam/aligned_depth_to_color/image_raw || true
      echo "== TF base_link → wrist_cam_color_optical_frame (변환이 출력되면 정상)"
      timeout -s INT 8 ros2 run tf2_ros tf2_echo base_link wrist_cam_color_optical_frame 2>&1 | head -12 || true' ;;
  node)
    mkdir -p "$DUMP"
    exec "${RUN[@]}" -it --name "$NODE" --gpus all "$IMG" bash -lc "$BUILD && exec ros2 run ready2go_vision inspect_region --ros-args -p config_dir:=/repo/config -p dump_dir:=/repo/logs/vision_dump -p code_sha:=$SHA" ;;
  call)
    docker ps -q -f name="^$NODE$" | grep -q . || { echo "비전 노드($NODE)가 안 떠 있음 — 먼저 node"; exit 1; }
    docker exec "$NODE" bash -lc "source /opt/ros/jazzy/setup.bash && source /tmp/install/setup.bash && timeout -s KILL 30 ros2 service call /vision/inspect_region ready2go_interfaces/srv/InspectRegion \"{region: drawer_top, search_target: ${2:-eraser}}\"" ;;
  measure)
    [ $# -eq 7 ] || { echo "사용: measure X1 Y1 Z1 X2 Y2 Z2 (펜던트 base mm, 지우개 긴 변 양 끝)"; exit 2; }
    "${RUN[@]}" "$IMG" python3 ros2_ws/src/ready2go_skills/ready2go_skills/core/stub_measure.py --class eraser --config-dir /repo/config \
      --point "$2" "$3" "$4" --point "$5" "$6" "$7" ;;
  replay)
    shift; target=/repo/logs/vision_dump
    if [ $# -eq 1 ] || [ $# -eq 4 ]; then target=/repo/logs/vision_dump/$(basename "$1"); shift; fi
    truth=(); [ $# -eq 3 ] && truth=(--truth "$@")
    "${RUN[@]}" "$IMG" python3 tools/dev/replay_inspect_dump.py "$target" "${truth[@]}" ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
