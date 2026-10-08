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
| `inspect_region` | `region`: 서랍 ID, `"staging_tray"`, `"handover_zone"`, `search_target`(클래스명, 선택) | `{target_found, target, candidates[], visible_count}` | 검출 + 3D 위치 + 가림 순서. **의미·정책은 정본** [관측 좌표의 의미](requirements.md#observation-policy)·[가림·추적·복구 정책](requirements.md#occlusion-policy) (FR-VIS-01–03) — 아래는 결과 형식. `target`은 `{id, class, pose, top_z}` 또는 `null`, `candidates`는 목표를 제외한 물체를 **서랍 좌표계 `top_z` 내림차순**으로 정렬(높이순 목록일 뿐 치우는 순서가 아님 — 치우는 순서는 아래 가림 필드 `occluded_by` 관계를 따른다). `pose`는 서랍 좌표계(원점 = 상자 안쪽 바닥 앞쪽 오른쪽 모서리, x 안쪽·y 왼쪽·z 위, 정의는 `config/places.yaml` 첫 부분·#6). **`position` = YOLO 박스 중심의 x·y, z는 항상 0**(높이는 `top_z`에만 둔다). **`yaw` = 물체 긴 변 방향**(서랍 x축 기준 rad), 범위 **(−π/2, π/2]**(긴 변은 180° 돌려도 같은 직선이라 한 범위로 고정, `ready2go_vision.core.pose_rules`), 위에서 본 모양이 정사각형이거나 둥근 물체(판정: `pose_rules.is_symmetric`, [vision.md](vision.md) V2)는 yaw 0 고정. **`yaw_valid`(bool)**: yaw를 믿어도 되는지. 대칭 물체와 정상 산출은 `true`, 덩어리가 비정상(뎁스 결손·너무 얇음 등)이면 `false`이고 이때 `yaw`는 0 자리표시이며 진짜 0°가 아니다. **받는 쪽은 필드가 없으면 `false`로 취급한다**(보내는 쪽은 항상 채운다). 소비자는 `false`이면 길쭉한 물체를 집지 않고 재인식하고, 그래도 `false`이면 오류로 처리한다(에러 코드는 `pick_object` 표 소관). 판정 임계값은 params(yaml)에 두며 `[팀 확정 필요]`. `size_m` 규약은 [ontology.md](ontology.md)의 "치수 계약". `top_z` = 서랍 바닥 기준 물체 윗면 높이. P1은 박스 중심만 제공하며 머리 방향(망치·스패너 등)은 B의 요청이 있을 때 계약 변경으로 추가. yaw 산출 방식(서랍 바닥 위 뎁스 덩어리 + `minAreaRect`, 사용자 확정 10/04)은 [vision.md](vision.md) V2. 박스 중심 픽셀을 서랍 좌표 x·y로 옮길 때는 **`z = top_z/2` 평면**과 교차시킨다(확정, [vision.md](vision.md) V2) **가림 필드 (P2, 계약 [#169](https://github.com/Jik-Kim/ready2go/pull/169) 머지 10/08 · 비전 노드 구현 전, 설계 [#120](https://github.com/Jik-Kim/ready2go/issues/120))**: `target`·`candidates[]` 물체마다 `occluded_by` = 이 물체 **위에 얹혀 일부를 덮은** 물체 `id` 목록(같은 결과 안의 id만, 자기 자신 없음), `[]` = 다 보이고 위에 얹힌 물체 없음, `null` = 모름(마스크 없음·박스 모델, 덜 보이거나 조각났는데 덮은 물체를 결과 안에서 못 찾음, 덮은 물체가 결과에서 빠짐). `visible_area_m2` = **지금 위에서 보이는** 마스크 부분의 넓이(m²): 마스크 픽셀마다 그 픽셀 뎁스 d로 `(d/fx)·(d/fy)`를 더한 값(탑뷰라 서랍 바닥에 거의 평행한 면으로 근사, 뎁스 결손 픽셀은 마스크 뎁스 중앙값). 물체 전체 넓이나 가림 비율이 아니다. `null` = 마스크 없음 또는 마스크 안 유효 뎁스가 없어 계산 불가. **받는 쪽은 필드가 없거나 `null`이면 '모름'**. 보내는 쪽 규칙: 비전 실제 노드와 stub은 **가림 구현 PR부터** 두 필드를 **항상 채운다**(지금은 둘 다 필드 없음)(모르면 `null`, 박스 모델·마스크 없음 포함). **선행 조건(C·E)**: 지금 Runner 변수 해석은 없는 키를 `VAR_UNDEFINED`로 실패시키므로(`ready2go_runner/core/variables.py`, #169 E 재검토 실측: 키 없음 → 오류, `null` → `== null` 참, `[]` → 거짓) 옛 결과·mock 대비 **수신 때 누락 필드를 `null`로 보완**하고 누락/`null`/`[]` 세 경우를 각각 시험한 뒤 태스크에 쓴다. **같은 결과 안의 `id`는 유일하다**(`occluded_by`가 id로 관계 끝점을 가리킴). **치우는 순서**: 정본 [가림·추적·복구 정책](requirements.md#occlusion-policy) — Runner 구현은 아래 `select_obstacle`. **태스크 조건은 `== null`을 먼저 확인하고 `empty` 단독으로 쓰지 않는다** — Runner `empty`는 `null`도 빈 값으로 본다(`conditions._is_empty`). id는 촬영마다 새로 매기므로 같은 결과 안에서만 유효(`restore_stack` 등에 저장 금지). **관계는 순환하지 않는다**(비전이 순환을 만들면 거기 걸린 물체를 `null`로 냄 — 순환이면 맨 위 물체를 정할 수 없음). 위·아래 방향은 맞닿은 경계의 높이로 판정하며 **`top_z` 순서와 같다고 보장하지 않는다**(얇은 물체가 키 큰 물체의 낮은 부분에 얹힌 경우) — 받는 쪽은 `top_z`로 관계를 다시 추정하지 않는다. 판정 방법·한계는 [vision.md](vision.md) 9장, 형식 검사 `pose_rules.result_errors` |
| `nudge_object` | `target`(`inspect_region` 결과의 `target`을 그대로 넘김: `$scan.target` — `id`·`class`·`pose`(`yaw` 포함)·`top_z`), `drawer_id`, `check_only`(선택, bool, 기본 `false`) | `{pushed, push_vector_m, clearance_before_m, floor_z_m, target_after}` (모두 서랍 좌표계 `drawer_<id>`, `inspect_region`의 `pose`와 같은 기준) | **1회 호출 = 1회 끌기.** 옆벽에 붙어 짧은 변으로 못 잡을 때만: 닫은 그리퍼(손끝을 벽 쪽으로 기울일 수 있음)로 물체 윗면을 위에서 눌러 힘 감지(접촉) → **서랍 옆(y)으로만** 끌기 → 올라감. 서랍이 닫히는 방향으로는 끌지 않는다(2 N에서도 서랍이 같이 밀림, B 실측 10/06, #37). 잡을 수 있는 자리면 움직이지 않고 `pushed: false`. `check_only: true`이면 움직이지 않고 판단만 한다. `target_after` = 입력 `target`에서 `pose.position`만 끈 만큼 옮긴 **예상** 위치(형식은 `target`과 같음). **성공일 때만** 채우고 실패면 `null` — 실패 결과의 좌표로 집지 않는다. 예상값이라 재인식이 아니다(FR-ACT-05의 재인식 완료로 보지 않음). 밀었으면 원칙은 다시 `inspect_region` 후 집기, stub 시연(10/06)은 `target_after`를 `pick_object`에 넘김. 결과 예시 `contracts/examples/nudge_object_result.json` (FR-ACT-05, 상세 [domain.md 8.5](domain.md#85-벽-인접-물체-밀어오기-담당-b) — 방식 변경은 시연 후 정리) |
| `pick_object` | 서랍에서: `target`(`inspect_region` 결과의 `target`을 그대로 넘김: `$scan.target` — `id`·`class`·`pose`·`top_z`) / 트레이에서: `source_slot` + `object_id`(인스턴스 ID). 공통: `approach_offset`, `grip_force`(선택, 기본 = 온톨로지 값) | `{object_id, class, pick_pose_drawer_frame, grasp_ok}` | 접근 → 파지 → 안전 높이 상승. 접근 위치는 `pose.position` x·y, 손목 회전은 `pose.yaw`, **파지 높이는 서랍 바닥(`places.yaml` tf) + 온톨로지 물체 높이**(`top_z`는 검산용, #18). 서랍에서 집을 때는 움직이기 전에 인출 거리 → `yaw_valid` → 바닥 위(`top_z`)를 확인하고 걸리면 움직이지 않고 에러(아래 표) |
| `place_object` | (복구·지지면 정책은 정본 [가림·추적·복구 정책](requirements.md#occlusion-policy), FR-ACT-04 — 이 행은 #166 계약 형식과 B 첫 구현 범위) 트레이: `location`: `"handover_zone"`(빈 칸 자동 할당, P1 구현) / **서랍 안(P2, #120 ② 계약 [#166](https://github.com/Jik-Kim/ready2go/pull/166) 머지 10/08 · B 스킬 서버 구현 전 — 지금은 `UNSUPPORTED_PARAMS`)**: `location`: 서랍 ID(`drawer_top`·`drawer_bottom`) + `pose`(서랍 좌표계 `{frame, position, yaw}` — `inspect_region` `target.pose`와 같은 기준: `frame` = `location`, `position` z = 0, `yaw` (−π/2, π/2], `yaw_valid` 없음) **또는** `slot`(교시한 고정 빈 자리 이름, `config/places.yaml` `<서랍>.place_slots` — `aside_1`·`aside_2`, B) — **둘 중 정확히 하나**(둘 다·둘 다 없음은 `BAD_PARAMS`), `position` x·y·`yaw`는 유한한 수 + **`scan`**(필수, 직전 `inspect_region` 결과 **전체**를 그대로: `$scan`. B는 `target`(찾았으면)과 `candidates`를 **모두** 이웃으로 검사 — `candidates`에는 `target`이 빠져 있어 그것만 넘기면 서랍에 남은 목표와 겹쳐도 통과함, #166 D 리뷰 P1) | `{slot, placed_pose}` (+ 거부 시 `blocked_by`) | 쥔 물체(스킬 서버가 `pick_object`에서 기억)를 지정 위치에 내려놓고 그리퍼 해제. 서랍 안: **움직이기 전에** 놓을 자리의 footprint(쥔 물체 온톨로지 `size_m` + 손가락 폭 + 여유 `[팀 확정 필요]`, `pose.yaw` 방향)가 서랍 벽·`scan`의 `target`·`candidates` 각 footprint(온톨로지 `size_m`, 클래스 치수 없으면 params 기본값)와 겹치는지 B가 확인해 겹치면 거부(아래 표). 쥔 물체와 같은 `id`의 이웃은 무시. 놓는 높이 = 서랍 바닥(`places.yaml` tf) + 쥔 물체 높이(+ `place.drop_m`) — 놓기 직전 재촬영 없음. **지지면은 서랍 바닥만**(B 첫 구현 범위 — 정본 지지면 기준과의 차이는 #134 협의 항목, #166 E 리뷰): 다른 물체 위로 되돌리기는 지원하지 않음 — 그 자리에 물체가 있으면 겹침 검사로 `PLACE_BLOCKED`, 없으면 바닥에 놓여 원래 높이와 달라짐(C 가 원래 관측 `top_z`와 비교해 AC-ACT-03 미달로 기록). **`scan`은 쥔 물체를 집을 때 쓴 `target`이 나온 같은 촬영 결과**를 넘김(그래야 쥔 물체 `id`가 같음) — 되돌리기는 C 가 고정 자리의 물체를 집기 전에 다시 찍고, 그 결과로 집고 그 결과를 놓기에도 넘김. B 는 쥔 물체 `id`가 `scan`에 없으면 `BAD_PARAMS`(다른 촬영 결과). `placed_pose` = **B가 놓으라고 명령한 자리**(서랍이면 위 pose 형식, 트레이면 칸 중심 `{frame, position}`)이며 재인식이 아님 — 실제 놓인 위치는 `inspect_region`으로만 안다(놓기 오차·미끄러짐). **그리퍼를 연 뒤에만** 채우고, 열기 전 실패면 `null`(연 뒤 올라오기 실패는 그 오류 + `placed_pose`). Runner 는 실패한 스텝의 결과(`output`)도 스텝 기록 `result`에 남김(#167, 블랙보드에는 넣지 않음 — 뒤 스텝이 실패 값을 성공 값으로 쓰지 않게) → 연 뒤 실패의 `placed_pose`는 실행 기록으로 확인. 그 전에도 B 쪽 중복 놓기는 없음 — 연 뒤에는 쥔 물체 기억을 지워 다시 보내면 `NOT_HOLDING`. `slot` = 트레이 칸·고정 자리 이름, `pose`로 놓으면 `null`. 예시·규칙 `contracts/examples/place_object_result.json`(`validate_contracts.py` 검사). ~~`frame: "drawer"`·배치 직전 재촬영 z 보정·`location`=서랍이면 `return_slot` 자동 적용~~ (구현된 적 없음 — 위 계약안으로 대체, #120) |

* **ID 규칙**: `object_id`·`target.id`는 비전이 부여한 **인스턴스 ID**(예: `eraser#1`, `unknown#3`), `search_target`과 온톨로지 키는 **클래스명**(예: `eraser`). 둘을 섞지 않음.
* **포즈 vs 위치**: `pose_name`은 로봇 관절 포즈, `location`은 월드의 물체 거치 장소. 이름 공간을 분리함.

**② 지식/상호작용 동작**

| 동작명 (`action`) | 주요 파라미터 | 반환값 | 설명 |
| :--- | :--- | :--- | :--- |
| `query_ontology` | `item` / `list` / `class` / `state`(상태 경로) 중 하나 | 단일: `{item, name_ko, drawer_id, grip_force}` / 다중: `{items[], groups[{drawer_id, items[]}]}` / 상태: `{path, value}` | 물품 위치, 리스트·클래스 구성, 현재 상태 조회 (다중 결과는 서랍별로 묶어 반환) |
| `update_ontology` | `item`, `drawer_id`, `pose`(선택) | - | 발견된 실제 위치로 지식 베이스 갱신 |
| `select_obstacle` | `scan`(직전 `inspect_region` 결과 전체 `$scan`), `moved`(선택, 치운 기록 목록 `$restore_stack`), `tol_m`(`moved` 대조 거리 m, `[팀 확정 필요]`), `prefer`(선택, 사용자가 고른 class) | `{obstacle, reason, excluded[], held_back[]}` — `obstacle` = 치울 물체(`scan`의 후보 그대로, 없으면 `null`), `reason` = `occluded_by`·`overlap_higher`·`largest_visible`·`highest`·`prefer` / 없을 때 `target_clear`·`occluder_unavailable`·`occlusion_unknown`·`none`. `moved`가 있는데 `tol_m`이 0보다 큰 유한한 숫자가 아니거나 기록이 객체가 아니면 `BAD_PARAMS` | **P2, 계약 [#176](https://github.com/Jik-Kim/ready2go/pull/176) 머지 10/08 (E 리뷰 전 C 판단으로 병합, 사후 검토 대기) · Runner 구현됨 · 실물 태스크 연결 전** (#120·#109). **정책은 정본 [가림·추적·복구 정책](requirements.md#occlusion-policy)** — 아래는 C 현재 구현. Runner 안에서 처리(로봇 동작 없음, `core/unpack.py`). 치울 순서: ① 목표 `occluded_by`에 물체 → 덮은 물체를 따라 맨 위(`[]`)부터 — 사슬 중간에 결과에 없는 물체(옮김·미검출)·모름(`null`)·고리가 있으면 고르지 않고 `occluder_unavailable`(#176 D 리뷰) ② 목표 다 보임 확인(`occluded_by == []`, 또는 박스 모델 = 결과 전체에 가림 필드 없음 + `pose.yaw_valid` true, P1 호환)이면 치울 것 없음(`target_clear`) ③ 목표 관계 모름(`null`, 분할 모델 결과에서 필드 누락, 박스 모델 + `yaw_valid` 아님) → 목표 footprint(온톨로지 `size_m`·`yaw`)와 겹치고 `top_z`가 더 높은 것 — **후보 자신은 위에 아무것도 없다고 확인된 것만**(분할 모델 `occluded_by == []`, 박스 모델은 전부). **고를 후보가 없으면 `occlusion_unknown` — 모름을 '다 보임'으로 바꾸지 않으므로 태스크는 목표를 집지 않음**(#182 D·E 리뷰). ③은 **비전 관계를 모를 때의 C 실행 대안 = 짐작**이며 가림 관계 판정·GT 정답이 아님(AC-VIS-02 평가에 쓰지 않음) ④ 목표 못 찾음 → `occluded_by == []` 중 `visible_area_m2` 큰 것. 박스 모델만 `top_z` 높은 것, 분할 모델인데 `null`·덮임·누락뿐이면 고르지 않음(`occlusion_unknown`). 한 결과에 가림 필드가 하나라도 있으면 분할 모델로 보고 필드가 빠진 물체는 '모름' — **이 판단은 옮긴·보류한 물체를 빼기 전 촬영 결과 전체로 한 번만**(#134 E 18:30 P1). `moved` 의 물체와 같은 것(`find_moved` 규칙으로 찾음)은 다시 치우지 않고(`excluded`), 확정 못 하면 그 class 는 고르지 않음(`held_back`). `prefer`는 같은 규칙의 후보 안에서만 순서를 바꿈. 파지·놓기 안전 판단의 책임은 정본을 따름 |
| `find_moved` | `scan`(`$scan`), `record`(치운 기록 1건 `{class, origin, placed}`), `tol_m` | `{status, object, distance_m}` — `status` = `found`(같은 class 1개가 `placed` 에서 `tol_m` 안, `object` = 그 후보) / `ambiguous`(같은 class 2개 이상 또는 `tol_m` 밖) / `missing`(없음) | **P2, 계약 #176 머지 10/08 · Runner 구현됨 · 실물 태스크 연결 전** (#109 재식별). **정책은 정본 [가림·추적·복구 정책](requirements.md#occlusion-policy)**(재식별·첫 시연 범위·모호할 때) — 아래는 C 현재 구현. Runner 안에서 처리(로봇 동작 없음). `target`도 대조. 같은 class 2개 이상은 `ambiguous`(첫 시연 범위 밖) → 태스크는 그 물체를 두고 기록. `tol_m` = 비전 오차 + 놓기 오차(B 실측) + 여유 `[팀 확정 필요]`. 형식 오류·`tol_m` 없음은 `BAD_PARAMS` |
| `speak` | `text` | - | TTS 음성 피드백 |

**③ 제어 블록 (Runner가 해석, 코드에는 시나리오가 들어가지 않음)**

| 블록 | 필드 | 설명 |
| :--- | :--- | :--- |
| `set_var` | `params.name`, `params.value` | 블랙보드 변수 설정 |
| `push` / `pop` | `params.stack`, `params.value` / `params.stack` + `output` | 리스트형 변수를 LIFO 스택으로 사용 (Rollback용). `value`가 null 참조면 `VAR_NULL`(엉뚱한 자리로 복구 금지), 빈 스택 pop 은 `STACK_EMPTY` — **P2 구현** |
| `if` | `cond`, `then[]`, `else[]` | 조건 분기 |
| `while` | `cond`, `body[]`, `max_iter`(필수) | 조건 반복. `max_iter`번 돈 뒤에도 조건이 참이면 `LOOP_LIMIT` 에러. 기록: 블록 `iterations`, 안쪽 스텝 `iteration`(회차) — **P2 구현(10/08)** |
| `for_each` | `in`, `as`, `body[]` | 리스트 순회 (번들 요청 처리). `in`이 리스트가 아니면 `NOT_A_LIST` — **P2 구현** |
| `fallback` | `options[]` (각 항목은 스텝 배열) | 첫 대안부터 시도해 하나라도 성공하면 성공 (예: `pick_object`가 `YAW_INVALID`로 동작 없이 거절 → 다른 접근). **다음 대안은 앞 대안이 로봇을 움직이지 않았음이 확인된 실패일 때만** 보냄(스킬 재시도와 같은 규칙, #159 E 리뷰): 그 대안에서 팔을 움직이는 동작을 보냈으면 성공한 이동 뒤 인식 실패라도 멈춤(`fallback_stopped: MOTION_UNCERTAIN`), 결과 불확실이면 그 이유(`TIMEOUT`·`LATE_RESULT`·`RESPONSE_LOST`). 움직이지 않았다고 보는 실패: 팔을 움직이지 않는 동작(`inspect_region`·`speak` 등)의 실패, 사전 조건·변수 오류, 그 동작의 "움직이기 전 거부" 코드(`NO_MOTION_BY_ACTION`, 예: `place_object`의 `PLACE_BLOCKED` → 다른 고정 자리). 모두 실패하면 마지막 코드. 기록 `option`(성공한 대안 번호) — **P2 구현** |
| `finally` (태스크 최상위 필드) | `finally[]` | `sequence`가 성공·실패 어느 쪽으로 끝나도 실행 (복구·서랍 닫기·홈 복귀) |
| `on_halt` (태스크 최상위 필드) | `on_halt[]` | 사용자 취소·비상정지 시 실행. **로봇 동작 없이** 상태 저장·로그·TTS 안내만 수행 — **미구현: 있으면 실행 전 거절(`TASK_INVALID`)** |
| 스텝 공통 필드 | `timeout_sec`, `recovery[]` | `timeout_sec` 초과 시 `TIMEOUT` 실패. 실패 시 `recovery[]`(예: 그리퍼 열고 후퇴)를 실행한 뒤 `retry` 횟수만큼 재시도 — **`recovery`는 미구현: 있으면 실행 전 거절(`TASK_INVALID`)**, `timeout_sec`은 구현 |

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
* `eval`을 사용하지 않고 Runner가 경로를 해석함. 존재하지 않는 변수는 `VAR_UNDEFINED` 에러. 로봇·백엔드로 보내는 동작(`set_var`·`if`·`speak`·`query_ontology`·`update_ontology` 제외)의 params 값 전체가 `$변수` 참조인데 `null`이면 보내지 않고 `VAR_NULL` 에러(예: 실패·누락된 `target_after`로 집기, #23).
* **P2 제어 블록과 비상정지** (10/08 구현): `while`·`for_each`·`push`·`pop`·`fallback`은 로봇을 움직이는 블록을 감싸므로, 중단(ABORTED) 뒤 finally 에서는 블록째 `SKIPPED` — 역순 복구 반복도 자동으로 하지 않고 `restore_stack`은 블랙보드·실행 기록에 남겨 사람이 확인한다. 반복 안 스텝은 같은 ID 로 회차마다 기록되고 `iteration`(가장 안쪽 반복의 회차)으로 구분(`run_report` `[s2.1 · 2회차]`). 보고서는 스킬 하위 동작을 기록 순서(`seq`)상 바로 앞의 같은 ID 스킬 기록에 붙이므로 중첩 반복에서도 섞이지 않음(#159 E 리뷰).
* **변수 스코프 (블랙보드)**: `output`·`set_var`로 만든 변수(`loc`, `scan`, `picked` 등)는 **태스크 단위 전역 블랙보드**에 저장되어 `sequence`·`finally`·`on_halt` 어디서든 태스크 종료 시까지 유지됨. 같은 이름으로 다시 `output`하면 덮어씀(예: Unpacking 루프의 `scan`은 재촬영마다 갱신, `loc`은 처음 값 유지). 예외로 `for_each`의 `as` 변수만 루프 안에서 유효함 — 루프가 끝나면(실패 포함) 루프 전 값으로 되돌리고, 없던 이름이면 지움. 중첩 루프가 같은 이름을 써도 바깥 값이 복구됨. 블랙보드는 태스크가 끝나면 사라지고(최종 값은 로그에 기록), **태스크 사이에 이어지는 정보는 상태 온톨로지(7.8)만** 사용함.

**조건식 (단일 형태)**: `{ "op": "<연산자>", "args": [ ... ] }`
* 비교 `==, !=, <, >, <=, >=` (args 2개) / 논리 `and, or` (2개 이상), `not` (1개) / 컬렉션 `empty, not_empty` (1개)

**실패 처리 규칙**
* 스텝별 `on_failure`: `abort`(기본) / `retry`(`retry` 횟수만큼) / `skip` / `safe_home`.
* `abort`로 `sequence`가 중단되면 `finally`가 실행되고 `overall_status = FAILED`.
* **비상정지(E-stop)로 인한 `ABORTED`에서는 `finally`의 로봇 동작을 실행하지 않음.** 사람이 상태를 확인한 뒤 재개 명령으로 복구함.
* `ABORTED` 경로: 백엔드가 `ESTOP`으로 실패하거나 Runner `halt()`(`/runner/estop`·음성 "멈춰")가 호출되면 `retry`·`skip`·`safe_home`을 적용하지 않고 즉시 중단. `halt()`는 진행 중인 액션에 즉시 취소를 요청하고(Runner 노드: `RosClients.cancel_all`), 백엔드가 멈춘 뒤 최종 결과(`canceled`)를 주면 그 스텝에서 `ABORTED`로 끝냄(스텝 기록에는 백엔드 코드, 예: `CANCELED`). 실제로 멈추는 것은 백엔드 책임(PR #74 리뷰). `finally`는 로봇을 움직이지 않는 동작(`speak`·`query_ontology`·`update_ontology`·`set_var`·`if`)만 실행하고 나머지는 `SKIPPED`로 기록(허용 목록이라 새 동작은 기본 생략). 다른 실패와 겹치면 `ABORTED`가 우선. 중단 요청은 스텝 시작·재시도·`safe_home` 직전마다 확인.
  * **중단과 결과 반영의 경계** (PR #64 E 리뷰): 중단 요청이 결과 반영 전에 들어오면 반영하지 않음. `skill`은 `effect` 직전에 확인해 상태를 바꾸지 않고 스킬을 `FAILURE`(`HALTED`)로 기록(하위 원자 동작은 받은 응답대로 기록). 원자 동작은 응답대로 기록하되 다음 동작을 보내지 않음. 마지막 스텝 도중의 중단도 `COMPLETED`가 아니라 `ABORTED`. 반영되지 않은 결과는 사람이 확인한 뒤 재개(중단 잠김). `halt()`와 effect 반영(중단 확인 → 상태 갱신)은 같은 잠금으로 묶어, 다른 스레드의 중단 요청은 반영 전이면 반영하지 않고 반영 중이면 반영이 끝난 뒤 적용(그 스킬은 완료로 기록).
* **중단 잠김**: `ABORTED` 뒤에는 Runner `resume()`(사람이 상태 확인 후 재개 명령)을 부르기 전까지 새 태스크를 로봇 동작 없이 `ABORTED`로 거절하고, 처음 멈춘 이유(`ESTOP`/`HALTED`)를 돌려줌.
* **재개 대기 (#152, P2 — 기준은 정본 [FR-SAF-03](requirements.md#fr-saf-03)·[AC-SAF-04](requirements.md#ac-saf-04), 잠금 해제만으로 단계 재개 완료가 아님은 [실행 원본과 구현 증빙의 경계](requirements.md#runtime-sources))** — 세 단계를 구분: ① **잠금 해제** `resume()` = P1 부터 있는 core 함수(ROS 통로 없음, 지금은 Runner 재시작으로 풀림) ② **단계 재개 core** = 아래 내용, PR #170 머지 10/08, 기본 꺼짐(`resumable=False`) ③ **운영 연결**(`/runner/status` `halt`·인텐트 `recover`·`resume`·`/skills/recover`·그리퍼 관측) = **미구현**, #152 C 계약안 v0·v1 승인 대기. ②: `Runner(resumable=True)`일 때 `sequence` 중 중단되면 실행을 끝내지 않고 보존(`overall_status: SUSPENDED`, finally 미실행). 정지마다 새 정지 사건 ID(`halt_event_id`). `resume()`(복구 뒤 잠금 해제) 후 `resume_window_sec`(기본 30 s `[팀 확정 필요]`) 안에 같은 사건 ID 로 `resume_run()` → **중단된 스텝을 처음부터** 다시 실행하고 이어 감(끝난 스텝은 다시 보내지 않음, 처음 고른 `if` 분기로 들어감, 같은 `run_id`에 이어서 기록). 중단된 스킬의 effect 는 반영된 적 없으므로 재실행해도 중복 없음. 다만 effect 직전 중단(하위 동작이 모두 끝난 뒤)이면 실물은 이미 동작했을 수 있어, **재실행 전 관측 검사(노드가 `blockers`로 전달 — B 재진입 조건·`/gripper/state`)가 필수**. 거절(`ResumeRejected`, 보존·잠금 그대로): `NOTHING_TO_RESUME`·`HALT_EVENT_MISMATCH`(과거·지연 응답, 복구 뒤 다시 멈춤)·`NOT_RECOVERED`·`RESUME_EXPIRED`·중단 스킬 `pre` 재검사 `PRE_UNMET`·관측 검사 결과. **스텝을 시작한 뒤 멈췄으면 B 재진입 조건**(#152 B 답 10/08, `REENTRY_GRIPPER` [팀 확정 필요]): 서랍 열기·닫기(`drawer_control`)·끌기는 항상 거절(`REENTRY_BLOCKED` → 사람 정리 → `reset_state`), 집기는 관측한 그리퍼가 빈손일 때만, 놓기는 아직 쥐고 있을 때만(열려 있으면 놓은 것으로 봄). 관측(`observed={"gripper": …}`, 노드가 `/gripper/state` 로)이 없으면 `STATE_UNOBSERVED`. 스텝 시작 전에 멈췄으면(앞 스텝은 끝남) 부분 동작이 없어 조건 없음. 보존 중 새 태스크는 `RESUME_PENDING`으로 거절. `discard_suspended()`("아니"·시간 초과·상태 초기화) → 지금처럼 `ABORTED`(finally 비동작만). 반복·`fallback` 안에서 멈추면 재개 위치를 보장할 수 없어 보존하지 않고 바로 `ABORTED`. 실행 문서 `halts[]`(`event_id`·`code`·`step`·`at`·`resumed_at`/`discarded_at`), `run_report` "⏸ 재개 대기". 기본값(`resumable=False`)은 이전과 같음.
* `retry` 횟수는 `on_failure: "retry"`일 때만 쓰며 1 이상이어야 함(아니면 실행 전 검사에서 거절). `skip`된 스텝은 `FAILURE`와 에러 코드를 그대로 기록하고 다음 스텝으로 진행. `safe_home`은 `home` 포즈로 이동한 뒤 중단.
* `finally` 스텝도 각자의 `on_failure`를 따름(기본 `abort`면 이후 `finally` 스텝은 실행되지 않음). `sequence`와 `finally`가 모두 실패하면 `sequence`의 원인을 태스크 실패 원인으로 남김.
* `timeout_sec`: `Skill` goal 에는 제한 시간 칸이 없으므로 Runner(ROS 클라이언트)가 시간이 지나면 **취소를 요청하고, 백엔드가 멈춘 뒤 최종 결과를 줄 때까지 기다린 다음** `TIMEOUT`으로 끝냄(#10, PR #74 리뷰) → `finally` 복구 동작이 앞 동작과 겹치지 않음. 취소 뒤 5초 `[추정]` 안에 최종 결과가 없으면 `STOP_UNCONFIRMED`: 멈췄는지 알 수 없으므로 `ESTOP`처럼 `ABORTED`·잠금, 사람 확인 전 새 동작 없음. 최종 결과가 와도 그 코드가 잠금 대상(아래 표의 `ESTOP`·`STOP_UNCONFIRMED`·B 서버 잠금 코드)이면 `TIMEOUT`으로 덮지 않고 그대로 잠금(PR #74 E 리뷰).
  * **goal 수락 응답이 늦을 때** (PR #74 D 리뷰): 5초 `[추정]` 안에 수락 응답이 없으면 "보내지 않음"으로 보지 않고, 늦게라도 수락되면 즉시 취소하고 정지 확인 뒤 `TIMEOUT`, 끝내 확인이 안 되면 `STOP_UNCONFIRMED`. 서버를 찾는 사이 중단 요청이 들어오면 goal 을 보내지 않음(`HALTED`). 중단 처리 뒤 `finally`의 비동작(`speak` 등)은 막지 않음. **실제로 멈추는 것은 백엔드 책임**(아래 "백엔드 구현 약속"). Runner는 걸린 시간을 재서 초과하면 결과가 성공이어도 `TIMEOUT`으로 처리. `if` 같은 블록은 끝난 뒤 판정하므로 동작을 끊으려면 원자 동작 스텝에 지정.
  * **늦게 온 결과는 재시도하지 않음** (PR #64 리뷰): Runner 가 판정한 `TIMEOUT`은 결과가 도착한 뒤라 동작이 실제로 끝났을 수 있으므로, `retry`가 있어도 같은 동작을 다시 보내지 않고 실패로 끝냄(기록 `retry_stopped: "LATE_RESULT"`). 취소 요청으로 끝난 `TIMEOUT`도 같음(`retry_stopped: "TIMEOUT"`). 단, **팔을 움직이지 않는 원자 동작**(`inspect_region`·`speak`·`query_ontology` 등)은 끝났어도 다시 해도 되므로 `TIMEOUT`·늦은 결과여도 `retry`대로 다시 보냄(#168, 인식 다시 찍기). 팔을 움직이는 동작을 보내다 백엔드 예외(보낸 뒤 응답 끊김 가능)가 나면 `BACKEND_ERROR`이되 다시 보내지 않음(`retry_stopped: "RESPONSE_LOST"`, #159 E 리뷰). 백엔드가 실패를 돌려준 경우의 재시도는 그대로.
* **실행 전 검사**: 스키마(7.2) + 현재 Phase 범위 밖 블록·필드 거절 + `set_var`의 `name`·`if`의 `cond`·스텝 ID 중복·`retry` 횟수 확인. 문제가 있으면 로봇을 움직이지 않고 `TASK_INVALID`(문제 목록 포함), `finally`도 실행하지 않음.
* **`skill` 스텝 (P1, #12)**: 스텝은 `action`(원자 동작)과 `skill`(온톨로지 primitive 스킬, 7.5) 중 하나. Runner 는 온톨로지를 받아 상태를 들고 있고(태스크 사이에 유지, ontology.md 7.8), 스킬마다 ① `pre` 확인 → 불충족이면 로봇 동작 없이 `PRE_UNMET` ② `expand`의 원자 동작을 차례로 실행(기록 ID `<스텝 ID>.e<n>`, `parent` = 스킬 스텝 ID, 출력은 스킬 안에서만 보임) ③ 모두 성공하면 `effect`로 상태 갱신. 하나라도 실패하면 상태는 그대로.
  * P1 은 **동작 응답 성공 = effect 반영**. `verify`(사후 관측)·`hold`(실행 중 유지 조건)는 P2(FR-ONT-02). P1 Runner 는 `primitive` 스킬만 `skill` 스텝으로 실행(`composite`는 거절). 선언형 복합 스킬 추가는 FR-PLN-03(P3).
  * **스킬 재시도는 로봇이 움직이지 않은 실패에만** (PR #64 D 리뷰 + PR #65 합의): 실패 응답을 받아도 앞 원자 동작이 실행됐거나 동작이 실제로 끝났을 수 있는데 P1 은 관측 확인(`verify`)이 없어 알 수 없으므로, 스킬 전체를 다시 보내면 이미 열린 서랍 재열기·이미 집은 물건 재집기가 될 수 있음. 그래서 `retry`는 ① 실패가 그 원자 동작의 "움직이기 전 거부"가 보장된 코드(`NO_MOTION_BY_ACTION`, 동작별 — 아래 "로봇 동작 공통 에러 코드" 표 전부, `nudge_object`의 `NO_PUSH_ACCESS`, `place_object`의 #166 "움직임 없음" 코드 — **임시**: #166 승인·B 구현·#168 카드 전 계약안 기준, `drawer_control`의 `NOT_AT_START_POSE`·`DRAWER_NOT_CONFIGURED`·`DRAWER_STATE_UNKNOWN`·`DRAWER_ALREADY_OPEN`·`OTHER_DRAWER_OPEN`·`HOLDING_OBJECT`·`BAD_PARAMS`(#181, 코드로 움직이기 전 확인), 집기·끌기의 `BAD_PARAMS`(서랍·좌표 불일치 등). 처음은 `YAW_INVALID` 하나, B PR #66·#168)이고 ② 그 시도에서 앞서 보낸 원자 동작이 모두 팔을 움직이지 않는 동작(`inspect_region`·`speak`·`query_ontology` 등)일 때만 적용. 예: `pick`(살펴보기 → 집기)에서 방향 산출 실패로 `pick_object`가 거절하면 재인식 1회. 그 밖에는 재시도하지 않고 기록에 `retry_stopped`(`MOTION_UNCERTAIN` = 앞서 팔을 움직임, `NOT_RETRYABLE` = 허용 목록에 없는 코드). 재인식 횟수는 태스크 `retry`로 정함 `[팀 확정 필요]`.
  * `timeout_sec`은 스킬 전체 시간(각 원자 동작에는 남은 시간을 전달). 로봇을 움직이므로 `ABORTED` 때 `finally`에서도 `SKIPPED`.
  * 실행 전 검사에서 온톨로지에 없는 스킬, `composite`, 스킬 정의와 다른 `params` 이름(빠짐·모름), 하위 기록 ID 중복을 `TASK_INVALID`로 거절. 실행 중에도 다시 확인(`UNKNOWN_SKILL`·`BAD_SKILL_PARAMS`).

**Runner 에러 코드** (스킬별 에러 코드는 7.5 온톨로지 `errors`)

| 코드 | 의미 |
| :--- | :--- |
| `TASK_INVALID` | 실행 전 검사 실패 (스키마·Phase 범위·필수 필드) |
| `VAR_UNDEFINED` | 존재하지 않는 변수 참조 |
| `VAR_NULL` | 백엔드로 보낼 동작의 `$변수` 값이 `null` → 동작을 보내지 않음 (#23) |
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
| `YAW_INVALID` | `pick_object`(서랍)·`nudge_object` | `target.pose.yaw_valid`가 `true`가 아님(`false`·필드 없음). 다시 인식은 공통 `pick` 안에서 끌기 뒤 1회(E #122). 그 뒤 실패는 팔이 이미 움직였으므로 Runner 가 다시 보내지 않음(`MOTION_UNCERTAIN`). 이력: #65 합의 때는 태스크 retry 로 다시 인식 1회(pick 이 촬영 → 집기만 하던 때) |
| `NOT_ON_FLOOR` | `pick_object`(서랍) | `top_z − 물체 높이`가 허용 오차보다 큼 → 다른 물체 위에 있음(또는 `top_z` 없음). 바닥 + 물체 높이로 내려가면 아래 물체와 부딪히므로 P1은 거부, `top_z` 기준 파지는 P2 |
| `WALL_TOO_CLOSE` | `pick_object`(서랍) | 짧은 변으로 잡으면 손가락·관절이 서랍 벽에 닿는 자리(그리퍼 벌림 폭 + 실측 벽 간섭 거리, `motion_plan.wall_blocks_grasp` — `nudge_object` 판단과 같음). 현재 공통 `pick`(E #122)은 `nudge_object` 뒤 탑뷰에서 **다시 촬영한 `scan.target`**으로 집는다(`target_after`는 예상 위치로 기록만, `knowledge/skills/pick.jsonld`·`test_tasks.py`). 이력: 10/06 추가(#83 A 요청) 때는 `target_after`로 바로 집었음 |

**`nudge_object` 에러 코드** (스킬이 아니라 원자 동작이라 온톨로지 `errors`가 아니라 여기에 둔다. 위 공통 코드도 반환)

| 코드 | 의미 |
| :--- | :--- |
| `NO_FLOOR_CONTACT` | 최대 하강 거리 안에서 바닥 접촉이 없음(서랍 덜 열림·좌표 오류) → 즉시 정지 |
| `NO_PUSH_ACCESS` | `nudge_object`: 끌어도 짧은 변으로 잡을 수 없는 자리 — ① 앞뒤 벽 때문에 막힘(옆으로 끌어도 해결 안 됨) ② 필요한 끌 거리가 최대(`drag.max_shift_mm`)보다 큼 ③ 누를 점이 물체 윗면 밖. 움직이지 않음 → P1은 실패 + TTS 안내(길이 방향 잡기는 P2 후보) |
| `PUSH_BLOCKED` | 밀다가(끌다가) 힘 임계 초과(끼임·다른 물건) |
| `NO_OBJECT_CONTACT` | 끌기: 물체 윗면 예상 높이보다 더 내려가도 접촉(힘)이 없음 — 위치·높이 확인 (10/06 추가) |
| `PUSH_LIMIT` | `check_only: true` 재판단에서 한 번 민 뒤에도 파지 가능한 자리가 아님(P1 Runner는 `while`이 없어 반복 밀기를 하지 않으므로 밀기는 1회로 제한) |

**`place_object` 에러 코드** (원자 동작. 위 로봇 동작 공통 코드도 반환. 서랍 안 놓기 코드는 #166 계약 머지 10/08 · B 구현 전)

| 코드 | 움직임 | 의미 |
| :--- | :--- | :--- |
| `NOT_HOLDING` | 없음 | 쥔 물체가 없음(스킬 서버 기억 기준) |
| `UNSUPPORTED_PARAMS` | 없음 | 지원하지 않는 `location`(현재 구현: `handover_zone`만, 서랍 안은 B 구현 후) |
| `PLACE_NOT_CONFIGURED` | 없음 | `places.yaml`에 그 장소 tf·`interior_m`(또는 `slot` 자리)이 없음 |
| `TRAY_FULL` | 없음 | 트레이 칸이 모두 사용 중(스킬 서버 기억, `ros2-core` 재시작으로만 초기화 — B 10/08 기록) |
| `BAD_PARAMS` | 없음 | 서랍 안 놓기에서 `pose`·`slot` 둘 다 없음·둘 다 있음, `pose` 규칙 위반(`frame` ≠ `location`·x·y·yaw 가 유한한 수가 아님·z ≠ 0·yaw 범위), `scan` 없음·형식 위반·쥔 물체 `id`가 `scan`에 없음 |
| `PLACE_BLOCKED` | 없음 | **(신설 제안)** 놓을 자리 footprint가 `scan`의 `target`·`candidates` 중 하나와 겹침(쥔 물체 `id` 제외) → `blocked_by` = 그 물체 `id`. Runner는 다른 자리로 다시 요청하거나 실패 처리 |
| `WALL_TOO_CLOSE` | 없음 | (공통 코드를 놓기에도) 놓을 자리 footprint·손가락이 서랍 벽에 닿음 → `blocked_by` = `"wall"` |
| `DRAWER_NOT_AT_TRAVEL` | 없음 | (공통 코드를 서랍 안 놓기에도) 서랍 인출 거리가 `tf_at_travel_m`에서 벗어남 |
| `OBJECT_DROPPED` | 그 자리 정지 | 옮기는 중·놓기 직전 놓침(현재 구현 `grasp_check.FAILURE_CODE["transport"]`). 오류 계약은 #78 결정을 따름 |

**백엔드(Skill 서버) 구현 약속** (#10, B·E·A 서버와 mock 공통. 참고 구현 `ready2go_runner/nodes/mock_backend.py`)

| 항목 | 약속 |
| :--- | :--- |
| 이름 | 로봇 동작 `/skills/<동작>`(`Skill` 액션), TTS `/voice/speak`(`Skill`), 인식 `/vision/inspect_region`(`InspectRegion`) — [ICD](interfaces.md). Runner 는 `BACKEND`(real·sim·mock)와 관계없이 같은 이름으로 보냄. mock 은 `BACKEND=mock` 일 때만 떠서 이름이 겹치지 않음 |
| goal | `params_json` = 위 표의 `params`를 JSON 문자열로(UTF-8, 한글 그대로). `$변수`는 Runner 가 풀어서 보냄 |
| result | `success`, `error_code`(실패 시 코드. 비우면 Runner 가 `ACTION_FAILED`), `output_json`(위 표의 반환값, 없으면 빈 문자열. 성공인데 JSON 을 읽을 수 없으면 Runner 는 `BACKEND_ERROR` 실패로 봄) |
| 취소 | `Skill` goal 에 제한 시간 칸이 없음. Runner 는 `timeout_sec`이 지나거나 `/runner/estop`이 오면 취소를 요청하고 **최종 결과를 기다림** → **서버는 취소 요청을 받으면 안전하게 멈추고 5초 `[추정]` 안에 `canceled`로 끝낼 것**. 없으면 Runner 는 `STOP_UNCONFIRMED`로 잠김 |
| 비상정지 | 펜던트 비상정지 등으로 멈추면 `error_code = "ESTOP"` → Runner `ABORTED`·잠김 (#19, B 확인) |
| 동작 없이 거절 | 모션 계획 전에 거절하면 로봇이 움직이지 않았음을 보장하고, 그 코드를 이 문서 해당 동작의 에러 표에 "움직이지 않음"으로 적는다. Runner 는 동작별 목록 `interpreter.NO_MOTION_BY_ACTION`(같은 코드라도 표에 없는 동작이면 움직였을 수 있다고 봄)으로 재시도·`fallback`을 판단 — 새 코드는 표와 목록에 함께 추가(#168 노드 카드 "움직였나" 칸이 정본이 되면 맞춤) |
| 서버 준비 | Runner 는 서버를 2초 안에 못 찾거나 goal 이 거절되면 `BACKEND_ERROR`(동작 안 함) `[추정, 실측 후 조정]` |

**Runner 노드** (#10, `ready2go_runner runner`, bringup launch 가 모든 `BACKEND`에서 실행)

* 시작할 때 스키마(`/contracts`)·온톨로지(`/knowledge`, 초기 상태 포함)를 읽고 실행 이력은 MongoDB(`MONGO_URI`) → 실패 시 `/logs` JSONL.
* `query_ontology`는 ICD 상 `OntologyManager` 담당이지만 아직 없어 Runner 현재 상태로 답함(물품 하나·상태 경로, E 확인 요청 #10).
* `/runner/status` (`std_msgs/String` JSON, 늦게 구독해도 마지막 값): `phase`(`idle`·`running`·`halted`), `task_id`, `current_step`, `halt_code`, `log_store`(`mongo`·`jsonl`), `last`(`task_id`·`run_id`·`overall_status`·`error_code`·`failed_step`·`problems`·`log_errors`), `last_intent`(마지막으로 받은 음성 인텐트: `intent`·`targets`·`confidence`·`stt_text`·`decision`·`reason`·`task_id`, 없으면 `null`), `state_reset_at`(마지막 `/runner/reset_state` 시각 UTC, 없으면 `null`).
* `/robot_state`: Runner 가 들고 있는 온톨로지 `state` JSON, 바뀔 때 발행.
* `/runner/estop` (`std_srvs/Trigger`) → `halt()` → 진행 중인 goal 에 즉시 취소 요청(정지 확인 전에는 다음 동작 없음). **재개(`resume()`) 통로는 ICD 에 없음** — P1 재개 절차(B 실물 확인·복구 → Runner 상태 맞춤 → 재개, PR #64 E 권고)와 함께 ICD 추가를 E 와 협의. 그 전에는 Runner 노드를 다시 시작하면 잠김이 풀리고 상태는 초기값으로 돌아감. **실행 중이 아니어도 잠금**(곧 시작하려던 태스크도 막힘) — 음성 빠른 정지 경로는 이 서비스를 그대로 호출하면 됨(#187 C 권고, 새 통로 불필요).
* `/runner/reset_state` (`std_srvs/Trigger`, #23·#107) → 온톨로지 상태를 **Runner 시작 때 상태(초기 상태)로 되돌림**. P1 은 실행 사이 사람이 물품을 원위치해도 관측으로 상태를 맞추지 못해, 켜 둔 Runner 에 연속 요청하면 1회차 끝 상태(지우개 = `handover_zone`)로 2회차가 트레이를 서랍 자리에 넣음(10/07 발견). 리스크 대응 "시연 전 상태 스냅샷 복원"(metrics_risks.md)을 **사람이 원위치(물품·서랍 닫힘·빈 그리퍼·홈)를 확인한 뒤 부르는 명시적 초기화**로 둠(팀 결정: 나중에 시연 화면 #59 버튼). Runner 가 스스로 되돌리지 않으므로 실패(예: 놓기 실패로 쥔 채 정지) 뒤 상태는 사람이 확인할 때까지 그대로(#107 D 리뷰). 실행 중이면 `success: false`로 거절, 중단 잠김은 풀지 않음(재개는 별도). 관측으로 맞추기는 P2(FR-ONT-02)·P3(FR-REC-01).
* 태스크 실행 통로: 정식은 `/voice/intent`(#17, `core/intent_router.py`). 시험용으로 `RUNNER_TASK_FILE`(compose 환경 변수 → `task_file` 파라미터)을 주면 시작할 때 한 번 실행. 온톨로지·인텐트 덮어쓰기는 `RUNNER_ONTOLOGY_FILE`·`RUNNER_INTENT_TASKS`(→ `ontology_file`·`intent_tasks`).
* **`/voice/intent` 처리** (#17·#23): E 음성 노드가 검증한 뒤 발행하지만, 로봇을 움직이는 쪽이라 Runner 가 한 번 더 확인하고 애매하면 실행하지 않음. 재질문·안내 TTS 는 E 음성 노드(`last_intent`를 보고 말할지는 E 합의).

  | 받은 인텐트 | Runner | `last_intent.decision` / `reason` |
  | :--- | :--- | :--- |
  | `intent.schema.json` 위반·JSON 아님 | 실행 안 함 | `hold` / `BAD_INTENT` |
  | `unknown`·`clarify` | 실행 안 함 | `hold` / `NEEDS_CLARIFY` |
  | 연결된 태스크가 없는 인텐트 (P1 은 `find_item`, P2 는 `achieve_goal` 플래너, 목록은 P3) | 실행 안 함 | `hold` / `UNSUPPORTED_INTENT` |
  | `confidence` < `min_confidence` | 실행 안 함 | `hold` / `LOW_CONFIDENCE` |
  | `targets` 없음·2개 이상(P1 은 물품 하나)·온톨로지 `items`에 없음 | 실행 안 함 | `hold` / `NO_TARGET`·`MULTI_TARGET`·`UNKNOWN_ITEM` |
  | 태스크 `trigger.targets`에 없는 물품 (물품이 정해진 태스크, 예: 지우개 시연 태스크에 "차키 찾아줘") | 실행 안 함 (서랍도 열지 않음) | `hold` / `UNSUPPORTED_ITEM` |
  | 중단 잠김 / 이미 실행 중(중복 요청, 줄 세우지 않음) | 실행 안 함 | `reject` / `LOCKED`·`BUSY` |
  | 태스크에 필요한 `/skills/*` 서버가 아직 안 뜸 (real 기동 직후, #108) | 실행 안 함 (로봇 동작·실행 기록 없음) | `reject` / `NOT_READY` |
  | `achieve_goal` 인데 `goals` 없음 / 목표 물품이 온톨로지에 없음 | 실행 안 함 | `hold` / `NO_GOAL`·`UNKNOWN_ITEM` |
  | `achieve_goal` → 플래너(#150): 목표가 **이미 만족** | 실행 안 함 (근거는 콘솔 `[plan]` 줄) | `hold` / `PLAN_SATISFIED` |
  | `achieve_goal` → 플래너: 목표를 만족하는 스킬 순서 **없음** | 실행 안 함 (원인은 콘솔 `[plan]` 줄) | `hold` / `UNPLANNABLE` |
  | `achieve_goal` → 플래너: **계획됨** | 계획을 태스크(`plan_<물품>_<값>`)로 실행, 계획·근거는 실행 기록 헤더 `plan` | `run` |
  | 위를 모두 통과한 `find_item` 등 | 태스크 실행, `inputs` = `{target: targets[0], source: "voice", stt_text, intent_confidence}`, 실행 기록 헤더 `intent`에 받은 JSON 그대로 (FR-LOG-01 입력 명령) | `run` |
  | `cancel` ("멈춰", 신뢰도·잠김과 상관없이) | 실행 중이면 `/runner/estop`과 같은 `halt()` (잠김, 자동 재개 없음). 실행 중이 아니면 할 일 없음 | `cancel` / 실행 중 아님 `NOT_RUNNING`. 판단은 실행 시작과 같은 잠금 안(`core/start_gate.py`, #187): 어떤 요청을 처리하는 사이(플래너 계산 등) "멈춰"가 오면 그 요청은 시작하지 않고 `STOPPED_BEFORE_START` |
  | `status` ("지금 뭐 해?") | `/runner/status` 다시 발행 | `status` |

  * 목표형(`achieve_goal`, P2 #150): 태스크 대신 플래너(`core/planner.py`, `docs/planner.md` 7.7)가 **현재 Runner 상태**에서 계획. 계획 스텝 제한 시간은 파라미터 `plan_timeouts`(기본 `open_drawer=60,close_drawer=60,pick=70,place=60,move_to_named_pose=60` [팀 확정 필요, pick 70초는 사용자·C 합의 #153], find_item 과 같음). **지원 범위** 파라미터 `plan_limits`(기본 = 현재 실물 [문서: B `skill_server.py` 10/08, 팀 확정 필요] `open_drawer.drawer_id=drawer_top,close_drawer.drawer_id=drawer_top,pick.from=drawer_top,place.to=handover_zone`, 빈 문자열 = 제한 없음·mock) — 범위 밖 계획은 실행 전에 `UNPLANNABLE`. `tasks/`에 `trigger.intent: achieve_goal` 태스크를 두면 그 태스크가 우선.
  * 인텐트 → 태스크: `tasks_dir`(기본 `/tasks`)의 `trigger.intent`. `intent_tasks` 파라미터(`인텐트=태스크파일`, 쉼표로 여러 개)가 우선 — P1 시연(벽 배치·끌기 뒤 다시 촬영, E #122 공통 pick): `-p intent_tasks:=find_item=/tasks/p1_demo_eraser.json` (공통 온톨로지 그대로). 같은 `trigger.intent` 태스크가 둘 이상이면 시작할 때 오류.
  * 받을 물품 제한: 태스크 `trigger.targets`(선택, **물품 키 문자열 배열, 1개 이상·중복 없음** — `contracts/task.schema.json`). 있으면 그 물품만 실행하고 나머지는 `UNSUPPORTED_ITEM` 보류, 없으면 온톨로지에 있는 물품 모두. 배열이 아니면(스키마를 거치지 않은 태스크) 부분 문자열로 통과시키지 않고 보류. `inputs.target`은 기본값일 뿐 제한이 아니다. `tasks/p1_demo_eraser.json`은 `["eraser"]` (#89 PM·D 리뷰).
  * `min_confidence` 기본 0.6 `[추정, E 음성 노드 임계값과 맞출 것]`.
* `BACKEND=mock`: `mock_backend` 노드가 `/skills/*`·`/voice/speak`·`/vision/inspect_region`을 같은 이름으로 응답. `MOCK_FAIL`(예: `pick_object=GRASP_FAILED*1`)·`MOCK_NOT_VISIBLE`(예: `car_key`)로 실패 경로 시험. `MOCK_SCENE`(예: `occluded_top` — A #109 위 칸 시나리오(사용자 결정 10/08) 렌치 ← 캐러멜 상자 ← 차키)이면 여러 물체가 겹친 장면으로 인식(`occluded_by`·`visible_area_m2` 포함)·집기·서랍 안 놓기(`PLACE_BLOCKED`)를 흉내 (`core/mock_scene.py`, Unpacking 흐름 시험용 — 실물 B·A 동작과 다를 수 있음).

### 7.2 태스크 시퀀스 스키마

`action` 값에 따라 `params`를 검증하여 **오타나 잘못된 파라미터를 실행 전에 차단**합니다. 스텝은 재귀 구조(`if/while/for_each` 내부에 스텝)입니다. 스텝에는 `action`과 `skill`(7.1 `skill` 스텝) 중 정확히 하나가 있어야 합니다(예시: [`contracts/examples/task_skill_steps.json`](../contracts/examples/task_skill_steps.json)).

> **원본 파일**: [`contracts/task.schema.json`](../contracts/task.schema.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

> 구현 시 `params`는 7.1의 동작별 표를 기준으로 `allOf/if-then`으로 세분화하여 `schema/actions/*.json`으로 분리 관리하고, `while`은 `max_iter`를 필수로 강제함.

### 7.3 실제 인스턴스 예시: 오클루전 탐색 + 복구 (하드코딩 ID 없음)

[문서] P2 Unpacking 태스크(기준은 정본 [가림·추적·복구 정책](requirements.md#occlusion-policy), FR-ACT-04). **10/08 C 재작성 — mock 장면으로만 확인, 실물 미검증, 음성 연결(`trigger`) 전**. `find_item` 흐름에 치우기(`select_obstacle` → 장애물 `pick_object` → 고정 자리 `place_object` aside_1·막히면 aside_2 → `restore_stack` push → 탑뷰 다시 찍기, 최대 2개)와 finally 역순 복구(쥔 장애물이 없을 때만: 다시 찍기 → `find_moved` 재식별 → 원래 자리, 막히면 꺼낸 그 고정 자리 — 빈손이면 남은 복구 계속, 쥔 채면 정지·안내·홈 안 감, B·C 합의 #168)를 넣음. 선행: B 서랍 안 놓기 구현(#166)·얹힌 물체 집기(`NOT_ON_FLOOR`, #120)·A 가림 노드(#169), `reid_tol_m` 실측.

> **원본 파일**: [`tasks/find_with_unpack.json`](../tasks/find_with_unpack.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* 이 한 파일로 **Unpacking(s6·s7), 꺼내지 못함 안내(s8 else), 역순 복구(fr), 서랍 닫기(f2)·홈(f3)** 이 모두 표현되며, `finally`에 복구를 표현했지만 실물 복구가 보장된다는 의미는 아님(중단이면 복구 반복 안 함, 쥔 채면 홈 안 감). 장애물 쥔 상태는 온톨로지가 아니라 블랙보드 `holding`(같은 서랍 안 이동은 상태를 바꾸지 않음). mock 시험 `test_unpack_task.py`(`MOCK_SCENE=occluded_top`·`plate_over_eraser`). TODO(C·E): 같은 서랍 내부 빈 공간 이동·재관측/재식별·원래 pose 기록·LIFO 복구 계약을 [domain.md 8.2~8.3](domain.md)에 따라 반영하고 검증해야 함. Python 코드에는 시나리오 로직이 없음.
* **번들 요청**(`find_list`, `find_class`)은 별도 템플릿 `find_group_by_drawer`로 처리함: `query_ontology`의 `groups[]`를 `for_each`로 순회하여 **서랍당 한 번만 열고**, 서랍 내부에서는 목표 목록이 모두 발견되거나 탐색 한도/안전 조건에 도달할 때까지 Unpacking 루프를 돈 뒤 복구·닫는 후속 설계임. 같은 서랍 안으로 옮긴 물체가 남으므로 서랍이 비워진다고 가정하지 않음.

### 7.4 실행 이력 자동 로깅 스키마 (Execution Log)

각 스텝(중첩 스텝 포함)마다 시작 시각, 소요 시간, 반복 인덱스, 시도 횟수, **성공 여부·결과 코드, 에러 정보, 조건 확인 결과(`pre_check`), 상태 변화(`state_diff`)**를 기록합니다. 플래너가 만든 실행은 `plan`(스킬 조합)도 함께 기록합니다.

> **Phase 구분**: 아래 목록은 전체 설계입니다. P1 에 구현된 범위는 맨 아래 "구현 (P1, #12)"이며, 사후 관측 성공 판정(`post_check`)·`states` 컬렉션은 P2(FR-ONT-02·FR-LOG-02), 관측 불일치 `STATE_MISMATCH`는 P3(FR-REC-01) 계획입니다.

> **원본 파일**: [`contracts/examples/execution_log.json`](../contracts/examples/execution_log.json) — JSON은 문서에 중복하지 않고 원본 파일만 유지함.

* `overall_status`: `COMPLETED`(시퀀스 정상 종료) / `FAILED`(스텝 abort, `finally` 실행됨) / `ABORTED`(사용자 취소·비상정지).
* `outcome`: 작업 결과 의미(`FOUND` / `NOT_FOUND` / `PARTIAL`)는 상태와 분리하여 기록.
* **시간 규칙**: `total_duration_sec`는 실행 전체의 **실제 경과 시간(wall-clock)**. 제어 블록(`while`/`if`)의 소요 시간은 자식 스텝을 포함하므로 합산에서 제외하고, **원자 동작(리프) 스텝 소요 시간의 합 ≤ `total_duration_sec`**를 검증함.
* **성공 여부**: 모든 스텝은 `status`(`SUCCESS`/`FAILURE`/`SKIPPED`)를 가짐. 실패 시 `error.code`(7.5 스킬의 `errors` 목록 기준)를 기록. 실패 응답에 결과(`output_json`)가 있으면 그 값도 `result`에 기록(예: 그리퍼를 연 뒤 실패한 `place_object`의 `placed_pose`, #166) — **블랙보드(`output` 변수)에는 넣지 않음**(뒤 스텝이 실패 값을 성공 값으로 쓰지 않게).
* **조건 확인**: `pre_check`는 `PASS` / `PRE_UNMET`과 함께 **조건별 결과 배열**(조건, 실제 값, 통과 여부)을 기록. `PRE_UNMET`이면 동작을 보내지 않음.
* **성공 판정** (P2 계획, FR-ONT-02. P1 은 액션 응답 성공 기준): 스텝 성공 = **액션 결과 성공 AND 사후 관측 확인(`post_check`) 통과**. 관측 기준은 스킬의 `verify`(그리퍼 폭, 서랍 변위, 재스캔). 액션은 성공했지만 관측이 안 맞으면 `POST_UNCONFIRMED`로 실패 처리.
* **안전 게이트(Phase별 구현 상태)**: 실물 실행 전 게이트(11장)의 단계별 통과 여부를 한 번에 판정해 `runs` 헤더에 기록하는 전체 게이트는 미구현이다. P2 BFS 계획과 `achieve_goal` → Runner 실행 연결은 구현됐지만(FR-PLN-02, #150), 실제 상태를 다시 보는 사후 관측 `verify` 후에만 `effect`를 반영하는 기능은 P2 미구현 계획(FR-ONT-02)이다. 트윈 사전 검증은 P3 계획(FR-TWN-02)이며 P2 미러링(FR-TWN-01)과 구분한다. P1은 실제 실행한 스텝의 `pre_check`·응답 기준 `state_diff`만 남기며 전체 게이트 결과를 만들지 않음.
* **상태 변화**: `state_diff`는 `{상태 경로: [이전 값, 이후 값]}`. 관측으로 고친 경우 `STATE_MISMATCH` 항목으로 따로 표시(P3 계획, FR-REC-01).
* **플래너 실행(P2 구현, #150)**: 목표는 `inputs.goals`, 계획과 단계별 근거는 `runs` 헤더의 `plan`에 저장하고, 계획을 태스크로 변환해 스킬 단위 기록과 그 아래 원자 동작 기록을 함께 남긴다. `/planner/plan` 토픽 발행과 시연 화면 소비는 미구현이다.
* **저장 전체 설계(P2 포함)**: 스텝이 끝날 때마다 `LogStore`를 통해 MongoDB에 저장하고, `runs` 헤더에 **온톨로지 파일 해시**, STT 원문, LLM 원문 응답, 안전 게이트 결과를 포함하며 `states` 컬렉션·제출용 JSON·rosbag2(MCAP)를 연결하는 것이 전체 설계다. **현재 구현은 아래의 P1 `runs`·`steps`와 JSONL 폴백, P2 계획 실행의 `inputs.goals`·`plan` 기록까지**이며, `states` 컬렉션·전체 안전 게이트 헤더·제출용 JSON·rosbag2 연결을 구현 완료로 보지 않는다.
* 위 예시는 지면상 일부 스텝만 표기. 실제 로그에는 `finally` 스텝을 포함한 모든 스텝이 기록됨.
* **구현 (P1, #12)**: `core/log_records.py`가 레코드 모양을, `core/logstore.py`가 저장을 맡음. Runner 는 `LogStore` 약속(`start_run`·`write_step`·`end_run`·`read_run`)에만 의존.
  * `MongoLogStore`: `cobot2`의 `runs`(실행 1건, `run_id`로 덮어써 시작 기록을 완성)·`steps`(스텝 1건, `run_id`·`seq` 색인). 접속 주소 `MONGO_URI`(기본 `mongodb://localhost:27017`), 연결·응답 제한 1초 `[추정, 실측 후 조정]`.
  * `JsonlLogStore`: `logs/<run_id>.jsonl`(`:`→`-`), 한 줄 = `{"collection": "runs"|"steps", "doc": ...}`. `doc`은 MongoDB 레코드와 같은 모양. 쓰다 만 줄은 건너뜀.
  * `FallbackLogStore`: MongoDB 실패 시 그 실행의 앞 기록까지 JSONL 에 다시 써서 한 파일에 실행 전체를 남기고, 그 실행은 끝까지 JSONL(스텝마다 연결 제한만큼 멈추지 않게). 다음 실행은 MongoDB 재시도. 상태는 `degraded`·`last_error`.
  * 사람이 읽는 조회(읽기 전용): `ros2 run ready2go_runner run_report` — 최근 실행을 한국어 요약으로(KST 시각·mm·오류 코드 설명, 스킬 밑에 원자 동작 들여쓰기, `if` 줄 생략). `-n 3` 최근 3건, `--run f45c86` run_id 끝 글자, `--markdown` GitHub 댓글 표, `--uri mongodb://<PC2 IP>:27017` 다른 PC, `--jsonl /logs` 예비 기록. 요약 규칙은 `core/run_report.py`(D 시연 화면 #59에서 재사용 가능).
  * **기록 누락 점검**(읽기 전용, [FR-LOG-02](requirements.md#fr-log-02)·[AC-LOG-01](requirements.md#ac-log-01) 증거): `run_report -n 20 --check` — 실행마다 헤더·끝 기록(종료 시각·전체 시간)·실패면 오류 코드·스텝 `seq` 빠짐/중복·결과 없는 스텝·부모 없는 하위 동작·다른 실행 섞임을 확인, 누락이 있으면 종료 코드 1. 기록만 보고 판단하며 실행 결과의 옳고 그름은 판단하지 않음. 10/06 PC2 실물 기록 2건 빠짐없음 [실측: 시험 자료].
  * **정지 기록 `halts[]`**(실행 문서, [FR-LOG-02](requirements.md#fr-log-02)·[AC-SAF-02](requirements.md#ac-saf-02) C 몫, #187): 정지마다 `source`(`service` = `/runner/estop`·`voice` = 음성 cancel·`backend` = 스킬 서버 중단 코드)·`requested_at`·`canceled_goals`(취소 요청한 동작 수)·`step`·`action_step`·`step_code`(백엔드 응답: `CANCELED`·`STOP_UNCONFIRMED`·`ESTOP`, 스텝 사이면 `HALTED`)·`stopped_at`(Runner 가 응답을 받은 시각)·`in_finally`. 재개(#152)면 `resumed_at`/`discarded_at` 추가. `run_report` 머리에 "정지 시각 · 코드 · 출처 · 스텝 · 응답 +초 → 중단/재개". 실물 정지 확인(B)·발화 종료 시각(E)은 각 담당 기록과 대조. 실행 중이 아닐 때 정지(잠금만)는 실행 기록이 없음.
  * 실행 중 콘솔 (#98): Runner 노드가 스텝마다 시작·끝 한 줄 — `[run_id 끝 6자리] (finally) (└ 원자 동작) ▶/✅/❌/⏭/🛑 스텝ID 한국어 이름 (동작·스킬 이름) · 시간 · 핵심 값`. 문구는 `run_report`와 같은 함수(`core/step_console.py`), 시작 줄의 KST 시각(ms)·동작 이름으로 B 스킬 서버 로그와 대조. 성공 info·건너뜀 warn·실패/중단 error. 즉시 끝나는 동작(`query_ontology`·`set_var`·`if`)은 끝 줄만. 콘솔은 보기용이며 저장 성공은 run_id 로 DB 조회로 확인(콘솔 줄 수 = 저장된 스텝 수, 시험). 콘솔 출력이 실패해도 실행·기록·중단 처리는 그대로(`Runner.on_step`).
  * `run_id` = 시작 시각(UTC) + 6자리 난수. 스텝 `seq` = 시작 순서. 실행 거절(`TASK_INVALID`·중단 잠김)도 기록. 기록 저장 실패는 `RunResult.log_errors`에 남기고 **실행은 멈추지 않음**.
  * 범위는 정본 [FR-LOG-01](requirements.md#fr-log-01)(P1)·[FR-LOG-02](requirements.md#fr-log-02)(P2)·[AC-LOG-01](requirements.md#ac-log-01). 현재 구현은 위 목록이고 `states` 컬렉션·`post_check`는 **미구현**.
  * `skill` 스텝 기록(#12): `action: "skill"`, `skill`, `params`, `pre_check`(온톨로지 `check` 결과 배열), 성공 시 `state_diff`(온톨로지 `apply` 결과). P1 실행에서 이미 계산되는 값을 **진단용 부가 기록**으로 남겨 `PRE_UNMET` 원인을 볼 수 있게 함(PR #64 E 검토 허용). FR-LOG-02 상세 로그 완료나 관측으로 검증된 상태를 뜻하지 않음(`state_diff`는 응답 기준 반영 결과). 하위 원자 동작 기록은 `parent`로 묶음. `state_diff` 키에 `.`이 있어 MongoDB 에서 키로 직접 조회하기는 불편함(저장·읽기는 7.0 실측 정상).
