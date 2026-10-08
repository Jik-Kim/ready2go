# CLAUDE.md

[`AGENTS.md`](AGENTS.md)와 [문서 인덱스](docs/README.md)를 먼저 읽는다. 요구사항 정본·참조 규칙은 AGENTS.md를 따른다. 이 파일은 검증 명령만 추가한다.

## 영역별 검증 명령
| 바꾼 곳 | 실행 |
| :--- | :--- |
| `contracts/`, `knowledge/`, `tasks/` | `python3 tools/validate_contracts.py` |
| 패키지 `core/` | `python3 -m pytest ros2_ws/src -q` |
| ROS 패키지 전체 | `cd ros2_ws && colcon build --symlink-install && colcon test` |
| `compose.yaml`, `docker/` | `docker compose --profile dev config -q` (real·sim도 동일) |

PR 올리기 전 로컬 CI(`tools/dev/ci_local.sh`)와 결과 기록 규칙은 [`AGENTS.md`](AGENTS.md) "PR 올리기 전 — 로컬 CI"를 따른다(Codex 등 모든 에이전트 공통이라 그곳에 둔다).
