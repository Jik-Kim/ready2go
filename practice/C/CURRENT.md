# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P2 (P1 통합 실험 10/08 종료)
- **최종 갱신**: 2026-10-08

## 지금 상태
- **#152 재개 대기 core (브랜치 `feat/c-runner-suspend-resume`, main 미반영)**: 계약안 v0([#152 댓글](https://github.com/Jik-Kim/ready2go/issues/152#issuecomment-6051650081), 승인 대기)의 Runner 안쪽 — 보존·재개·거절·버림. [실측: 시험 `test_suspend_resume.py` 18개, B #152 스킬별 재진입 조건 포함] 실제 find_item 으로 집기 중 비상정지 → 재개 시 집기부터·열기 재전송 없음·상태 1회 반영. 남은 것: 계약 승인 → 노드(`/runner/status` `halt`, 인텐트 `recover`·`resume`, `/skills/recover`), B 재진입 조건·관측 검사.
- **pick 제한 시간 70초 (#153 사용자·C 합의)**: `find_item` s5.1·`p1_demo_eraser` s3·플래너 `plan_timeouts` 의 `pick` 만 70초, 다른 단계 그대로 [실측: 시험 `test_pick_timeout_is_70s_and_other_steps_unchanged`]. 실물 pick 구간 시간은 미측정.
- **P2 제어 블록 (PR #159, [FR-ACT-04](../../docs/requirements.md#fr-act-04) Runner 쪽)**: `while`(max_iter·`LOOP_LIMIT`)·`for_each`(as 변수 루프 안에서만, 끝나면 복구)·`push`/`pop`(`restore_stack` LIFO 역순 복구)·`fallback`(앞 대안이 로봇을 움직이지 않았음이 확인된 실패일 때만 다음 대안, 아니면 `fallback_stopped`). 중단 뒤 finally 에서는 블록째 SKIPPED. 반복 회차 `iteration` 기록·보고서 `[s2.1 · 2회차]`(하위 동작은 seq 로 부모 연결). E 리뷰(10/08) P1 1·P2 2 반영 [실측: 모의 시험]. 남은 것: 실물 Unpacking 태스크는 #120(서랍 안 빈 자리·놓기)·#109(재식별) 결정 뒤 `tasks/find_with_unpack.json` 갱신, `recovery`·`on_halt`는 미구현(실행 전 거절).
- **P2 자동 스킬 플래너 (#150, FR-PLN-02)** — PR #151: `core/planner.py` BFS(깊이 8)·단계별 근거·이미 만족/계획 불가·연 서랍 자동 닫기·`to_task`(안전 finally). [실측: 시험] planner.md 7.7 예 순서·근거 일치, P1 전달 흐름 도출, 계획 → 태스크 → mock Runner 실행 뒤 명시 목표 유지. 리뷰 반영(D·E P1): 성공 뒤 finally 가 "열어 둬" 목표를 다시 닫던 것 → 끝나지 못했을 때만 정리, 실물 지원 범위(`limits`) 안에서만 계획. [문서: B `skill_server.py`] 실물 범위 = 서랍 `drawer_top`·서랍에서 집기·`handover_zone`에 놓기 → 서랍 간 이동·트레이 집기는 mock 에서만. 음성 연결 PR #154: `achieve_goal` → 현재 상태로 계획 → 실행(기록 헤더 `plan`), 이미 만족·계획 불가는 보류(안내 문장은 E 후속), Runner `plan_limits` 기본 = 실물 범위 [실측: ROS mock 시험 — 실물 기본에서 "립밤 아래 서랍에" 보류, "지우개 트레이에" 실행]. 남은 것: 실물 검증 10/12, 재계획(#43 뒤), B 와 실물 범위 확정.
- **P1 통합 실험 종료 (10/08)** [문서: #23 팀 결정·C 최종 결과 코멘트]: [실측: C PC2 MongoDB `cobot2` 읽기 전용 조회] PC2 실물 14건 중 **1회 성공** `2026-10-07T12:12:46Z_4315ef`(116.0 s, 녹음 끝 → 놓기 끝 95.3 s, 끌기 뒤 재인식 0.2 mm). 실패 13건은 Runner 밖(시작 절차 4·비전 4·B 스킬 5), Runner 는 14건 모두 재시도 없음·안전 종료·비상정지 뒤 로봇 동작 0건·기록 완전 [PC2 DB 확인]. [문서: requirements.md·#23 규칙] **미달**: 3회 연속(AC-DEMO-01), 비상정지·실패 주입 정식 시험(AC-SAF-01) → P2 준비로. 결과·기준 표는 #23 C 최종 결과 코멘트.
  - [문서: GitHub PR] 10/08 C PR: #145 mock 영상용, #147 Runner 스텝 진행 콘솔(#98), #148 오류 표 정합성(#134)·로그 위치(#98). 리뷰: E #144 Approve(실제 Runner 상태로 안내 정책 검증).
  - [문서: #23·#98·#138·#78·#134 코멘트] P2 로 넘긴 C 항목 (계획, 미착수 포함): `/runner/status` `run_id`·`error` 칸(실패 즉시 안내, #138, 계약 승인 필요), 실행 기록 `code_sha`(계약), Runner 콘솔 ↔ B 스킬 로그 실물 대조(#98), `OBJECT_DROPPED` 오류 표(#78, E·B 계약 뒤), `safety.md`·`interfaces.md` 구현/계획 구분(#134, D·E 공동).
  - [문서: #23 C 최종 결과·`docker.md` 4.3] 운용 수칙: 시작 전 서랍 닫힘, 회차 사이 원위치 → `/runner/reset_state`, 컨테이너 재생성 전 로그 수집(`docker.md` 4.3), PC2 DB 는 `run_report --uri mongodb://<PC2 IP>:27017` 로 다른 PC 에서 읽기 가능.
- **CI numpy (PR #90, #88 E 요청·D 리뷰 P1)**: `contracts-and-core` 에 `numpy>=1.24,<2` 설치(voice `setup.py` 와 같은 범위, skip 우회 없음). 목적: #88 음성 시험의 numpy import 수집 실패로 core 검사 전체가 멈추던 것. 검증: 깨끗한 venv(CI 설치 목록 + numpy)에서 #88 head `0336120` 806 passed·12 skipped(의도된 importorskip) [실측 10/06], #90 CI 3개 통과. 남은 확인: #90 머지 → #88 에 main 반영 → #88 최신 head CI 통과 (E 통합 완료 조건).
- **#9 완료** (PR #27 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01) 중 실행기 부분): `ready2go_runner/core/` 의 variables·conditions·validation·interpreter. sequence·if·set_var·on_failure·finally·timeout_sec, 실행 전 검사, E-stop·halt → `ABORTED`(retry·skip·safe_home 미적용, finally 는 비동작만), 중단 잠김 → `resume()` 전까지 거절, 내부 에러도 `INTERNAL_ERROR` 로 finally 보장. 원자 동작은 `execute(action, params, timeout_sec) → ActionResult` 로 위임.
- **#3 완료** (PR #40 머지 10/03, `Closes #3, #34`): `dev`·`real`(PC2)·`sim`(PC1) 기동, PC1↔PC2 컨테이너·호스트 송수신, PC2 `tf2_echo base_link wrist_cam_color_optical_frame` 확인(A·B). bringup 고정 TF(`static_tf.py`, NaN·무한대 거부), ros2-core `/colcon` 분리, MongoDB 7.0. sim 드라이버·에뮬레이터 버전 불일치는 P2(B).
- **#12 완료** (PR #64 E 머지 10/04 05:35Z, #46 과 함께 main 반영. E 리뷰의 halt·문서 수정은 후속 PR #67 머지, [FR-PLN-01](../../docs/requirements.md#fr-pln-01)·[FR-LOG-01](../../docs/requirements.md#fr-log-01)·[NFR-DB-01](../../docs/requirements.md#nfr-db-01)).
  - 실행 이력: `core/log_records.py`·`core/logstore.py` — MongoDB `cobot2` `runs`·`steps`, DB 실패 시 그 실행 전체를 JSONL 로 폴백, 기록 실패에도 실행 계속(`log_errors`).
  - 스킬: 태스크 스텝 `skill`(스키마·예시 `task_skill_steps.json`), Runner 가 온톨로지(E) 상태를 들고 `pre` → `PRE_UNMET` / `expand`(`<id>.e<n>`) / `effect`. 실행 전 검사로 없는 스킬·composite·파라미터 이름 거절. E 의 `ontology.check`·`apply` 사용(E 코드 수정 없음).
  - 시험: 호스트 pytest 전체 통과(MongoDB 테스트는 건너뜀), ros2-core 컨테이너 + MongoDB 7.0 에서 건너뜀 없이 통과. 예시 태스크로 시계·지갑·미발견·비상정지·재실행 확인.
- **#10 main 머지** (PR #74 10/06 10:41, D·E 재검토 "P1 해결"·PM 동의. 실물 연결 확인 대기 → `Closes #10`) ( [FR-PLN-01](../../docs/requirements.md#fr-pln-01) "mock 환경에서 정상·실패 경로"). real 확인은 B 스킬 서버 이후.
  - `core/backend.py`(동작별 보낼 곳·JSON 변환), `core/ontology_query.py`(`query_ontology` 를 Runner 상태로 응답), `adapters/ros_clients.py`(Skill 액션·InspectRegion 클라이언트, 시간 초과 시 취소 요청), `nodes/mock_backend.py`, `nodes/runner_node.py`(`/runner/status`·`/robot_state`·`/runner/estop`).
  - 스킬 재시도는 로봇이 움직이지 않은 실패(`YAW_INVALID`)에만 (PR #65 합의, PM #10 요청). B 에 "백엔드 구현 약속"(취소 시 멈춤·`ESTOP`) 전달 (#10 코멘트·Slack 10/04).
  - CI: `contracts-and-core` 에 MongoDB 7.0 서비스·pymongo, `REQUIRE_MONGO=1` 이면 DB 없을 때 실패.

- **#17 태스크 머지** (PR #82 10/06 13:55): `tasks/find_item.json`(정식, speak·미발견 안내 포함)·`tasks/p1_demo_eraser.json`(#22 점검용, speak 없음, E 시연 `pick_demo` PR #85 와 실행 조합). mock 정상·파지 실패·미발견·안전 코드 5종 확인.
- **#17 `/voice/intent` 연결 진행** (브랜치 `feat/c-voice-intent`, E 통합 공지 #23 C 요청): `core/intent_router.py`(ROS 비의존 판단) + Runner 노드 구독. `trigger.intent`·`intent_tasks`(10/08 시연 find_item → `p1_demo_eraser`)로 태스크 선택, 보류(형식·모호·미지원·저신뢰·미등록 물품)·거절(실행 중·잠김)·`cancel` → `halt()`·`status` 재발행, `inputs` 에 음성 입력 기록, `/runner/status` `last_intent`. 시험 중 찾은 빈틈: `target_after: null` 이면 pick 을 보내던 것 → `VAR_NULL` 로 막음. PM·D 리뷰 P1(10/06 20:57): 시연 덮어쓰기에서 "차키 찾아줘"도 지우개 태스크로 서랍을 열던 것 → 태스크 `trigger.targets` 로 받을 물품 제한, 다르면 `UNSUPPORTED_ITEM` 보류. D 재검토 P1(10/07 10:48): 스키마에 `targets` 형식이 없어 문자열 `"car_key_eraser"`도 통과 → `task.schema.json`에 문자열 배열로 선언, Runner 도 배열이 아니면 보류. 10/07 E 음성 노드(text_override) ↔ Runner mock 연결 확인: 실행·보류·BUSY·cancel→ABORTED·LOCKED 기대대로 [실측]. 발견: Runner 를 켜 둔 채 두 번째 요청이면 지우개 위치를 `handover_zone`으로 기억해 트레이를 서랍처럼 다룸 → 10/08 은 시연마다 Runner 재시작, 근본 대책은 E·PM 협의. 남은 것: E 음성 노드와 mock 연결 확인(10/07), E 합의(`min_confidence`, 보류·cancel·status 안내 담당, 시연 태스크 speak).

- **실행 기록 보고서** (브랜치 `feat/c-run-report`, 10/07): MongoDB 기록이 사람이 읽기 어렵다는 문제(사용자) → `ros2 run ready2go_runner run_report`로 최근 실행을 한국어 요약·Markdown 표로. #23 C 항목 "MongoDB/JSONL 조회", 10/08 결과 보고에 사용.

- **상태 초기화 서비스** (PR #107, 10/07): `/runner/reset_state` — 사람이 원위치 확인 후 호출(팀 결정, 나중에 대시보드 버튼 #59). 자동 초기화 안은 D P1(놓기 실패 뒤 쥔 상태를 덮어씀)로 철회. 시연 사이 초기화 → 3회 연속 COMPLETED, 놓기 실패 뒤 다음 요청 로봇 동작 0건, 실행 중 거절 [실측·시험]. 10/08: 시연 사이 원위치 → `ros2 service call /runner/reset_state std_srvs/srv/Trigger`.
- **real 기동에 스킬 서버** (PR #108, 10/07): `--profile real up` 한 번으로 드라이버·그리퍼·스킬 서버·Runner(NFR-ENV-01, 사용자 결정: 로봇 기능은 컨테이너에). D P1(서버 준비 전 요청) → Runner `NOT_READY` 거절. 속도 기본 60·40(B 호스트와 같음)
- **닫기 성공 안내** (#138 C, PR #140, 10/07): `tasks/find_item.json` finally — `f1d`·`f2d`로 닫기 전·후 `open.<서랍>`을 조회해 이번 실행에서 열림 → 닫힘일 때만 `f2s.1` "서랍을 닫았어요"(닫기 → 안내 → 홈). 처음부터 닫힘·닫기 실패/skip/`PRE_UNMET`·비상정지/취소는 안내 없음. 새 단계는 모두 `on_failure: skip`, 안내는 `timeout_sec` 20(음성 노드 무응답에도 홈이 막히지 않게, PM 리뷰). 시험 11개(정상 순서·집기 실패 후 닫음·닫기 실패·PRE_UNMET·비상정지 3곳·취소·TTS 실패·무응답 TIMEOUT·조회 실패·쥔 채 정지), mock 스택 실제 실행으로 순서 확인 [실측]. 남은 것: PC2 `logs/voice_eval/voice.local.yaml`의 `tts_engine`·`tts_melotts_speed` 확인, E 사전 캐시 뒤 PC2 실행 기록에서 닫기 → 안내 → 홈 구간 시간, E 중단·오류 안내와 순서(닫았어요 → 실패 원인) 맞추기.
- **P1 실물 1회차 성공** (10/07 21:12 KST, PC2 `2026-10-07T12:12:46Z_4315ef`, main `55829e3`): 음성 → 열기 → 탑뷰 → 촬영 → 끌기 40.1 mm → 다시 촬영(예상과 0.2 mm) → 집기 → 놓기 → 닫기 → 홈, 116.0 s. 녹음 끝 → 놓기 끝 95.3 s, pick 41.0 s [실측 DB]. 같은 날 실패 7건은 Runner 밖(서랍 열린 채 시작 3·비전 `DEPTH_INVALID` 3·B 스킬 2). 남은 것: 3회 연속(AC-DEMO-01), 비상정지 정식 시험.

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
| Runner 에러 코드 | `TASK_INVALID`·`VAR_UNDEFINED`·`BAD_FILTER`·`BAD_CONDITION`·`TIMEOUT`·`ESTOP`·`HALTED`·`ACTION_FAILED`·`BACKEND_ERROR`·`INTERNAL_ERROR`, 스킬 `PRE_UNMET`·`UNKNOWN_SKILL`·`BAD_SKILL_PARAMS`(#12), `query_ontology` `UNKNOWN_ITEM`·`BAD_QUERY`·`NOT_SUPPORTED`(#10), `VAR_NULL`(#23) | [문서] docs/runner.md 7.1 |
| 재인식 코드 | `YAW_INVALID` (모션 전 거절, 로봇 동작 없음), 태스크에서 재인식 1회 [팀 확정 필요] | [문서] B PR #66, PR #65 PM 정리 |
| dev 전체 흐름 | Runner 노드 → ROS → mock 백엔드로 예시 태스크 COMPLETED 약 4.5초, MongoDB `runs`·`steps` 14건, `/robot_state` 갱신 | [실측] 10/04 C 노트북 |
| PC1↔PC2 통신 | 공용 Wi-Fi `Rokey_A`, `cyclonedds.multi.xml`(멀티캐스트 끔). PC2 `joint_states` 100 Hz → PC1 86~96 Hz | [실측] A·B 10/03, PR #40 |

## 막힌 점 · 필요한 도움
- PM: Day 3 목록의 `while`·`for_each`·`push`·`pop`·"7.3 예시 mock 실행"은 requirements.md 기준 P2 → 만들지 않음, 확인 요청 (#10 코멘트 10/04). → 10/08 P2 시작, PR #159 로 구현.
- E: `query_ontology` 를 Runner 안에 둔 것 확인, 재개(`resume`) 통로 ICD 추가 협의.
- D: `/runner/status` 내용이 #59 에 충분한지.
- E 권고(10/04 PR #64, 새 설계 제안이며 합의 아님) → 후속:
  - `NOT_VISIBLE`: A 는 미발견 `success + target_found=false` 유지, E 가 `pick` 스킬에 미발견 분기·오류 의미 정의, C 가 Runner 에서 실행·기록. `VAR_UNDEFINED` 일괄 변환은 하지 않음. 실패 TTS 후속 확인.
  - `resume()`: P1 은 B 가 실물 확인·기준 상태 복구 → C 가 Runner 상태를 맞춘 뒤 재개하는 명시적 절차. 재개 서비스는 ICD 에 없어 E 협의 후 추가 (지금은 Runner 노드 재시작 = 잠김 해제·상태 초기화). 자동 검증·불일치 조정은 FR-ONT-02(P2)·FR-REC-01(P3).
  - `pre_check`·`state_diff`: P1 진단용 부가 기록으로 허용 (runner.md 7.4 에 구분 반영).
- B: 스킬 서버(`/skills/*`) — runner.md 7.1 "백엔드 구현 약속" 동의(Slack 10/04): 취소 시 `MoveStop` 후 `canceled`(물건은 놓지 않음), 비상정지·안전정지 `ESTOP`, 움직이기 전 `TOOL_NOT_SET`(재시도 대상 아님). **10/06 오전 PC2 에서 real 연결 확인**(#10 완료 기준). `sim` 드라이버·에뮬레이터 버전 맞추기 (P2).
- B (#17 때): `finally` 서랍 닫기 실패 시 홈 복귀 여부(`on_failure` skip/abort).

## 다음 할 일
- [ ] #10 PC2 real 연결 확인(`home` → `drawer_approach` → `home`, B) → `Closes #10`
- [ ] #22 1차 점검 (10/06 16:00 KST, B 실행·D 비상정지): `tasks/p1_demo_eraser.json`, MongoDB 스텝 기록 누락 0 확인 (AC-LOG-01)
- [ ] 점검 뒤: 스킬 서버 bringup 자동 실행(NFR-ENV-01, B·C), B 잠금 코드 runner.md 확정, 놓기 실패로 쥔 경우 안전 종료·홈 이동 조건(B·C·E)
- [ ] #10 후속: 재개(`resume`) 서비스 ICD 협의(E), Docker 가 만든 root 소유 `logs/` 정리
- [ ] #17: `/voice/intent` 연결 PR → 리뷰·머지 → E 음성 노드와 mock 확인(10/07) → `Closes #17`
- [ ] #23: 10/07 작업 종료 전 C 회신(수락·준비 상태·로봇 시간·막힌 것), 10/08 16:00 P1 음성 통합

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
- ~~MongoDB 8.0 (결정 #18)~~ → 커널 6.19+ 에서 기동 불가, 7.0 으로 변경 (이슈 #34, 10/03).
- ~~`places.yaml` 의 `tf` 블록이 있으면 값이 모두 채워져 있어야 한다~~ → 측정 전 null 블록(PR #28 형식)은 건너뛰도록 변경 (10/03).
- ~~C 노트북 호스트 `ROS_DOMAIN_ID=99`~~ → 팀 규칙 70 으로 변경 (`~/.bashrc`, 10/03). 99 에서는 컨테이너와 통신 안 됨 [실측].
