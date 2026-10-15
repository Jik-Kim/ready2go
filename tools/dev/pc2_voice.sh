#!/usr/bin/env bash
# PC2 한 대 통합점검 — 터미널 ② 음성 (E 노드, 호스트 실행). 런북 1절 7번·Voice README "Runner 연동용" 명령과 같음.
#   bash tools/dev/pc2_voice.sh            # 1단계 통합점검 (음성 노드 기본 설정)
#   bash tools/dev/pc2_voice.sh --control  # 제어 연결만: request_run_enabled:=true (복구·재개·종료 runtime)
#   bash tools/dev/pc2_voice.sh --p2       # P2 운영: request_run_enabled + p2_goal_enabled + upper_drawer_enabled (위 서랍 열기·닫기 목표만,
#                                          #   E 10/14) — Runner 는 pc2_up.sh --p2 (재개 보존). 설치된 음성 노드에 upper_drawer_enabled 가
#                                          #   없으면(E 구현·호스트 빌드 전) 목표 범위가 제한되지 않으므로 거부(종료 3)
# 띄우기 전에 음성(install_host)·Runner(pc2_up 기준점) C 코드가 같은지 확인 — 다르면 종료 4 (tools/dev/pc2_version_check.py)
# 세 값(request_run·p2_goal·upper_drawer)은 모드마다 true/false 를 모두 노드에 넘김 — 로컬 YAML 값과 모드 로그가 어긋나지 않게 (#349 E 리뷰 1)
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
# 음성(호스트 install_host)과 Runner(도커 — pc2_up 때 checkout)가 같은 C 코드인지 (#384 E·C 합의 10/15: 목록 안내가 C 문장을 대조하므로
# 버전이 다르면 안내가 조용히 거절됨 — 구조화 안내 계약은 후속). 다르면 멈춤, 확인 못 함(ready.txt 없음 등)은 경고만.
# 일부러 다른 버전으로 띄울 때만 PC2_SKIP_VERSION_CHECK=1
if [ "${PC2_SKIP_VERSION_CHECK:-}" = 1 ]; then echo "⚠️  버전 확인 건너뜀 (PC2_SKIP_VERSION_CHECK=1)"
else
  rc=0; python3 tools/dev/pc2_version_check.py || rc=$?
  [ "$rc" = 1 ] && { echo "❌ 음성·Runner C 코드 버전이 다름 — 위 '맞추기' 뒤 다시 (일부러면 PC2_SKIP_VERSION_CHECK=1)"; exit 4; }
fi
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
if [ "$UPPER" = true ]; then   # 구형 E 노드는 upper_drawer_enabled 를 몰라 무시 → p2_goal 이 위 서랍으로 제한되지 않음 (#349 E 리뷰 2)
  python3 - <<'CHECK' || { echo "❌ --p2: 설치된 음성 노드(install_host)에 upper_drawer_enabled 가 없음 — E 위 서랍 제한 구현이 main 에 들어오고 호스트 빌드된 뒤에 씀. 지금은 --control"; exit 3; }
import inspect, sys
import ready2go_voice.nodes.voice_node as node
sys.exit(0 if "upper_drawer_enabled" in inspect.getsource(node) else 1)
CHECK
fi
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
    args += ['-p', f"{name}:={'true' if os.environ.get(env) == 'true' else 'false'}"]   # false 도 명시 (로컬 YAML 덮음)
print('VoiceNode argv:', ' '.join(args), flush=True)
main(args=args)
PYTHON
