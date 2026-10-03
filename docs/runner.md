# Runner · 원자 동작 · JSON 규격 · 실행 로그

> 상위 인덱스: [docs/README.md](README.md) · 원본: 기획서 v4.1 (`docs/archive/project_plan_v4.1.md`)
>
> **Phase 범위**: **P1**: 원자 동작 전체, 제어 블록 `sequence`·`if`·`set_var`·`retry`·`timeout_sec`·`finally`, 변수·조사 필터, 로그(성공 여부·에러 코드, JSONL) · **P2**: `while`·`for_each`·`push`/`pop`·`recovery`·`fallback`·`on_halt`, 7.3 예시(Unpacking), 로그 `pre_check`·`post_check`·`state_diff` + MongoDB · **P3**: 안전 게이트 기록.

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
| `inspect_region` | `region`: 서랍 ID, `"staging_tray"`, `"handover_zone"`, `search_target`(클래스명, 선택) | `{target_found, target, candidates[], visible_count}` | 검출 + 3D 위치 + 가림 순서. `target`은 `{id, class, pose, top_z}` 또는 `null`, `candidates`는 목표를 제외한 물체를 **위에 있는 순서(서랍 좌표계 `top_z` 내림차순)**로 정렬 |
| `pick_object` | `object_id`(인스턴스 ID), `approach_offset`, `grip_force`(선택, 기본 = 온톨로지 값), `source_slot`(선택, 트레이에서 집을 때) | `{object_id, class, pick_pose_drawer_frame, grasp_ok}` | 접근 → 파지 → 안전 높이 상승 |
| `place_object` | `location`: `"staging_tray"`(빈 슬롯 자동 할당) / `"handover_zone"` / 슬롯명, 또는 `pose` + `frame` | `{slot, placed_pose}` | 지정 위치에 거치 후 그리퍼 해제. `frame: "drawer"`일 때는 배치 직전 재촬영으로 높이(z) 보정. **`location`이 서랍(`Drawer` 클래스)이면 백엔드가 `frame: "drawer"`, 현재 인출 거리 반영 서랍 좌표, z 보정을 자동 적용**(서랍의 `return_slot` 또는 지정 `pose` 사용) |

* **ID 규칙**: `object_id`는 비전이 부여한 **인스턴스 ID**(예: `watch#1`, `unknown#3`), `search_target`과 온톨로지 키는 **클래스명**(예: `watch`). 둘을 섞지 않음.
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
* **한국어 조사 필터**: `"{{loc.name_ko|을}}"`처럼 조사를 붙이면 Runner가 앞 단어의 받침 유무(유니코드 한글 음절 계산)로 `을/를`, `이/가`, `은/는`, `과/와`, `으로/로`를 자동 선택함. 목록은 `"{{list.items_ko|목록|을}}"` → "차키, 지갑, 시계를"처럼 쉼표로 잇고 마지막 단어 기준으로 조사를 붙임. 영문·숫자로 끝나면 받침 없음으로 처리.
* `eval`을 사용하지 않고 Runner가 경로를 해석함. 존재하지 않는 변수는 `VAR_UNDEFINED` 에러.
* **변수 스코프 (블랙보드)**: `output`·`set_var`로 만든 변수(`loc`, `scan`, `picked` 등)는 **태스크 단위 전역 블랙보드**에 저장되어 `sequence`·`finally`·`on_halt` 어디서든 태스크 종료 시까지 유지됨. 같은 이름으로 다시 `output`하면 덮어씀(예: Unpacking 루프의 `scan`은 재촬영마다 갱신, `loc`은 처음 값 유지). 예외로 `for_each`의 `as` 변수만 루프 안에서 유효함. 블랙보드는 태스크가 끝나면 사라지고(최종 값은 로그에 기록), **태스크 사이에 이어지는 정보는 상태 온톨로지(7.8)만** 사용함.

**조건식 (단일 형태)**: `{ "op": "<연산자>", "args": [ ... ] }`
* 비교 `==, !=, <, >, <=, >=` (args 2개) / 논리 `and, or` (2개 이상), `not` (1개) / 컬렉션 `empty, not_empty` (1개)

**실패 처리 규칙**
* 스텝별 `on_failure`: `abort`(기본) / `retry`(`retry` 횟수만큼) / `skip` / `safe_home`.
* `abort`로 `sequence`가 중단되면 `finally`가 실행되고 `overall_status = FAILED`.
* **비상정지(E-stop)로 인한 `ABORTED`에서는 `finally`의 로봇 동작을 실행하지 않음.** 사람이 상태를 확인한 뒤 재개 명령으로 복구함.
* `ABORTED` 경로: 백엔드가 `ESTOP`으로 실패하거나 Runner `halt()`(`/runner/estop`·음성 "멈춰")가 호출되면 `retry`·`skip`·`safe_home`을 적용하지 않고 즉시 중단. `halt()`는 다음 스텝 시작 전에 적용(진행 중 동작 취소는 백엔드 책임). `finally`는 로봇을 움직이지 않는 동작(`speak`·`query_ontology`·`update_ontology`·`set_var`·`if`)만 실행하고 나머지는 `SKIPPED`로 기록(허용 목록이라 새 동작은 기본 생략). 다른 실패와 겹치면 `ABORTED`가 우선. 중단 요청은 스텝 시작·재시도·`safe_home` 직전마다 확인.
* **중단 잠김**: `ABORTED` 뒤에는 Runner `resume()`(사람이 상태 확인 후 재개 명령)을 부르기 전까지 새 태스크를 로봇 동작 없이 `ABORTED`로 거절하고, 처음 멈춘 이유(`ESTOP`/`HALTED`)를 돌려줌.
* `retry` 횟수는 `on_failure: "retry"`일 때만 쓰며 1 이상이어야 함(아니면 실행 전 검사에서 거절). `skip`된 스텝은 `FAILURE`와 에러 코드를 그대로 기록하고 다음 스텝으로 진행. `safe_home`은 `home` 포즈로 이동한 뒤 중단.
* `finally` 스텝도 각자의 `on_failure`를 따름(기본 `abort`면 이후 `finally` 스텝은 실행되지 않음). `sequence`와 `finally`가 모두 실패하면 `sequence`의 원인을 태스크 실패 원인으로 남김.
* `timeout_sec`: Runner가 제한을 백엔드에 함께 전달하고, **동작 취소는 백엔드 책임**. Runner는 걸린 시간을 재서 초과하면 결과가 성공이어도 `TIMEOUT`으로 처리. `if` 같은 블록은 끝난 뒤 판정하므로 동작을 끊으려면 원자 동작 스텝에 지정.
* **실행 전 검사**: 스키마(7.2) + 현재 Phase 범위 밖 블록·필드 거절 + `set_var`의 `name`·`if`의 `cond`·스텝 ID 중복·`retry` 횟수 확인. 문제가 있으면 로봇을 움직이지 않고 `TASK_INVALID`(문제 목록 포함), `finally`도 실행하지 않음.

**Runner 에러 코드** (스킬별 에러 코드는 7.5 온톨로지 `errors`)

| 코드 | 의미 |
| :--- | :--- |
| `TASK_INVALID` | 실행 전 검사 실패 (스키마·Phase 범위·필수 필드) |
| `VAR_UNDEFINED` | 존재하지 않는 변수 참조 |
| `BAD_FILTER` | `{{x\|필터}}`에 없는 조사·`목록` 필터 오용 |
| `BAD_CONDITION` | 조건식 인자 개수·타입 오류 |
| `TIMEOUT` | `timeout_sec` 초과 |
| `ESTOP` | 백엔드가 비상정지로 동작 실패를 반환 → `ABORTED` |
| `HALTED` | Runner `halt()`로 중단(사용자 취소·`/runner/estop`) → `ABORTED` |
| `ACTION_FAILED` | 백엔드가 에러 코드 없이 실패를 반환 |
| `BACKEND_ERROR` | 백엔드 호출 중 예외(통신 끊김 등). 스텝 실패로 처리해 `finally`를 보장 |

### 7.2 태스크 시퀀스 스키마

`action` 값에 따라 `params`를 검증하여 **오타나 잘못된 파라미터를 실행 전에 차단**합니다. 스텝은 재귀 구조(`if/while/for_each` 내부에 스텝)입니다.

> **원본 파일**: [`contracts/task.schema.json`](../contracts/task.schema.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

> 구현 시 `params`는 7.1의 동작별 표를 기준으로 `allOf/if-then`으로 세분화하여 `schema/actions/*.json`으로 분리 관리하고, `while`은 `max_iter`를 필수로 강제함.

### 7.3 실제 인스턴스 예시: 오클루전 탐색 + 복구 (하드코딩 ID 없음)

음성으로 "시계 찾아줘" → `inputs.target = "watch"`로 바인딩되어 실행됩니다. 장애물 ID는 미리 알 수 없으므로 `inspect_region`의 반환값을 변수로 받아 사용합니다.

> **원본 파일**: [`tasks/find_with_unpack.json`](../tasks/find_with_unpack.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* 이 한 파일로 **Unpacking(s7), 미발견 처리(s8 else), Rollback(f1), 서랍 닫기(f2)** 가 모두 표현되며, 중간에 실패해도 `finally`로 복구가 보장됨. Python 코드에는 시나리오 로직이 없음.
* **번들 요청**(`find_list`, `find_class`)은 별도 템플릿 `find_group_by_drawer`로 처리함: `query_ontology`의 `groups[]`를 `for_each`로 순회하여 **서랍당 한 번만 열고**, 서랍 내부에서는 목표 목록이 모두 발견되거나 비워질 때까지 Unpacking 루프를 돈 뒤 복구·닫기.

### 7.4 실행 이력 자동 로깅 스키마 (Execution Log)

각 스텝(중첩 스텝 포함)마다 시작 시각, 소요 시간, 반복 인덱스, 시도 횟수, **성공 여부·결과 코드, 에러 정보, 조건 확인 결과(`pre_check`), 상태 변화(`state_diff`)**를 기록합니다. 플래너가 만든 실행은 `plan`(스킬 조합)도 함께 기록합니다.

> **원본 파일**: [`contracts/examples/execution_log.json`](../contracts/examples/execution_log.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* `overall_status`: `COMPLETED`(시퀀스 정상 종료) / `FAILED`(스텝 abort, `finally` 실행됨) / `ABORTED`(사용자 취소·비상정지).
* `outcome`: 작업 결과 의미(`FOUND` / `NOT_FOUND` / `PARTIAL`)는 상태와 분리하여 기록.
* **시간 규칙**: `total_duration_sec`는 실행 전체의 **실제 경과 시간(wall-clock)**. 제어 블록(`while`/`if`)의 소요 시간은 자식 스텝을 포함하므로 합산에서 제외하고, **원자 동작(리프) 스텝 소요 시간의 합 ≤ `total_duration_sec`**를 검증함.
* **성공 여부**: 모든 스텝은 `status`(`SUCCESS`/`FAILURE`/`SKIPPED`)를 가짐. 실패 시 `error.code`(7.5 스킬의 `errors` 목록 기준)를 기록.
* **조건 확인**: `pre_check`는 `PASS` / `PRE_UNMET`과 함께 **조건별 결과 배열**(조건, 실제 값, 통과 여부)을 기록. `PRE_UNMET`이면 동작을 보내지 않음.
* **성공 판정**: 스텝 성공 = **액션 결과 성공 AND 사후 관측 확인(`post_check`) 통과**. 관측 기준은 스킬의 `verify`(그리퍼 폭, 서랍 변위, 재스캔). 액션은 성공했지만 관측이 안 맞으면 `POST_UNCONFIRMED`로 실패 처리.
* **안전 게이트**: 실물 실행 전 8단계 게이트(11장)의 단계별 통과 여부를 `runs` 헤더에 기록.
* **상태 변화**: `state_diff`는 `{상태 경로: [이전 값, 이후 값]}`. 관측으로 고친 경우 `STATE_MISMATCH` 항목으로 따로 표시.
* **플래너 실행**: 헤더에 `goal`과 `plan`(스킬 조합 목록), 스킬 단위 기록과 그 아래 원자 동작 기록을 함께 저장.
* **저장**: 스텝이 끝날 때마다 `LogStore`를 통해 MongoDB(`runs`·`steps`·`states` 컬렉션)에 저장. `runs` 헤더에는 **온톨로지 파일 해시**, STT 원문, LLM 원문 응답, 안전 게이트 결과를 포함. DB 연결 실패 시 **JSONL 파일로 자동 폴백**하여 시연이 멈추지 않게 하고, 제출·발표용으로 `logs/*.json`도 내보냄. 원시 토픽(카메라·조인트)은 rosbag2(MCAP)로 별도 녹화.
* 위 예시는 지면상 일부 스텝만 표기. 실제 로그에는 `finally` 스텝을 포함한 모든 스텝이 기록됨.
