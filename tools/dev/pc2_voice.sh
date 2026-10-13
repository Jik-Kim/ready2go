#!/usr/bin/env bash
# PC2 한 대 통합점검 — 터미널 ② 음성 (E 노드, 호스트 실행). 런북 1절 7번·Voice README "Runner 연동용" 명령과 같음.
#   bash tools/dev/pc2_voice.sh            # 1단계 통합점검 (음성 노드 기본 설정)
#   bash tools/dev/pc2_voice.sh --control  # 2단계: request_run_enabled:=true (E 제어 연결 opt-in — #315 머지·RUNNER_RESUMABLE=1 과 함께)
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
CONTROL=false
[ "${1:-}" = "--control" ] && CONTROL=true
echo "음성 노드 (Runner 연동, evaluation_mode false, request_run_enabled $CONTROL) — 로그 $log"
[ "$CONTROL" = true ] || echo "   1단계: E 제어 연결(종료·복구·재개 wire)은 꺼짐 — evaluation_mode false 만으로는 켜지지 않음 (#313 E 리뷰)"
PC2_CONTROL=$CONTROL python3 -u - <<'PYTHON' 2>&1 | tee "$log"
import os
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main
load_dotenv('secrets/voice.env')
args = ['--ros-args', '-p', 'config_file:=logs/voice_eval/voice.local.yaml', '-p', 'evaluation_mode:=false', '-p', 'diagnostic_detail:=true']
if os.environ.get('PC2_CONTROL') == 'true':
    args += ['-p', 'request_run_enabled:=true']
main(args=args)
PYTHON
