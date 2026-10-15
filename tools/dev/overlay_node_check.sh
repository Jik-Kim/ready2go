#!/usr/bin/env bash
# 촬영 장면 오버레이(#348) 노드 시험 — 실물 없이 PC 한 대에서: 덤프 프레임을 가짜 카메라로 내보내고 실제 inspect_region 노드를 띄워
# N회 호출 응답 시간과 늦게 붙은 구독자가 받은 마지막 오버레이 JPEG 를 본다. 로봇·카메라 명령 없음.
# 팀 장비와 섞이지 않게 시험 전용 도메인 OVERLAY_CHECK_DOMAIN(기본 77) + DDS local — 셸의 ROS_DOMAIN_ID(PC2 운영 70)는 쓰지 않고,
# 70 을 주면 거부 (E #370 P1). DRY_RUN=1 이면 docker 명령만 출력. 저장소 루트에서:
#   bash tools/dev/overlay_node_check.sh <덤프.npz> [호출 수 8] [overlay_enable true|false] [호출 간격 s 0.5 — 0 이면 연속]
# 출력: 응답 시간 줄, late subscriber got 1, 결과 JPEG = 덤프 옆 폴더 overlay_check_out/overlay_<enable>.jpg
set -euo pipefail
cd "$(dirname "$0")/../.."
DUMP=$(realpath "$1"); N=${2:-8}; EN=${3:-true}; GAP=${4:-0.5}
DOM=${OVERLAY_CHECK_DOMAIN:-77}
[[ "$DOM" =~ ^[0-9]+$ ]] || { echo "OVERLAY_CHECK_DOMAIN 은 숫자만: '$DOM'"; exit 2; }
DOM=$((10#$DOM))                                          # 070 같은 입력도 70 으로 읽어 비교 (ROS 는 십진으로 읽음)
if [ "$DOM" -eq 70 ]; then echo "시험 도메인이 운영 도메인 70 과 같음 — OVERLAY_CHECK_DOMAIN 을 다른 값으로"; exit 2; fi
OUT=$(dirname "$DUMP")/overlay_check_out; mkdir -p "$OUT"; cp "$DUMP" "$OUT/d.npz"
RUN=(docker run --rm --network host --gpus all --user "$(id -u):$(id -g)" -e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/y
  -e ROS_DOMAIN_ID="$DOM" -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///repo/config/cyclonedds.local.xml
  -v "$PWD:/repo" -v "$PWD/knowledge:/knowledge:ro" -v "$PWD/models:/models:ro" -v "$OUT:/t" -w /repo ready2go-vision:latest)
if [ "${DRY_RUN:-0}" = 1 ]; then printf '%q ' "${RUN[@]}"; echo; exit 0; fi
"${RUN[@]}" bash -lc "
source /opt/ros/jazzy/setup.bash && cd /repo/ros2_ws && colcon build --build-base /tmp/build --install-base /tmp/install --packages-up-to ready2go_vision >/tmp/build.log 2>&1 || { tail -20 /tmp/build.log; exit 1; }
source /tmp/install/setup.bash
python3 /repo/tools/dev/overlay_check/fake_cam.py /t/d.npz > /t/fake.log 2>&1 &
ros2 run ready2go_vision inspect_region --ros-args -p config_dir:=/repo/config -p overlay_enable:=$EN > /t/node_$EN.log 2>&1 &
python3 /repo/tools/dev/overlay_check/call_and_grab.py /t/overlay_$EN.jpg $N $GAP
kill %1 %2; sleep 1"
