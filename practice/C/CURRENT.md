# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- #9 Runner P1 구현 완료 (브랜치 `feat/c-runner-p1`): `core/variables.py`(`$경로`·`{{}}`·조사 필터), `core/conditions.py`, `core/validation.py`(실행 전 검사), `core/interpreter.py`(sequence·if·set_var·on_failure·finally·timeout_sec). core pytest 108개 통과.
- PR #27 리뷰(D) 반영: E-stop(`ESTOP`)·`halt()` → `ABORTED`, retry·skip·safe_home 미적용, `finally` 는 비동작만 실행.
- Runner 는 원자 동작을 `execute(action, params, timeout_sec) → ActionResult` 로 위임 → #10 에서 ROS 액션 클라이언트·mock 백엔드를 이 자리에 연결.
- PR #25 에 결정 #26(MongoDB P1)·#27(스킬 4종) 의견 제출, 이슈 #3 에 결정 #23·TF 설정 파일 형식 답변 → A·B 동의.

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 고정 TF 설정 파일 | bringup 이 `calibration_meta.yaml`의 `derived_tf`(A)·`places.yaml`(B·E)을 직접 읽음 | [문서] 이슈 #3 A·B 동의 10/02 |
| 손목 카메라 TF 부모 프레임 | `link_6` (접두어 없음), `base_link` | [실측] B 10/02, 이슈 #3 |
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ACTION_FAILED`·`BACKEND_ERROR` | [문서] docs/runner.md 7.1 |

## 막힌 점 · 필요한 도움
- E: #26(MongoDB P1)·#27(P1 스킬 4종) 승인, **태스크 JSON 에서 스킬을 부르는 방식** 결정 → #12 `pre`/`effect` 확인 시점에 필요.
- B·E: `places.yaml` 키 형식(이슈 #6) → bringup 서랍·트레이 TF 에 필요.
- E: 결정 #23 결정 로그 확정 승인.
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] PR #27 (#9) 리뷰 반영 후 머지
- [ ] #3 (Day 1): 이미지 빌드·compose 기동·PC1↔PC2 DDS·CI, bringup `link_6 → wrist_cam_link` static TF
- [ ] #12: 스킬 `pre`/`effect`(E 결정 후), JSONL 스텝 로그(+ #26 승인 시 MongoDB 폴백)
- [ ] #10: mock 백엔드 + Skill 액션 클라이언트, `/runner/estop` → `Runner.halt()` 연결, 백엔드 비상정지 시 `ESTOP` 반환

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
