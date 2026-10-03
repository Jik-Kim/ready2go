#!/usr/bin/env bash
# Isaac Sim 실행 전에 source 하는 환경 스크립트 (담당 A). 사용:
#   source sim/isaac_env.sh && ~/isaac-sim-5.1.0/isaac-sim.sh --/isaac/startup/ros_bridge_extension=isaacsim.ros2.bridge
#
# [실측 10/03] Isaac Sim 5.1의 내장 Python은 3.11이고 시스템 Jazzy의 rclpy는 Python 3.12용이라,
# 시스템 ROS를 source 하면 rclpy를 불러오지 못한다. 그래서 이 스크립트는 시스템 ROS를 source 하지 않고
# Isaac Sim 번들의 내부 ROS 라이브러리(exts/isaacsim.ros2.bridge/jazzy/lib)를 쓰도록 맞춘다.
# DDS 값은 컨테이너(compose.yaml x-ros-env)와 같게: Domain 70, CycloneDDS.
#   DDS_MODE=local(기본, 단일 PC, lo) | multi(PC1↔PC2, DDS_IFACE·PEER_PC1·PEER_PC2 필요)
# ros2 CLI(topic list 등)는 별도 터미널에서 시스템 ROS를 source 하고 같은 DDS 값을 줘서 사용한다 (sim/README.md).

_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_ISAAC="${ISAAC_SIM_ROOT:-$HOME/isaac-sim-5.1.0}"
_LIB="${_ISAAC}/exts/isaacsim.ros2.bridge/jazzy/lib"
_ERR=""

[ -d "$_LIB" ] || _ERR="Isaac Sim 번들 ROS 라이브러리가 없습니다: $_LIB (ISAAC_SIM_ROOT 확인)"
if [ -z "$_ERR" ] && { [ -n "${AMENT_PREFIX_PATH:-}" ] || [[ "${PYTHONPATH:-}" == */opt/ros/* ]]; }; then
  _ERR="시스템 ROS가 source 된 셸입니다. Python 3.11/3.12 충돌을 피하려면 새 터미널에서 실행하세요."
fi
_DDS_MODE="${DDS_MODE:-local}"
if [ -z "$_ERR" ] && [ ! -f "${_REPO}/config/cyclonedds.${_DDS_MODE}.xml" ]; then
  _ERR="config/cyclonedds.${_DDS_MODE}.xml 이 없습니다."
fi
if [ -z "$_ERR" ] && [ "$_DDS_MODE" = "multi" ] && { [ -z "${DDS_IFACE:-}" ] || [ -z "${PEER_PC1:-}" ] || [ -z "${PEER_PC2:-}" ]; }; then
  _ERR="multi 모드에는 DDS_IFACE, PEER_PC1, PEER_PC2 가 필요합니다."
fi

if [ -n "$_ERR" ]; then
  echo "[isaac_env] $_ERR" >&2
  unset _REPO _ISAAC _LIB _ERR _DDS_MODE
  return 1 2>/dev/null || exit 1
fi

export ROS_DISTRO=jazzy
export ROS_DOMAIN_ID=70
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export DDS_MODE="$_DDS_MODE"
export CYCLONEDDS_URI="file://${_REPO}/config/cyclonedds.${DDS_MODE}.xml"
case ":${LD_LIBRARY_PATH:-}:" in *":${_LIB}:"*) ;; *) export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}${_LIB}";; esac

echo "[isaac_env] ROS_DISTRO=${ROS_DISTRO} ROS_DOMAIN_ID=${ROS_DOMAIN_ID} RMW=${RMW_IMPLEMENTATION} DDS_MODE=${DDS_MODE} (내부 ROS 라이브러리 사용)"
unset _REPO _ISAAC _LIB _ERR _DDS_MODE
