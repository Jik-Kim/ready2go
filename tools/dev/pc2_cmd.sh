#!/usr/bin/env bash
# PC2 한 대 통합점검 — 터미널 ③ 명령 (C). 런북 2·5·7절 명령을 짧게. 모두 ros2-core 컨테이너 안에서 실행(r2genv 필요 없음).
#   bash tools/dev/pc2_cmd.sh help
set -euo pipefail
cd "$(dirname "$0")/../.."
X=(docker compose exec ros2-core /entrypoint.sh)
W=(-w 1 --max-wait-time-secs 10)   # 받는 쪽(Runner·음성 노드)이 없으면 10 s 뒤 그만 (계속 기다리지 않게)
# ROS 메시지 YAML 을 Python 으로 만든다 — 문장에 따옴표가 있어도 깨지지 않게 (#313 E 리뷰 P2). data 값은 JSON 문자열 표기(YAML 호환)
msg() { python3 -c 'import json, sys; print("data: " + json.dumps(sys.argv[1], ensure_ascii=False))' "$1"; }
intent_json() {  # goal <목표 JSON 목록> <문장> | find <물품 키> → /voice/intent JSON
  python3 - "$@" <<'PY'
import json, sys
kind, args = sys.argv[1], sys.argv[2:]
if kind == "goal":
    doc = {"intent": "achieve_goal", "goals": json.loads(args[0]), "confidence": 0.95, "source": {"stt_text": args[1]}}
else:
    doc = {"intent": "find_item", "targets": [args[0]], "confidence": 0.95, "source": {"stt_text": f"{args[0]} 찾아줘"}}
print(json.dumps(doc, ensure_ascii=False))
PY
}
pub() {   # 실패하면 안내 후 실패 코드 그대로 (#313 E 리뷰 P2)
  local rc=0
  "${X[@]}" ros2 topic pub --once "${W[@]}" /voice/intent std_msgs/msg/String "$(msg "$1")" || rc=$?
  [ "$rc" = 0 ] || echo "⚠️  Runner 가 안 받음 (종료 코드 $rc) — pc2_up.sh 확인" >&2
  return "$rc"
}
goal() {  # $1 = 목표 JSON 목록, $2 = 문장
  pub "$(intent_json goal "$1" "$2")"
}
case "${1:-help}" in
  status|state)   # 긴 JSON 을 자르지 않고(--full-length) 보기 좋게
    topic=/runner/status; [ "$1" = state ] && topic=/robot_state
    "${X[@]}" bash -c "ros2 topic echo --once --full-length --field data $topic | python3 -c '
import json, sys, yaml
data = yaml.safe_load(sys.stdin.read().split(\"---\")[0])
data = data if isinstance(data, dict) else json.loads(data)
print(json.dumps(data, ensure_ascii=False, indent=2))'" ;;
  reset)  "${X[@]}" ros2 service call /runner/reset_state std_srvs/srv/Trigger '{}' ;;
  report) "${X[@]}" ros2 run ready2go_runner run_report -n "${2:-1}" ;;
  check)  "${X[@]}" ros2 run ready2go_runner run_report -n "${2:-20}" --check ;;
  md)     "${X[@]}" ros2 run ready2go_runner run_report -n "${2:-5}" --markdown ;;
  say)    shift; [ $# -gt 0 ] || { echo "say <문장>"; exit 2; }
          rc=0; "${X[@]}" ros2 topic pub --once "${W[@]}" /voice/text_override std_msgs/msg/String "$(msg "$*")" || rc=$?
          [ "$rc" = 0 ] || { echo "⚠️  음성 노드가 안 받음 (종료 코드 $rc) — 터미널 ② pc2_voice.sh 확인 (급하면 find <물품>)" >&2; exit "$rc"; } ;;
  find)   item=${2:?물품 키 (예: eraser)}
          [[ "$item" =~ ^[a-z][a-z0-9_]*$ ]] || { echo "물품 키는 영문 소문자·숫자·_ 만 (예: eraser, lip_balm)"; exit 2; }
          pub "$(intent_json find "$item")" ;;
  goal)
    case "${2:-}" in
      1) goal '[{"predicate": "located_in", "subject": "eraser", "value": "handover_zone"}]' "지우개 트레이에 갖다 놔" ;;
      2) goal '[{"predicate": "open", "subject": "drawer_top", "value": true}]' "위 서랍 열어 둬" ;;
      3) goal '[{"predicate": "open", "subject": "drawer_top", "value": false}]' "위 서랍 닫아" ;;
      4) goal '[{"predicate": "located_in", "subject": "eraser", "value": "handover_zone"}, {"predicate": "open", "subject": "drawer_top", "value": true}]' "지우개 갖다 놓고 서랍은 열어 둬" ;;
      5) goal '[{"predicate": "located_in", "subject": "lip_balm", "value": "handover_zone"}]' "립밤 트레이에 갖다 놔" ;;
      *) echo "goal 1~5 (런북 5절 순서: 1 → reset → 2 → 3 → reset → 4 → reset → 5)"; exit 2 ;;
    esac ;;
  unlock) docker compose restart ros2-core ;;   # 정지 잠김 풀기 = Runner 재시작 (재개 모드 꺼짐) — 실물 확인·원위치 뒤
  logs)   docker compose --profile real --profile pc2 logs -f --tail 50 "${2:-ros2-core}" ;;
  *) cat <<'H'
bash tools/dev/pc2_cmd.sh <명령>
  status            /runner/status 한 번 (phase·last_intent·halt)
  state             /robot_state 한 번 (Runner 기억: 서랍·그리퍼·물품 위치)
  reset             Runner 기억을 시작 상태로 (회차 시작 전, 배치 확인 뒤)
  report [n]        최근 n 회 결과 (기본 1)
  check [n]         기록 빠짐 점검 (기본 20)
  md [n]            공유용 표 (기본 5)
  say <문장>        글자로 음성 입력 (E 음성 노드 해석을 거침) 예: say 지우개 찾아줘
  find <물품>       Runner 에 직접 find_item (음성이 안 될 때) 예: find eraser
  goal <1~5>        목표 5종 (런북 5절)
  unlock            정지 잠김 풀기 = Runner 재시작 (실물 확인·원위치 뒤)
  logs [서비스]     로그 보기 (ros2-core·vision-node·realsense·db)
H
  ;;
esac
