# 도메인 기능: 탐색 · 복구 · 서랍 개폐

> 관련 요구사항: [FR-ACT-01–04](requirements.md#fr-act-01), [FR-INT-02](requirements.md#fr-int-02), [FR-REC-01](requirements.md#fr-rec-01). 도메인 동작 구현 상세는 이 문서에서 다룹니다.

## 8. 메인 도메인 기능 상세

### 8.1 온톨로지 기반 물품-서랍 추론
* "출근 준비물 찾아줘" → 별칭 매칭으로 `commute_set` 식별 → 구성 물품 추출 → `groups[]`로 서랍별로 묶어 **서랍당 한 번만 개방**.
* "귀중품 다 찾아줘" → `Valuables`와 하위 클래스(`Key`)에 속한 물품 전체를 추론하여 동일하게 처리.

### 8.2 오클루전 극복 순차 탐색 (Unpacking Loop)

[문서] P2 FR-ACT-04·UC-P2의 목표 흐름입니다. 같은 서랍 내부 빈 공간으로 가림 물체를 옮기는 사용자 확정([#6 최종 승인](https://github.com/Jik-Kim/ready2go/issues/6#issuecomment-6006660678))을 반영하며 구현 완료 설명이 아닙니다. 전달 트레이 `handover_zone`은 유지합니다.
1. **1차 스캔**: 서랍 개방 후 탑뷰 촬영. 목표 물품이 보이면 바로 꺼내 `handover_zone`(사용자 앞 트레이)에 배치.
2. **미발견 시 (오클루전 발생)**:
   * **장애물 선택 정책**: 기준은 [FR-ACT-04](requirements.md#fr-act-04)·가림 순서는 [FR-VIS-03](requirements.md#fr-vis-03)을 따른다(여기서 다시 정의하지 않음, #134). 현재 선택 구현은 C `select_obstacle`(#176). 근거로 남기는 선행 연구: Mechanical Search 실물 실험에서 큰 것부터 평균 4.85회 vs 무작위 10.87회. B 는 집기 직전에 그 동작이 안전한지만 판단·거부한다(#120 B 입장).
   * **시연 배치 주의**: 선행 연구 실패의 85~90%가 벽·모서리에 붙은 물체였음 → 물품을 서랍 벽에서 띄워 배치.
   * 같은 서랍 내부 빈 공간으로 옮김. 빈 공간이 없으면 실행 불가를 안내하고 안전 종료·필요 복구 절차를 적용하며 외부 임시 트레이로 우회하지 않음. 빈 공간 선정·손가락/목표물 여유·놓기 pose·오류 코드는 B·C·E 설계/계약 승인·실측이 필요함.
   * 원래 **서랍 로컬 좌표계 기준 pose**와 옮긴 물체를 재식별할 정보를 기록하여 LIFO 복구에 사용함. 기존 트레이 `slot`을 서랍 내부 pose로 단순 치환하지 않음. TODO(C·E): `restore_stack` 기록/수신 필드 계약 확정.
   * 장애물을 하나 옮길 때마다 재촬영하여 반복; 이미 옮긴 물체를 다시 치우지 않는 구분은 C 인계 (`while`, `max_iter` 제한).
3. **완전 부재 처리**: 서랍 내부 이동 후에도 정해진 탐색 한도/안전 조건 안에서 목표를 찾지 못하면 미발견 또는 실행 불가를 안내함. 장애물이 서랍 안에 남으므로 서랍이 비워진다고 가정하지 않음.

### 8.3 스마트 원위치 복구 (Rollback) & 동적 온톨로지 갱신
* **스마트 복구**: 목표물을 `handover_zone`에 전달한 뒤, 기록을 역순으로 읽어 같은 서랍 안에서 옮긴 장애물을 재관측·재식별하여 **원래 서랍 로컬 좌표**로 복구하는 P2 계획. 복구 직전에 서랍 좌표계를 재추정(현재 인출 거리 반영)하고, 원래 자리 점유 등 안전 조건이 맞지 않으면 임의 위치를 원위치 복구 성공으로 처리하지 않음. 대응은 B·C·E가 검증·합의해야 함. 높이(z): **현재 B `place_object` 서랍 안 놓기는 서랍 바닥만 지원**(#166, [runner.md 7.1](runner.md) `place_object`) — 받치던 물체가 남아 있으면 겹침 검사로 `PLACE_BLOCKED`(움직이기 전), 없으면 바닥에 놓여 원래 높이와 달라짐(C 가 AC-ACT-03 미달로 기록). 다른 물체 위 복구는 [FR-ACT-04](requirements.md#fr-act-04) 목표와의 차이로 **협의 항목**(#134, 완료 아님).
* **복구 정확도 측정**: 선행 연구에 정량 자료가 없으므로 위치·요(yaw) 오차를 같은 카메라로 직접 측정해 지표로 보고(14장).
* **동적 온톨로지 업데이트**: 목표 발견 시 `update_ontology`로 명시 갱신하고, 같은 서랍 안에서 옮긴 장애물의 `located_in`은 해당 서랍으로 유지됨. 임시/원래 pose 추적과 관측 기반 상태 반영은 C·E 후속 설계이며 `inspect_region` 호출만으로 자동 갱신 완료를 뜻하지 않음.

### P2 계약·데이터 인계 (현재 미완료)

| 대상·담당 | 근거·영향·필요 조치 |
| :--- | :--- |
| TODO(B·C·E): `place_object`/`inspect_region` 연결 | 서랍 안 놓기 계약안(#120 ②, B 제안·승인 전): `location` 서랍 + `pose`/`slot` + `scan`(`$scan`, `target`·`candidates` 모두 이웃), 이웃·벽 겹침은 움직이기 전 거부, `placed_pose` = 명령한 자리(실제 위치는 재관측) — [runner.md 7.1](runner.md), `contracts/examples/place_object_result.json`. 빈 자리 자동 계산·실패/취소 복구 계약은 아직. 기존 `aside`/`avoid` 제안은 확정 필드로 추가하지 않음 |
| TODO(C·E): `tasks/find_with_unpack.json` | 현재 s7.2=`staging_tray`, f1.2=`tray_view`, f1.3=`source_slot`인 이전 예시. 내부 이동/재식별·원래 pose 기록 계약을 반영한 뒤 갱신·검증. 새 좌표를 임의로 넣지 않음 |
| TODO(C·E): Runner/플래너·온톨로지 | 이미 옮긴 물체의 반복 제거 방지, `restore_stack` 식별/pose·역순 복구, located_in 유지와 pre/effect 의미 대조 필요 |
| TODO(B·C·A·E): 잔존 `staging_tray` | world/초기상태, places.yaml, vision_stub, ICD TF/region·place, 관련 테스트·로그 예시가 참조함. 승인·소비자 정리 전에 삭제하지 않음. `tray_view`는 전달 트레이 용도 필요 여부를 B가 판단 |
| TODO(C·D·E): 계약·예시·기록 | `contracts/examples/execution_log.json`의 staging_tray_slot_1은 이전 예시. 계약 변경은 스키마·예시·문서 동시 대조와 승인2명(그중E) 필요. B/C CURRENT의 과거 교시 기록은 삭제하지 않고 담당자가 현 상태를 추가해야 함 |

[문서] 완료 기준은 [AC-ACT-02](requirements.md#ac-act-02)·[AC-ACT-03](requirements.md#ac-act-03)을 따른다(수치는 정본에만, #134). 실제 연결·원위치 복구 완료는 별도 실물 검증이 필요합니다.

### 8.4 실물 서랍 개폐 구현 (담당 B)
> 10/08 기준 현재 구현(스킬 서버 `drawer_control`, 값은 `ros2_ws/src/ready2go_skills/params/skills.yaml` `drawer_open_close`·`drawer_control`, 교시는 `config/poses.yaml`). 원자 동작 입출력·에러 코드는 [runner.md 7.1](runner.md). 노드 카드·상황별 대응은 #168.

* **열기** (위·아래 공통): **손잡이 앞(`drawer_approach`, ready)에서만 시작** — Runner `open_drawer` 가 `move_to_named_pose(drawer_approach)` 를 먼저 보냄. 다른 자세면 그리퍼도 움직이기 전에 `NOT_AT_START_POSE`(노드 안에서 ready 로 알아서 가지 않음, #168) → 손잡이까지 직선(손잡이 앞 12 N 접촉이면 멈추고 60 mm 빼고 `GRASP_FAILED`) → 잡기(폭으로 확인) → 당기기(저항 30 N 넘으면 `DRAWER_STUCK`, 끝 10 mm 안 걸림은 스토퍼 도달) → 놓고 60 mm 빼기 → 홈.
  * 손잡이를 못 잡으면: 그리퍼 열고 여는 방향으로 60 mm 빼고 멈춤(`GRASP_FAILED`) [사용자 10/08].
  * 당기다 걸리면: 그리퍼만 열고 그 자리 정지 — 재개 안 하고 사람이 정리(#152 B 답).
* **닫기**: 손잡이를 잡지 않고 손끝으로 **앞판을 닫히는 방향(y)으로 밂**. 닫힘 = 닫힘 위치(교시) 도달, 그 전에 15 N 넘게 걸리면 `CLOSE_NOT_CONFIRMED`. 끝나면 여는 방향으로 60 mm 빼기(홈은 안 감).
  * **교시한 기울인 자세(45°)로 앞판 중앙을 밂** (위·아래 통일, `close_push.<서랍>` = 시작 posj·posx·끝 posx) [사용자 10/08]. 미는 동안 손목·높이는 시작 자세 그대로, 끝 자세는 y 만 씀. 시작·끝 교시값 x·z 가 5 mm 넘게 다르면 움직이기 전 `DRAWER_NOT_CONFIGURED`, 시작 자세 도착 위치가 교시값과 다르면 밀지 않고 `CLOSE_NOT_CONFIRMED`(#181 C 리뷰).
  * **닫기는 노드 하나가 다 함** [B 결정 10/08, #181 C·E 리뷰]: Runner 는 `drawer_control(close)` 한 번, 노드가 (서랍 위면 홈 →) 시작 자세로 관절 이동(이동하며 45° 기울이기) → 밀기. #168 "숨은 이동 없음"의 예외 — 온톨로지 `close_drawer` 전개(`drawer_control` 하나)·C 태스크 그대로. C·E 동의 확인 필요. 실패 후 상태: 이동 중 실패면 그 자리 정지, 미는 중 걸림이면 정지(`CLOSE_NOT_CONFIRMED`), 취소는 다음 명령(그리퍼 포함) 전에 멈춤. 20° 는 손잡이에 닿음 [실측 10/08].
  * 아래 칸은 수직 그리퍼 몸통이 위 서랍 앞판에 닿아(`vertical_close_ok: false`) `close_push` 교시 전엔 `DRAWER_NOT_CONFIGURED`. 위 칸은 교시 전이면 예전 수직 밀기.
* **서랍 상태**: 열린 거리는 센서가 아니라 스킬 서버가 움직인 거리를 기억(`drawer_displacement`). 서버를 다시 켜면 닫혀 있다고 봄 → 손으로 연 서랍은 `displacement`(m)로 알려 줌. `/drawers/state` 는 미구현.
* **아래 서랍(`drawer_bottom`)** [실측 B 10/08]: 손잡이 파지(닫힘) TCP z 120.5 (위 칸 268.6, 같은 손목 방향), 손잡이 앞 = +y 108 mm, 최대 인출 226.6 mm. 넛지·집기·들고 나오기 경유점과 서랍 안 이동 높이 상한은 교시 전.
* 이전 설계안(DRL 컴플라이언스 제어로 인출 축 외 방향 부드럽게, 닫힘 실패 시 5 cm 다시 열고 재시도)은 **구현하지 않음** — 위치 이동 + 축 방향 힘 감시로 대신함.

### 8.5 벽 인접 물체 밀어오기 (담당 B)
> 10/07 기준. 아래를 **① 현재 P1 실행 경로**, **② 과거 예시(현재 경로 아님)**, **③ P2 이후 후보**로 나눈다. 원자 동작 입출력·에러 코드는 [runner.md 7.1](runner.md) `nudge_object` 행이 정본이다. 실제 동작은 위에서 눌러 옆으로 **끄는** 것이며, FR-ACT-05의 "밀기" 표현과의 차이는 요구사항 정본 담당에게 인계한 상태다(#122).

* **배경**: 얇은 물체(예: 지우개 1.15 cm)는 서랍 가운데에서만 잡히고, 벽 근처에서는 손가락이 들어갈 자리가 없다 [실측 10/03, A]. 그래서 닫은 그리퍼로 물체를 가운데 쪽으로 끌어온 뒤 **다시 보고** 집는다. 상세 작업 명세: GitHub 이슈 #37.

**① 현재 P1 실행 경로 — 공통 `pick` 스킬 안에서 선형 전개** ([`knowledge/skills/pick.jsonld`](../knowledge/skills/pick.jsonld), E #122; 정식 태스크 [`tasks/find_item.json`](../tasks/find_item.json) `s5.1`)
1. `move_to_named_pose(drawer_top_view)` → 2. `inspect_region` → `scan` → 3. `nudge_object(target=$scan.target)` → 4. 같은 서랍 탑뷰로 이동 → 5. `inspect_region` 재관측(스킬 로컬 `scan` 갱신) → 6. `pick_object(target=$scan.target)`.
* **끌지 않아도 될 때도 재관측한다.** 공간이 충분하면 `nudge_object`가 움직이지 않고 `pushed: false`로 성공하고, 그래도 4·5단계를 그대로 한다. 스킬 안에 분기·`check_only` 단계를 두지 않는다.
* **집기는 재관측 좌표로만 한다.** `nudge_object`의 `target_after`는 끈 거리만큼 옮긴 **예상** 위치로 기록(e3)만 하고 집기에 쓰지 않는다. 최초·재관측 응답은 각각 e2·e5 기록에 남는다.
* **관측 실패**: 최초 또는 재관측 `target`이 `null`이면 Runner가 `VAR_NULL`로 다음 `nudge_object`/`pick_object`를 보내지 않는다. 스킬 effect는 6단계 전체가 성공했을 때만 반영된다.
* **재시도**: 태스크의 `pick` `retry: 1`은 팔이 움직이기 전 실패에만 적용된다. 1단계 탑뷰 이동이나 3단계 끌기 뒤의 실패는 `YAW_INVALID`를 포함해 Runner가 스킬을 다시 보내지 않는다(`retry_stopped: MOTION_UNCERTAIN`, `interpreter.py` `NON_MOTION_ACTIONS`). 이 제약을 우회하지 않는다.
* **실패 뒤**: 태스크 `finally`의 서랍 닫기·홈은 Runner의 기존 안전 조건을 따른다. ESTOP·잠금(`HALT_CODES`)이면 로봇을 움직이는 finally 동작은 건너뛰고, 물품을 쥔 채면 홈으로 가지 않는다(`find_item` 설명). 실패하면 항상 닫고 홈으로 간다고 가정하지 않는다.
* **`nudge_object` 백엔드 동작** (스킬 서버 `_do_nudge_object`, 값은 `ros2_ws/src/ready2go_skills/params/skills.yaml` `drag`)
  * **판단** (`core/motion_plan.plan_drag`, ROS 없이 테스트): 물체 크기(온톨로지 `size_m`) + `yaw` + 서랍 `interior_m` + 옆벽 실제 위치 보정(`drawer_wall_offset_mm`)으로 짧은 변 파지 여유를 계산 → 잡을 수 있으면 움직이지 않고 `pushed: false`. 앞뒤 벽 때문에 옆으로 끌어도 안 되거나, 누를 점이 물체 위 밖이면 움직이지 않고 `NO_PUSH_ACCESS`.
  * **접근**: 닫은 그리퍼를 벽 쪽 손끝·가운데 쪽 손목으로 `tilt_deg` 20° 기울인 채 물체 위 `start_above_mm`(3 mm)까지 한 번에 이동.
  * **누르기**: `press_speed_mm_s` 2 mm/s로 내려가며 힘 z가 `touch_force_n` 5 N을 넘으면 즉시 멈춘다. 멈춘 채 0.1 s 간격으로 3번(`press_confirm`) 모두 5 N 이상일 때만 접촉으로 보고, 아니면 그 자리에서 다시 내려간다(접촉 확인 재시도 `touch_retries` 최대 2번 — 튄 값 대책). 누르는 동안 `press_max_force_n` 8 N 상한을 항상 본다. 위 서랍은 z 14 N에서 앞으로 넘어가므로 10 N을 넘기지 않는다 [실측 B 10/07]. 접촉 높이가 예상 ± 3 mm 밖이면 끌지 않는다.
  * **힘 풀기**: 0.1 mm씩 올려 누르는 힘을 `drag_force_n` 1.5~2.5 N으로 맞춘다. 3 mm 올려도 상한을 넘으면 `PUSH_BLOCKED`. 눌린 채 0.1 mm 이동은 제어기가 덜 움직여 도착 판정(0.05 mm) 전에 멈출 수 있어 [실측 B 10/07 PC2 `relax:2` 남은 0.1 mm], 한 칸의 `NOT_REACHED`는 실패로 끝내지 않고 다음 칸으로 넘어간다(목표는 명령 위치에 누적). 힘이 범위에 들면 **실제 멈춘 자리**를 끌기 시작 위치로 다시 읽는다(#135).
  * **끌기 전 재시도**: 누르기·힘 풀기에서 안전 코드가 아닌 실패(`NO_OBJECT_CONTACT`, `PUSH_BLOCKED`, `NOT_REACHED` 등)가 나면 누를 자리 위(`start_above_mm`)로 올라가고, 그 자리에 1 mm 안으로 돌아온 것을 확인한 뒤 같은 좌표에서 누르기부터 다시 한다. 총 `press_attempts` 3회. 물체가 아직 끌리지 않았으므로 같은 좌표를 쓴다. 위의 `touch_retries`(멈춘 자리에서 접촉 확인만 다시)와 다르다. **끌기 시작 뒤 실패·안전 코드는 재시도하지 않는다.** Runner의 이동 뒤 pick 재시도 억제(`MOTION_UNCERTAIN`)는 그대로이며, 이 재시도는 `nudge_object` 한 번의 호출 안에서만 일어난다 [사용자 10/07 "넛지 안 되면 닫지 말고 다시"].
  * **끌기**: 누른 z 그대로 서랍 옆(y)으로 `shift_mm`만큼 끈다(현재 값은 params 정본, 10/07 저녁 **40 mm**). 33 mm는 10/07 손끝 실측 좌표(y 0.2904) 기준으로 실물 성공했지만, PC2 P1에서 비전 좌표가 벽 쪽 2 mm(0.2924)라 끈 뒤 집기 `WALL_TOO_CLOSE` 1.8 mm 부족 → 40 mm(비전 오차 ±2 mm 여유) [#135]. **40 mm는 실물 미검증.** 끄는 중 힘 변화가 `max_force_n` 8 N을 넘으면 멈추고 `PUSH_BLOCKED`. 서랍이 닫히는 방향으로는 끌지 않는다(서랍이 같이 밀림, 10/06).
  * **끝**: `lift_mm` 30 mm 위로 올라간 뒤 응답한다. 안전 정지 코드가 아닌 실패에서도 같이 올라간다. 도착 판정은 좌표 기준(목표 ± 허용 오차 + 정지)이다.
  * **바닥 높이**: 서랍 TF z에는 설치 오차가 있어, 누르는 높이는 힘 감지로 확인한다.
* **`pick_object` 접근 경로** (스킬 서버 `_do_pick_object`, #136): `config/poses.yaml` `drag_down`이 교시된 서랍이면 넛지와 같은 길로 간다 — 그리퍼를 닫고(경유점이 서랍 안 바닥 위 약 37 mm라 벌린 RG2 손끝이 닿지 않게) → `drag_down` 관절 이동 → y를 목표 y로 맞추며 목표 위까지 블렌딩 한 번(`transit.blend_mm`, 구간 절반까지) → 목표 위에서 벌림 → 1 cm 전까지 빠르게(`line_mm_s`) → 마지막 `grasp_mm_s`. 목표 위 높이는 `grasp.z + min(approach_offset.z, 30 mm)`이며(입력 m → mm), **safe_z 300 mm 하한을 적용하지 않는다** — 탑뷰(J3 약 10°)에서 safe_z로 내려가 직선 이동하다 특이점에 걸림 [실측 B 10/07 저녁 PC2 Runner]. `drag_down` 교시 전 서랍(아래 서랍)은 예전대로 safe_z로 옮긴다. **P1 지우개 단일 물품 조건**의 경로이며, 서랍 안 다른 물체 위를 지나가는 P2 장면의 간섭은 검증하지 않았다(장애물 회피 경로가 아님). 넛지에서 `drag_down` 경유는 실물 사용 중이고, 집기 경로 변경 뒤 Runner 실물 재실행은 미확인.
* **이동 속도** (#136·#139): **큰 이동은 빠르게** — 관절 이동(탑뷰·홈·준비 자세)은 `.env` `SKILL_JOINT_VEL_DEG_S`·`ACC`, 빈 공간 직선(서랍 밖으로 빼기, 들고 나오기 블렌딩, 놓은 뒤 트레이 위 올리기, 서랍 밖에서 관절 이동 전 올리기)은 `speed.free_mm_s` 250, 서랍 당기기·밀기는 `pull_mm_s`·`push_mm_s` 그대로. **서랍 안은 느리게** [사용자 10/07 밤] — 서랍 안 경유점(`drag_down`)으로 들어가는 관절 이동은 `in_drawer_joint_deg_s` 30(설정 관절 속도보다 크지 않게), 서랍 안·위 직선(경유점 → 물체 위, 집으러 내려가기 1 cm 전까지, 서랍 안 올리기, 들고 경유점 1로)은 `in_drawer_mm_s` 75. 누르기 2·끌기 10·집기/놓기 마지막 15 mm/s, 손잡이 접근(접촉 감시)·닫기 마지막 10 mm/s는 그대로. 관절 이동 '도착' 뒤 멈춤을 확인하고(최대 2 s) 다음 직선·블렌딩을 보내며, 블렌딩·직선이 1 mm도 출발하지 않았으면 한 번만 다시 보낸다(#139 블렌딩, 관절 90°/s 실물에서 드러남; 10/08 직선 — 놓기 트레이 위 도착 직후 `lower_fast`. 접촉 감시 직선·누르기·힘 맞추기는 제외). 멈춤 확인 중 취소·상태 조회 1 s 넘게 실패·2 s 안에 안 멈춤이면 정지 + 정지 확인 뒤 `CANCELED`·`STATE_UNKNOWN`·`NOT_REACHED`(정지 미확인이면 `STOP_UNCONFIRMED`)로 끝내고 다음 명령을 보내지 않으며, 다시 보내기 직전에도 취소를 확인한다. 실물 미확인.
* **실물 결과**: 위 서랍 손잡이 쪽 모서리 지우개 끌기 → 집기 → 전달 트레이까지 성공했다 [실측 B 10/07, `ros2_ws/src/ready2go_skills/scripts/b_sk.py dragtest`]. 끈 뒤 탑뷰 재관측 → 그 좌표로 집기 경로도 `b_sk.py` 호스트 흐름으로 확인했다. Runner를 거친 전체 실행, AC-ACT-05 벽 근처 10회 중 8회, 공통 pick 전체 시간(제한은 태스크 원본 [`tasks/find_item.json`](../tasks/find_item.json) `s5.1` `timeout_sec`)은 아직 미측정이다.

**② 과거 예시 (현재 P1 경로 아님)** — 10/06 시연 원본 파일은 삭제됨, 10/05 태스크 예시 파일은 유지
* **[삭제된 원본]** 10/06 시연 `pick_demo`(`robot_ontology_demo.jsonld`): `nudge_object` → `target_after`(예상값)로 바로 `pick_object`. 재관측이 없어 FR-ACT-05 재인식 완료로 보지 않는다. 두 원본 파일은 공통 pick으로 대체되어 삭제됐고(E 정리, #17), 그 실행 기록은 과거 로그·`ready2go_runner` 테스트 fixture(`pc2_run_20261006_f45c86.json`)·변경 이력에만 남는다.
* **[유지되는 예시]** 10/05 설계안 [`contracts/examples/task_nudge_then_pick.json`](../contracts/examples/task_nudge_then_pick.json): 태스크에서 `inspect_region` → `nudge_object` → (`pushed`일 때만) 재관측 → `nudge_object(check_only: true)`(아직 못 잡으면 `PUSH_LIMIT`) → `pick_object`. 예시 파일은 계약 예시로 남아 있지만 현재 P1 실행 경로가 아니다. `check_only` 옵션도 원자 동작에 남아 있지만 현재 공통 pick은 쓰지 않는다.
* 그 전 설계의 "바닥 감지 → 수 mm 상승 → 옆으로 밀기"는 10/06 실물에서 위에서 눌러 끄는 방식으로 바뀌었다(트러블슈팅 2, `practice/B/2026-10-06_practice.md`).

**③ P2 이후 후보 (미확정)**
* 아래 서랍(`drawer_bottom`): 위 서랍 앞판에 그리퍼 몸통이 걸려 수직으로는 안쪽 약 151 mm까지만 닿는다. 그 안쪽 띠는 20° 기울여 누른 뒤 손잡이 쪽(서랍 −x)으로 끌어오는 안이다 [실측 B 10/07, K4·K5 측정 중]. 이 경우 서랍이 닫히는 방향과 반대라 위 ①의 옆(y) 제한과 다르다. 코드·TF 미반영.
* 벽 따라 밀기, 긴 변 방향 잡기, 주변 물체 간격까지 본 공간 판단의 주체·필드는 [#120](https://github.com/Jik-Kim/ready2go/issues/120) 후속 합의 대상이다.

### 8.6 파지 실패·놓침 처리 (담당 B)
* **배경**: 집다가 빈손으로 닫히거나, 들어 올리거나 옮기는 중에 물체가 빠질 수 있다. 실패를 알아채면 로봇이 **서랍 안에서 그대로 멈춰 있지 않고 안전하게 빠져나온 뒤** 실패를 응답한다. 판정 코드는 `ready2go_skills/core/grasp_check.py`(ROS 없이 테스트).
* **확인 시점과 즉시 동작** (백엔드 `pick_object`·`place_object` 안, 10/07 스킬 서버 기준)

  | 시점 | 판정 | 로봇 즉시 동작 | 응답 코드 |
  | :--- | :--- | :--- | :--- |
  | ① 닫은 직후 | `check_grasp`: 감지 없음·빈손 닫힘·기대 폭과 다름 | 그리퍼 열기 → 물체 위 접근 높이로 상승 | `GRASP_FAILED` (물체는 거의 제자리) |
  | ② 경유점으로 들어 올린 직후 | `check_hold`: 폭이 최소 폭 이하 = 빠짐 | 그 자리(경유점)에서 멈춤. 그리퍼는 빈손으로 닫혀 있음 | `GRASP_FAILED` (물체는 집으려던 자리 근처로 떨어짐) |
  | ③ 놓기 직전 | `check_hold` (`place_object` 안, 놓는 자리 위에서) | 그 자리 정지, 쥔 상태 기록 해제 | `OBJECT_DROPPED` (떨어진 위치 모름: 서랍 안 또는 작업대) `[팀 확정 필요: 오류 계약은 #78]` |

  * 폭이 NaN·inf·RG2 범위(0~110 mm) 밖이면 판정은 `SENSOR_INVALID`이다. 잡았는지 **알 수 없는** 상태라 놓침 확정과 구분해 정상 파지로 보지 않는다. 현재 노드는 응답 코드를 위 표 코드(`GRASP_FAILED`/`OBJECT_DROPPED`)로 내고 `reason`에 `SENSOR_INVALID`를 적는다. 별도 응답 코드·후처리는 #78에서 B·C·E가 정한다 (#72 D·E 리뷰).
  * 폭이 조금 변했지만 아직 잡고 있으면 `SLIPPED`로 기록만 하고 계속한다(손가락 안에서 돌아 놓는 위치·방향 오차가 커질 수 있음).
  * 놓치면 RG2가 계속 닫혀 폭이 빈손 닫힘(0.9 mm)까지 줄어든다 [실측 B 10/03]. 고무 물체는 잡는 힘에 조금 눌리므로(지우개 22 → 21.4 mm [실측 B 10/04]) 작은 변화는 정상으로 본다.
  * 옮기는 동안 `/gripper/state`를 계속 감시하지는 않는다. 확인은 위 세 시점뿐이다.
* **실패 뒤 흐름 — 현재 P1** (공통 `pick`, 8.5 ①)
  * `pick_object`는 6단계 중 마지막이라 앞서 탑뷰 이동(과 끌기)이 이미 있었다. 그래서 `GRASP_FAILED` 등 어떤 실패든 Runner는 `pick` 스킬을 다시 보내지 않는다(`MOTION_UNCERTAIN`). 태스크의 `retry: 1`이 있어도 같다.
  * 실패는 태스크로 전파되어 `finally`로 간다. 서랍 닫기·홈·TTS 안내는 Runner 안전 조건을 따른다: ESTOP·잠금이면 움직이는 동작은 건너뛰고, 물품을 쥔 채(놓기 실패 등)면 홈으로 가지 않고 사람 복구를 기다린다.
  * P1 Runner에는 `recovery`가 없어 "다시 보고 다시 집기"를 자동으로 하지 않는다. 호스트 시험 스크립트 `ros2_ws/src/ready2go_skills/scripts/b_sk.py`의 재시도(탑뷰 → 재관측 → 실패한 단계부터 다시, 최대 2회)는 B 실물 시험용이며 Runner 경로가 아니다.
* **P2 계획 (미구현)**: 실패한 `pick_object` 스텝에 `recovery`로 `move_to_named_pose(drawer_top_view)` → `inspect_region`(출력 `scan`)을 두고 새로 본 `$scan` 좌표로 다시 집는다 (C 확인: Runner는 시도마다 `params`를 그때의 블랙보드로 다시 푼다, #72). ③ 뒤 다시 봐도 목표가 서랍에 없으면 작업대로 떨어진 것으로 보고 TTS로 사람에게 확인을 요청한다(로봇이 작업대를 찾아 집지는 않음). Runner `recovery`·이동 뒤 재시도 허용 조건은 C·E 합의가 필요하다.
* **값** (`ros2_ws/src/ready2go_skills/params/skills.yaml` `gripper`): 최소 폭 `min_width_m` 2 mm(빈손 닫힘 0.9 mm보다 큼), 미끄러짐 허용 `slip_tolerance_m` 2 mm, 기대 폭 허용 오차 `grasp_width_tolerance_m` 3 mm [실측 B 10/03~10/06, 지우개 기준]. 다른 물품 값은 `[팀 확정 필요]`.
