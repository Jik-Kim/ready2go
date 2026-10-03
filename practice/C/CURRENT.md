# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- #9 Runner P1 구현 완료 ([FR-PLN-01](../../docs/requirements.md#fr-pln-01) 중 실행기 부분, PR #27 CI 통과): `core/variables.py`(`$경로`·`{{}}`·조사 필터), `core/conditions.py`, `core/validation.py`(실행 전 검사), `core/interpreter.py`(sequence·if·set_var·on_failure·finally·timeout_sec). core pytest 116개 통과. FR-PLN-01 의 `pre`/`effect` 는 #12, mock 정상·실패 경로는 #10 에서 채움.
- PR #27 리뷰(D) 반영: E-stop(`ESTOP`)·`halt()` → `ABORTED`, retry·skip·safe_home 미적용, `finally` 는 비동작만 실행.
- 자체 코드 리뷰 A~E 반영: 재시도·safe_home 직전 중단 확인, 중단 잠김 → `resume()` 전까지 새 태스크 거절.
- 2차 리뷰 반영: 중단 시 처음 멈춘 위치 유지, Runner 내부 에러도 `INTERNAL_ERROR` 스텝 실패로 처리해 `finally` 보장.
- Runner 는 원자 동작을 `execute(action, params, timeout_sec) → ActionResult` 로 위임 → #10 에서 ROS 액션 클라이언트·mock 백엔드를 이 자리에 연결.
- PR #25(요구사항 기준 문서) 머지로 C 의견 반영: P1 스킬 4종([FR-ONT-01](../../docs/requirements.md#fr-ont-01)), MongoDB P1부터([FR-LOG-01](../../docs/requirements.md#fr-log-01)). 이슈 #3 에 결정 #23·TF 설정 파일 형식 답변 → A·B 동의.

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 고정 TF 설정 파일 | bringup 이 `calibration_meta.yaml`의 `derived_tf`(A)·`places.yaml`(B·E)을 직접 읽음 | [문서] 이슈 #3 A·B 동의 10/02 |
| 손목 카메라 TF 부모 프레임 | `link_6` (접두어 없음), `base_link` | [실측] B 10/02, 이슈 #3 |
| P1 온톨로지 스킬 | 4종(열기·닫기·집기·놓기), 이동·관측은 Runner 원자 동작 | [문서] requirements.md FR-ONT-01 |
| 실행 이력 저장 | P1부터 MongoDB(실행 ID·입력 명령·단계 ID·시작 시각·상태·오류 코드), DB 장애 시 JSONL | [문서] requirements.md FR-LOG-01 |
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ESTOP`·`HALTED`·`ACTION_FAILED`·`BACKEND_ERROR`·`INTERNAL_ERROR` | [문서] docs/runner.md 7.1 |

## 막힌 점 · 필요한 도움
- E: **태스크 JSON 에서 스킬을 부르는 방식** 결정 → #12 `pre`/`effect` 확인 시점에 필요 (requirements.md 에도 미정).
- B·E: `places.yaml` 키 형식(이슈 #6) → bringup 서랍·트레이 TF 에 필요.
- E: 결정 #23 결정 로그 확정 승인 (main 기준 아직 "C 확인 대기").
- B: 펜던트 비상정지 시 백엔드가 `ESTOP` 코드를 반환해야 Runner 가 `ABORTED` 로 처리 (이슈 #19 확인 필요).
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] PR #27 (#9) 머지
- [ ] #3 (Day 1): 이미지 빌드·compose 기동·PC1↔PC2 DDS·CI, bringup `link_6 → wrist_cam_link` static TF
- [ ] #12 (FR-PLN-01·FR-LOG-01): 스킬 `pre`/`effect`(E 결정 후), MongoDB 실행 이력 + JSONL 폴백
- [ ] #10: mock 백엔드 + Skill 액션 클라이언트, `/runner/estop` → `Runner.halt()`, 재개 → `Runner.resume()` 연결(재개 서비스는 ICD 추가 필요), 백엔드 비상정지 시 `ESTOP` 반환

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
