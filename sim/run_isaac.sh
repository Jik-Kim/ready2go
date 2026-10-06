#!/usr/bin/env bash
# Isaac Sim 실행기 (담당 A). 어떤 터미널에서든 실행할 수 있다:  bash sim/run_isaac.sh [Isaac Sim 인자...]
# 시스템 ROS(~/.bashrc 등)가 source 된 셸에서도 쓸 수 있도록, ROS 관련 환경을 모두 버린 깨끗한 환경에서
# sim/isaac_env.sh 를 source 하고 Isaac Sim 을 실행한다 (Kit Python 3.11 ↔ 시스템 Jazzy rclpy 3.12 충돌 방지, 이유: sim/README.md).
# 화면·세션 변수와 DDS 설정 변수(DDS_MODE, DDS_IFACE, PEER_PC1, PEER_PC2, ISAAC_SIM_ROOT), --exec 스크립트 설정 READY2GO_* 만 넘긴다.
# 인자가 없으면 ROS 2 Bridge 확장을 켜서 실행한다. ISAAC_SIM_CMD 로 실행 명령을 바꿀 수 있다(테스트용).
set -euo pipefail

_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_CMD="${ISAAC_SIM_CMD:-${ISAAC_SIM_ROOT:-$HOME/isaac-sim-5.1.0}/isaac-sim.sh}"

_pass=()
for v in HOME USER LOGNAME LANG LC_ALL DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_RUNTIME_DIR XDG_SESSION_TYPE \
         XDG_DATA_DIRS XDG_CONFIG_DIRS DBUS_SESSION_BUS_ADDRESS DDS_MODE DDS_IFACE PEER_PC1 PEER_PC2 ISAAC_SIM_ROOT \
         $(compgen -v READY2GO_ || true); do                     # READY2GO_* 는 --exec 스크립트 설정(READY2GO_TRACE 등) — 전부 넘김
  if [ -n "${!v:-}" ]; then _pass+=("$v=${!v}"); fi
done

if [ "$#" -eq 0 ]; then
  set -- --/isaac/startup/ros_bridge_extension=isaacsim.ros2.bridge
fi

exec env -i "${_pass[@]}" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  bash --noprofile --norc -c 'repo=$1; cmd=$2; shift 2; source "$repo/sim/isaac_env.sh" || exit 1; exec "$cmd" "$@"' \
  _ "$_REPO" "$_CMD" "$@"
