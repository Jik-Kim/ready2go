# B 시뮬레이션 모음 (`practice/B/sim`)

로봇 없이 B 스킬 서버의 **실제 판단 코드**(사전 검사·`core/clear_plan`)를 돌려 보는 도구들이다. 로봇·그리퍼·카메라는 가짜이고, 결과는 [추정]이다(실물 확인은 날짜별 일지).
저장소 루트에서 `python3 practice/B/sim/<파일>.py [인자]`로 실행한다. 출력 예시 JSON(`clear_sim_examples_*.json`)은 실행할 때 새로 만들어지며 git에 넣지 않는다.

| 파일 | 하는 일 | 실행 예 | 마지막으로 쓴 곳 |
| :--- | :--- | :--- | :--- |
| `demo_sim.py` | P2 시연 흐름(열기 → 보기 → 집기 → 트레이 → 닫기)을 서버 코드 + 기구학 가짜 로봇(A `sim/motion_check`)으로. 다른 sim 이 가져다 씀 | `demo_sim.py` | 10/11 |
| `p2_demo.py` | P2 시연 배치 하나를 처음부터 끝까지 | `p2_demo.py` | 10/11 |
| `p2_random.py` | P2 시연 배치를 무작위로 여러 번, 실패를 이유별로 | `p2_random.py 40 1` | 10/11 |
| `edge_cases.py` | 가장자리 동작 기구학: 기울여 잡기·벽까지 밀기·들고 나오기 (위·아래 칸) | `edge_cases.py` | 10/10 |
| `fail_sim.py` | 중간 실패(빈손 닫힘·놓침·걸림·서버 재시작) 뒤 다음 스킬이 되는지, 단계별 추정 시간 | `fail_sim.py` | 10/11 |
| `collide_sim.py` | 시나리오 궤적 전체의 부딪힘(손가락↔벽·물체, 쥔 물체↔벽·물체, 아래 칸 깊이) | `collide_sim.py 6` (오래 걸림) | 10/11 |
| `rand_sim2.py` | 물체 하나 무작위 자리 — 바로 집기/넛지/멈춤 비율 | `rand_sim2.py` | 10/11 |
| `noise_sim.py` | 비전 오차(위치 ±E mm·각도 ±A°)에서 집기·넛지 성공률 | `noise_sim.py 1500 3 5 1` | 10/11 |
| `clear_sim.py` | 무작위 배치(쌓기·가림막 밑 포함)에서 꺼내기 — 예전 방식(aside·벽 넛지) vs 공간 만들기(`clear_plan`). 설정은 스킬 서버와 같음(`_room_cfg`) | `clear_sim.py 40 1 [rules]` | 10/13 (10 배치: 31.8% → 68.2%) |
| `p2_clear_sim.py` | P2 시연 배치만으로 같은 비교 | `p2_clear_sim.py 50 1` | 10/11 |
| `cluster_sim.py` | 뭉친 물체 공간 만들기 — 덤프 장면 재생(`test_real`)·무작위 뭉침(`test_rand`), 스킬 서버 판단으로 집힐 때까지 반복 (pytest 로 실행) | `NSIM=400 SEED=3 python3 -m pytest -q -s practice/B/sim/cluster_sim.py -k rand` | 10/13 (3 seed 성공 346 — #300) |
| `movesx_carry_sim.py` | 들고 나오기 moveb vs movesx(스플라인) 경로 — 교시 경유점을 그대로 스플라인에 넣은 것·moveb 둥근 경로 위 8점(guided) 비교, 서랍 앞벽·트레이 벽 높이 여유·곡률 | `python3 practice/B/sim/movesx_carry_sim.py --png out.png` | 10/13 (경유점 그대로는 위로 90 mm 부풂 → guided 제안, 그림 `img/2026-10-13_movesx_carry_sim.png`) |
| `flow_time_sim.py` | 전체 흐름(unpack) 시간 어림 — A `trace_unpack.py` 결과(B 실제 코드 명령 목록)에 속도·가속 사다리꼴 + 고정 시간(그리퍼·비전 [추정]), 줄이는 방법 ①~⑥ 비교 | `python3 sim/motion_check/trace_unpack.py --dump <덤프> --target eraser --out s2.json` → `python3 practice/B/sim/flow_time_sim.py s2.json` | 10/13 (S2 126 s·S1 170 s 어림, 속도 그대로 −18~22%, 손목(J6) 172° 왕복이 가장 큼 — 카메라 쪽 간섭 확인 전) |
| `p2_unpack_sim.py` | P2 시연 배치 무작위(S1 몽키·캐러멜·차키 쌓기 / S2 판 밑 지우개·립밤) — 치우기 free → 목표 → 원복을 스킬 서버 판단으로, 실패 단계·코드별. **원복 넛지는 지금 C 흐름에 없는 가정**(지금 Runner 와 같게 = `RESTORE_NUDGE=0`). `MODE=main`·`strict`(설정 비교)·`OBST_NUDGE=1`·`MAKE_ROOM=1`(흐름 가정)·`LIP_YAW=0`·`WRENCH_YAW=0`·`PLATE_ANY=1` | `NSIM=40 SEED=1 RESTORE_NUDGE=0 python3 -m pytest -q -s -p no:cacheprovider practice/B/sim/p2_unpack_sim.py` | 10/14 (원복 넛지 없이 S1 몽키 원복까지: main 55% → 바꿔 잡기 58%, `free_repickable_only false` 면 45% — #345) |
| `force_drag_sim.py` | 넛지 누르기·끌기 — 위치 방식 vs 힘 제어(`drag.force_mode`) 1차원 접촉 모델 | `force_drag_sim.py` | 10/13 (일지 29번) |

`cluster_sim.py` 는 저장소 CI(`pytest ros2_ws/src`)에 들어가지 않는다 — 직접 경로를 줘서 돌린다.
