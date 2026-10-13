#!/usr/bin/env bash
# PC2 한 대 통합점검 끄기 (C). 로그 저장 → 컨테이너 내리기 → 시작 상태 되돌리기 안내. 런북 7절.
#   bash tools/dev/pc2_down.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p "${PC2_LOG_DIR:-$HOME/ready2go_pc2_logs}"
LOG=${PC2_LOG_DIR:-$HOME/ready2go_pc2_logs}/down_$(date +%m%d_%H%M).log   # 저장소 logs/ 는 root 소유일 수 있음
docker compose --profile real --profile pc2 logs --no-color > "$LOG" 2>&1 || true
echo "로그 저장: $LOG"
docker compose --profile real --profile pc2 down
if ! git diff --quiet -- knowledge/snapshots/initial_state.json; then
  echo "⚠️  시작 상태가 임시 변경된 채예요 — 되돌리기: git checkout knowledge/snapshots/initial_state.json"
fi
