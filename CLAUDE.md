# CLAUDE.md

[`AGENTS.md`](AGENTS.md)와 [문서 인덱스](docs/README.md)를 먼저 읽는다. 요구사항 정본·참조 규칙은 AGENTS.md를 따른다. 이 파일은 검증 명령만 추가한다.

## 영역별 검증 명령
| 바꾼 곳 | 실행 |
| :--- | :--- |
| `contracts/`, `knowledge/`, `tasks/` | `python3 tools/validate_contracts.py` |
| 패키지 `core/` | `python3 -m pytest ros2_ws/src -q` |
| ROS 패키지 전체 | `cd ros2_ws && colcon build --symlink-install && colcon test` |
| `compose.yaml`, `docker/` | `docker compose --profile dev config -q` (real·sim도 동일) |

## PR 올리기 전 — 로컬 CI (GitHub Actions `ci` 비활성화 중)
Actions 무료분 소진으로 `ci` 워크플로를 비활성화했다(10/08, 11/1 초기화 뒤 재검토). 그동안 PR 작성자(사람·에이전트)는 PR head 기준으로 아래를 돌리고 **마지막 결과 한 줄을 PR 본문 `근거`에 붙인다**. 커밋을 더 올리면 다시 돌린다.

```bash
bash tools/dev/ci_local.sh <PR 번호 | 브랜치 | SHA>
```

- `.github/workflows/ci.yml` 세 작업(계약·core 테스트 + MongoDB, compose 3프로파일, `colcon build`)을 같은 조건으로 임시 worktree에서 돌린다: core는 Python 3.12 강제·ci.yml pip 목록만 든 venv·빈 환경(ROS `source`의 `PYTHONPATH`, `PYTEST_ADDOPTS` 등을 넘기지 않음), compose는 `.env`·셸 변수 없이. 검사 SHA는 원격에서 먼저 정해(`git ls-remote`) 동시 실행끼리 섞이지 않는다. 작업 폴더의 브랜치·`.env`·빌드 결과는 건드리지 않는다.
- docker를 이 사용자로 실행할 수 있어야 한다. 에이전트 샌드박스가 docker를 막으면 터미널에서 돌리고 결과 줄만 옮긴다.
- 하나만: `ONLY=core|compose|build` — 결과 줄에 "부분 검사"로 표시되며 전체 CI 대체가 아니다. 실패하면 종료 코드 1, 로그는 `~/.cache/ready2go-ci/logs/`. 결과 줄에는 검사 SHA와 스크립트 버전(`ci_local.sh@…`)이 들어간다.
- PR·main 커밋의 빨간 X(Actions 미실행)는 이 기간 판정 근거가 아니다. 리뷰는 본문의 로컬 CI 줄(head SHA 포함)로 확인한다.
