## 무엇을 바꿨나
-

## Phase
- [ ] P1  - [ ] P2  - [ ] P3   관련 요구사항 ID: ______ (범위 밖 기능을 넣지 않았는지 `docs/requirements.md`의 해당 FR/NFR 항목으로 확인)

## 체크리스트
- [ ] 내 담당 패키지만 수정했다 (아니면 해당 담당 승인)
- [ ] 계약(`contracts/`, `ready2go_interfaces`, `docs/interfaces.md`)을 바꿨다면 스키마·예시·문서를 함께 고쳤고 승인 2명(조장 포함)을 받았다
- [ ] 확정되지 않은 값을 코드에 하드코딩하지 않았다
- [ ] 관련 검증 명령(`CLAUDE.md`)을 실행했다
- [ ] `practice/<담당>/CURRENT.md`를 갱신했다

## 근거
- 측정·판단 근거: [실측] / [문서] / [추정]
- 로컬 CI (`bash tools/dev/ci_local.sh <PR 번호>`, Actions 비활성화 기간): 마지막 결과 한 줄을 붙인다
