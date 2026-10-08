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

- `.github/workflows/ci.yml` 세 작업(계약·core 테스트 + MongoDB, compose 3프로파일, `colcon build`)을 같은 조건으로 임시 worktree에서 돌린다. 작업 폴더의 브랜치·`.env`·빌드 결과는 건드리지 않는다.
- 하나만: `ONLY=core|compose|build`. 실패하면 종료 코드 1, 로그는 `~/.cache/ready2go-ci/logs/`.
- PR·main 커밋의 빨간 X(Actions 미실행)는 이 기간 판정 근거가 아니다. 리뷰는 본문의 로컬 CI 줄(head SHA 포함)로 확인한다.
