# AGENTS.md — ready2go 공통 작업 규칙 (사람·AI 에이전트)

## 작업 시작
- 먼저 `docs/README.md`(인덱스)만 읽고, 작업에 필요한 문서만 연다. **문서 전체를 한 번에 읽지 않는다.**
- `docs/requirements.md`에서 작업에 연결된 요구사항 ID와 Phase를 확인하고, **그 Phase 범위 밖 기능은 만들지 않는다.** 별도 Phase 요약 문서는 기준으로 사용하지 않는다.
- 요구사항 문서 전체를 읽지 않는다. 작업 관련 ID를 먼저 찾아 해당 FR/NFR 항목과 연결된 완료 기준만 확인한다. 범위가 불명확하면 `requirements.md` 2장의 Phase 요약을 확인한다.
- JSON은 문서가 아니라 원본 파일(`contracts/`, `knowledge/`, `tasks/`)을 본다.
- `git status`로 작업 트리 상태를 확인한다. `docs/archive/`는 읽지 않는다.

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
- `main`은 PR로만 반영한다. 요청받지 않은 push·PR 생성은 하지 않는다.
- 작업이 끝나면 `practice/<담당>/CURRENT.md`를 갱신한다.
