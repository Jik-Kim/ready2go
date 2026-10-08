#!/usr/bin/env bash
# 로컬 CI — GitHub Actions `ci` 워크플로를 대신해 같은 세 작업을 이 PC에서 돌린다 (PM, 10/08).
# Actions 무료분 소진으로 `ci` 워크플로를 비활성화했다(사용자 결정 10/08, 11/1 초기화). 그동안 PR 마다 이 결과를 본문에 붙인다.
# 기준은 .github/workflows/ci.yml 이다 — 거기 바뀌면 이 스크립트도 같이 바꾼다.
#
#   bash tools/dev/ci_local.sh            # 지금 저장소 HEAD (커밋된 것만 — 커밋 안 한 수정은 검사하지 않음)
#   bash tools/dev/ci_local.sh 185        # PR #185 의 head (origin 에서 받음)
#   bash tools/dev/ci_local.sh <브랜치|SHA>
#   ONLY=core bash tools/dev/ci_local.sh 185     # 하나만: core | compose | build
#
# 하는 일 (ci.yml 과 같은 조건):
#   1. core    — 깨끗한 Python 3.12 venv(ci.yml 의 pip 목록만) + 임시 MongoDB 7.0 컨테이너로
#                `tools/validate_contracts.py` → `REQUIRE_MONGO=1 pytest ros2_ws/src -q -rs`
#   2. compose — `docker compose --profile real|sim|dev config -q` (.env·셸 환경변수 없이)
#   3. build   — `ros:jazzy-ros-base-noble` 컨테이너에서 `colcon build`
# 검사는 임시 worktree(LFS 파일은 받지 않음 = Actions checkout 과 같음)에서 하므로 작업 폴더의 .env·빌드 결과·
# 커밋 안 한 파일이 섞이지 않고, 작업 폴더의 브랜치도 바꾸지 않는다. 끝나면 worktree·컨테이너를 지운다.
# 마지막 줄 = PR 본문에 붙일 결과. 하나라도 실패하면 종료 코드 1. 로그는 ~/.cache/ready2go-ci/logs/ 에 남는다.
#
# 필요: git, docker(compose 플러그인), python3.12(-venv), flock. 처음 한 번은 pip 패키지·Docker 이미지를 받는다.
# MongoDB 는 빈 포트로 띄우므로 PC2 의 compose DB(27017)와 겹치지 않는다.
set -euo pipefail
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
REF=${1:-HEAD}
ONLY=${ONLY:-}
case "$ONLY" in ""|core|compose|build) ;; *) echo "ONLY 는 core|compose|build 중 하나"; exit 2 ;; esac
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/ready2go-ci

# --- 검사할 커밋 정하기 -------------------------------------------------------------
if [[ $REF =~ ^[0-9]+$ ]]; then
  git -C "$REPO" fetch -q origin "pull/$REF/head"            # FETCH_HEAD 로만 받음 (로컬 브랜치·ref 를 만들지 않음)
  SHA=$(git -C "$REPO" rev-parse FETCH_HEAD); LABEL="PR #$REF"
else
  SHA=$(git -C "$REPO" rev-parse --verify -q "$REF^{commit}" || true)
  if [[ -z $SHA ]]; then                                      # 로컬에 없으면 origin 브랜치로
    git -C "$REPO" fetch -q origin "$REF" && SHA=$(git -C "$REPO" rev-parse FETCH_HEAD)
  fi
  LABEL=$REF
fi
SHORT=${SHA:0:7}
STAMP=$(date +%Y%m%d_%H%M%S)
LOGS="$CACHE/logs/${SHORT}_$STAMP"
mkdir -p "$LOGS"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/r2g-ci.XXXXXX")
SRC="$TMP/src"
MONGO="r2g-ci-mongo-$$"

cleanup() {
  docker rm -f "$MONGO" >/dev/null 2>&1 || true
  git -C "$REPO" worktree remove --force "$SRC" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "로컬 CI: $LABEL → $SHA"
GIT_LFS_SKIP_SMUDGE=1 git -C "$REPO" worktree add -q --detach "$SRC" "$SHA"

declare -A RESULT=()
FAIL=0
run_step() {                                                  # run_step 이름 명령... → 로그에 저장, 결과 기록
  local name=$1; shift
  local log="$LOGS/$name.log" rc
  echo "  [$name] 실행 중… (로그 $log)"
  set +e                                                      # if 조건 안에서 돌리면 함수 안 set -e 가 꺼져 중간 실패를 놓침 → 서브셸 종료 코드로
  ( set -e; "$@" ) >"$log" 2>&1
  rc=$?
  set -e
  if [[ $rc == 0 ]]; then RESULT[$name]=OK; else RESULT[$name]=FAIL; FAIL=1; echo "  [$name] 실패 — 로그 마지막 20줄:"; tail -n 20 "$log" | sed 's/^/    /'; fi
}

# --- 1. core ----------------------------------------------------------------------
core() {
  local pkgs pyver venv
  pkgs=$(sed -n 's/^ *- run: pip install //p' "$SRC/.github/workflows/ci.yml" | head -1)
  [[ -n $pkgs ]] || { echo "ci.yml 에서 pip 목록을 못 찾음"; return 1; }
  pyver=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
  [[ $pyver == 3.12 ]] || echo "주의: python3 $pyver (CI 는 3.12)"
  venv="$CACHE/venv-py$pyver"
  mkdir -p "$CACHE"
  (                                                           # 여러 에이전트가 같은 PC 에서 동시에 돌려도 venv 설치는 한 번에 하나
    flock 9
    if [[ ! -x $venv/bin/python || $(cat "$venv/.pkgs" 2>/dev/null) != "$pkgs" ]]; then
      rm -rf "$venv" && python3 -m venv "$venv"
      eval "\"$venv/bin/python\" -m pip install -q --disable-pip-version-check $pkgs"
      echo "$pkgs" >"$venv/.pkgs"
    fi
  ) 9>"$CACHE/venv.lock"

  local port
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  docker run -d --rm --name "$MONGO" -p "127.0.0.1:$port:27017" mongo:7.0 >/dev/null
  local i
  for i in $(seq 60); do                                      # ci.yml health-check 와 같은 ping (최대 60 s)
    docker exec "$MONGO" mongosh --quiet --eval 'db.runCommand({ping: 1})' >/dev/null 2>&1 && break
    sleep 1
  done
  docker exec "$MONGO" mongosh --quiet --eval 'db.runCommand({ping: 1})' >/dev/null

  cd "$SRC"
  echo "== validate_contracts"; "$venv/bin/python" tools/validate_contracts.py
  echo "== pytest"
  MONGO_URI="mongodb://127.0.0.1:$port" REQUIRE_MONGO=1 \
    "$venv/bin/python" -m pytest ros2_ws/src -q -rs -p no:cacheprovider
}

# --- 2. compose -------------------------------------------------------------------
compose() {
  cd "$SRC"
  local p
  for p in real sim dev; do                                   # 셸에 export 한 BACKEND·DDS_MODE 등이 결과를 바꾸지 않게 빈 환경으로
    echo "== profile $p"
    env -i PATH="$PATH" HOME="$HOME" ${DOCKER_HOST:+DOCKER_HOST="$DOCKER_HOST"} docker compose --profile "$p" config -q
  done
}

# --- 3. build ---------------------------------------------------------------------
build() {                                                     # 원본은 읽기 전용으로 붙이고 컨테이너 안 복사본에서 빌드 (root 소유 산출물을 남기지 않음)
  docker run --rm -v "$SRC:/src:ro" ros:jazzy-ros-base-noble bash -c \
    'cp -r /src /tmp/ws && source /opt/ros/jazzy/setup.bash && cd /tmp/ws/ros2_ws && colcon build --event-handlers console_direct-'
}

[[ -z $ONLY || $ONLY == core ]] && run_step core core
[[ -z $ONLY || $ONLY == compose ]] && run_step compose compose
[[ -z $ONLY || $ONLY == build ]] && run_step build build

# --- 결과 한 줄 -------------------------------------------------------------------
parts=()
if [[ -n ${RESULT[core]:-} ]]; then
  if [[ ${RESULT[core]} == OK ]]; then
    summary=$(grep -E '^[0-9]+ passed' "$LOGS/core.log" | tail -1 | sed 's/ in [0-9.]*s.*//')
    parts+=("validate_contracts OK" "pytest $summary (REQUIRE_MONGO=1)")
  else
    parts+=("core ❌")
  fi
fi
[[ -n ${RESULT[compose]:-} ]] && parts+=("compose real·sim·dev $([[ ${RESULT[compose]} == OK ]] && echo OK || echo ❌)")
[[ -n ${RESULT[build]:-} ]] && parts+=("colcon build $([[ ${RESULT[build]} == OK ]] && echo OK || echo ❌)")
line=$(IFS='/'; echo "${parts[*]}" | sed 's#/# / #g')
echo
echo "로컬 CI [실측] head \`$SHORT\` ($LABEL) — $line (tools/dev/ci_local.sh, $(date '+%m/%d %H:%M'))"
[[ $FAIL == 0 ]] || { echo "실패 로그: $LOGS"; exit 1; }
