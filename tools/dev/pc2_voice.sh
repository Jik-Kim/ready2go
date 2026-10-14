#!/usr/bin/env bash
# PC2 한 대 통합점검 — 터미널 ② 음성 (E 노드, 호스트 실행). 런북 1절 7번·Voice README "Runner 연동용" 명령과 같음.
#   bash tools/dev/pc2_voice.sh            # 1단계 통합점검 (음성 노드 기본 설정)
#   bash tools/dev/pc2_voice.sh --control  # 제어 연결만: request_run_enabled:=true (복구·재개·종료 runtime)
#   bash tools/dev/pc2_voice.sh --p2       # P2 운영: request_run_enabled + p2_goal_enabled + upper_drawer_enabled (위 서랍 열기·닫기 목표만,
#                                          #   E 10/14) — Runner 는 pc2_up.sh --p2 (재개 보존). upper_drawer_enabled 는 E 코드 반영 전이면 노드가 무시
# r2genv(~/.bashrc 함수)가 하는 일(ROS Jazzy·Domain 70·CycloneDDS local)을 여기서 직접 한다 — 컨테이너 Runner 와 같은 DDS.
# 음성 노드가 /voice/speak(TTS)도 맡음 — 꺼져 있으면 태스크 첫 안내("○○을 찾아 올게요")에서 실패.
set -eo pipefail          # set -u 없음: ROS setup.bash 가 미정의 변수를 참조
cd "$(dirname "$0")/../.."
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=70 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI="file://$PWD/config/cyclonedds.local.xml"
[ -f .venvs/project/bin/activate ] || { echo "❌ .venvs/project 없음 (Voice README 설치)"; exit 1; }
source .venvs/project/bin/activate
[ -f ros2_ws/install_host/setup.bash ] || { echo "❌ ros2_ws/install_host 없음 (호스트 빌드 — 컨테이너 install 과 섞지 않음)"; exit 1; }
source ros2_ws/install_host/setup.bash
cfg=logs/voice_eval/voice.local.yaml
[ -f "$cfg" ] || { echo "❌ $cfg 없음"; exit 1; }
grep -qE '^\s*audio_enabled:\s*true' "$cfg" || echo "⚠️  $cfg audio_enabled 가 true 가 아님 — 마이크·웨이크가 안 켜짐 (글자 입력만)"
[ -f secrets/voice.env ] || echo "⚠️  secrets/voice.env 없음 — STT·LLM 호출 실패"
mkdir -p logs/voice_eval
log=$(mktemp logs/voice_eval/voice.run.XXXXXXXX.log)
CONTROL=false GOAL=false UPPER=false MODE_NAME="기본(1단계·P1)"
case "${1:-}" in
  "") ;;
  --control) CONTROL=true MODE_NAME="제어 연결" ;;
  --p2) CONTROL=true GOAL=true UPPER=true MODE_NAME="P2 운영" ;;
  *) echo "모르는 옵션: $1 (--control · --p2)"; exit 2 ;;
esac
# 실제 노드에 넘기는 값을 그대로 출력·로그 첫 줄에 남김 (E 10/14: 기본/--control/위 서랍 옵션의 실효 값)
echo "음성 노드 [$MODE_NAME] evaluation_mode=false request_run_enabled=$CONTROL p2_goal_enabled=$GOAL upper_drawer_enabled=$UPPER — 로그 $log" | tee "$log"
[ "$CONTROL" = true ] || echo "   기본: E 제어 연결(종료·복구·재개 wire)은 꺼짐 — evaluation_mode false 만으로는 켜지지 않음 (#313 E 리뷰)"
[ "$CONTROL" = true ] && echo "   Runner 도 재개 보존이 켜져야 '이어서 해'가 됨: pc2_up.sh --p2 (실효 값은 pc2_up 출력·ready.txt)"
PC2_CONTROL=$CONTROL PC2_GOAL=$GOAL PC2_UPPER=$UPPER python3 -u - <<'PYTHON' 2>&1 | tee -a "$log"
import os
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main
load_dotenv('secrets/voice.env')
args = ['--ros-args', '-p', 'config_file:=logs/voice_eval/voice.local.yaml', '-p', 'evaluation_mode:=false', '-p', 'diagnostic_detail:=true']
for env, name in (('PC2_CONTROL', 'request_run_enabled'), ('PC2_GOAL', 'p2_goal_enabled'), ('PC2_UPPER', 'upper_drawer_enabled')):
    if os.environ.get(env) == 'true':
        args += ['-p', f'{name}:=true']
print('VoiceNode argv:', ' '.join(args), flush=True)
main(args=args)
PYTHON
