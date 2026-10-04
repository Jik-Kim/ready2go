# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-04

## 지금 상태
- **#9 완료** (PR #27 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01) 중 실행기 부분): `ready2go_runner/core/` 의 variables·conditions·validation·interpreter. sequence·if·set_var·on_failure·finally·timeout_sec, 실행 전 검사, E-stop·halt → `ABORTED`(retry·skip·safe_home 미적용, finally 는 비동작만), 중단 잠김 → `resume()` 전까지 거절, 내부 에러도 `INTERNAL_ERROR` 로 finally 보장. 원자 동작은 `execute(action, params, timeout_sec) → ActionResult` 로 위임.
- **#3 완료** (PR #40 머지 10/03, `Closes #3, #34`): `dev`·`real`(PC2)·`sim`(PC1) 기동, PC1↔PC2 컨테이너·호스트 송수신, PC2 `tf2_echo base_link wrist_cam_color_optical_frame` 확인(A·B). bringup 고정 TF(`static_tf.py`, NaN·무한대 거부), ros2-core `/colcon` 분리, MongoDB 7.0. sim 드라이버·에뮬레이터 버전 불일치는 P2(B).
- **#12 완료** (PR #64 E 머지 10/04 05:35Z, #46 과 함께 main 반영. E 리뷰의 halt·문서 수정은 후속 PR #67 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01)·[FR-LOG-01](../../docs/requirements.md#fr-log-01)·[NFR-DB-01](../../docs/requirements.md#nfr-db-01)).
  - 실행 이력: `core/log_records.py`·`core/logstore.py` — MongoDB `cobot2` `runs`·`steps`, DB 실패 시 그 실행 전체를 JSONL 로 폴백, 기록 실패에도 실행 계속(`log_errors`).
  - 스킬: 태스크 스텝 `skill`(스키마·예시 `task_skill_steps.json`), Runner 가 온톨로지(E) 상태를 들고 `pre` → `PRE_UNMET` / `expand`(`<id>.e<n>`) / `effect`. 실행 전 검사로 없는 스킬·composite·파라미터 이름 거절. E 의 `ontology.check`·`apply` 사용(E 코드 수정 없음).
  - 시험: 호스트 pytest 전체 통과(MongoDB 테스트는 건너뜀), ros2-core 컨테이너 + MongoDB 7.0 에서 건너뜀 없이 통과. 예시 태스크로 시계·지갑·미발견·비상정지·재실행 확인.
- **#10 mock 까지 구현, PR 준비** (브랜치 `feat/c-runner-node`, [FR-PLN-01](../../docs/requirements.md#fr-pln-01) "mock 환경에서 정상·실패 경로"). real 확인은 B 스킬 서버 이후.
  - `core/backend.py`(동작별 보낼 곳·JSON 변환), `core/ontology_query.py`(`query_ontology` 를 Runner 상태로 응답), `adapters/ros_clients.py`(Skill 액션·InspectRegion 클라이언트, 시간 초과 시 취소 요청), `nodes/mock_backend.py`, `nodes/runner_node.py`(`/runner/status`·`/robot_state`·`/runner/estop`).
  - 스킬 재시도는 로봇이 움직이지 않은 실패(`YAW_INVALID`)에만 (PR #65 합의, PM #10 요청). B 에 "백엔드 구현 약속"(취소 시 멈춤·`ESTOP`) 전달 (#10 코멘트·Slack 10/04).
  - CI: `contracts-and-core` 에 MongoDB 7.0 서비스·pymongo, `REQUIRE_MONGO=1` 이면 DB 없을 때 실패.

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
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ESTOP`·`HALTED`·`ACTION_FAILED`·`BACKEND_ERROR`·`INTERNAL_ERROR`, 스킬 `PRE_UNMET`·`UNKNOWN_SKILL`·`BAD_SKILL_PARAMS`(#12), `query_ontology` `UNKNOWN_ITEM`·`BAD_QUERY`·`NOT_SUPPORTED`(#10) | [문서] docs/runner.md 7.1 |
| 재인식 코드 | `YAW_INVALID` (모션 전 거절, 로봇 동작 없음), 태스크에서 재인식 1회 [팀 확정 필요] | [문서] B PR #66, PR #65 PM 정리 |
| dev 전체 흐름 | Runner 노드 → ROS → mock 백엔드로 예시 태스크 COMPLETED 약 4.5초, MongoDB `runs`·`steps` 14건, `/robot_state` 갱신 | [실측] 10/04 C 노트북 |
| PC1↔PC2 통신 | 공용 Wi-Fi `Rokey_A`, `cyclonedds.multi.xml`(멀티캐스트 끔). PC2 `joint_states` 100 Hz → PC1 86~96 Hz | [실측] A·B 10/03, PR #40 |

## 막힌 점 · 필요한 도움
- PM: Day 3 목록의 `while`·`for_each`·`push`·`pop`·"7.3 예시 mock 실행"은 requirements.md 기준 P2 → 만들지 않음, 확인 요청 (#10 코멘트 10/04).
- E: `query_ontology` 를 Runner 안에 둔 것 확인, 재개(`resume`) 통로 ICD 추가 협의.
- D: `/runner/status` 내용이 #59 에 충분한지.
- E 권고(10/04 PR #64, 새 설계 제안이며 합의 아님) → 후속:
  - `NOT_VISIBLE`: A 는 미발견 `success + target_found=false` 유지, E 가 `pick` 스킬에 미발견 분기·오류 의미 정의, C 가 Runner 에서 실행·기록. `VAR_UNDEFINED` 일괄 변환은 하지 않음. 실패 TTS 후속 확인.
  - `resume()`: P1 은 B 가 실물 확인·기준 상태 복구 → C 가 Runner 상태를 맞춘 뒤 재개하는 명시적 절차. 재개 서비스는 ICD 에 없어 E 협의 후 추가 (지금은 Runner 노드 재시작 = 잠김 해제·상태 초기화). 자동 검증·불일치 조정은 FR-ONT-02(P2)·FR-REC-01(P3).
  - `pre_check`·`state_diff`: P1 진단용 부가 기록으로 허용 (runner.md 7.4 에 구분 반영).
- B: 스킬 서버(`/skills/*`) — 취소 요청 시 멈춤, 비상정지 시 `ESTOP` (runner.md 7.1 "백엔드 구현 약속"). 서버가 나오면 PC2 에서 real 연결 확인(#10 완료 기준). `sim` 드라이버·에뮬레이터 버전 맞추기 (P2).
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] #10 PR 리뷰 → 머지 (`Refs #10`), B 스킬 서버가 나오면 PC2 에서 real 연결 확인 후 `Closes #10`
- [ ] #10 후속: 재개(`resume`) 서비스 ICD 협의(E), Docker 가 만든 root 소유 `logs/` 정리
- [ ] #17 (10/06): P1 시나리오 태스크(skill 스텝), `/voice/intent` → 태스크 실행, mock 성공·실패

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
- ~~MongoDB 8.0 (결정 #18)~~ → 커널 6.19+ 에서 기동 불가, 7.0 으로 변경 (이슈 #34, 10/03).
- ~~`places.yaml` 의 `tf` 블록이 있으면 값이 모두 채워져 있어야 한다~~ → 측정 전 null 블록(PR #28 형식)은 건너뛰도록 변경 (10/03).
- ~~C 노트북 호스트 `ROS_DOMAIN_ID=99`~~ → 팀 규칙 70 으로 변경 (`~/.bashrc`, 10/03). 99 에서는 컨테이너와 통신 안 됨 [실측].
