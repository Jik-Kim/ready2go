# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-04

## 지금 상태
- **#9 완료** (PR #27 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01) 중 실행기 부분): `ready2go_runner/core/` 의 variables·conditions·validation·interpreter. sequence·if·set_var·on_failure·finally·timeout_sec, 실행 전 검사, E-stop·halt → `ABORTED`(retry·skip·safe_home 미적용, finally 는 비동작만), 중단 잠김 → `resume()` 전까지 거절, 내부 에러도 `INTERNAL_ERROR` 로 finally 보장. 원자 동작은 `execute(action, params, timeout_sec) → ActionResult` 로 위임.
- **#3 완료** (PR #40 머지 10/03, `Closes #3, #34`): `dev`·`real`(PC2)·`sim`(PC1) 기동, PC1↔PC2 컨테이너·호스트 송수신, PC2 `tf2_echo base_link wrist_cam_color_optical_frame` 확인(A·B). bringup 고정 TF(`static_tf.py`, NaN·무한대 거부), ros2-core `/colcon` 분리, MongoDB 7.0. sim 드라이버·에뮬레이터 버전 불일치는 P2(B).
- **#12 완료** (PR #64 E 머지 10/04 05:35Z, #46 과 함께 main 반영. 후속 PR: E 리뷰의 halt·문서 수정, 브랜치 `fix/c-runner-halt-effect`, [FR-PLN-01](../../docs/requirements.md#fr-pln-01)·[FR-LOG-01](../../docs/requirements.md#fr-log-01)·[NFR-DB-01](../../docs/requirements.md#nfr-db-01)).
  - 실행 이력: `core/log_records.py`·`core/logstore.py` — MongoDB `cobot2` `runs`·`steps`, DB 실패 시 그 실행 전체를 JSONL 로 폴백, 기록 실패에도 실행 계속(`log_errors`).
  - 스킬: 태스크 스텝 `skill`(스키마·예시 `task_skill_steps.json`), Runner 가 온톨로지(E) 상태를 들고 `pre` → `PRE_UNMET` / `expand`(`<id>.e<n>`) / `effect`. 실행 전 검사로 없는 스킬·composite·파라미터 이름 거절. E 의 `ontology.check`·`apply` 사용(E 코드 수정 없음).
  - 시험: 호스트 pytest 전체 통과(MongoDB 테스트는 건너뜀), ros2-core 컨테이너 + MongoDB 7.0 에서 건너뜀 없이 통과. 예시 태스크로 시계·지갑·미발견·비상정지·재실행 확인.

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 고정 TF 설정 파일 | bringup 이 `calibration_meta.yaml`의 `derived_tf`(A)·`places.yaml`의 `tf` 블록(B·E)을 직접 읽음 | [문서] 이슈 #3·#6, 결정 #23 확정 |
| TF 부모 프레임 | `link_6`·`base_link` (접두어 없음) | [실측] B 10/02, 이슈 #3 |
| 손목 카메라 TF | `link_6 → wrist_cam_link` 발행, `tf2_echo` 값이 `derived_tf` 와 일치 (좌표계 연결 확인이며 위치 정확도는 #7 5점 검증) | [실측] 10/03 호스트·컨테이너 |
| `dev` 통신 | Domain 70·`cyclonedds.local.xml`: 컨테이너↔컨테이너, 컨테이너↔호스트 송수신 | [실측] 10/03 C 노트북 |
| MongoDB | 7.0 (`mongo:7.0`, 7.0.43 기동 확인). 8.0 은 커널 6.19+ 에서 기동 거부, 팀 PC 3대 커널 7.0.0-34 | [실측] 10/03, 이슈 #34 |
| `ros2-core` 이미지 | DSR 드라이버 포함 빌드 5분 4초, 3.23 GB | [실측] 10/03 C 노트북 |
| PC2 `real` 기동 | 5개 서비스 Up, DSR 드라이버 실물 접속·컨트롤러 활성화, vision CUDA(RTX 4060), 카메라 30 Hz, db 7.0, `tf2_echo base_link wrist_cam_link` 수신 | [실측] B 10/03, PR #40 코멘트 |
| `/gripper/state` `width` 단위 | m (열림 약 0.100). ICD 반영(#12 PR), B `grasp_check.py` 도 m | [실측] B, PR #28 |
| P1 온톨로지 스킬 | 4종(열기·닫기·집기·놓기), 이동·관측은 Runner 원자 동작 | [문서] requirements.md FR-ONT-01 |
| 실행 이력 저장 | P1부터 MongoDB(실행 ID·입력 명령·단계 ID·시작 시각·상태·오류 코드), DB 장애 시 JSONL | [문서] requirements.md FR-LOG-01 |
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ESTOP`·`HALTED`·`ACTION_FAILED`·`BACKEND_ERROR`·`INTERNAL_ERROR`, 스킬 `PRE_UNMET`·`UNKNOWN_SKILL`·`BAD_SKILL_PARAMS`(#12) | [문서] docs/runner.md 7.1 |
| PC1↔PC2 통신 | 공용 Wi-Fi `Rokey_A`, `cyclonedds.multi.xml`(멀티캐스트 끔). PC2 `joint_states` 100 Hz → PC1 86~96 Hz | [실측] A·B 10/03, PR #40 |

## 막힌 점 · 필요한 도움
- E: #12 후속 PR 리뷰 — PR #64 의 Request changes(마지막 동작 중 halt → effect 반영, Phase 문구)를 고쳤으나 수정 전 커밋으로 머지되어 후속 PR 로 올림.
- E 권고(10/04 PR #64, 새 설계 제안이며 합의 아님) → 후속:
  - `NOT_VISIBLE`: A 는 미발견 `success + target_found=false` 유지, E 가 `pick` 스킬에 미발견 분기·오류 의미 정의, C 가 Runner 에서 실행·기록. `VAR_UNDEFINED` 일괄 변환은 하지 않음. 실패 TTS 후속 확인.
  - `resume()`: P1 은 B 가 실물 확인·기준 상태 복구 → C 가 Runner 상태를 맞춘 뒤 재개하는 명시적 절차 (#10 재개 서비스·상태 설정). 자동 검증·불일치 조정은 FR-ONT-02(P2)·FR-REC-01(P3).
  - `pre_check`·`state_diff`: P1 진단용 부가 기록으로 허용 (runner.md 7.4 에 구분 반영).
- B·C (PR #65): `yaw_valid=false` → B 가 모션 전 차단·`YAW_INVALID`(가칭), 재인식 1회 [팀 확정 필요], 누락은 false. C 는 "동작 없이 차단된 실패"만 스킬 재시도 허용 (#10/#17).
- B: 펜던트 비상정지 시 백엔드가 `ESTOP` 코드를 반환해야 Runner 가 `ABORTED` 로 처리 (#19·#10). `sim` 드라이버·에뮬레이터 버전 맞추기 (P2).
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] #12 후속 PR (halt·effect 경계, Phase 문구) 리뷰 → 머지
- [ ] #10: mock 백엔드 + Skill 액션 클라이언트, `/runner/estop` → `Runner.halt()`, 재개 → `Runner.resume()` 연결(재개 서비스는 ICD 추가 필요), 백엔드 비상정지 시 `ESTOP` 반환, 온톨로지 파일 로딩(#46 머지 후 `snapshots/initial_state.json`)·`/robot_state` 발행, 재개 절차(상태 맞춘 뒤 `resume()`), CI 에 MongoDB 테스트, Docker 가 만든 root 소유 `logs/` 정리

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
- ~~MongoDB 8.0 (결정 #18)~~ → 커널 6.19+ 에서 기동 불가, 7.0 으로 변경 (이슈 #34, 10/03).
- ~~`places.yaml` 의 `tf` 블록이 있으면 값이 모두 채워져 있어야 한다~~ → 측정 전 null 블록(PR #28 형식)은 건너뛰도록 변경 (10/03).
- ~~C 노트북 호스트 `ROS_DOMAIN_ID=99`~~ → 팀 규칙 70 으로 변경 (`~/.bashrc`, 10/03). 99 에서는 컨테이너와 통신 안 됨 [실측].
