# AGENTS.md — ready2go 공통 작업 규칙 (사람·AI 에이전트)

## 작업 시작
- 먼저 `docs/README.md`(인덱스)만 읽고, 작업에 필요한 문서만 연다. **문서 전체를 한 번에 읽지 않는다.**
- 작업에 연결된 요구사항 ID와 Phase는 `docs/requirements.md`(요구사항 기준 원본)에서 확인하고, **그 Phase 범위 밖 기능은 만들지 않는다.**
- 요구사항 문서 전체를 읽지 않는다. 작업 관련 ID를 먼저 찾아 해당 FR/NFR 항목과 연결된 완료 기준만 확인한다. 범위가 불명확하면 `requirements.md` 2장의 Phase 요약을 확인한다.
- JSON은 문서가 아니라 원본 파일(`contracts/`, `knowledge/`, `tasks/`)을 본다.
- `git status`로 작업 트리 상태를 확인한다. `docs/archive/`는 읽지 않는다.

## 요구사항 정본과 참조 (P1·P2·P3 공통)
- 의미·정의·정책·책임 경계·Phase·수용 기준은 `docs/requirements.md`에만 정의한다. 변경은 승인된 범위에서 정본을 먼저 수정하고, 관련 문서는 해당 FR/NFR/AC 앵커 링크를 갱신한다.
- README·기술 문서·시연·예시·에이전트 지시문에 기준 내용을 복사하거나 다른 표현으로 재정의하지 않는다. 각 문서에는 자기 모듈의 현재 구현·운용 방법·시험 절차·실측 결과만 두고 기준은 링크로 참조한다. 예시나 시연 문서 변경으로 정책·Phase를 우회하지 않는다.
- 실행 필드·타입·enum·값은 `contracts/`, `knowledge/`, `config/`, `params/`, `tasks/` 등 실행 원본에서 확인한다. 정본에는 원본 위치를 연결하며 JSON/YAML을 통째로 복제하지 않는다. 수용 기준 숫자·런타임 설정값·실측 결과를 구분한다.
- 승인된 정책, 미확정 제안, 현행 구현·미연결·미검증을 구분한다. 정본/링크 정리는 자동 참조·자동 검사 구현이나 기능 완료가 아니다. 담당 소유권과 아래 계약 승인·검증 규칙을 그대로 적용한다.

## 범위와 소유권
- 다른 담당의 패키지는 수정하지 않는다. 필요하면 GitHub Issue로 요청한다 (담당: 각 패키지 `README.md`).
- 로봇을 움직이는 코드는 `ready2go_skills`에만, 상태·로그를 쓰는 코드는 `ready2go_runner`에만 둔다. USD 씬은 A(김병직)만 편집한다.
- 요청받은 범위에서 가장 작은 변경으로 목적을 달성한다.

## 계약과 값
- 계약(`contracts/`, `ready2go_interfaces`, `docs/interfaces.md`)을 바꾸면 **스키마·예시·문서를 같은 PR에서** 고친다. 승인 2명, 그중 1명은 조장(E).
- 확정되지 않은 값은 `[팀 확정 필요]` 주석과 함께 `config/` 또는 `params/*.yaml`에 두고 코드에 하드코딩하지 않는다.
- 이름은 전부 소문자 + `_` (ROS 패키지, Docker 이미지·서비스).

## 근거 표시
- 측정·판단에는 **[실측] / [문서] / [추정]** 태그를 붙인다. [추정]이면 검증 방법을 같이 적는다.

## 코드 구조
- 패키지 안은 `core/`(ROS 비의존, `pytest` 대상) · `nodes/`(rclpy) · `adapters/`(장치·외부 서비스)로 나눈다.
- 구현하지 않은 부분은 `TODO(담당)`으로 남긴다.

## Git
- `main`은 PR로만 반영한다. 요청받지 않은 push·PR 생성은 하지 않는다. PR 본문에는 아래 로컬 CI 결과 줄을 붙인다.
- 작업이 끝나면 `practice/<담당>/CURRENT.md`를 갱신한다.

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

- `.github/workflows/ci.yml` 세 작업(계약·core 테스트 + MongoDB, compose 3프로파일, `colcon build`)을 같은 조건으로 임시 worktree에서 돌린다: core는 Python 3.12 강제·ci.yml pip 목록만 든 venv·빈 환경(ROS `source`의 `PYTHONPATH`, `PYTEST_ADDOPTS` 등을 넘기지 않음), compose는 `.env`·셸 변수 없이. 입력은 숫자 = PR 번호(원격 `refs/pull/N/head`의 SHA를 먼저 정함) → 로컬에 있는 브랜치·SHA(로컬 브랜치는 커밋된 것) → 로컬에 없는 40자 SHA는 원격에서 그 커밋을 받음 → 그 밖은 원격 브랜치 순서로 처리하고, 짧은 SHA는 로컬에 있어야 한다. FETCH_HEAD를 쓰지 않아 동시 실행끼리 섞이지 않는다. 작업 폴더의 브랜치·`.env`·빌드 결과는 건드리지 않는다.
- docker를 이 사용자로 실행할 수 있어야 한다. 에이전트 샌드박스가 docker를 막으면 터미널에서 돌리고 결과 줄만 옮긴다.
- 하나만: `ONLY=core|compose|build` — 결과 줄에 "부분 검사"로 표시되며 전체 CI 대체가 아니다. 실패하면 종료 코드 1, 로그는 `~/.cache/ready2go-ci/logs/`. 결과 줄에는 검사 SHA와 스크립트 버전(`ci_local.sh@…`)이 들어간다.
- PR·main 커밋의 빨간 X(Actions 미실행)는 이 기간 판정 근거가 아니다. 리뷰는 본문의 로컬 CI 줄(head SHA 포함)로 확인한다.

## GitHub Issue 라벨링
- 사용자가 승인하거나 요청한 이슈를 생성할 때는 저장소의 **현재 기존 라벨 목록**을 가능한 API·도구로 조회한다. 과거 이슈 예시만으로 라벨 전체 목록을 추정하거나 새 라벨을 임의로 만들지 않는다.
- 이슈 본문, 루트 또는 패키지 README의 담당 정보, `docs/requirements.md`의 관련 요구사항 ID·Phase를 대조해 기존 `owner:*`, `area:*`, `phase:*` 라벨 중 근거가 있는 것을 고른다. 여러 담당이 근거로 확인되면 owner 라벨을 복수로 적용한다.
- 담당이나 Phase가 미확정이면 임의로 정하지 않는다. 심각도 `P1`~`P3` 표기는 프로젝트 Phase로 해석하지 않는다.
- 라벨 목록을 조회할 수 없으면 확인된 기존 라벨만 사용하고, 목록 확인의 한계를 보고한다. 이슈 생성 권한은 사용자 승인 없이 새로 부여되지 않는다.
- 이슈 생성 API의 `labels` 인자로 라벨을 함께 부착한다. 생성 도구가 이를 지원하지 않으면 생성 직후 기존 라벨을 추가한다.
- 생성 후 이슈를 다시 조회해 라벨 부착을 확인한다. 이슈 링크, 적용 라벨, 미확정·조회 실패·부착 실패 항목을 보고하며, 라벨이 없는 이슈를 완료로 보고하지 않는다.
- 라벨은 담당자의 수락, 설계·계약 승인, 작업 착수 또는 완료를 뜻하지 않는다.
- 기존 이슈를 갱신할 때는 기존 라벨을 보존하고 필요한 라벨만 추가한다.
