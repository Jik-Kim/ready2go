# Runner · 원자 동작 · JSON 규격 · 실행 로그

> 아래 내용은 requirements.md의 요구사항에 따른 설계·계약 설명입니다. 문서의 존재나 현재형 표현만으로 구현 완료를 의미하지 않으며, Phase·완료 기준은 requirements.md를 따릅니다. 실제 연결 여부는 담당 코드와 작업 기록에서 확인합니다. [문서]

> 관련 요구사항: [FR-PLN-01](requirements.md#fr-pln-01), [FR-ONT-01–02](requirements.md#fr-ont-01), [FR-LOG-01–02](requirements.md#fr-log-01). Runner 동작·JSON 형식·로그 상세는 이 문서에서 다룹니다.

## 7. 로봇 온톨로지 및 JSON 규격 (강사 챌린지 핵심)

> **강사 챌린지**: "로봇의 움직임, 상태 등을 JSON(온톨로지)으로 다 만들고, 명령을 내리면 그 조합으로 다양한 행동을 할 수 있도록 한다. 로봇의 세부 동작 및 성공 여부까지 로그로 남긴다."

| 챌린지 요소 | 이 장의 구성 |
| :--- | :--- |
| 로봇의 **움직임** | 7.1 원자 동작 규격 + 7.5 스킬 정의(조건·결과·원자 동작 전개) |
| 로봇의 **상태** | 7.5 `state` + 7.8 상태 추적 규칙 |
| 명령 → **조합**으로 다양한 행동 | 7.7 플래너(스킬 자동 조합) + 7.2·7.3 제어 블록 JSON(탐색형 작업) + 7.6 스킬 추가 |
| **세부 동작·성공 여부 로그** | 7.4 실행 로그(성공 여부·조건 확인·상태 변화) + DB 저장 |

### 7.1 원자 동작(Primitive Action) 정의 규격

**동작 이름과 파라미터 명은 본 표를 단일 기준(Single Source of Truth)으로 하고, 코드/일정/예시 전체에서 그대로 사용합니다.**

**① 로봇/인식 동작**

| 동작명 (`action`) | 주요 파라미터 (`params`) | 반환값 (`output`으로 저장 가능) | 설명 |
| :--- | :--- | :--- | :--- |
| `move_to_named_pose` | `pose_name`: `"home"`, `"drawer_approach"`, `"drawer_top_view"`, `"tray_view"` / `drawer_id`(서랍 관련 포즈일 때) | - | 사전 정의된 로봇 관절 포즈로 이동 |
| `drawer_control` | `drawer_id`, `state`: `"open"`/`"close"`, `distance`(선택, 기본 = `max_travel_m`) | `{drawer_displacement, close_confirmed}` | 손잡이 파지 및 슬라이딩 개폐 (real: 컴플라이언스 인출, **닫힘 = 닫힘 위치 도달 AND 미는 축 힘 임계 초과**, 8.4 / sim: 조인트 직접 구동 폴백) |
| `inspect_region` | `region`: 서랍 ID, `"staging_tray"`, `"handover_zone"`, `search_target`(클래스명, 선택) | `{target_found, target, candidates[], visible_count}` | 검출 + 3D 위치 + 가림 순서. `target`은 `{id, class, pose, top_z}` 또는 `null`, `candidates`는 목표를 제외한 물체를 **위에 있는 순서(서랍 좌표계 `top_z` 내림차순)**로 정렬. `pose`는 서랍 좌표계(원점 = 상자 안쪽 바닥 앞쪽 오른쪽 모서리, x 안쪽·y 왼쪽·z 위, 정의는 `config/places.yaml` 첫 부분·#6). **`position` = YOLO 박스 중심의 x·y, z는 항상 0**(높이는 `top_z`에만 둔다). **`yaw` = 물체 긴 변 방향**(서랍 x축 기준 rad), 범위 **(−π/2, π/2]**(긴 변은 180° 돌려도 같은 직선이라 한 범위로 고정, `ready2go_vision.core.pose_rules`), 위에서 본 모양이 정사각형이거나 둥근 물체(판정: `pose_rules.is_symmetric`, [vision.md](vision.md) V2)는 yaw 0 고정. **`yaw_valid`(bool)**: yaw를 믿어도 되는지. 대칭 물체와 정상 산출은 `true`, 덩어리가 비정상(뎁스 결손·너무 얇음 등)이면 `false`이고 이때 `yaw`는 0 자리표시이며 진짜 0°가 아니다. **받는 쪽은 필드가 없으면 `false`로 취급한다**(보내는 쪽은 항상 채운다). 소비자는 `false`이면 길쭉한 물체를 집지 않고 재인식하고, 그래도 `false`이면 오류로 처리한다(에러 코드는 `pick_object` 표 소관). 판정 임계값은 params(yaml)에 두며 `[팀 확정 필요]`. `size_m` 규약은 [ontology.md](ontology.md)의 "치수 계약". `top_z` = 서랍 바닥 기준 물체 윗면 높이. P1은 박스 중심만 제공하며 머리 방향(망치·스패너 등)은 B의 요청이 있을 때 계약 변경으로 추가. yaw 산출 방식(서랍 바닥 위 뎁스 덩어리 + `minAreaRect`, 사용자 확정 10/04)은 [vision.md](vision.md) V2. 박스 중심 픽셀을 서랍 좌표 x·y로 옮길 때는 **`z = top_z/2` 평면**과 교차시킨다(확정, [vision.md](vision.md) V2) |
| `nudge_object` | `target`(`inspect_region` 결과의 `target`을 그대로 넘김: `$scan.target` — `id`·`class`·`pose`(`yaw` 포함)·`top_z`), `drawer_id`, `check_only`(선택, bool, 기본 `false`) | `{pushed, push_vector_m, clearance_before_m, floor_z_m, target_after}` (모두 서랍 좌표계 `drawer_<id>`, `inspect_region`의 `pose`와 같은 기준) | **1회 호출 = 1회 끌기.** 옆벽에 붙어 짧은 변으로 못 잡을 때만: 닫은 그리퍼(손끝을 벽 쪽으로 기울일 수 있음)로 물체 윗면을 위에서 눌러 힘 감지(접촉) → **서랍 옆(y)으로만** 끌기 → 올라감. 서랍이 닫히는 방향으로는 끌지 않는다(2 N에서도 서랍이 같이 밀림, B 실측 10/06, #37). 잡을 수 있는 자리면 움직이지 않고 `pushed: false`. `check_only: true`이면 움직이지 않고 판단만 한다. `target_after` = 입력 `target`에서 `pose.position`만 끈 만큼 옮긴 **예상** 위치(형식은 `target`과 같음). **성공일 때만** 채우고 실패면 `null` — 실패 결과의 좌표로 집지 않는다. 예상값이라 재인식이 아니다(FR-ACT-05의 재인식 완료로 보지 않음). 밀었으면 원칙은 다시 `inspect_region` 후 집기, stub 시연(10/06)은 `target_after`를 `pick_object`에 넘김. 결과 예시 `contracts/examples/nudge_object_result.json` (FR-ACT-05, 상세 [domain.md 8.5](domain.md#85-벽-인접-물체-밀어오기-담당-b) — 방식 변경은 시연 후 정리) |
| `pick_object` | 서랍에서: `target`(`inspect_region` 결과의 `target`을 그대로 넘김: `$scan.target` — `id`·`class`·`pose`·`top_z`) / 트레이에서: `source_slot` + `object_id`(인스턴스 ID). 공통: `approach_offset`, `grip_force`(선택, 기본 = 온톨로지 값) | `{object_id, class, pick_pose_drawer_frame, grasp_ok}` | 접근 → 파지 → 안전 높이 상승. 접근 위치는 `pose.position` x·y, 손목 회전은 `pose.yaw`, **파지 높이는 서랍 바닥(`places.yaml` tf) + 온톨로지 물체 높이**(`top_z`는 검산용, #18). 서랍에서 집을 때는 움직이기 전에 인출 거리 → `yaw_valid` → 바닥 위(`top_z`)를 확인하고 걸리면 움직이지 않고 에러(아래 표) |
| `place_object` | `location`: `"staging_tray"`(빈 슬롯 자동 할당) / `"handover_zone"` / 슬롯명, 또는 `pose` + `frame` | `{slot, placed_pose}` | 지정 위치에 거치 후 그리퍼 해제. `frame: "drawer"`일 때는 배치 직전 재촬영으로 높이(z) 보정. **`location`이 서랍(`Drawer` 클래스)이면 백엔드가 `frame: "drawer"`, 현재 인출 거리 반영 서랍 좌표, z 보정을 자동 적용**(서랍의 `return_slot` 또는 지정 `pose` 사용) |

* **ID 규칙**: `object_id`·`target.id`는 비전이 부여한 **인스턴스 ID**(예: `eraser#1`, `unknown#3`), `search_target`과 온톨로지 키는 **클래스명**(예: `eraser`). 둘을 섞지 않음.
* **포즈 vs 위치**: `pose_name`은 로봇 관절 포즈, `location`은 월드의 물체 거치 장소. 이름 공간을 분리함.

**② 지식/상호작용 동작**

| 동작명 (`action`) | 주요 파라미터 | 반환값 | 설명 |
| :--- | :--- | :--- | :--- |
| `query_ontology` | `item` / `list` / `class` / `state`(상태 경로) 중 하나 | 단일: `{item, name_ko, drawer_id, grip_force}` / 다중: `{items[], groups[{drawer_id, items[]}]}` / 상태: `{path, value}` | 물품 위치, 리스트·클래스 구성, 현재 상태 조회 (다중 결과는 서랍별로 묶어 반환) |
| `update_ontology` | `item`, `drawer_id`, `pose`(선택) | - | 발견된 실제 위치로 지식 베이스 갱신 |
| `speak` | `text` | - | TTS 음성 피드백 |

**③ 제어 블록 (Runner가 해석, 코드에는 시나리오가 들어가지 않음)**

| 블록 | 필드 | 설명 |
| :--- | :--- | :--- |
| `set_var` | `params.name`, `params.value` | 블랙보드 변수 설정 |
| `push` / `pop` | `params.stack`, `params.value` / `params.stack` + `output` | 리스트형 변수를 LIFO 스택으로 사용 (Rollback용) |
| `if` | `cond`, `then[]`, `else[]` | 조건 분기 |
| `while` | `cond`, `body[]`, `max_iter`(필수) | 조건 반복. 초과 시 `LOOP_LIMIT` 에러 |
| `for_each` | `in`, `as`, `body[]` | 리스트 순회 (번들 요청 처리) |
| `fallback` | `options[]` (각 항목은 스텝 배열) | 첫 대안부터 시도해 하나라도 성공하면 성공 (예: 손잡이 파지 실패 → 다른 접근 포즈) |
| `finally` (태스크 최상위 필드) | `finally[]` | `sequence`가 성공·실패 어느 쪽으로 끝나도 실행 (복구·서랍 닫기·홈 복귀) |
| `on_halt` (태스크 최상위 필드) | `on_halt[]` | 사용자 취소·비상정지 시 실행. **로봇 동작 없이** 상태 저장·로그·TTS 안내만 수행 |
| 스텝 공통 필드 | `timeout_sec`, `recovery[]` | `timeout_sec` 초과 시 `TIMEOUT` 실패. 실패 시 `recovery[]`(예: 그리퍼 열고 후퇴)를 실행한 뒤 `retry` 횟수만큼 재시도 |

**BehaviorTree 대응표 (발표 질의 대비: "왜 BT 프레임워크를 쓰지 않았나")**

| 우리 Runner | BehaviorTree.CPP / Nav2 | 차이 |
| :--- | :--- | :--- |
| `sequence` | Sequence | 동일 |
| `if` / `while` / `for_each` | IfThenElse / WhileDoElse / LoopNode | 동일 의미 |
| `retry` + `recovery[]` | RetryUntilSuccessful / Nav2 RecoveryNode | 동일 의미 |
| `fallback` | Fallback | 동일 의미 |
| `timeout_sec` | Timeout | 동일 의미 |
| `finally` | TryCatch(v4.9) | **TryCatch는 실패 시에만 정리 실행, 우리 `finally`는 성공 시에도 실행** |
| `on_halt` | TryCatch `catch_on_halt` / `_onHalted` | 동일 의미 |
| 스텝별 `pre_check`·`post_check`·`state_diff` 로그 | (기본 로거에 없음) | 우리 고유 기능 |

> **자체 Runner를 유지하는 사유**: BehaviorTree.CPP는 C++ 기반이라 14일 일정에서 개발·빌드 부담이 크고, 실시간 시각화 도구(Groot2)는 유료 버전에서만 제공됨. py_trees는 JSON 태스크 파일을 읽는 로더와 무조건 실행되는 정리 노드(`finally`)를 기본 제공하지 않음. 따라서 기존 프레임워크를 새로 익히기보다 그 핵심 제어 의미만 차용해 경량 자체 Runner를 구축하는 편이 일정과 성공 가능성 면에서 유리하다고 판단함(결정 로그 #19).

**변수 문법 (2종만 허용)**
* **값 전체 참조**: `"$scan.target.id"`, `"$scan.candidates[0].id"` → 원래 타입(불리언·숫자·객체) 그대로 치환.
* **문자열 보간**: `"{{loc.name_ko}} 찾기를 시작합니다"` → 문자열로 치환.
* **한국어 조사 필터**: `"{{loc.name_ko|을}}"`처럼 조사를 붙이면 Runner가 앞 단어의 받침 유무(유니코드 한글 음절 계산)로 `을/를`, `이/가`, `은/는`, `과/와`, `으로/로`를 자동 선택함. 목록은 `"{{list.items_ko|목록|을}}"` → "차키, 립밤, 지우개를"처럼 쉼표로 잇고 마지막 단어 기준으로 조사를 붙임. 영문·숫자로 끝나면 받침 없음으로 처리.
* `eval`을 사용하지 않고 Runner가 경로를 해석함. 존재하지 않는 변수는 `VAR_UNDEFINED` 에러.
* **변수 스코프 (블랙보드)**: `output`·`set_var`로 만든 변수(`loc`, `scan`, `picked` 등)는 **태스크 단위 전역 블랙보드**에 저장되어 `sequence`·`finally`·`on_halt` 어디서든 태스크 종료 시까지 유지됨. 같은 이름으로 다시 `output`하면 덮어씀(예: Unpacking 루프의 `scan`은 재촬영마다 갱신, `loc`은 처음 값 유지). 예외로 `for_each`의 `as` 변수만 루프 안에서 유효함. 블랙보드는 태스크가 끝나면 사라지고(최종 값은 로그에 기록), **태스크 사이에 이어지는 정보는 상태 온톨로지(7.8)만** 사용함.

**조건식 (단일 형태)**: `{ "op": "<연산자>", "args": [ ... ] }`
* 비교 `==, !=, <, >, <=, >=` (args 2개) / 논리 `and, or` (2개 이상), `not` (1개) / 컬렉션 `empty, not_empty` (1개)

**실패 처리 규칙**
* 스텝별 `on_failure`: `abort`(기본) / `retry`(`retry` 횟수만큼) / `skip` / `safe_home`.
* `abort`로 `sequence`가 중단되면 `finally`가 실행되고 `overall_status = FAILED`.
* **비상정지(E-stop)로 인한 `ABORTED`에서는 `finally`의 로봇 동작을 실행하지 않음.** 사람이 상태를 확인한 뒤 재개 명령으로 복구함.
* `ABORTED` 경로: 백엔드가 `ESTOP`으로 실패하거나 Runner `halt()`(`/runner/estop`·음성 "멈춰")가 호출되면 `retry`·`skip`·`safe_home`을 적용하지 않고 즉시 중단. `halt()`는 진행 중인 액션에 즉시 취소를 요청하고(Runner 노드: `RosClients.cancel_all`), 백엔드가 멈춘 뒤 최종 결과(`canceled`)를 주면 그 스텝에서 `ABORTED`로 끝냄(스텝 기록에는 백엔드 코드, 예: `CANCELED`). 실제로 멈추는 것은 백엔드 책임(PR #74 리뷰). `finally`는 로봇을 움직이지 않는 동작(`speak`·`query_ontology`·`update_ontology`·`set_var`·`if`)만 실행하고 나머지는 `SKIPPED`로 기록(허용 목록이라 새 동작은 기본 생략). 다른 실패와 겹치면 `ABORTED`가 우선. 중단 요청은 스텝 시작·재시도·`safe_home` 직전마다 확인.
  * **중단과 결과 반영의 경계** (PR #64 E 리뷰): 중단 요청이 결과 반영 전에 들어오면 반영하지 않음. `skill`은 `effect` 직전에 확인해 상태를 바꾸지 않고 스킬을 `FAILURE`(`HALTED`)로 기록(하위 원자 동작은 받은 응답대로 기록). 원자 동작은 응답대로 기록하되 다음 동작을 보내지 않음. 마지막 스텝 도중의 중단도 `COMPLETED`가 아니라 `ABORTED`. 반영되지 않은 결과는 사람이 확인한 뒤 재개(중단 잠김). `halt()`와 effect 반영(중단 확인 → 상태 갱신)은 같은 잠금으로 묶어, 다른 스레드의 중단 요청은 반영 전이면 반영하지 않고 반영 중이면 반영이 끝난 뒤 적용(그 스킬은 완료로 기록).
* **중단 잠김**: `ABORTED` 뒤에는 Runner `resume()`(사람이 상태 확인 후 재개 명령)을 부르기 전까지 새 태스크를 로봇 동작 없이 `ABORTED`로 거절하고, 처음 멈춘 이유(`ESTOP`/`HALTED`)를 돌려줌.
* `retry` 횟수는 `on_failure: "retry"`일 때만 쓰며 1 이상이어야 함(아니면 실행 전 검사에서 거절). `skip`된 스텝은 `FAILURE`와 에러 코드를 그대로 기록하고 다음 스텝으로 진행. `safe_home`은 `home` 포즈로 이동한 뒤 중단.
* `finally` 스텝도 각자의 `on_failure`를 따름(기본 `abort`면 이후 `finally` 스텝은 실행되지 않음). `sequence`와 `finally`가 모두 실패하면 `sequence`의 원인을 태스크 실패 원인으로 남김.
* `timeout_sec`: `Skill` goal 에는 제한 시간 칸이 없으므로 Runner(ROS 클라이언트)가 시간이 지나면 **취소를 요청하고, 백엔드가 멈춘 뒤 최종 결과를 줄 때까지 기다린 다음** `TIMEOUT`으로 끝냄(#10, PR #74 리뷰) → `finally` 복구 동작이 앞 동작과 겹치지 않음. 취소 뒤 5초 `[추정]` 안에 최종 결과가 없으면 `STOP_UNCONFIRMED`: 멈췄는지 알 수 없으므로 `ESTOP`처럼 `ABORTED`·잠금, 사람 확인 전 새 동작 없음. 최종 결과가 와도 그 코드가 잠금 대상(아래 표의 `ESTOP`·`STOP_UNCONFIRMED`·B 서버 잠금 코드)이면 `TIMEOUT`으로 덮지 않고 그대로 잠금(PR #74 E 리뷰).
  * **goal 수락 응답이 늦을 때** (PR #74 D 리뷰): 5초 `[추정]` 안에 수락 응답이 없으면 "보내지 않음"으로 보지 않고, 늦게라도 수락되면 즉시 취소하고 정지 확인 뒤 `TIMEOUT`, 끝내 확인이 안 되면 `STOP_UNCONFIRMED`. 서버를 찾는 사이 중단 요청이 들어오면 goal 을 보내지 않음(`HALTED`). 중단 처리 뒤 `finally`의 비동작(`speak` 등)은 막지 않음. **실제로 멈추는 것은 백엔드 책임**(아래 "백엔드 구현 약속"). Runner는 걸린 시간을 재서 초과하면 결과가 성공이어도 `TIMEOUT`으로 처리. `if` 같은 블록은 끝난 뒤 판정하므로 동작을 끊으려면 원자 동작 스텝에 지정.
  * **늦게 온 결과는 재시도하지 않음** (PR #64 리뷰): Runner 가 판정한 `TIMEOUT`은 결과가 도착한 뒤라 동작이 실제로 끝났을 수 있으므로, `retry`가 있어도 같은 동작을 다시 보내지 않고 실패로 끝냄(기록 `retry_stopped: "LATE_RESULT"`). 취소 요청으로 끝난 `TIMEOUT`도 같음(`retry_stopped: "TIMEOUT"`). 백엔드가 실패를 돌려준 경우의 재시도는 그대로.
* **실행 전 검사**: 스키마(7.2) + 현재 Phase 범위 밖 블록·필드 거절 + `set_var`의 `name`·`if`의 `cond`·스텝 ID 중복·`retry` 횟수 확인. 문제가 있으면 로봇을 움직이지 않고 `TASK_INVALID`(문제 목록 포함), `finally`도 실행하지 않음.
* **`skill` 스텝 (P1, #12)**: 스텝은 `action`(원자 동작)과 `skill`(온톨로지 primitive 스킬, 7.5) 중 하나. Runner 는 온톨로지를 받아 상태를 들고 있고(태스크 사이에 유지, ontology.md 7.8), 스킬마다 ① `pre` 확인 → 불충족이면 로봇 동작 없이 `PRE_UNMET` ② `expand`의 원자 동작을 차례로 실행(기록 ID `<스텝 ID>.e<n>`, `parent` = 스킬 스텝 ID, 출력은 스킬 안에서만 보임) ③ 모두 성공하면 `effect`로 상태 갱신. 하나라도 실패하면 상태는 그대로.
  * P1 은 **동작 응답 성공 = effect 반영**. `verify`(사후 관측)·`hold`(실행 중 유지 조건)는 P2(FR-ONT-02). P1 Runner 는 `primitive` 스킬만 `skill` 스텝으로 실행(`composite`는 거절). 선언형 복합 스킬 추가는 FR-PLN-03(P3).
  * **스킬 재시도는 로봇이 움직이지 않은 실패에만** (PR #64 D 리뷰 + PR #65 합의): 실패 응답을 받아도 앞 원자 동작이 실행됐거나 동작이 실제로 끝났을 수 있는데 P1 은 관측 확인(`verify`)이 없어 알 수 없으므로, 스킬 전체를 다시 보내면 이미 열린 서랍 재열기·이미 집은 물건 재집기가 될 수 있음. 그래서 `retry`는 ① 실패 코드가 "동작 없이 거절"이 보장된 코드(`NO_MOTION_CODES`: `YAW_INVALID`, B PR #66)이고 ② 그 시도에서 앞서 보낸 원자 동작이 모두 팔을 움직이지 않는 동작(`inspect_region`·`speak`·`query_ontology` 등)일 때만 적용. 예: `pick`(살펴보기 → 집기)에서 방향 산출 실패로 `pick_object`가 거절하면 재인식 1회. 그 밖에는 재시도하지 않고 기록에 `retry_stopped`(`MOTION_UNCERTAIN` = 앞서 팔을 움직임, `NOT_RETRYABLE` = 허용 목록에 없는 코드). 재인식 횟수는 태스크 `retry`로 정함 `[팀 확정 필요]`.
  * `timeout_sec`은 스킬 전체 시간(각 원자 동작에는 남은 시간을 전달). 로봇을 움직이므로 `ABORTED` 때 `finally`에서도 `SKIPPED`.
  * 실행 전 검사에서 온톨로지에 없는 스킬, `composite`, 스킬 정의와 다른 `params` 이름(빠짐·모름), 하위 기록 ID 중복을 `TASK_INVALID`로 거절. 실행 중에도 다시 확인(`UNKNOWN_SKILL`·`BAD_SKILL_PARAMS`).

**Runner 에러 코드** (스킬별 에러 코드는 7.5 온톨로지 `errors`)

| 코드 | 의미 |
| :--- | :--- |
| `TASK_INVALID` | 실행 전 검사 실패 (스키마·Phase 범위·필수 필드) |
| `VAR_UNDEFINED` | 존재하지 않는 변수 참조 |
| `BAD_FILTER` | `{{x\|필터}}`에 없는 조사·`목록` 필터 오용 |
| `BAD_CONDITION` | 조건식 인자 개수·타입 오류 |
| `TIMEOUT` | `timeout_sec` 초과 (Runner 판정, 또는 클라이언트가 취소 요청). 결과가 불확실해 재시도하지 않음 |
| `ESTOP` | 백엔드가 비상정지로 동작 실패를 반환 → `ABORTED` |
| `STOP_UNCONFIRMED` | 취소를 요청했지만 정해진 시간 안에 백엔드의 정지 확인(최종 결과)이 없음, 또는 백엔드가 정지 확인 실패를 돌려줌 → `ABORTED`·잠금 (PR #74 리뷰) |
| `STATE_UNKNOWN`·`MOVE_UNCONFIRMED`·`LOCKED` | B 스킬 서버 잠금 코드(PR #73: 이동 중 상태 조회 실패·이동 명령 수락 여부 모름·서버 잠김) → Runner 도 `ABORTED`·잠금. **10/06 실물 확인 후 B·C 확정** |
| `HALTED` | Runner `halt()`로 중단(사용자 취소·`/runner/estop`) → `ABORTED` |
| `ACTION_FAILED` | 백엔드가 에러 코드 없이 실패를 반환 |
| `BACKEND_ERROR` | 백엔드 호출 중 예외(통신 끊김 등), 서버 없음·goal 거절(동작 안 함), 성공 응답의 JSON 을 읽을 수 없음. 스텝 실패로 처리해 `finally`를 보장 |
| `INTERNAL_ERROR` | Runner 내부의 예상 못 한 에러. 스텝 실패로 처리해 `finally`를 보장하고 기록의 `internal_error`에 원인을 남김 |
| `PRE_UNMET` | `skill` 스텝의 `pre` 조건 불충족. 로봇 동작을 보내지 않음(틀린 조건은 기록의 `pre_check`) |
| `UNKNOWN_SKILL` | 온톨로지에 없거나 P1 미지원(`composite`) 스킬 (보통 실행 전 검사에서 `TASK_INVALID`로 먼저 걸림) |
| `BAD_SKILL_PARAMS` | `skill` 스텝에 스킬 정의의 `params`가 빠짐 (보통 실행 전 검사에서 `TASK_INVALID`로 먼저 걸림) |

**`query_ontology` 에러 코드** (#10, Runner 안에서 처리 — `core/ontology_query.py`)

| 코드 | 의미 |
| :--- | :--- |
| `UNKNOWN_ITEM` | 온톨로지 `world.items`에 없는 물품이거나 위치(`located_in`)를 모름 |
| `BAD_QUERY` | 조회 파라미터 형식 오류 (`item`·`state` 중 하나, `state`는 `"predicate.subject"` 경로) |
| `NOT_SUPPORTED` | P1 미지원: `list`·`class` 다중 조회(번들 요청은 `for_each`가 필요한 P2), `update_ontology` |

**`inspect_region` 에러 코드** (`InspectRegion.srv`의 `error_code`, 실패 시 `success=false`. 미발견은 에러가 아니라 `success=true` + `target_found=false`)

| 코드 | 의미 |
| :--- | :--- |
| `UNKNOWN_REGION` | 알 수 없는 `region` |
| `STUB_NOT_READY` | stub 좌표가 실측 전(`config/vision_stub.yaml`의 `ready: false`) |
| `CONFIG_INVALID` | stub 설정 값의 형식 오류(예: `yaw_valid`가 bool이 아님) |

실제 `inspect_region`(V2, `ready2go_vision/nodes/inspect_region.py`)은 위 코드에 더해 아래를 쓴다 `[팀 확정 필요]`(A 제안, 1차 점검 10/06에 처음 사용).

| 코드 | 의미 |
| :--- | :--- |
| `CAMERA_TIMEOUT` | 요청 이후 컬러·뎁스·`camera_info`가 제한 시간(기본 3 s) 안에 오지 않음 |
| `TF_UNAVAILABLE` | `base_link` → `wrist_cam_color_optical_frame` TF를 얻지 못함(로봇 드라이버·bringup 확인) |
| `DEPTH_INVALID` | 검출 박스 안 뎁스가 쓸 수 없음(결손 비율·유효 픽셀 부족, 서랍 바닥 위로 올라온 덩어리 없음). 하나라도 있으면 전체 실패(안전 우선, `config/vision_params.yaml` `policy`) |
| `RESULT_INVALID` | 만든 결과가 pose 규칙(runner.md 7.1)을 어김 — 코드 버그 신호 |

**로봇 동작 공통 에러 코드** (원자 동작이 **움직이기 전에** 확인하고 반환. 모두 로봇 동작 없음. 판단 코드 `ready2go_skills/core/motion_guard.py`, 허용 오차 `ready2go_skills/params/skills.yaml` `[팀 확정 필요]`)

| 코드 | 대상 | 의미 |
| :--- | :--- | :--- |
| `TOOL_NOT_SET` | 로봇을 움직이는 모든 원자 동작 | 펜던트 활성 TCP·툴이 `config/calibration/calibration_meta.yaml`의 값(`GripperDA_v1`·`tool_weight`)과 다르거나 조회 실패 (결정 #28). 노드 시작·첫 동작 직전에 확인. P1은 거부 + TTS 안내(자동 전환은 선택) |
| `DRAWER_NOT_AT_TRAVEL` | `pick_object`(서랍)·`nudge_object` | 마지막 `drawer_control`의 `drawer_displacement`가 `places.yaml` `tf_at_travel_m`(서랍 좌표계가 유효한 인출 거리)에서 허용 오차를 벗어남 또는 값 없음 |
| `YAW_INVALID` | `pick_object`(서랍)·`nudge_object` | `target.pose.yaw_valid`가 `true`가 아님(`false`·필드 없음). 다시 인식은 스킬이 아니라 태스크에서 1회(#65 합의) |
| `NOT_ON_FLOOR` | `pick_object`(서랍) | `top_z − 물체 높이`가 허용 오차보다 큼 → 다른 물체 위에 있음(또는 `top_z` 없음). 바닥 + 물체 높이로 내려가면 아래 물체와 부딪히므로 P1은 거부, `top_z` 기준 파지는 P2 |
| `WALL_TOO_CLOSE` | `pick_object`(서랍) | 짧은 변으로 잡으면 손가락·관절이 서랍 벽에 닿는 자리(그리퍼 벌림 폭 + 실측 벽 간섭 거리, `motion_plan.wall_blocks_grasp` — `nudge_object` 판단과 같음). 태스크는 `nudge_object` 뒤 그 `target_after`로 다시 집는다 (10/06 추가, #83 A 요청) |

**`nudge_object` 에러 코드** (스킬이 아니라 원자 동작이라 온톨로지 `errors`가 아니라 여기에 둔다. 위 공통 코드도 반환)

| 코드 | 의미 |
| :--- | :--- |
| `NO_FLOOR_CONTACT` | 최대 하강 거리 안에서 바닥 접촉이 없음(서랍 덜 열림·좌표 오류) → 즉시 정지 |
| `NO_PUSH_ACCESS` | `nudge_object`: 끌어도 짧은 변으로 잡을 수 없는 자리 — ① 앞뒤 벽 때문에 막힘(옆으로 끌어도 해결 안 됨) ② 필요한 끌 거리가 최대(`drag.max_shift_mm`)보다 큼 ③ 누를 점이 물체 윗면 밖. 움직이지 않음 → P1은 실패 + TTS 안내(길이 방향 잡기는 P2 후보) |
| `PUSH_BLOCKED` | 밀다가(끌다가) 힘 임계 초과(끼임·다른 물건) |
| `NO_OBJECT_CONTACT` | 끌기: 물체 윗면 예상 높이보다 더 내려가도 접촉(힘)이 없음 — 위치·높이 확인 (10/06 추가) |
| `PUSH_LIMIT` | `check_only: true` 재판단에서 한 번 민 뒤에도 파지 가능한 자리가 아님(P1 Runner는 `while`이 없어 반복 밀기를 하지 않으므로 밀기는 1회로 제한) |

**백엔드(Skill 서버) 구현 약속** (#10, B·E·A 서버와 mock 공통. 참고 구현 `ready2go_runner/nodes/mock_backend.py`)

| 항목 | 약속 |
| :--- | :--- |
| 이름 | 로봇 동작 `/skills/<동작>`(`Skill` 액션), TTS `/voice/speak`(`Skill`), 인식 `/vision/inspect_region`(`InspectRegion`) — [ICD](interfaces.md). Runner 는 `BACKEND`(real·sim·mock)와 관계없이 같은 이름으로 보냄. mock 은 `BACKEND=mock` 일 때만 떠서 이름이 겹치지 않음 |
| goal | `params_json` = 위 표의 `params`를 JSON 문자열로(UTF-8, 한글 그대로). `$변수`는 Runner 가 풀어서 보냄 |
| result | `success`, `error_code`(실패 시 코드. 비우면 Runner 가 `ACTION_FAILED`), `output_json`(위 표의 반환값, 없으면 빈 문자열. 성공인데 JSON 을 읽을 수 없으면 Runner 는 `BACKEND_ERROR` 실패로 봄) |
| 취소 | `Skill` goal 에 제한 시간 칸이 없음. Runner 는 `timeout_sec`이 지나거나 `/runner/estop`이 오면 취소를 요청하고 **최종 결과를 기다림** → **서버는 취소 요청을 받으면 안전하게 멈추고 5초 `[추정]` 안에 `canceled`로 끝낼 것**. 없으면 Runner 는 `STOP_UNCONFIRMED`로 잠김 |
| 비상정지 | 펜던트 비상정지 등으로 멈추면 `error_code = "ESTOP"` → Runner `ABORTED`·잠김 (#19, B 확인) |
| 동작 없이 거절 | 모션 계획 전에 거절하면 로봇이 움직이지 않았음을 보장하고 `NO_MOTION_CODES`의 코드 사용(현재 `YAW_INVALID`). 새 코드는 runner.md 와 `interpreter.NO_MOTION_CODES`에 함께 추가 |
| 서버 준비 | Runner 는 서버를 2초 안에 못 찾거나 goal 이 거절되면 `BACKEND_ERROR`(동작 안 함) `[추정, 실측 후 조정]` |

**Runner 노드** (#10, `ready2go_runner runner`, bringup launch 가 모든 `BACKEND`에서 실행)

* 시작할 때 스키마(`/contracts`)·온톨로지(`/knowledge`, 초기 상태 포함)를 읽고 실행 이력은 MongoDB(`MONGO_URI`) → 실패 시 `/logs` JSONL.
* `query_ontology`는 ICD 상 `OntologyManager` 담당이지만 아직 없어 Runner 현재 상태로 답함(물품 하나·상태 경로, E 확인 요청 #10).
* `/runner/status` (`std_msgs/String` JSON, 늦게 구독해도 마지막 값): `phase`(`idle`·`running`·`halted`), `task_id`, `current_step`, `halt_code`, `log_store`(`mongo`·`jsonl`), `last`(`task_id`·`run_id`·`overall_status`·`error_code`·`failed_step`·`problems`·`log_errors`).
* `/robot_state`: Runner 가 들고 있는 온톨로지 `state` JSON, 바뀔 때 발행.
* `/runner/estop` (`std_srvs/Trigger`) → `halt()` → 진행 중인 goal 에 즉시 취소 요청(정지 확인 전에는 다음 동작 없음). **재개(`resume()`) 통로는 ICD 에 없음** — P1 재개 절차(B 실물 확인·복구 → Runner 상태 맞춤 → 재개, PR #64 E 권고)와 함께 ICD 추가를 E 와 협의. 그 전에는 Runner 노드를 다시 시작하면 잠김이 풀리고 상태는 초기값으로 돌아감.
* 태스크 실행 통로: 정식은 `/voice/intent`(#17). 지금은 시험용으로 `RUNNER_TASK_FILE`(compose 환경 변수 → `task_file` 파라미터)을 주면 시작할 때 한 번 실행.
* `BACKEND=mock`: `mock_backend` 노드가 `/skills/*`·`/voice/speak`·`/vision/inspect_region`을 같은 이름으로 응답. `MOCK_FAIL`(예: `pick_object=GRASP_FAILED*1`)·`MOCK_NOT_VISIBLE`(예: `car_key`)로 실패 경로 시험.

### 7.2 태스크 시퀀스 스키마

`action` 값에 따라 `params`를 검증하여 **오타나 잘못된 파라미터를 실행 전에 차단**합니다. 스텝은 재귀 구조(`if/while/for_each` 내부에 스텝)입니다. 스텝에는 `action`과 `skill`(7.1 `skill` 스텝) 중 정확히 하나가 있어야 합니다(예시: [`contracts/examples/task_skill_steps.json`](../contracts/examples/task_skill_steps.json)).

> **원본 파일**: [`contracts/task.schema.json`](../contracts/task.schema.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

> 구현 시 `params`는 7.1의 동작별 표를 기준으로 `allOf/if-then`으로 세분화하여 `schema/actions/*.json`으로 분리 관리하고, `while`은 `max_iter`를 필수로 강제함.

### 7.3 실제 인스턴스 예시: 오클루전 탐색 + 복구 (하드코딩 ID 없음)

음성으로 "지우개 찾아줘" → `inputs.target = "eraser"`로 바인딩되어 실행됩니다. 장애물 ID는 미리 알 수 없으므로 `inspect_region`의 반환값을 변수로 받아 사용합니다.

> **원본 파일**: [`tasks/find_with_unpack.json`](../tasks/find_with_unpack.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* 이 한 파일로 **Unpacking(s7), 미발견 처리(s8 else), Rollback(f1), 서랍 닫기(f2)** 가 모두 표현되며, 중간에 실패해도 `finally`로 복구가 보장됨. Python 코드에는 시나리오 로직이 없음.
* **번들 요청**(`find_list`, `find_class`)은 별도 템플릿 `find_group_by_drawer`로 처리함: `query_ontology`의 `groups[]`를 `for_each`로 순회하여 **서랍당 한 번만 열고**, 서랍 내부에서는 목표 목록이 모두 발견되거나 비워질 때까지 Unpacking 루프를 돈 뒤 복구·닫기.

### 7.4 실행 이력 자동 로깅 스키마 (Execution Log)

각 스텝(중첩 스텝 포함)마다 시작 시각, 소요 시간, 반복 인덱스, 시도 횟수, **성공 여부·결과 코드, 에러 정보, 조건 확인 결과(`pre_check`), 상태 변화(`state_diff`)**를 기록합니다. 플래너가 만든 실행은 `plan`(스킬 조합)도 함께 기록합니다.

> **Phase 구분**: 아래 목록은 전체 설계입니다. P1 에 구현된 범위는 맨 아래 "구현 (P1, #12)"이며, 사후 관측 성공 판정(`post_check`)·`states` 컬렉션은 P2(FR-ONT-02·FR-LOG-02), 관측 불일치 `STATE_MISMATCH`는 P3(FR-REC-01) 계획입니다.

> **원본 파일**: [`contracts/examples/execution_log.json`](../contracts/examples/execution_log.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* `overall_status`: `COMPLETED`(시퀀스 정상 종료) / `FAILED`(스텝 abort, `finally` 실행됨) / `ABORTED`(사용자 취소·비상정지).
* `outcome`: 작업 결과 의미(`FOUND` / `NOT_FOUND` / `PARTIAL`)는 상태와 분리하여 기록.
* **시간 규칙**: `total_duration_sec`는 실행 전체의 **실제 경과 시간(wall-clock)**. 제어 블록(`while`/`if`)의 소요 시간은 자식 스텝을 포함하므로 합산에서 제외하고, **원자 동작(리프) 스텝 소요 시간의 합 ≤ `total_duration_sec`**를 검증함.
* **성공 여부**: 모든 스텝은 `status`(`SUCCESS`/`FAILURE`/`SKIPPED`)를 가짐. 실패 시 `error.code`(7.5 스킬의 `errors` 목록 기준)를 기록.
* **조건 확인**: `pre_check`는 `PASS` / `PRE_UNMET`과 함께 **조건별 결과 배열**(조건, 실제 값, 통과 여부)을 기록. `PRE_UNMET`이면 동작을 보내지 않음.
* **성공 판정** (P2 계획, FR-ONT-02. P1 은 액션 응답 성공 기준): 스텝 성공 = **액션 결과 성공 AND 사후 관측 확인(`post_check`) 통과**. 관측 기준은 스킬의 `verify`(그리퍼 폭, 서랍 변위, 재스캔). 액션은 성공했지만 관측이 안 맞으면 `POST_UNCONFIRMED`로 실패 처리.
* **안전 게이트**: 실물 실행 전 8단계 게이트(11장)의 단계별 통과 여부를 `runs` 헤더에 기록.
* **상태 변화**: `state_diff`는 `{상태 경로: [이전 값, 이후 값]}`. 관측으로 고친 경우 `STATE_MISMATCH` 항목으로 따로 표시(P3 계획, FR-REC-01).
* **플래너 실행**: 헤더에 `goal`과 `plan`(스킬 조합 목록), 스킬 단위 기록과 그 아래 원자 동작 기록을 함께 저장.
* **저장**: 스텝이 끝날 때마다 `LogStore`를 통해 MongoDB(`runs`·`steps`·`states` 컬렉션)에 저장. `runs` 헤더에는 **온톨로지 파일 해시**, STT 원문, LLM 원문 응답, 안전 게이트 결과를 포함. DB 연결 실패 시 **JSONL 파일로 자동 폴백**하여 시연이 멈추지 않게 하고, 제출·발표용으로 `logs/*.json`도 내보냄. 원시 토픽(카메라·조인트)은 rosbag2(MCAP)로 별도 녹화.
* 위 예시는 지면상 일부 스텝만 표기. 실제 로그에는 `finally` 스텝을 포함한 모든 스텝이 기록됨.
* **구현 (P1, #12)**: `core/log_records.py`가 레코드 모양을, `core/logstore.py`가 저장을 맡음. Runner 는 `LogStore` 약속(`start_run`·`write_step`·`end_run`·`read_run`)에만 의존.
  * `MongoLogStore`: `cobot2`의 `runs`(실행 1건, `run_id`로 덮어써 시작 기록을 완성)·`steps`(스텝 1건, `run_id`·`seq` 색인). 접속 주소 `MONGO_URI`(기본 `mongodb://localhost:27017`), 연결·응답 제한 1초 `[추정, 실측 후 조정]`.
  * `JsonlLogStore`: `logs/<run_id>.jsonl`(`:`→`-`), 한 줄 = `{"collection": "runs"|"steps", "doc": ...}`. `doc`은 MongoDB 레코드와 같은 모양. 쓰다 만 줄은 건너뜀.
  * `FallbackLogStore`: MongoDB 실패 시 그 실행의 앞 기록까지 JSONL 에 다시 써서 한 파일에 실행 전체를 남기고, 그 실행은 끝까지 JSONL(스텝마다 연결 제한만큼 멈추지 않게). 다음 실행은 MongoDB 재시도. 상태는 `degraded`·`last_error`.
  * 사람이 읽는 조회(읽기 전용): `ros2 run ready2go_runner run_report` — 최근 실행을 한국어 요약으로(KST 시각·mm·오류 코드 설명, 스킬 밑에 원자 동작 들여쓰기, `if` 줄 생략). `-n 3` 최근 3건, `--run f45c86` run_id 끝 글자, `--markdown` GitHub 댓글 표, `--uri mongodb://<PC2 IP>:27017` 다른 PC, `--jsonl /logs` 예비 기록. 요약 규칙은 `core/run_report.py`(D 시연 화면 #59에서 재사용 가능).
  * `run_id` = 시작 시각(UTC) + 6자리 난수. 스텝 `seq` = 시작 순서. 실행 거절(`TASK_INVALID`·중단 잠김)도 기록. 기록 저장 실패는 `RunResult.log_errors`에 남기고 **실행은 멈추지 않음**.
  * P1 범위: FR-LOG-01 항목(실행 ID·입력 명령·단계 ID·시작 시각·상태·오류 코드). `states` 컬렉션·`post_check`는 P2(FR-LOG-02).
  * `skill` 스텝 기록(#12): `action: "skill"`, `skill`, `params`, `pre_check`(온톨로지 `check` 결과 배열), 성공 시 `state_diff`(온톨로지 `apply` 결과). P1 실행에서 이미 계산되는 값을 **진단용 부가 기록**으로 남겨 `PRE_UNMET` 원인을 볼 수 있게 함(PR #64 E 검토 허용). FR-LOG-02 상세 로그 완료나 관측으로 검증된 상태를 뜻하지 않음(`state_diff`는 응답 기준 반영 결과). 하위 원자 동작 기록은 `parent`로 묶음. `state_diff` 키에 `.`이 있어 MongoDB 에서 키로 직접 조회하기는 불편함(저장·읽기는 7.0 실측 정상).
