# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- **#9 완료** (PR #27 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01) 중 실행기 부분): `ready2go_runner/core/` 의 variables·conditions·validation·interpreter. sequence·if·set_var·on_failure·finally·timeout_sec, 실행 전 검사, E-stop·halt → `ABORTED`(retry·skip·safe_home 미적용, finally 는 비동작만), 중단 잠김 → `resume()` 전까지 거절, 내부 에러도 `INTERNAL_ERROR` 로 finally 보장. 원자 동작은 `execute(action, params, timeout_sec) → ActionResult` 로 위임.
- **#3 진행 중** (Draft PR #40, 브랜치 `feat/c-compose-dds`, [FR-COM-02](../../docs/requirements.md#fr-com-02)·[NFR-ENV-01](../../docs/requirements.md#nfr-env-01)): `dev`(C)·`real`(PC2, B) 통과, PC1 `sim`·PC1↔PC2 통신 대기. 시험 방법은 이슈 #3 C 댓글.
  - bringup 고정 TF: `static_tf.py` 가 `calibration_meta.yaml` 의 `derived_tf`·`places.yaml` 의 `tf` 블록을 읽어 발행. 값이 null 이면 측정 전으로 건너뜀, 형식 오류면 launch 중단.
  - `dev` 5개 서비스 기동 수정: ros2-core 빌드 산출물 `/colcon` 분리(+ `entrypoint.sh`), dsr-emulator `tty`·`ROBOT_MODEL`, mock-sim `/config` 마운트.
  - MongoDB 8.0 → 7.0 (이슈 #34 E 승인): 커널 6.19+ 에서 8.0 기동 거부.
  - main(PR #28 DSR 드라이버 등) 병합, 충돌 해결 후 재빌드·기동 확인. CI 에 `pyyaml` 추가(bringup 테스트 import 실패 수정).
  - `docs/docker.md` 4.3: `real` 기동 전 호스트 DSR 드라이버·RealSense 종료 주의 (B 요청).
  - D 리뷰: `sim` 에서 DSR 드라이버가 `dsr-emulator` 에 붙지 않음 → 드라이버(DRCF v2)·에뮬레이터(v3) 버전 불일치로 멈춤 [실측]. P2 범위라 B 확인 후 별도 PR.

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
| `/gripper/state` `width` 단위 | m (열림 약 0.100) — B 제안에 C 동의, ICD 반영 예정 | [실측] B, PR #28 |
| P1 온톨로지 스킬 | 4종(열기·닫기·집기·놓기), 이동·관측은 Runner 원자 동작 | [문서] requirements.md FR-ONT-01 |
| 실행 이력 저장 | P1부터 MongoDB(실행 ID·입력 명령·단계 ID·시작 시각·상태·오류 코드), DB 장애 시 JSONL | [문서] requirements.md FR-LOG-01 |
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ESTOP`·`HALTED`·`ACTION_FAILED`·`BACKEND_ERROR`·`INTERNAL_ERROR` | [문서] docs/runner.md 7.1 |

## 막힌 점 · 필요한 도움
- A·B: **PC1 `sim` 기동**, **PC1↔PC2 송수신**(`DDS_MODE=multi`, 두 사람이 시간 합의), PC2 `tf2_echo base_link wrist_cam_color_optical_frame` (#3 완료 기준). 통신 시험 때 C 노트북으로 같이 수신 확인.
- E: #12 에 답한 **스킬 호출 방식(태스크 `skill` 스텝 → Runner 가 pre·expand·effect)** 최종 확인 → #12 착수 조건.
- B: 펜던트 비상정지 시 백엔드가 `ESTOP` 코드를 반환해야 Runner 가 `ABORTED` 로 처리 (PR #28 에 요청, #19·#10). `sim` 드라이버·에뮬레이터 버전 맞추기 (P2).
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] #3: PC1 `sim`·PC1↔PC2 통신 결과 정리 → PR #40 Ready → 머지 (`Closes #3, #34`)
- [ ] ICD `/gripper/state` `width` 단위(m) 추가 (계약 변경, 승인 2명)
- [ ] #12 (FR-PLN-01·FR-LOG-01): `skill` 스텝(스키마 변경 포함), `pre`/`effect`, MongoDB 실행 이력 + JSONL 폴백
- [ ] #10: mock 백엔드 + Skill 액션 클라이언트, `/runner/estop` → `Runner.halt()`, 재개 → `Runner.resume()` 연결(재개 서비스는 ICD 추가 필요), 백엔드 비상정지 시 `ESTOP` 반환

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
- ~~MongoDB 8.0 (결정 #18)~~ → 커널 6.19+ 에서 기동 불가, 7.0 으로 변경 (이슈 #34, 10/03).
- ~~`places.yaml` 의 `tf` 블록이 있으면 값이 모두 채워져 있어야 한다~~ → 측정 전 null 블록(PR #28 형식)은 건너뛰도록 변경 (10/03).
- ~~C 노트북 호스트 `ROS_DOMAIN_ID=99`~~ → 팀 규칙 70 으로 변경 (`~/.bashrc`, 10/03). 99 에서는 컨테이너와 통신 안 됨 [실측].
