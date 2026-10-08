#!/usr/bin/env bash
# 로컬 CI — GitHub Actions `ci` 워크플로를 대신해 같은 세 작업을 이 PC에서 돌린다 (PM, 10/08).
# Actions 무료분 소진으로 `ci` 워크플로를 비활성화했다(사용자 결정 10/08, 11/1 초기화). 그동안 PR 마다 이 결과를 본문에 붙인다.
# 기준은 .github/workflows/ci.yml 이다 — 거기 바뀌면 이 스크립트도 같이 바꾼다.
#
#   bash tools/dev/ci_local.sh            # 지금 저장소 HEAD (커밋된 것만 — 커밋 안 한 수정은 검사하지 않음)
#   bash tools/dev/ci_local.sh 185        # PR #185 의 head (origin 에서 받음)
#   bash tools/dev/ci_local.sh <브랜치|SHA>
#   ONLY=core bash tools/dev/ci_local.sh 185     # 하나만: core | compose | build (결과 줄에 "부분 검사"로 표시)
#
# 하는 일 (ci.yml 과 같은 조건):
#   1. core    — Python 3.12 venv(ci.yml 의 pip 목록만) + 임시 MongoDB 7.0 컨테이너로
#                `tools/validate_contracts.py` → `REQUIRE_MONGO=1 pytest ros2_ws/src -q -rs`.
#                호스트 환경(ROS source 의 PYTHONPATH, PYTEST_ADDOPTS 등)은 넘기지 않는다(빈 환경).
#   2. compose — `docker compose --profile real|sim|dev config -q` (.env·셸 환경변수 없이)
#   3. build   — `ros:jazzy-ros-base-noble` 컨테이너에서 `colcon build`
# 검사 커밋은 원격에서 SHA 로 먼저 정하고(`git ls-remote`) 그 SHA 만 받는다 — FETCH_HEAD·로컬 ref 를 쓰지 않아
# 같은 저장소에서 동시에 여러 개를 돌려도 서로의 커밋을 집지 않는다. 검사는 임시 worktree(LFS 파일은 받지 않음 =
# Actions checkout 과 같음)에서 하므로 작업 폴더의 .env·빌드 결과·커밋 안 한 파일이 섞이지 않고, 작업 폴더의
# 브랜치도 바꾸지 않는다. 끝나면 worktree·컨테이너를 지운다.
# 마지막 줄 = PR 본문에 붙일 결과(검사 SHA·스크립트 버전 포함). 하나라도 실패하면 종료 코드 1.
# 로그는 ~/.cache/ready2go-ci/logs/<SHA>_<시각>_<실행ID>/ 에 남는다.
#
# 필요: git, docker(compose 플러그인, 이 사용자로 docker 명령 가능해야 함 — 에이전트 샌드박스가 막으면 터미널에서),
#       python3.12 + venv, flock. 처음 한 번은 pip 패키지·Docker 이미지를 받는다.
# MongoDB 는 빈 포트로 띄우므로 PC2 의 compose DB(27017)와 겹치지 않는다.
set -euo pipefail
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
REF=${1:-HEAD}
ONLY=${ONLY:-}
case "$ONLY" in ""|core|compose|build) ;; *) echo "ONLY 는 core|compose|build 중 하나"; exit 2 ;; esac
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/ready2go-ci
TOOL_VER=$(git hash-object "$0" | cut -c1-7)                  # 결과 줄에 남길 이 스크립트 버전

# --- 검사할 커밋 정하기 (SHA 를 먼저 정하고 그 SHA 만 받음) ---------------------------
remote_sha() { git -C "$REPO" ls-remote origin "$1" | awk 'NR==1{print $1}'; }
fetch_sha() { git -C "$REPO" -c fetch.prune=false fetch -q --no-write-fetch-head origin "$1"; }
if [[ $REF =~ ^[0-9]+$ ]]; then
  SHA=$(remote_sha "refs/pull/$REF/head"); LABEL="PR #$REF"
  [[ -n $SHA ]] || { echo "PR #$REF 를 origin 에서 찾지 못함"; exit 2; }
  git -C "$REPO" cat-file -e "$SHA^{commit}" 2>/dev/null || fetch_sha "$SHA"
else
  SHA=$(git -C "$REPO" rev-parse --verify -q "$REF^{commit}" || true)
  if [[ -z $SHA ]]; then                                      # 로컬에 없으면 origin 브랜치로
    SHA=$(remote_sha "refs/heads/$REF")
    [[ -n $SHA ]] || { echo "$REF 를 로컬·origin 어디서도 찾지 못함"; exit 2; }
    git -C "$REPO" cat-file -e "$SHA^{commit}" 2>/dev/null || fetch_sha "$SHA"
  fi
  LABEL=$REF
fi
git -C "$REPO" cat-file -e "$SHA^{commit}"                    # 받은 커밋이 정한 SHA 와 같은지(없으면 여기서 실패)
SHORT=${SHA:0:7}
mkdir -p "$CACHE/logs"
LOGS=$(mktemp -d "$CACHE/logs/${SHORT}_$(date +%Y%m%d_%H%M%S)_XXXX")
TMP=$(mktemp -d "${TMPDIR:-/tmp}/r2g-ci.XXXXXX")
SRC="$TMP/src"
MONGO="r2g-ci-mongo-$(basename "$TMP")"

cleanup() {
  docker rm -f "$MONGO" >/dev/null 2>&1 || true
  git -C "$REPO" worktree remove --force "$SRC" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "로컬 CI: $LABEL → $SHA (ci_local.sh $TOOL_VER)"
GIT_LFS_SKIP_SMUDGE=1 git -C "$REPO" worktree add -q --detach "$SRC" "$SHA"
[[ $(git -C "$SRC" rev-parse HEAD) == "$SHA" ]] || { echo "worktree HEAD 가 검사 SHA 와 다름"; exit 1; }

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
  local pkgs py venv hash
  pkgs=$(sed -n 's/^ *- run: pip install //p' "$SRC/.github/workflows/ci.yml" | head -1)
  [[ -n $pkgs ]] || { echo "ci.yml 에서 pip 목록을 못 찾음"; return 1; }
  py=$(command -v python3.12) || { echo "python3.12 가 없음 (CI 는 3.12 — 다른 버전 결과는 CI 대체로 쓰지 않음)"; return 1; }
  # venv 는 (Python 버전 + pip 목록) 마다 따로, 한 번 만들면 바꾸지 않음 → 다른 목록을 검사하는 동시 실행이 지우지 못함
  hash=$(printf '%s' "$pkgs" | sha256sum | cut -c1-12)
  venv="$CACHE/venv-py3.12-$hash"
  mkdir -p "$CACHE"
  (
    flock 9
    if [[ ! -f $venv/.ready ]]; then
      local build="$venv.build.$$"
      rm -rf "$build"
      env -i PATH=/usr/bin:/bin HOME="$HOME" "$py" -m venv "$build"
      eval "env -i PATH=/usr/bin:/bin HOME=\"$HOME\" \"$build/bin/python\" -m pip install -q --disable-pip-version-check $pkgs"
      echo "$pkgs" >"$build/.pkgs"
      touch "$build/.ready"
      rm -rf "$venv" && mv "$build" "$venv"                   # 준비가 끝난 뒤에만 이름을 붙임
    fi
  ) 9>"$CACHE/venv.lock"
  # venv 를 옮겨 만들었으므로 실행 파일 경로가 아닌 python -m 으로만 부른다
  local vpy="$venv/bin/python"
  [[ -x $vpy ]] || { echo "venv python 없음: $vpy"; return 1; }

  local port i
  port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  docker run -d --rm --name "$MONGO" -p "127.0.0.1:$port:27017" mongo:7.0 >/dev/null
  for i in $(seq 60); do                                      # ci.yml health-check 와 같은 ping (최대 60 s)
    docker exec "$MONGO" mongosh --quiet --eval 'db.runCommand({ping: 1})' >/dev/null 2>&1 && break
    sleep 1
  done
  docker exec "$MONGO" mongosh --quiet --eval 'db.runCommand({ping: 1})' >/dev/null

  cd "$SRC"
  # 빈 환경: 호스트의 PYTHONPATH(ROS source)·PYTHONHOME·PYTEST_ADDOPTS·VIRTUAL_ENV 등을 넘기지 않음
  local clean=(env -i PATH=/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8)
  echo "== 환경: $("${clean[@]}" "$vpy" -c 'import sys; print(sys.version.split()[0], sys.prefix)')"
  echo "== rclpy 보임 여부(CI 는 없음): $("${clean[@]}" "$vpy" -c 'import importlib.util as u; print("있음" if u.find_spec("rclpy") else "없음")')"
  echo "== validate_contracts"; "${clean[@]}" "$vpy" tools/validate_contracts.py
  echo "== pytest"
  "${clean[@]}" MONGO_URI="mongodb://127.0.0.1:$port" REQUIRE_MONGO=1 \
    "$vpy" -m pytest ros2_ws/src -q -rs -p no:cacheprovider
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
    parts+=("validate_contracts OK" "pytest $summary (py3.12, REQUIRE_MONGO=1)")
  else
    parts+=("core ❌")
  fi
fi
[[ -n ${RESULT[compose]:-} ]] && parts+=("compose real·sim·dev $([[ ${RESULT[compose]} == OK ]] && echo OK || echo ❌)")
[[ -n ${RESULT[build]:-} ]] && parts+=("colcon build $([[ ${RESULT[build]} == OK ]] && echo OK || echo ❌)")
line=$(IFS='/'; echo "${parts[*]}" | sed 's#/# / #g')
scope="전체"
[[ -n $ONLY ]] && scope="부분 검사 ONLY=$ONLY — 전체 CI 대체 아님"
echo
echo "로컬 CI [실측] head \`$SHORT\` ($LABEL, $scope) — $line (tools/dev/ci_local.sh@$TOOL_VER, $(date '+%m/%d %H:%M'))"
[[ $FAIL == 0 ]] || { echo "실패 로그: $LOGS"; exit 1; }
