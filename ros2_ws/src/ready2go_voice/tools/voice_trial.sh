#!/usr/bin/env bash
# 사용자가 명시한 prepare/live 한 단계만 실행합니다.
set -eo pipefail
VOICE_TRIAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$VOICE_TRIAL_ROOT"
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export PYTHONPATH="$VOICE_TRIAL_ROOT/ros2_ws/src/ready2go_voice:$VOICE_TRIAL_ROOT/ros2_ws/src/ready2go_knowledge:$VOICE_TRIAL_ROOT/ros2_ws/src/ready2go_runner:${PYTHONPATH:-}"
exec .venvs/project/bin/python -u ros2_ws/src/ready2go_voice/tools/voice_trial.py "$@"
