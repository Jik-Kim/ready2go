# 플래너: 명령 → 스킬 조합

> 아래 내용은 requirements.md의 요구사항에 따른 설계·계약 설명입니다. 문서의 존재나 현재형 표현만으로 구현 완료를 의미하지 않으며, Phase·완료 기준은 requirements.md를 따릅니다. 실제 연결 여부는 담당 코드와 작업 기록에서 확인합니다. [문서]

> 관련 요구사항: [FR-PLN-02–03](requirements.md#fr-pln-02), [FR-ONT-02–03](requirements.md#fr-ont-02). 플래너 알고리즘과 실행 상세는 이 문서에서 다룹니다.

## 7. 로봇 온톨로지 및 JSON 규격 (일부)

### 7.7 플래너: 명령 → 스킬 조합 (담당 C)

기준(목표에서 스킬 순서 생성·계획 불가 시 원인 반환·Phase)은 정본 [FR-PLN-02](requirements.md#fr-pln-02)·[AC-PLN-01](requirements.md#ac-pln-01). 이 절은 C 현재 구현(BFS·근거·`plan_limits`)과 예시.

```
음성 명령 → LLM(6.4)이 목표 추출: goals = [{predicate: located_in, subject: lip_balm, value: drawer_bottom}]
         → 플래너: 현재 state에서 primitive 스킬을 너비 우선 탐색(BFS)하여 목표를 만족하는 최단 조합 탐색
            (기본 목표에 "이번 계획에서 연 서랍은 닫기"를 자동 추가)
         → 계획(7.2 형식 JSON) 생성 → 스키마 검증 → 화면 표시 → Runner 실행
```

**예: "립밤 아래 서랍에 넣어줘"** (립밤은 전달 트레이, 아래 서랍은 닫힘, 그리퍼 비어 있음)

| 순서 | 스킬 | 이 순서가 나온 이유 (조건) |
| :--- | :--- | :--- |
| 1 | `open_drawer(drawer_bottom)` | `place`는 `open.drawer_bottom = true`가 필요. `open_drawer`는 `gripper = empty`가 필요하므로 **집기 전에** 열어야 함 |
| 2 | `pick(lip_balm, handover_zone)` | `place`는 `gripper = lip_balm`이 필요 |
| 3 | `place(lip_balm, drawer_bottom)` | 목표 `located_in.lip_balm = drawer_bottom` 달성 |
| 4 | `close_drawer(drawer_bottom)` | 자동 추가 목표(연 서랍 닫기), `place` 후 그리퍼가 비어 있어 가능 |

* **탐색 범위**: 스킬 수가 10개 안팎인 작은 세계이므로 BFS(깊이 제한 8)로 충분함. 외부 플래닝 라이브러리 없이 Python으로 구현.
* **계획 불가 시**: 어떤 조건을 만족할 수 없는지 설명하여 TTS로 응답(예: "같은 서랍 내부에 가림 물체를 옮길 빈 공간이 없어 실행할 수 없습니다").
* **이미 만족된 목표**: 계획 길이 0 → "이미 아래 서랍에 있습니다" / "이미 닫혀 있습니다"처럼 상태를 근거로 응답.
* **실행 중 실패 시 재계획 — 미구현 (설계)**: 스텝이 실패하면 관측으로 갱신된 상태에서 1회 재계획, 그래도 실패하면 안전 정지. **현재 구현(#151·#154)은 실행 전에 1회만 계획**하고, 실행 중 실패는 계획 태스크의 finally(이번 계획이 연 서랍 닫기·빈손이면 홈)로 끝냄. 관측으로 상태를 갱신하는 `verify`(FR-ONT-02, #43)가 먼저 필요.
* LLM 역할(목표만 추출)은 정본 [FR-INT-02](requirements.md#fr-int-02)·[FR-PLN-02](requirements.md#fr-pln-02). 현재 구현: `achieve_goal` 인텐트의 `goals`만 받아 플래너가 순서를 만듦(#154).

**구현 상태 (#150, 10/08)** [코드·시험]
* `ready2go_runner/core/planner.py` — `plan(state, onto, goals)`: primitive 스킬의 `pre`·`effect`로 BFS(깊이 8, 상태 상한 20000). 물품 파라미터 후보는 **목표에 나온 물품과 지금 쥔 물품만**(다른 물품은 목표 달성에 필요 없음), 장소는 world `places`의 클래스(`subClassOf`)로. 결과 `PLANNED`(스텝 + 단계별 근거: 어느 뒤 스텝의 조건이나 목표를 만족시키는지) / `SATISFIED`(이미 만족) / `UNPLANNABLE`(모르는 대상·장소, 어떤 스킬도 못 바꾸는 상태, 깊이 안에 순서 없음)
* 자동 목표: 계획 시작 때 닫힌 서랍은 끝에 닫힘 (명시 목표가 그 서랍의 `open`을 정하면 그것을 따름)
* `to_task(result)`: 계획 → 7.2 태스크(스텝 `p1..pn`, 앞뒤 `p0`·`p(n+1)`은 `plan_done` 표시, 근거는 `description`). finally 는 **계획이 끝나지 못했을 때만** 이번 계획이 연 서랍 닫기(skip), 빈손일 때만 홈. 성공하면 서랍은 계획대로 둠 — "열어 둬" 같은 명시 목표를 finally 가 되돌리지 않음(#151 D·E 리뷰 P1, 시험: 실행이 끝난 뒤 모든 명시 목표가 참). `timeout_sec`은 호출하는 쪽이 설정에서 넘김
* **지원 범위(`limits`)**: 백엔드가 실제로 할 수 있는 파라미터 값만 후보로 써서, 기호상 가능하지만 실물이 못 하는 계획은 만들지 않고 `UNPLANNABLE`("지원 범위 안에서 …") (#154 E 리뷰 P1). 형식 `스킬.파라미터=값|값,…`(`parse_limits`). **현재 실물 기준** [문서: B `skill_server.py`·`poses.yaml` 10/08]: 서랍 `drawer_top`만(`drawer_bottom` 교시 전), 집기는 서랍에서만("트레이에서 집기는 P2"), 놓기는 `handover_zone`만 → 위 예("립밤 아래 서랍에")와 "쥔 채로 끝내기"(트레이 경유)는 **mock(제한 없음)에서만 계획·실행되고 실물 기본 범위에서는 계획 불가**. 실물 범위가 넓어지면 설정만 바꿈
* 위 예("립밤 아래 서랍에 넣어줘")와 P1 전달(`located_in.eraser = handover_zone` → 열기 → 집기 → 놓기 → 닫기)을 시험에서 도출, mock Runner 실행·실패 finally·비상정지 확인
* **음성 연결 (#150 2단계)**: `achieve_goal` 인텐트(E LLM 이 목표만) → Runner 노드가 **현재 상태**로 계획 → 계획됨이면 태스크로 실행(실행 기록 헤더 `plan`에 단계별 근거, `inputs.goals`), 이미 만족·계획 불가면 실행하지 않고 `/runner/status` `last_intent` `hold`/`PLAN_SATISFIED`·`UNPLANNABLE`(근거는 콘솔 `[plan]` 줄). 이 기록은 **보류 사실**이고, 사람에게 읽어 주는 안내는 E 음성 쪽 후속(#154). Runner 는 `plan_limits`(기본 = P2 실물 지원 범위 `planner.DEFAULT_PLAN_LIMITS` — 위·아래 칸, 서랍은 한 번에 하나만)로 계획 — 서랍 안에 놓기는 범위 밖이라 "립밤 위 서랍으로 옮겨"는 계획 불가로 보류, "지우개 트레이에 갖다 놔"(P2 단일 배치에서 지우개는 아래 칸)는 계획·실행. 예: "립밤을 쥔 채로 끝내기"는 쥔 채로 서랍을 못 닫으므로 트레이에 잠깐 놓고 서랍을 닫은 뒤 다시 집는 순서를 **제한 없는(mock) 범위에서** 스스로 찾음(실물은 트레이 집기 미지원이라 계획 불가)
* **묶음 스킬(언패킹) 계획 — core·mock 구현, 노드 미연결 (#302 E 결정 10/15, C 권고 2안)**: `plan(..., composites=True)` 이면 계획 전용 `plan_effect`(목록)와 `task` 가 있는 composite 도 후보 — 예 `handover_with_unpack(target, from)`(실제 effect `"sensing"`, 안은 `find_with_unpack`; pre = 빈손·`located_in(target)==from`·`open(from)==false`, plan_effect = `located_in(target)=handover_zone` — E 온톨로지 PR 대기, 시험은 E 제안 형식의 복사본). BFS 가 짧은 쪽을 골라 "지우개 갖다주고 위 서랍 열어 둬" = `handover_with_unpack(eraser, drawer_bottom)` → `open_drawer(drawer_top)` 2단계. 한 번에 서랍 하나 규칙을 묶음 진입에도 적용(다른 서랍이 열려 있으면 먼저 닫는 계획). 기본 `composites=False`(노드 `achieve_goal` 은 지금 그대로 primitive 만), `to_task` 는 묶음 스텝을 거부(Runner 가 composite 를 `UNKNOWN_SKILL` 로 거부하므로). 실행은 `core/plan_exec.run_plan`: 계획 맨 앞이 묶음이면 그 태스크 단독 실행, 아니면 다음 묶음 전까지 primitive 를 `to_task` 한 번 → 구간마다 **실제 Runner 상태**에서 처음 목표 + 처음 상태 기준 자동 닫힘 목표로 다시 계획. `plan_effect` 는 실제 상태에 쓰지 않고, 묶음이 COMPLETED 여도 실제 상태가 plan_effect 를 만족하지 않으면 `PLAN_EFFECT_UNMET` 로 멈춤. 실패·정지·복구 실패 표식이면 후속 구간 없음(#371 규칙 재사용 — 도는 동안 재개 보존 끔·잠금 유지), 전달 뒤 후속 실패는 전달 상태 그대로 전체 FAILED + 그 코드, 상태 변화 없음·구간 수 상한(6) 안에 목표를 못 이루면 `PLAN_NO_PROGRESS`(마지막 구간에서 이루면 `COMPLETED`, 마지막 구간 직후 정지면 `ABORTED` + 정지 코드 — #373 E 리뷰). 남는 제한: 묶음 안은 블랙박스(치울 물건은 플래너가 안 고름), 묶음마다 서랍을 열고 닫음, 묶음 안 재개 없음. 노드 연결(`achieve_goal` → `run_plan`, 수락 `run_id`·음성 후속 안내 상관)은 별도 [실측: mock `test_plan_exec.py` 11 — 판 밑 지우개 장면에서 판 치우기→전달→판 원위치→위 서랍 열기]
* **아직 아님**: 실행 중 실패 시 재계획(관측 기반 상태 #43 뒤), 실물 검증(10/12). 현재 공통 `pick`은 서랍 전용 동작(탑뷰·끌기)이라 트레이에서 집기는 B·E 확인 필요(#150)

**AC-PLN-01 목표형 명령 시험표 (#150)** — 명령·목표는 [E 선정 5종](https://github.com/Jik-Kim/ready2go/issues/150#issuecomment-6095722634)(E-150-GOAL-CATALOG-20261010-01). [실측: 시험 `test_planner_catalog.py`] 계획·근거·mock 실행 뒤 상태. **실물 결과 칸은 10/12 실물 기록**으로 채움(mock 통과·계획 성공은 실물 결과가 아님)

실물 지원 범위 = Runner `plan_limits` 기본값 `planner.DEFAULT_PLAN_LIMITS`(시험이 같은지 확인, `RUNNER_PLAN_LIMITS` 로 바꿈): 서랍 `drawer_top`·`drawer_bottom` — **한 번에 하나만 엶**(`open_drawer.one_open=true`, 위 칸이 열리면 아래 칸 위를 덮어 두 칸을 같이 열고 집는 계획을 만들지 않음), 서랍에서 집기, `handover_zone`에 놓기 [B 확인 필요 — 아래 칸 열기 교시·S2 꺼내기 실물 10/12]. 시작 상태는 사용자 확정 P2 단일 배치(위 칸 S1 `toy_wrench`·`caramel_box`·`car_key`, 아래 칸 S2 `cover_plate`·`eraser`·`lip_balm`, #283)를 시험이 직접 정함.

| # | 명령 | 시작 상태 (실물은 관측으로 확인) | 목표 | 생성 계획 — 단계별 근거 | mock 실행 뒤 상태 | 실물 결과 |
| :---: | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 지우개 트레이에 갖다 놔 | 두 서랍 닫힘, 지우개 **아래** 서랍, 빈손 | `located_in.eraser = handover_zone` | 아래 열기(집기 조건) → 집기(놓기 조건) → 놓기(**목표**) → 아래 닫기(자동 목표: 연 서랍 닫기) | 목표 참, 두 서랍 닫힘, 빈손 | 10/12 (당시 위 칸 배치) |
| 2 | 위 서랍 열어 둬 | 위 서랍 닫힘, 빈손 | `open.drawer_top = true` | 열기(**목표**) | 목표 참, 서랍 열림, 빈손 | 10/12 |
| 3 | 위 서랍 닫아 | 위 서랍 **열림**, 빈손 | `open.drawer_top = false` | 닫기(**목표**) | 목표 참, 서랍 닫힘, 빈손 | 10/12 |
| 4 | 지우개 갖다 놓고 서랍은 열어 둬 | 1과 같음 | 1 + `open.drawer_top = true` | 아래 열기 → 집기 → 놓기(**목표**) → 아래 닫기 → 위 열기(**목표**) — 서랍은 한 번에 하나만이라 아래 칸을 닫은 뒤 위 칸을 엶 | 두 목표 참, 위 열림·아래 닫힘, 빈손 | 10/12 (당시 위 칸 배치) — 목표 문구("서랍" = 위 칸)는 E 선정 그대로 |
| 5 | 립밤 트레이에 갖다 놔 | 1과 같음(물품 립밤, 아래 서랍) | `located_in.lip_balm = handover_zone` | 1과 같은 순서 | 목표 참, 두 서랍 닫힘, 빈손 | 10/12 — **B 립밤 파지 확인 선행**(불가 시 E 대체 선정) |

별도 시험 (5종 실물 기록을 대체하지 않음 — 로봇 동작 0, 태스크를 만들지 않음):

| 명령 | 결과 | 이유 (플래너 응답 요지) |
| :--- | :--- | :--- |
| 지우개 서랍에 둬 (이미 있음) | 이미 만족 | `이미 만족: located_in.eraser = "drawer_bottom"` |
| 위 서랍 닫아 (이미 닫힘) | 이미 만족 | `이미 만족: open.drawer_top = false` |
| 트레이의 지우개 서랍에 다시 넣어 | 계획 불가 | 지원 범위 안에 순서 없음 — 트레이에서 집기·서랍 안에 놓기 미지원 |
| 립밤 위 서랍으로 옮겨 | 계획 불가 | 지원 범위 안에 순서 없음 — 서랍 안에 놓기 미지원(`place.to` = `handover_zone` 만) |
| 전달 트레이 닫아 | 계획 불가 | 순서 없음 — 트레이 `open`을 바꾸는 스킬이 없음 |

* 실물 때 확인할 것: 시작 상태는 저장 상태가 아니라 **관측**(서랍 열림·그리퍼 빈손 — 실행 시작 전 그리퍼 검사 #23)으로 맞춘 뒤 `/runner/reset_state`. 실행 기록 헤더 `plan`에 위 근거가 남는지, `run_report`로 단계·결과 확인
* 사후 검증(#43 `verify`)은 아직 main 미반영(계약 승인 대기) → 10/12 실물 결과는 스킬 응답 기준 + 사람 확인으로 기록하고, 관측 verify 통과로 적지 않음
* 트레이 집기·재계획·Unpacking 확장은 이번 5종에 포함하지 않음(E 결정). 아래 서랍은 사용자 확정 P2 단일 배치(#283 — 지우개·립밤이 아래 칸)에 맞춰 `plan_limits` 기본에 넣음(10/13, E #283 리뷰 요청) — 서랍 열기·닫기·집기만, **한 번에 하나만**, B 확인 필요(아래 칸 열기 교시 10/08·S2 꺼내기 실물 10/12). P3 다중 서랍 동시 작업은 범위 밖

