# contracts — JSON 계약

> 문서 설명: [`docs/runner.md`](../docs/runner.md), [`docs/voice_llm.md`](../docs/voice_llm.md), [`docs/interfaces.md`](../docs/interfaces.md)

| 파일 | 내용 | Phase |
| :--- | :--- | :--- |
| `task.schema.json` | 태스크(복합 스킬) JSON 스키마. `trigger.targets`(받을 물품 키 문자열 배열, 선택) 예시는 `tasks/p1_demo_eraser.json` (runner.md 7.1) | P1~ |
| `intent.schema.json` | 음성·LLM 인텐트 출력 (`/voice/intent`) | P1~ (`goals`·`query`는 P2) |
| `examples/execution_log.json` | 실행 로그 예시 (`pre_check`·`post_check`·`state_diff`는 P2) | P1~ |
| `examples/inspect_region_result.json` | `inspect_region` 결과 예시 (runner.md 7.1). `pose` = `{frame, position, yaw, yaw_valid}`: 박스 중심 x·y, z = 0, yaw (−π/2, π/2]는 확정(정의: runner.md 7.1, `config/places.yaml` 첫 부분). yaw 산출 방식(뎁스 덩어리 + `minAreaRect`)은 확정(vision.md V2), 대칭 물체 판정(`pose_rules.is_symmetric`, vision.md V2)은 확정. `yaw_valid`(bool)는 yaw를 믿어도 되는지(false이면 yaw = 0). `validate_contracts.py`가 이 예시의 z·yaw 범위·`yaw_valid`를 검사. **P2 추가 필드(계약 초안 #169, 승인 전)**: `occluded_by`(위에 얹힌 물체 id 목록, `[]` 없음, `null` 모름)·`visible_area_m2`(지금 보이는 마스크 넓이 m², `null` 모름) — 예시에 가려짐·없음·모름 세 경우. 검사(`pose_rules.result_errors`): 형식, 결과 안 id·자기 자신 아님·관계 비순환·같은 결과 안 id 유일·면적 0 이상 유한값·두 필드가 모든 물체에 있거나(분할 모델) 결과 전체에 없음(박스 모델). 필드 의미·보내는 쪽/받는 쪽 규칙(누락을 `null`로 바꾸지 않음)은 runner.md 7.1 | P1 (가림 필드 P2 초안) |
| `examples/task_unpack_select.json` | **P2 계약 #176 머지 10/08 (E 사후 검토 대기)** `select_obstacle`·`find_moved`를 쓰는 Unpacking 최소 흐름(치우기 → 고정 자리 놓기·막히면 다른 자리 → 전달 → finally 거꾸로 재식별·복구). `validate_contracts.py`가 스키마·실행 전 검사를 확인. `tol_m` 0.02 는 설명용 `[팀 확정 필요]`, 실물 태스크 아님 | P2 |
| `examples/intent_{recover,resume_register,resume_answer,resume_request,end_task}.json` | **계약안 W3 (#152, 이름 E 동의 10/13 — 필드 E 포함 2명 승인 전)**: 제어 인텐트별 필수 칸 예시. `validate_contracts.py`·`test_control_intent_schema.py` 가 스키마 통과·누락 거절을 검사. 처리는 runner.md 제어 인텐트 | P2 |
| `examples/task_fallback_next_on.json` | **계약 #121·#245 (E 대화 승인 10/13, 사용자 전달 — #263)**: `fallback.next_on` — 정한 오류 코드일 때만 다음 대안. 스킬 expand 안 fallback 은 필수(runner.md 7.5) | P2 |
| `examples/task_nudge_then_pick.json` | `nudge_object`를 쓰는 P1 태스크 예시(밀기 → 다시 인식 → 재판단 → 집기). `validate_contracts.py`가 스키마와 P1 범위를 검사 | P1 |
| `examples/nudge_object_result.json` | `nudge_object` 결과 예시 (runner.md 7.1): 끌어 옮김·끌 필요 없음·`check_only` 재판단 실패(`PUSH_LIMIT`)·끈 뒤 lift 실패. `target_after`는 끈 뒤 **예상** 위치(입력 `target`과 같은 형식, 재인식 아님), **성공일 때만** 채우고 실패면 `null`. `validate_contracts.py`가 이 규칙과 pose 규칙을 검사. 기존 `task_nudge_then_pick.json`은 재인식 정상 경로 예시로 그대로 둠(10/06 stub 시연은 `target_after`를 pick에 넘김) | P1 |
| `examples/inspect_region_handover_found.json`·`_not_found.json`·`_error.json` | `inspect_region(handover_zone)` 응답 세 가지 — 찾음 / 정상 미검출 / 관측 오류(`REGION_NOT_VISIBLE`) (#43, A 제안 10/11 `[팀 확정 필요]`, runner.md 7.1 "관측 결과 세 가지"). `result` 는 `result_json` 을 푼 것. `test_tray_observe.py` 가 `pose_rules.result_errors`·frame 을 검사 | P2 |
| `examples/place_object_result.json` | `place_object` 입력·결과 예시 (runner.md 7.1). **서랍 안 놓기는 #120 ② 계약안(B 제안, E 포함 2명 승인 전, P2)**: `location` 서랍 + `pose`(inspect_region pose 기준, `yaw_valid` 없음) 또는 `slot` + `scan`(`$scan`, 직전 인식 결과 전체 — `target`도 이웃으로 검사). `placed_pose`는 B가 명령한 자리(재인식 아님), 그리퍼를 연 뒤에만 채우고 움직이기 전 거부면 `null`. 이웃·벽 거부는 `PLACE_BLOCKED`·`WALL_TOO_CLOSE` + `blocked_by`. 트레이(`handover_zone`)는 현행 그대로. `validate_contracts.py`가 이 규칙을 검사 | P1(트레이)·P2(서랍 안) |
| `examples/pick_object_result.json` | `pick_object` 결과 예시 (runner.md 7.1). **PR #223 제안(B, C 확인·E 포함 2명 승인 전, P2)**: 기존 `grasp_ok`와 별도로 `hand`(`holding`/`empty`/`released`/`unknown`)·`grasp_evidence`. 빈손 확정 `empty`는 들어 올리다 폭이 2 mm 이하로 줄었을 때만(#43 결정 10), 실패 뒤 다시 벌림은 `released`. `validate_contracts.py`가 규칙을, B 노드 시험이 예시 = 실제 출력을 검사 | P2 |
| `examples/drawer_control_result.json` | `drawer_control` 결과 예시 (runner.md 7.1). **PR #223 제안(B, C 확인·E 포함 2명 승인 전, P2)**: 열기 `open_distance_m`(verify `drawer_displacement ≥ 0.9 × distance` 근거), 닫기 `close_remaining_m`·`close_pos_tol_m`·`close_push_interrupted`(`close_confirmed` 근거). `validate_contracts.py`가 규칙을 검사 | P2 |
| `skills_safe_state.schema.json` · `examples/skills_check_state.json` · `examples/skills_recover.json` | B 무동작 안전 상태 조회 W1 `/skills/check_state`·B 복구 W2 `/skills/recover` (`std_srvs/Trigger`) 응답 `message` JSON. **계약안 #297 머지 10/13**. W1 `success` = 조회 끝남(값이 좋은지와 무관), W2 `success` = `recovered`(C 잠금 해제·재개 허가와 별개). `drawers` 는 센서값이 아닌 B 서버의 인출 거리 기억(m), `external_force` 는 지속 외력 판정(멈춘 채 판정 창 동안 \|F\| 모두 문턱 초과면 true, 못 읽음·멈춤 아님 null — 값은 B `params/skills.yaml` `safe_state`, 근거 B 실측 10/13, 이 판정은 B 제안·E 포함 2명 승인 전), W2 는 true 면 `EXTERNAL_FORCE`·null 이면 `EXTERNAL_FORCE_UNKNOWN` 거절. 예시: 정상·비상정지·쥐었는지 모름 / 복구·거절(비상정지·`HOLD_UNCERTAIN`·`BUSY`) / 조회·서버 오류(상태 칸 없음). 검사는 B 시험(`test_safe_state.py` 스키마·칸 사이 규칙 `response_errors`(시험 파일 안, #374), `test_skill_server_node.py` 예시 = 노드 출력) — `validate_contracts.py` 연결은 아직 없음(도구 담당 요청). ICD 행·C 호출은 `docs/interfaces.md`(#304) | P2 |
| `examples/intent_find_item.json` | P1 인텐트 예시 | P1 |
| `examples/intent_goal.json` | 목표형 명령 인텐트 예시 | P2 |
| `examples/intent_find_list.json` · `examples/intent_find_class.json` | **P3 목록·분류 요청 (#302 계약안 — E 포함 2명 승인 전)**: `targets`(E 가 풀어 준 활성 물품 키, 1개 이상·중복 없음) + `semantic{source{kind=list|class, id, name_ko, sha256}, evidence}`(E `semantic_query` 결과 그대로 — 예시는 실제 `knowledge/examples/p3_semantics.ttl` 조회값). `validate_contracts.py` 가 스키마 통과를, `test_intent_router.py` 가 group 결정·보류를 검사. 처리는 runner.md 7.3 목록·분류 요청 | P3 |
| `examples/runner_status.json` | `/runner/status` 예시 (runner.md 7.1). **계약07(E-C-REQUEST-RUN-WIRE-20261011-07, 10/11 사용자 승인)**: 기존 칸 + `last_intent.request_id`·`run_id` — 수락 시 고정, 보류·거절은 `null`, 최종 결과는 `last.run_id` 로 대조. Runner 구현 전(운영 PR 별도). `test_runner_status_example.py` 가 기존 칸은 코드와 같은지, 새 칸 규칙을 검사. **`halt` 계약(E 대화 승인 10/13, 사용자 전달 — #259)**: 정지 요청과 실제 정지 확인 구분(`stop_*`·`halted_object_dropped` 사례), 같은 시험이 `Runner.halt_summary` 칸과 같은지 검사 | P2 |

## 규칙
- 계약을 바꾸면 스키마·예시·문서를 **같은 PR**에서 고치고 `python3 tools/validate_contracts.py`를 통과시킨다.
- 물품 키·장소 이름 enum은 런타임에 온톨로지(`knowledge/robot_ontology.jsonld`)에서 생성하므로 스키마에는 문자열로만 둔다.
- TODO(C 이영훈): 실행 로그·온톨로지 스키마(`log.schema.json`, `ontology.schema.json`) — Phase 2.

## 물품 목록 예시 갱신 (#8)

- 인텐트·태스크·로그·인식 예시의 제거된 `watch`·`wallet` 참조를 등록 물품으로 변경했다. 인텐트·태스크 스키마 구조와 ROS 메시지 필드는 유지한다.
- 물품 키는 `world.jsonld` 원본 또는 공통 로더에서 얻고, 인스턴스 ID는 비전이 제공한다. 예시 좌표·로그 성공 기록은 새 물품의 실물 검증 증빙이 아니다.
- 공유 계약·담당별 실행 인계는 `docs/interfaces.md` 5.1, 치수 축·단위는 `docs/ontology.md`를 따른다.
