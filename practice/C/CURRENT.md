# CURRENT — C 이영훈

- **담당**: Runner · 플래너 · 로그 · 기술 통합 · **현재 Phase**: P2 (P1 통합 실험 10/08 종료)
- **최종 갱신**: 2026-10-12 — 날짜별 기록 [10/08](2026-10-08_practice.md) · [10/10](2026-10-10_practice.md) · [10/11](2026-10-11_practice.md) · [10/12](2026-10-12_practice.md)

## 지금 상태
- **상태 칸 W4 (10/13, #285 위 PR)**: `boot_id`·`seq`·`stamp`·`halt.resume` [실측: 호스트 749·임시 컨테이너 ROS 포함 766 passed]. 
- **recover (10/13, W4 PR 위 PR)**: B 조회 mock/none·`resumable` 기본 꺼짐 [실측: 호스트 753·임시 컨테이너 ROS 포함 772 passed]. 다음: 재개 질문·답(`resume_register`·`resume_answer`), B W1·W2 PR 오면 실제 조회 연결.
- **end_task 구현 (10/13, #271 위 쌓은 PR — #271 승인 뒤 머지)**: 다른 run·기동 거절, 지금 실행 종료 = 정지·잠금(해제 아님), 보존 작업 폐기, 같은 ID 재전송 [실측: 호스트 747·임시 컨테이너 ROS 포함 763 passed]. 다음: 상태 칸 W4 → recover → 재개 질문·답.
- **제어 인텐트 계약안 W3·W4 (10/13 PR, E 포함 2명 승인 대기)**: 종료·복구·재개 인텐트 5개 스키마·예시·문서. E 동의: P2 판정 범위(실물 재개 1 + "아니" 1 + 거절 1), 인텐트 이름. 다음: 승인 → Runner 구현(end_task 먼저, B 조회는 mock) → B W1·W2 → 실물.
- **10/12 2차 점검일 (Unpacking 실물, PC2 한 대)** [실측: PC2 DB]: 14:30 `5ca017`·16:21 `7b8141` 성공(A안 — 판 원래 자리가 립밤 위라 빈 자리 + 안내), 16:36 `cfa886` 판 원위치 1.7 mm(단 **사람이 립밤을 뺀 회차**), 15:11 `7d18c6`·16:33 `440324` **판을 쥔 채 정지**(놓을 자리 확인 전에 집음). 판정 A안 = **그 점검의 제한적 통과**(#239 E 리뷰, AC-ACT-03 완료 아님). main 반영: #231·#232·#233(Unpacking)·#239(진행표·mock 되돌리기). 자세히 [10/12 기록](2026-10-12_practice.md).
- **#121·#245 스킬 expand 블록 (10/13 #263 병합, E 대화 승인 10/13, 사용자 전달 — #263)**: expand 안 `fallback`(next_on 필수)·`if`, `fallback.next_on`, 넛지 뒤 다시 찍기 검사 [실측: 시험 8개, 기존 시험 그대로]. 다음: E `pick.jsonld` 전환 + C P1·Unpacking 회귀, B `next_on` 코드 확정.
- **`/runner/status` `halt` 계약 (10/13 #259 병합, E 대화 승인 10/13, 사용자 전달 — #259)**: 정지 요청과 실제 정지 확인 구분(`stop`: requested·confirmed·unconfirmed·none, `response_code`·`response_received_at`, `boot_id`·`run_id`·`event_id`) — E 10/12 P2 음성 안전 연결 요청 1번. 남은 C 몫: 잠금 해제(B 복구 확인 뒤만)·`recover`·`resume`·종료 인텐트 수신(계약), 10/13 PC2 음성 "멈춰" 실물 1회.
- **3차 챌린지 작업 2종 (10/13 E 선정, #256)**: `tasks/show_drawer.json`(서랍 안 보여주기)·`tasks/move_aside.json`(○○ 옆 빈 자리로 치우기) — JSON 만, Python 변경 없음. 최신 main(#250 포함) 위 [실측: mock] 보여주기·옮기기(차키·덮개 판)·빈 자리 없음(안 집음)·못 찾음 의도대로, `check_task` 통과, runner·knowledge 시험 678 passed. 실행은 `RUNNER_TASK_FILE`(새 인텐트 이름은 계약 변경). 실물은 10/13 [확인 목록](2026-10-13_pc2_checklist.md) 3절.
- **#242·#245 — PR #250 (B #241 머지 뒤 main 기준, B·D 리뷰 대기 · E 리뷰 문서 정정 반영, 코드·mock 검증 완료, PC2 실물 미확인 → 10/13 [확인 목록](2026-10-13_pc2_checklist.md) U2)**: 집기 전에 놓을 자리 판단(aside_1 → aside_2 → `free`, 셋 다 안 되면 안 집고 "꺼내지 못했어요"), 복구 전 원래 자리 → 꺼낸 자리 판단(헛동작·쥔 채 정지 없음), `check_only` 는 코드와 무관하게 움직이지 않음으로 셈, **이미 그 자세면 이동 안 보냄**(목표 `pick` 탑뷰 왕복 제거), 되돌리기 집기 `scan`, P2 `RUNNER_INTENT_TASKS` 안내 [실측: 호스트 2573 passed, 컨테이너 runner 697 passed].
- **#78 HALT_MOTION (10/10)**: `OBJECT_DROPPED`·`SENSOR_INVALID` → 즉시 ABORTED·잠금, finally 이동 없음, 재개 보존 안 함 [실측: 시험 4개, E 반례 그대로]. 남은 것: 복구 뒤 상태 맞추기·잠금 해제 절차(계약, B·E 협의), B `SENSOR_INVALID` 구분 PR, E 온톨로지 errors.
- **#187 음성 정지 후속 C 몫 (브랜치 `feat/c-unpack-task`)**: [C 수락](https://github.com/Jik-Kim/ready2go/issues/187#issuecomment-6056813537) — 빠른 정지는 `/runner/estop` 재사용 권고, 요청 처리 사이 "멈춰" → 시작 안 함(`StartGate`), 정지 기록 `halts[]` 항상 [실측: 호스트 1692·컨테이너 ROS 632 passed]. 선행: B 정지 확인 결과 형식(#152), E 수신 방식.
- **기록 누락 점검 `run_report --check` (FR-LOG-02 "DB 누락 확인", AC-LOG-01 증거, 브랜치 `feat/c-unpack-task`)**: [실측: 시험] 10/06 PC2 실물 기록 2건 빠짐없음, 일부러 망가뜨린 9가지 누락 모두 찾음, Runner 정상·거절·재개 기록 빠짐없음. PC2 DB 직접 점검은 10/08 저녁 연결 안 됨(PC2 꺼짐/IP 변경) → 다음 실물 때.
- **Unpacking 태스크 (10/11 실물 준비, 브랜치 `feat/c-unpack-task`, PR 전)**: `tasks/find_with_unpack.json` 재작성 + mock 겹친 장면 `MOCK_SCENE` [실측: 시험 7개 — 치우기 2개·막힌 자리·전달·역순 재식별 복구·되돌리기 두 번 막힘 → 쥔 채 정지(B·C 합의 #168)·비상정지·움직인 뒤 놓기 실패·장애물 3개 LOOP_LIMIT, 컨테이너 ROS 603 passed, mock 노드 장면 인식 확인]. **10/10**: main·#202 반영, mock 놓기가 B #191 과 같게(쥔 물체 id 가 scan 에 없으면 `BAD_PARAMS`), 치우던 중 놓침·센서 이상 → 즉시 정지·잠금 시험, 안내 문장은 쥠 여부를 단정하지 않게 [실측: 전체 1730 passed]. 남은 것: #191 병합(서랍 안 놓기·얹힌 물체 집기 `allow_stacked`), B 고정 자리 `aside_1`·`aside_2` 교시, A 가림 노드, `reid_tol_m` 실측, 음성 연결(`trigger`) 여부.
- **#134 문서 정본화 C 항목 (#180 인계 12~18)**: C 문서 정책 문장 → 정본 링크 19개(main 앵커 확인), 병합·미구현 상태 표시, 정본 3.3 대조로 `select_obstacle` ③ 후보를 확인된 것만으로 [실측: 시험]. 협의 항목(7·8·9·19~22·24·26·28·29·31)은 주 담당 수정 때 C 확인.
- **Unpacking 판단 원자 동작 계약안 (#120 치울 순서·#109 재식별, 승인 대기)**: `select_obstacle`·`find_moved` (`core/unpack.py`, 로봇 동작 없음), 예시 태스크 mock 끝까지 [실측: 시험 23개]. 남은 것: E 포함 2명 승인, `tol_m` B 놓기 실측, A 가림 필드 계약, 실물 `tasks/find_with_unpack.json`(10/10).
- **#152 재개 대기 core (PR #170 main 병합 10/08 `78de8ca`, 기본 꺼짐 — 계약 v0·v1 승인 대기, 노드·E 운영 연결 미구현)**: 계약안 v0([#152 댓글](https://github.com/Jik-Kim/ready2go/issues/152#issuecomment-6051650081), 승인 대기)의 Runner 안쪽 — 보존·재개·거절·버림. [실측: 시험 `test_suspend_resume.py` 18개, B #152 스킬별 재진입 조건 포함] 실제 find_item 으로 집기 중 비상정지 → 재개 시 집기부터·열기 재전송 없음·상태 1회 반영. 남은 것: 계약 승인 → 노드(`/runner/status` `halt`, 인텐트 `recover`·`resume`, `/skills/recover`), B 재진입 조건·관측 검사.
- **"움직이기 전 거부" 동작별 목록 (#168 C 표 후속 1번)**: `NO_MOTION_BY_ACTION` — `PLACE_BLOCKED` → 다른 고정 자리 fallback 가능 [실측: 시험 9개]. #168 B 노드 카드 "움직였나" 칸이 나오면 맞춤.
- **실패 스텝 결과 기록 (#166 D 리뷰 P1, B 요청)**: 실패 응답의 `output` 을 스텝 기록 `result` 에 남김(블랙보드 제외) [실측: 시험 3개]. B `place_object` 서랍 안 놓기 계약(#166) 소비 준비.
- **인식 실패 다시 찍기 (#168 C 표 1번)**: `find_item` s4 retry 1, 비동작 원자 동작은 TIMEOUT·늦은 결과도 재시도 [실측: 시험 6개]. 끌기·집기 안의 인식 실패는 그대로(앞서 팔이 움직임 → 재시도 없음).
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

- **실행 시작 전 그리퍼 관측** (`feat/c-status-contract`, 10/10·10/11): Runner 가 `/gripper/state`로 쥔 증거가 기억과 어긋나면 로봇 동작 없이 `STATE_MISMATCH`(#23). 10/11 #43 E Critical 반영 — `holding`/`gripping`(손잡이 7.9 mm)/`empty`(≤ 2 mm만 빈손 확정)/`released`, 관측은 막는 근거로만, 재개 값은 확정 빈손만. 서랍·물품 위치 관측은 P3(FR-REC-01).

- **#152 수명 분리** (`feat/c-status-contract`, 10/11): E 10/10 결정 6건(질문 등록·시간·수명 분리·작업 종료·독립 요청·녹음 증빙) core 반영 — 질문만 닫고 작업 보존, `end_task`, 독립 요청 10 s, 증빙 순서 2차 확인, status ACK 규칙(같은 seq 비교 아님). 노드·인텐트 wire 는 승인 뒤.

- **실행 기록 예시·운용값 YAML** (`feat/c-status-contract`, 10/11): `contracts/examples/execution_record.json`(구현된 기록 4건, 코드 대조 시험), `ready2go_runner/params/runner.yaml`(C 운용값 원본, core·노드가 읽음) — #196 소유표의 C 몫.

- **#152 답이 안 와도 C 가 닫음** (`feat/c-status-contract` `954ed61`, 10/11 E 검토 03): 기한 지난 질문·독립 요청이 status 에 남아 새 재개를 막던 것 → status 조회·등록·답 때마다 C 시계로 먼저 닫음, 늦은 답 `RESUME_EXPIRED`, 옛 ID 연장 없음 [실측: 시험 3개, ROS 703 passed].

- **Unpacking 실물 준비 10/11** (`feat/c-unpack-task`): 복구 오차 기록(되돌린 뒤 닫기 전 다시 찍어 원래 자리·지금 자리, `run_report` "복구 오차 (판정 아님)", AC-ACT-03), 가림 모름이면 같은 자세에서 한 번 다시 찍기(A #214 권고), **원래 자리 대신 빈 자리에 둔 물체 안내·기록**(목표 집기 실패 시 목표 위였던 장애물 — 놓기는 바닥에만, 실패 회차 판정 기준은 #196 E 확인 중), **음성으로 시작**(코드 수정 없이 `RUNNER_INTENT_TASKS=find_item=/tasks/find_with_unpack.json`, ROS 노드 mock 끝까지 성공 — 10/12 2차 점검용), 최신 main(#206·#214·#216·#220) 합침, `runner.md` 파지 높이·받침 설명 #206 에 맞춤(#134) [실측: 로컬 CI·ROS 컨테이너 시험]. 실물 결과는 10/11 오후.

- **계약07 요청 상관 C 합류** (E 공동 브랜치 `codex/e-c-request-run-contract-20261011` `bc7e0aa`, 10/11 사용자(E) 승인 E-C-REQUEST-RUN-WIRE-20261011-07): `runner_status.json`(새, `last_intent.request_id`·`run_id` 사례 5개)·`runner.md` 7.1 규칙 표·`interfaces.md` 5.3 C 구간·예시 검사 시험. Runner 구현은 계약 병합 뒤 운영 PR.

- **목표 5종 시험표** (PR #213, 10/11): E 선정 5종(E-150-GOAL-CATALOG-20261010-01) 계획·근거·mock 실행 뒤 상태, 이미 만족·계획 불가 별도 시험, 실물 범위 = Runner `plan_limits` 기본값 확인. #150 C 수락. 실물 10/12.

- **#43 트레이 place 사용자 확인** (`feat/c-tray-confirm` `5a11f88`, 10/11, E 승인08·09 C 몫): `verify_mode: enforce` — 다시 찍기·정상 미검출이면 `/runner/status` `confirm` 요청·E `confirm` 수신·최초 asked 부터 100 s·확인돼야 effect·`last.verify` 단계 결과, 서랍 열기 확인에 B `open_distance_m` [실측: 모의 21·ROS 노드 2]. 남은 것: E 답 2개·계약 PR·실물.

- **계약07 Runner 운영 — PR #249 (코드 작성·mock/ROS 시험 완료 / PR 미병합 / E 연결 미검증, 10/12)**: 계약 #221·E #225 머지 뒤 main 기준. `request_id` 기억(재전송·충돌, 동시 콜백에도 그 요청 자신의 결정), 수락 때 `run_id` 고정, `accept_text` 첫 안내 1회(`find_item`·`find_with_unpack`·목표형 계획, 실패면 **로봇 동작 0번** — finally 홈도 없음, #249 E 리뷰 P1·P2 반영) [실측: 호스트 8·ROS 노드 1]. 남은 것: #221 정리·병합 → 운영 PR.

- **실패 응답 결과 기록** (`feat/c-unpack-task` `1d677d9`): `to_result` 가 실패 응답 결과를 버려 실물 실패 근거(`placed_pose`·`hand`)가 기록에 없던 빈틈 수정, 집기 실패 `hand` 모름이면 정지.

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

## 막힌 점 · 필요한 도움 (10/12 기준)
- **B**: #250 리뷰. `reset_state` 와 같이 부를 B 정리 서비스(쥔 물체 기록·서랍 인출) — 생기면 연결(#242 C 회신). 10/13 PC2 #250 실물 확인(같은 배치).
- **E**: #249(계약07 운영) 리뷰 P1·P2 반영 중 — 수락 안내 실패면 로봇 동작 0번, 요청 기억 동시 콜백, Unpacking 태스크 수락 문장. E voice 쪽 연결(`request_run_enabled`·source mapper)은 아직 — 실제 연결은 미검증. #238 A/B안 선택, #245 같은 자세 생략 유지 여부, 10/13 챌린지 작업 2종 결정.
- **E + 1명**: `feat/c-status-contract`(#43·#152 C 몫 core, `runner.yaml`, 실행 기록 예시) 계약 승인 — 승인 전 PR·main 반영 안 함.
- **B**: 그리퍼 기준(`pick_min_width_m` 10 mm·`empty_max_width_m` 2 mm·`gripper_max_age_s` 0.5 s) 실측 확정, 무동작 안전 check·정지 확인 증빙(#152), 립밤 파지 확인(#150 5번), 서랍 place 뒤 top view 이동(#43).
- **A**: 실물 가림 출력 샘플(`occluded_by`·모름·재식별, #109), 트레이 `inspect_region(handover_zone)` 지원(#43 — 지금은 서랍 2곳만).
- **D**: 대시보드 초기화 버튼 → `/runner/reset_state`(#59), `basis_id`(코드 SHA·설정 버전) 받을 형식.
- 유지 중인 합의: B 스킬 서버 "백엔드 구현 약속"(runner.md 7.1, 10/04) — 취소 시 `MoveStop` 후 `canceled`(물건은 놓지 않음), 비상정지 `ESTOP`, 움직이기 전 거절 코드.

## 다음 할 일 (P2, 10/12 기준 — 진행 추적은 [#196](https://github.com/Jik-Kim/ready2go/issues/196))
**지금 (10/12 저녁~)**
- [x] #242·#245 PR — #250 (리뷰 중, `Refs #242` — 실물 확인 뒤 이슈 닫기)
- [x] 계약07 운영 PR — #249 / [ ] E 리뷰 P1·P2 반영
- [x] `runner.md` 7.3·태스크 설명 B #243 반영 / [ ] mock 도 물건 위 놓기
- [x] #196 C 항목 상태 댓글, #238 C 회신(A안 추천)
- [ ] 10/13 3차 챌린지 새 복합 작업 2종 JSON + mock 검증 (E 결정 뒤)

**10/11 에 적었던 것**
- [x] Unpacking 실물 시험 — 10/12 PC2 (위 "지금 상태", [10/12 기록](2026-10-12_practice.md))
- [x] 복구 오차를 위치·방향 둘 다 기록 — 없어서 추가함 (`ea8e161`, [AC-ACT-03](../../docs/requirements.md#ac-act-03))
- [x] Unpacking PR — #233 머지 10/12 11:36 / [ ] #196 결과 보고는 남음
- [x] 목표 5종 시험표 PR #213 + #150 수락 댓글 (10/11 12:39)

**10/12 에 못 한 것**
- [ ] 목표 5종 실물 ([AC-PLN-01](../../docs/requirements.md#ac-pln-01)) — 시작 상태 관측 확인, 실행 기록 `plan` 근거, 립밤은 B 확인 뒤 (10/12 은 Unpacking 만 돌림)

**E wire·승인 뒤**
- [x] 수락 TTS 게이트·`request_id` 중복 막기·`last_intent.run_id` — PR #249 (E 리뷰 반영, 머지·E 연결 대기)
- [ ] #152 노드 연결: `/runner/status` `halt.resume`, 질문 등록·답, 독립 재개, "종료" → `end_task`
- [ ] #43 노드 연결: 사후 검증으로 effect 막기, 확인 100 s·등록 5 s 를 `runner.yaml` 로
- [ ] `feat/c-status-contract` PR (E 포함 2명 승인 뒤)

**그 뒤 (P2 남은 것)**
- [ ] #78 놓침 뒤 잠금 해제·상태 맞추기 절차 (B·E 계약)
- [ ] #121 스킬 안 `if`·하위 스킬 호출 (#120 결정 뒤)
- [ ] 정지·실패 주입 정식 시험 기록 ([AC-SAF-01](../../docs/requirements.md#ac-saf-01)·[AC-SAF-02–04](../../docs/requirements.md#ac-saf-02)), 3회 연속 ([AC-DEMO-01](../../docs/requirements.md#ac-demo-01))
- [ ] 실행 기록 `code_sha`·설정 버전 (D `basis_id`, 계약)

## 철회한 결론
- ~~bringup 고정 TF 를 `config/static_tf.yaml` 한 파일로 모은다~~ → 값이 두 곳에 복사되어 어긋날 수 있어 각 담당 파일을 직접 읽기로 함 (이슈 #3, 10/02).
- ~~MongoDB 8.0 (결정 #18)~~ → 커널 6.19+ 에서 기동 불가, 7.0 으로 변경 (이슈 #34, 10/03).
- ~~`places.yaml` 의 `tf` 블록이 있으면 값이 모두 채워져 있어야 한다~~ → 측정 전 null 블록(PR #28 형식)은 건너뛰도록 변경 (10/03).
- ~~C 노트북 호스트 `ROS_DOMAIN_ID=99`~~ → 팀 규칙 70 으로 변경 (`~/.bashrc`, 10/03). 99 에서는 컨테이너와 통신 안 됨 [실측].
