#!/usr/bin/env bash
# PC2 한 대 통합점검 — 터미널 ① 도커 (C). 카메라·로봇·Runner·DB·비전을 한 번에 띄우고 준비를 확인한 뒤 Runner 로그를 계속 보여 준다.
#   bash tools/dev/pc2_up.sh            # 처음: 컨테이너 안 빌드로 몇 분 걸림
#   bash tools/dev/pc2_up.sh --yes      # .env·호스트 확인 경고가 있어도 묻지 않고 진행
#   bash tools/dev/pc2_up.sh --check    # 띄우지 않고 1~4 확인만
# 터미널 ② 음성: bash tools/dev/pc2_voice.sh   터미널 ③ 명령: bash tools/dev/pc2_cmd.sh help   끄기: bash tools/dev/pc2_down.sh
# 띄우는 것은 런북(practice/C/2026-10-12_checkpoint2_runbook.md 1-1절)의 ①②③ 과 같은 서비스·설정 — 비전만 compose vision-node(pc2 프로필).
# Ctrl+C 는 로그 보기만 멈춘다(컨테이너는 계속 돎). 끌 때는 pc2_down.sh.
# 범위: 1단계 통합점검(RUNNER_RESUMABLE 비움 = 재개 모드 끔, 음성 기본) — 종료·복구·재개 실물(2단계)은 RUNNER_RESUMABLE=1 +
# 음성 pc2_voice.sh --control(request_run_enabled) + E #315·B #297 머지가 필요 (진행표 1-2절). 준비 실패면 로그 보기 없이 종료 코드 1.
set -euo pipefail
cd "$(dirname "$0")/../.."
MODE=${1:-}
export HOST_UID=$(id -u) HOST_GID=$(id -g) CODE_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
export VISION_DUMP=${VISION_DUMP:-$HOME/ready2go_vision_dump}
# 로그는 저장소 밖 — compose ros2-core 가 저장소 logs/ 를 root 소유로 만들어 쓰기 실패함 (vision_real_check.sh 덤프와 같은 이유)
LOG=${PC2_LOG_DIR:-$HOME/ready2go_pc2_logs}/$(date +%m%d_%H%M)
COMPOSE=(docker compose --profile real --profile pc2)
warn=0
say() { printf '%s\n' "$*"; }
bad() { say "⚠️  $*"; warn=1; }

say "== 1. .env 확인"
[ -f .env ] || { say "❌ .env 없음 — .env.example 을 복사해 채우기"; exit 1; }
want() { local v; v=$(grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/[[:space:]]*$//'); [ "$v" = "$2" ] || bad ".env $1='$v' (기대 '$2')"; }
want BACKEND real; want DDS_MODE local; want VISION_MODE yolo; want MOCK_SCENE ""
want RUNNER_INTENT_TASKS "find_item=/tasks/find_with_unpack.json"
grep -qE '^RUNNER_RESUMABLE=(1|true|on)' .env && bad "RUNNER_RESUMABLE 켜짐 — 통합점검은 비움(재개 모드 끔)"
for k in ROBOT_HOST RG2_HOST; do grep -qE "^$k=[0-9]" .env || bad ".env $k 비어 있음"; done

say "== 2. 호스트에서 켜 둔 것 (같은 /dsr01·카메라·스킬 서버와 충돌)"
running=$("${COMPOSE[@]}" ps -q 2>/dev/null || true)
if [ -n "$running" ]; then
  # 떠 있는 ros2-core 를 그대로 쓰면 지금 checkout·시작 상태와 다른 기동을 "준비 끝"으로 볼 수 있음 (#313 E 리뷰 P2) → 새로 띄우게 함
  bad "compose 컨테이너가 이미 떠 있음 — bash tools/dev/pc2_down.sh 로 내린 뒤 다시 (기존 기동을 이어 쓰지 않음)"
  [ "$MODE" = "--check" ] || { say "❌ 이미 떠 있어 멈춤"; exit 1; }
else   # 컨테이너가 없을 때만 — 컨테이너 안 프로세스도 호스트 pgrep 에 보이므로
  for p in realsense2_camera dsr_bringup2 skill_server inspect_region; do
    if pgrep -af "$p" | grep -v pgrep >/dev/null; then bad "호스트에 $p 실행 중 — Ctrl+C 로 끄기"; fi
  done
fi
docker ps --format '{{.Names}}' | grep -qx vision_check && bad "vision_real_check.sh node 컨테이너(vision_check)가 떠 있음 — 비전 노드가 둘이 됨"

say "== 3. 모델 (v2 b2ae5af07e2d…)"
m=models/yolo11s_seg_ready2go_v2.pt
if [ ! -f "$m" ] || [ "$(stat -c %s "$m")" -lt 100000 ]; then bad "$m 없음·포인터 — git lfs pull"
elif ! sha256sum "$m" | grep -q '^b2ae5af07e2d'; then bad "$m SHA 다름"; fi
docker image inspect ready2go-vision:latest >/dev/null 2>&1 || bad "ready2go-vision 이미지 없음 — docker compose --profile real build vision"

say "== 4. 시작 상태 (Runner 가 기동 때 한 번 읽음)"
git diff --quiet -- knowledge/snapshots/initial_state.json && say "   initial_state.json 저장소 그대로" \
  || say "   initial_state.json 이 저장소와 다름 (임시 변경 — 끝나면 pc2_down.sh 가 되돌리라고 알려 줌)"
python3 -c 'import json; d=json.load(open("knowledge/snapshots/initial_state.json", encoding="utf-8"))["state"]["located_in"]
print("   위 칸:", ", ".join(k for k, v in d.items() if v == "drawer_top") or "없음")
print("   아래 칸:", ", ".join(k for k, v in d.items() if v == "drawer_bottom") or "없음")' || bad "initial_state.json 을 못 읽음"

if [ "$MODE" = "--check" ]; then
  [ "$warn" = 0 ] && say "확인 끝 — 경고 없음" || say "확인 끝 — 위 ⚠️ 확인"; exit 0
fi
if [ "$warn" = 1 ] && [ "$MODE" != "--yes" ]; then
  read -r -p "경고가 있어요. 그래도 띄울까요? [y/N] " a; [ "$a" = y ] || exit 1
fi

mkdir -p "$LOG" "$VISION_DUMP"
say "== 5. 띄우기: realsense ros2-core db vision-node (기준점 $CODE_SHA)"
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)   # 준비 확인은 이 시각 뒤 로그만 (옛 기동 줄을 세지 않게)
"${COMPOSE[@]}" up -d realsense ros2-core db vision-node
( "${COMPOSE[@]}" logs -f --no-color realsense db vision-node > "$LOG/others.log" 2>&1 & )

wait_for() {  # 서비스 로그에 문구가 나올 때까지 (초)
  local svc=$1 text=$2 limit=$3 t=0
  until "${COMPOSE[@]}" logs --no-color --since "$START" "$svc" 2>/dev/null | grep -q -- "$text"; do
    sleep 5; t=$((t+5))
    if [ $t -ge "$limit" ]; then say "❌ $svc: '$text' 가 ${limit}s 안에 안 나옴 — docker compose logs $svc"; return 1; fi
  done
  say "   ✅ $svc: $text"
}
say "== 6. 준비 확인 (처음은 빌드로 몇 분)"
ok=1
wait_for ros2-core "Runner 준비" 900 || ok=0
wait_for vision-node "inspect_region 시작" 900 || ok=0
"${COMPOSE[@]}" logs --no-color --since "$START" vision-node | grep "inspect_region 시작" | tail -1 | grep -q "yolo11s_seg_ready2go_v2" \
  && say "   ✅ 비전 v2 모델" || { say "❌ 비전 모델이 v2 가 아님"; ok=0; }
"${COMPOSE[@]}" logs --no-color --since "$START" ros2-core | grep "Runner 준비" | tail -1 | grep -q "find_with_unpack" \
  && say "   ✅ find_item → find_with_unpack" || say "⚠️  Runner 인텐트에 find_with_unpack 없음 (.env RUNNER_INTENT_TASKS)"
say "   스킬 서버는 SKILL_START_DELAY_S(기본 15 s) 뒤 — 그 전 요청은 NOT_READY 로 거절(동작 없음)"
say ""
say "기준점(Python 0줄 비교): $CODE_SHA   로그: $LOG/"
if [ "$ok" != 1 ]; then   # 실패는 로그 보기와 섞지 않고 기록·종료 코드로 (#313 E 리뷰 P2)
  say "❌ 준비 확인 실패 — 위 ❌ 확인. 컨테이너는 떠 있음: bash tools/dev/pc2_cmd.sh logs <서비스> / 끄기 pc2_down.sh"
  echo "FAIL $CODE_SHA $START" > "$LOG/ready.txt"
  exit 1
fi
echo "OK $CODE_SHA $START" > "$LOG/ready.txt"
say "준비 끝. 터미널 ② bash tools/dev/pc2_voice.sh · 터미널 ③ bash tools/dev/pc2_cmd.sh status"
say "== 7. Runner 로그 (Ctrl+C = 보기만 멈춤, 컨테이너는 계속)"
"${COMPOSE[@]}" logs -f --no-color --tail 30 ros2-core 2>&1 | tee -a "$LOG/ros2-core.log"
