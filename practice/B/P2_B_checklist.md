# P2 체크리스트 — B 항목 대조 (2026-10-11)

> 기준: P2 체크리스트 페이지(갱신 10/10, main `d52c1bb`)·[#196](https://github.com/Jik-Kim/ready2go/issues/196). 의미·수용 기준은 [`docs/requirements.md`](../../docs/requirements.md)만 정본이며 여기서는 B 구현·실측 상태와 근거만 적는다.
> 상태: **코드** = 이 저장소에 구현·테스트됨(실물 아님) / **실측** = PC2 실물 확인 / **실물 필요** = 아직 / **협의** = C·E 계약 승인 필요.

## 한눈에
| PDF 항목 | B 상태 | 근거 |
| :--- | :--- | :--- |
| 1절 지원 범위·미교시 보고 | 아래 "1. 지원 범위" 표 | `config/places.yaml`·`poses.yaml`·`params/skills.yaml` |
| 1절 물품별 파지 폭·힘·유지검사·교시/보정 버전 → A/C | 아래 "2. 물품별 파지" 표 | `skills.yaml` `pick`·`gripper`, `knowledge/world.jsonld` |
| 4절 B→C pick 폭 > 10 mm·파지/유지, open ≥ 90 %, close 도달·오차·힘 근거 | **코드 (10/11)**: 결과 `output_json` 에 근거 필드 | 아래 "3. 결과 근거" |
| 5절 `OBJECT_DROPPED` / `SENSOR_INVALID` 분리 | 코드 (#216) | `core/grasp_check.py` `FAILURE_CODE`·`check_hold` |
| 5절 보유 불명확을 빈손으로 갱신 안 함·그리퍼 명령 전 차단 | **코드 (10/11)**: 재시작 때 폭 못 읽음·들어 올리다 멈춤까지 막음 | 아래 "4. 보유 불명확" |
| Critical: 파지 실패를 빈손으로 분류(C `gripper_observation.py:20`, 미병합 브랜치) | **코드 (10/11)**: B 가 `grasp_ok` 와 별도로 `hand` 를 줌 → C 가 `hand` 로 빈손 판단하도록 요청 | 아래 "3" |
| 5절 실제 정지·외력·신선도·TCP/툴 관측·검사 / 2단계 무동작 안전 check | **협의**: 초안만 (아래 "5") | 계약 변경 = 승인 2명(E 포함) |
| 8절 #192 씬 vs B 교시 좌표 | 실물·A 협의 | 교시 원본 `config/poses.yaml`·`places.yaml` |
| 8절 `basis_id` (코드 SHA·설정·교시/보정 버전) | 아래 "2" 끝 | 시험 때 SHA 를 D 기록표에 |

## 1. 지원 범위 (10/11 main + 이 브랜치)
| 대상 | 위 칸 `drawer_top` | 아래 칸 `drawer_bottom` |
| :--- | :--- | :--- |
| 열기 | 실측 (10/06~) | 실측 (10/11, 걸림 기준 45 N) |
| 닫기 | 실측 (45° `close_push`, 닫고 홈 블렌딩 10/10) | 45° `close_push` — 시작 자세는 **계산값**, 실물 1회(10/08) |
| 넛지(뒤에서 밀기) | 실측 (10/11 지우개) | 실물 필요 |
| 집기 | 실측: 지우개·캐러멜(긴 변)·차키·차키 2단 | 실물 필요 |
| 들고 나오기 → 트레이 | 실측 (`carry_line` 교시) | `carry_out.drawer_bottom` **null**, 계산 경로 → **실물 필요** |
| aside_1 / aside_2 | 교시 기반 (aside_1 은 사용자 허락으로 y −10 mm) | 실측 교시 10/10 (aside_1 은 yaw π/2) |
| 서랍 안 놓기(#166) | 코드, 실물 필요 | 코드, 실물 필요 |
| 쌓인 물체 집기 | 2단 실측, 3단 차키 `받침 37.0 mm` **결과 못 받음** | 실물 필요 |
| 원래 자리 되돌리기 `return_slot` | **null** (미교시) | **null** |
| 서랍 안 높이 상한 `interior_clearance_height_m` | 0.08 | **null** |
| `staging_tray` | tf **null** (안 씀 — 트레이는 `handover_zone`) | |
| 쌓였던 물체를 다른 물체 위로 되돌리기 `place.allow_stack_place` | 기본 끔 — **협의**(계약 #166 은 바닥만) | |

미준비(null) 위치는 실물 시험에서 빼고 미달로 남긴다.

## 2. 물품별 파지 (B 파라미터, 잡는 힘 기본 20 N `gripper.default_grip_force_n`)
- 성공 하한: 닫은 폭 > 10 mm(`gripper.pick_min_width_m`), 기대 폭 ± 3 mm(`grasp_width_tolerance_m`), 긴 변 잡기는 각도 여유 7°. 들어 올린 뒤 `check_hold`(폭 변화 ≤ 2 mm = HELD), 빈손 기준 2 mm(`min_width_m`).
- 잡는 높이: 닫은 손끝 = 받침 위 온톨로지 높이 × 0.5, 예외 덮개 판 25 mm·차키 4 mm.
- `config/item_grasp.yaml` 의 `grip_force`·`grasp_verified` 는 E 규칙으로 null/false 유지 — B 실측 힘(20 N)은 `skills.yaml` 에만.

| 물품 | 크기 m (온톨로지) | 잡는 폭 | B 실측 |
| :--- | :--- | :--- | :--- |
| 지우개 | 0.0525 × 0.022 × 0.0115 | 22 | 집기·트레이 여러 번 (10/04~10/10) |
| 캐러멜 상자 | 0.075 × 0.049 × 0.0185 | 49 / 긴 변 75 | 긴 변 바닥 찍기 확인(10/11), 최종 방식으로 한 바퀴는 실물 필요 |
| 차키 | 0.0695 × 0.039 × 0.0158 | 39 | 단독·캐러멜 위 2단 (10/11) |
| 립밤 | 0.0718 × 0.02 × 0.02 | 20 | 교시 손끝 약 11 mm(10/10), 원통 옆벽 처리 — **E 목표 5종 조건부** |
| 덮개 판(가림막) | 0.0985 × 0.0742 × 0.0405 | 74.2 | 실물 필요 (손끝 25 mm) |
| 장난감 스패너(몽키) | 0.17 × 0.061 × 0.0185 | 25.9 (`grasp_width_m`) | 3단 밑, 집기는 실물 필요 |
| 장난감 망치 | 0.18 × 0.075 × 0.025 | 12.5 손잡이 | #43 회신 기준, 실물 필요 |
| 에어팟·마스킹테이프·장난감 자동차 | `world.jsonld` | 짧은 변 | 실물 안 함 (P2 시연 밖) |
| 당근 펜 | `world.jsonld` | — | **실물 없음 [사용자 10/11]** — 저장소엔 아직 등록(`world.jsonld`·`item_grasp.yaml`·`yolo_classes.txt`), E·A 정리 필요 |

### 물품별 파지 시험 (하나씩 들어 보기) — PDF 1절·6절, `item_grasp.yaml` `grasp_verified`
모델 등록·시뮬레이션만으로 "잡을 수 있음"이라 하지 않는다. 물품마다 실물로 들어 올려 결과 `output_json` 을 기록하고, B·E 가 확인한 뒤에만 `grasp_verified: true`(E 파일 — B 는 기록을 넘김).
- 절차(물품 하나씩, 위 칸 가운데 바닥, 옆 물체 없이): `rm -f /tmp/b_target_*.json` → `B view top` → `B scan top <물체>` → `B pick` → (들고 2~3 초 멈춤 = 결과의 `lift: HELD` 확인) → `B putback`(집기 전 자리에 되돌림, 10/11 추가) → 다음 회차는 `B view top` 부터. 반복 횟수 **[팀 확정 필요 — 제안 3회]**, 자세는 세로·가로 각 1회 이상.
- 기록: 결과의 `grasp_evidence.closed_width_m`·`grasp_detected`·`lift`·`lift_width_m`, 실패면 `error_code`·`close`, 잡는 힘(20 N), 사진 1장.
- 우선순위: P2 시연 물품(지우개·립밤·캐러멜·차키·덮개 판·스패너) → 망치 → 나머지 3종(에어팟·마스킹테이프·자동차, 단일 요청 대상이라 최소 1회). 당근 펜은 실물 없음 [사용자 10/11].
- 값 차이 확인 필요: `docs/hardware.md` 표는 스패너 손잡이 29.8 mm·망치 손잡이 29 mm, B 파라미터는 스패너 25.9 mm(실측 10/10)·망치 12.5 mm(#43 사용자 제공) — 망치는 실물로 잡아 닫은 폭을 보고 A/E 와 맞춘다.

| 물품 | 1 | 2 | 3 | 닫은 폭 mm | 메모 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| 지우개 | ✓ | | | 21.2 | 세로 짧은 변 [실측 10/11]. 긴 변 우회 51.4 때 앞판 닿음 → front_across (일지 25) |
| 립밤 | ✓ | | | 72.4 | 가로 → 긴 변, 기대 71.8 [실측 10/11]. 6절 목표 5종 조건 |
| 캐러멜 상자 | ✗ | | | | 그리퍼가 바닥에 닿음 — 원인 확인 중 (일지 28) |
| 차키 | ✓ | | | 39.5 | 세로 짧은 변, 기대 39 [실측 10/11] |
| 덮개 판 | | | | | 손끝 25 mm·폭 74.2 |
| 장난감 스패너 | ✓ | | | 25.3 | 판정 25.9 ± 3 안 [실측 10/11]. 넓게 벌려 파지공간 부족 → 손잡이 폭 벌림 (일지 26) |
| 장난감 망치 | | | | | 손잡이 폭 확인 |
| 에어팟 케이스 | ✓ | - | - | 45.2 | 세로, 기대 45 [실측 10/11] |
| 마스킹테이프 | | | | | 벽 0.7 mm — 찌그러짐 |
| 장난감 자동차 | | | | | |

**basis (D 기록표용)**: 코드 = 시험한 `git log --oneline -1`. 교시 = `config/poses.yaml`·`places.yaml` 마지막 커밋(main `8bc630d`, `tray_view` 10/11 재교시). 보정 = `config/calibration/calibration_meta.yaml`(A, 10/01 측정·10/03 B 5점 verify). 실행 파라미터 = `ros2_ws/src/ready2go_skills/params/skills.yaml`.

## 3. 결과 근거 (`output_json`, 10/11)
상세 필드 정의는 [B 패키지 안내](../../ros2_ws/src/ready2go_skills/README.md)의 "결과 `output_json` 의 판정 근거".
- `pick_object`: `grasp_ok` 와 **별도로** `hand` = `holding`/`empty`/`released`/`unknown`, `grasp_evidence` = 같은 pick 의 닫은 폭·`grasp_detected`·하한 10 mm·들어 올린 뒤 검사. `grasp_ok: false` 는 빈손이 아니다 — 빈손 확정은 `hand: empty`(닫힌 폭 ≤ 2 mm)만, 다시 벌린 상태는 `released`(#43 결정 E-B-C-GRIPPER-OBSERVATION-10, C `gripper_observation` 분류와 같은 이름).
- `drawer_control` 열기: `drawer_displacement`(TCP 이동량 추정) + `open_distance_m`(명령 거리) → `drawer_displacement ≥ 0.9 × open_distance_m` 을 C 가 바로 계산.
- 닫기: `close_confirmed` + `close_remaining_m`·`close_pos_tol_m`·`close_push_interrupted`.
- 필드 추가만(기존 키 그대로) — C `run_report`·mock 영향 없음. C 가 쓰려면 C 쪽 연결 필요.

## 4. 보유 불명확 (10/11 이 브랜치, **재시작 두 경우 실측 PC2 10/11**)
- 재시작 때 쥔 기록이 있는데 그리퍼 폭을 못 읽으면(이상값·연결 실패) `hold_unknown` → 서랍·넛지·집기·놓기를 **움직이기 전·그리퍼 명령 없이** `SENSOR_INVALID`. 기준 포즈 이동만 됨. 풀기: 사람이 그리퍼 확인 → 서버 재시작.
  - 전: 메모리를 빈손으로 둬서 다음 `pick_object` 가 그리퍼를 벌려 쥔 물체를 떨어뜨릴 수 있었음.
- `pick_object` 가 닫아서 잡은 순간 바로 쥔 것으로 기억 → 들어 올리다 비상정지·이동 실패여도 빈손으로 안 봄(`hand: unknown`, 다음 집기 `HOLDING_OBJECT`).
  - 전: 들어 올린 뒤 검사까지 가야 기억해서, 그 사이 멈추면 빈손으로 남았음.
- 놓침은 폭이 빈손 닫힘(≤ 2 mm)까지 줄어든 **실측**일 때만 기억을 지움(`hand: empty`).

## 5. 무동작 안전 확인 — B → C/E 제안 초안 (미구현, 계약 승인 필요)
재개 판정 3개 중 "B 안전 상태"용. 로봇을 움직이지 않고 한 번에 읽어 돌려주는 액션(이름 예: `/skills/check_state`)을 제안한다.
- 돌려줄 것(모두 지금 B 가 읽을 수 있는 값): 로봇 상태값(이동 중·안전/비상정지 `ESTOP_STATES`), 서버 잠금 사유, 펜던트 TCP·툴 이름 일치(`motion_guard.check_tool`), 그리퍼 폭·`grasp_detected`·safety error 와 `hand`(holding/empty/unknown), 쥔 기억·`hold_unknown`, 툴 힘(멈춘 채 평균)과 읽은 시각, 서랍 인출 기억(`disp`).
- 정할 것(C/E): 액션 이름·결과 스키마, 지속 외력 판정(힘 변화량만으로 안전이라 하지 않기 — 임계·유지 시간·신선도 상한을 B 실측으로), 미확인 시 복구 거절 문구.
- B 실측 필요: 정지 중 툴 힘 잡음(빈손·쥔 채), 사람이 손으로 미는 지속 외력 크기, 읽기 주기·지연.

## 6. 실물로 할 것 (PC2)
`HANDOVER.md` 4절 순서로 켠 뒤 이 브랜치로 `git pull`.
1. ~~재시작 막힘 확인~~ **[실측 PC2 10/11 완료]** — 쥔 채 재시작 → 복원(eraser 21.2 mm) → `B pick` `HOLDING_OBJECT` / 지우개 다시 집어 기록 → `RG2_HOST=192.168.1.250 Bserver`(그리퍼 못 읽음 흉내 — RG2 박스는 세팅이 막고 있어 못 건드림) → "쥔 물체 복원 못 함" → `B pick` `SENSOR_INVALID`·로봇·그리퍼 안 움직임 → `B home` 됨 → `Bserver` → 복원 → `B aside top`. 일지 트러블슈팅 24.
2. **결과 근거 확인** — `B pick` 성공 때 결과에 `hand: holding`, `grasp_evidence.closed_width_m` 이 실제 폭. `B open top` 결과 `open_distance_m`, `B close top` 결과 `close_remaining_m ≤ close_pos_tol_m`. 출력 그대로 붙여 주기.
3. **물품별 파지 시험(하나씩 들어 보기)** — 위 2절 표 채우기. 립밤 결과가 E 목표 5종 확정 조건.
4. **3단 차키** `B scan top 차키` → `B pick` 이 `받침 37.0 mm 위` 인지 (#216 뒤 미확인).
5. **시연 체크리스트(보드 `demo1`) 한 바퀴** — 쌓기 차키 → aside / 캐러멜 → aside2 / `B find top 몽키` / 가림막 → 지우개 → 립밤 / `B trayview`.
6. **아래 칸 처음 확인** — 들고 나오기(계산 경로, 저속), 가림막 집기(25 mm·폭 74.2), 넛지.
7. **트레이 칸 좌표** — 10/10 터치 뒤 트레이가 옮겨졌는지, 3칸 놓기 위치.
8. **무동작 안전 확인용 실측** — 멈춘 채 툴 힘 30 초 기록(빈손·지우개 쥔 채), 손으로 그리퍼를 2~3 초 밀 때 힘 크기. (5절 제안 숫자 근거)
9. **P2 Unpacking 10회** — 무작위 배치 10회, 성공률·원위치 오차(3 cm)·방향 오차 기록 → D 기록표.
