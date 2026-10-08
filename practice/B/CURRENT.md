# CURRENT — B 서동권

- **담당**: 실물 로봇 모션 (`ready2go_skills`) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-08

## 지금 상태
- **10/08 낮 (#120·PR #156·#166)**:
  - **#120 ② 수락 [사용자 10/08]**: `place_object` 서랍 안 놓기(빈 자리에 놓기·원래 자리로 되돌리기)는 B 가 움직임까지 구현, 10/10 구현(빠듯) → 10/11 저속 첫 실물. 빈 자리는 교시한 고정 1곳 + 놓기 전 이웃 간격 확인. 계약안 draft PR #166 (`pose`/`slot` + 필수 `neighbors`, `placed_pose` = 명령한 자리, `PLACE_BLOCKED`·`WALL_TOO_CLOSE` + `blocked_by`) — E 포함 2명 승인 대기, 스킬 서버 구현은 승인 뒤.
  - **PR #156 머지**: E 리뷰 P2 반영 — 출발 판정에 방향도(위치 1 mm 안이어도 0.5° 넘게 돌았으면 출발한 것, 다시 보내지 않음, `3d8ab1e`). 실물 미확인.
  - **결정 [사용자 10/08 오후]**: 옮기기·놓기는 한 노드로 유지(분리 안 함). 되돌리기도 놓기 검사 그대로, 막히면 C 가 고정 자리에 둔 채 기록(AC-ACT-03 미달). 고정 빈 자리 2곳(`place_slots` `aside_1`·`aside_2`, 10/10 교시). 서랍 열기·닫기 중 중단은 재개 안 함·사람 정리(#152). 스킬 노드는 처음부터 다시 짜고 조합은 C·E — 이슈 #168. PR #166 C 승인(E 대기), C Runner 실패 output 보존 #167.
  - 답변: #153 A 질문(끌기 뒤 재인식 전 탑뷰 정지 확인 — `_named` 가 `wait_motion`·`_settle`·`check_reached` 뒤 결과 반환, 예), PR #154 C `plan_limits` 기본값(놓기 트레이만·집기 서랍에서만·`drawer_top` 만) 맞음.
- **10/08 PC2 P1 3회 연속 시도 → 2회에서 종료 [사용자 결정]** (상세 `2026-10-08_practice.md`).
  - 1회차: 음성 → 열기 → 탑뷰 → 인식 → 끌기(명령 40.1 mm, 비전 39.6 mm) → 재인식 → **집기 성공** → 놓기 `NOT_REACHED`(트레이 위 도착 직후 `lower_fast` 직선이 출발 안 함, 남은 73.6 mm) → 출발 안 한 직선도 멈춤 확인 뒤 1회 재전송(블렌딩과 공통 `_send_wait`, 접촉 감시·느린 직선 제외, 실물 미확인).
  - 2회차: 재시작 뒤 인식 `CAMERA_TIMEOUT`(원인 미확정) → 닫기 전 탑뷰에서 빼기 250 mm/s 1.1 s 만에 컨트롤러 `External_Force` 98 N > 96 N 정지. 탑뷰 빼기 속도 150 제안 [미결정].
  - **탑뷰를 그리퍼 180° 돌린 자세로 [사용자 10/08, P2 아래 서랍]**: 위 칸 교체·아래 칸 추가(`poses.yaml`, z 만 145.7 mm 차이). 위 칸 비전 예전 방향과 0.6 mm 안, 지우개 쪽 벽 뎁스 결손 없음. `drag_down`·들고 나오기는 예전 손목 방향 → J6 163° 회전 4번, 집기 약 9 s 늘어 60 s 제한 근처 [계산] — 결정 필요. 비전 `drawer_bottom` 지원 A #157 머지, **아래 칸 tf 초안 반영**(하단 비전 vs 손끝 정답 2.5 mm, #155) — PR #156.
- **10/07 (브랜치 `claude/friendly-newton-2cgz40`)**: 위 서랍 **끌기 → 집기 → 트레이 실물 성공** (손잡이 쪽 오른쪽 모서리 지우개, 상세 `2026-10-07_practice.md` 트러블슈팅 3).
  - 끌기: 5 N 넘으면 바로 멈춤 → 멈춘 채 3번 5 N 확인 → 0.1 mm 씩 올려 1.5~2.5 N → 누른 z 그대로 33 mm 수평. 1 mm/s → 2 mm/s, 힘 상한 8 N(서랍 14 N 에서 넘어감), 기울기 20°.
  - 이동 끝 판정을 좌표로(느린 이동이 '멈춤'으로 보여 NOT_REACHED·정지 명령 없이 끝나던 문제), 오른쪽 옆벽 보정 7.1 mm(집기 판단만).
  - 매끄럽게: 손잡이 한 번에, 올리기 → 관절 이동 이어서(radius 20), 넛지 접근 블렌딩, 회전 2배, 집기·놓기 1 cm 전까지 빠르게, 들고 나오기 반지름 50 (실물 일부 확인 — 사용자 "너무 좋음").
  - `b_flow.sh dragtest`: 실패하면 탑뷰 → 인식 → 다시 (최대 2번). 지우개 시연 세팅은 종이 부분이 모서리에.
  - 아래 서랍: 위 서랍 앞판·손잡이 아래 막힌 구역 → 20° 기울여 앞쪽으로 끌어낸 뒤 집기 [사용자 결정]. 서랍 좌표계 초안·수직 한계 127 mm(손잡이 정면 132.5 − 5)·20° 약 196 mm 실측 (`2026-10-07_practice.md` "아래 서랍 실측"). 남은 교시 B·C·D·E.
  - 끌기 뒤 재관측: E #122 공통 pick + C #118 태스크(병합 대기), B 문서 `domain.md` 8.5·8.6 동기화. `b_sk.py all`·`dragtest` 끝에 구간별 시간표(C 요청: pick 60초 예산).
- **10/07 밤 속도 나눔**: 큰 이동 빠르게(관절 .env 90·60 제안, 빈 공간 250), 서랍 안 경유점 관절 30°/s·서랍 안 직선 75 mm/s (실물 미확인).
- **10/07 밤 관절 90°/s 첫 실행**: 넛지 접근 블렌딩이 경유점에서 출발 안 함 → `NOT_REACHED`(남은 204 mm) → 관절 이동 뒤 멈춤 확인·출발 안 한 블렌딩 1회 재전송 (실물 미확인). 그 전까지 PC2 는 60·40.
- **10/07 밤 #136 (실물 미확인)**: 집기가 탑뷰에서 바로 가다 특이점 → 넛지와 같은 `drag_down` 경유(경유점 전에 그리퍼 닫음, PM 리뷰), 목표 위 `grasp` + 30 mm. 빈 공간 직선 250 mm/s(`free_mm_s`), 관절 속도는 `.env` 90·60 제안(코드 아님).
- **10/07 저녁 PC2 Runner P1 (main `76ff9f9`)**: 음성 → 열기 → 탑뷰 → 촬영 → 끌기 → 다시 촬영까지 실물로 돎. 실패 ① 집기 `WALL_TOO_CLOSE` 1.8 mm(비전 y 벽 쪽 2 mm) ② 끌기 `relax:2` `NOT_REACHED` → #135: 끌기 33 → 40 mm, 끌기 전 실패 같은 자리 재시도 3회, 힘 맞추기 멈춤 허용·끌기 시작은 실제 위치 (**실물 미검증**). 그 전: 탑뷰 → 홈 직행이 열린 서랍을 쳐 충돌 알람 7060 → #133 서랍 밖으로 먼저 빼기(실물 확인). 손으로 닫으면 스킬 서버가 열림으로 기억 → `DRAWER_ALREADY_OPEN`(로봇으로 닫거나 ros2-core 재시작).
- **10/06 (PR #83 머지)**: 위 서랍 열기 → 탑뷰 → (인식) → 30° 기울여 눌러 끌기 → 집기 → 들고 나오기 → 트레이 → 밀어 닫기. `scripts/b_demo.py`(직접교시 좌표 그대로) 처음부터 끝까지 성공 (저녁, 열림 226.1 mm, 접촉 z 219.90, 닫힘 잘 됨).
  - 저녁 수정은 브랜치 `claude/amazing-lamport-81s469` (`2c4cc6e`~`3dd1534`, PR 안 만듦, 실물 미확인): Runner 열기 경로 z 300, 들고 나오기 직선 블렌딩(`poses.yaml carry_line`), 닫기 실측 위치·저속·15 N, 끌기 수평·누르기 깊이, 빈 공간 2배. 상세 `2026-10-06_practice.md` "저녁 통합·수정".
  - ~~방향 바꿈 [사용자 10/06 저녁]: 끌기 그만 → 기울여 잡기~~ → **끌기 유지 [사용자 10/07]**: 모서리 쪽은 어차피 끌어야 함. 살포시만 닿아도 잘 끌림.
  - 실행: `b_flow.sh demo [go|N]` (스킬 서버 없이) / `server` + `all` (스킬 서버). PC2 호스트 터미널은 모두 `CYCLONEDDS_URI=~/.config/cyclonedds/cyclonedds.xml`(lo) — roboton·스킬 서버와 같게. 이 설정에서 PC1 stub(multi)은 호출 안 됨.
  - 안전: J5 133°·J3 10° 제한. 경유점은 사용자가 말한 것만 (10/06 홈 경유를 임의로 넣어 위험 — 재발 금지).
- #4 완료 (10/03 실물 확인): `ros2-core` 컨테이너에서 DSR 드라이버 Real 모드 접속, `move_joint`로 실물 동작, RG2 열기·닫기·폭 읽기, `/gripper/state` 발행.
  - 컨테이너 실행 (PR #40 머지 후): `docker compose --profile real up` — bringup이 DSR 드라이버·`/gripper/state`·고정 TF를 함께 띄움 (`.env`: `BACKEND=real`, `ROBOT_HOST=192.168.1.100`, `RG2_HOST=192.168.1.1`). 빌드 산출물은 컨테이너 전용 `/colcon`, `entrypoint.sh`가 `/colcon/install`을 source.
  - 스킬만 따로: `docker compose --profile real run --rm ros2-core bash -c "colcon --log-base /colcon/log build --symlink-install --build-base /colcon/build --install-base /colcon/install --packages-select ready2go_interfaces ready2go_skills && source /colcon/install/setup.bash && ros2 launch ready2go_skills dsr_real.launch.py"`
  - 호스트 드라이버(`cobot2_ws`)·호스트 `realsense2_camera`와 동시에 띄우지 않는다 — 같은 `/dsr01` 이름으로 spawner가 호스트 controller_manager에 붙어 실패하고 제어기에 이중 접속됨 [실측 10/03, PR #40].
- #3 완료 (10/03): PC2 `real` 5개 서비스 기동, `tf2_echo base_link wrist_cam_color_optical_frame` 값 수신(계산값과 1 mm 이내), PC1↔PC2 양방향 송수신.
- #7: B 확인 항목(프레임 이름, `link_6` 원점, TCP·툴, `set_current_tcp`) 완료. **5점 검증 완료 (10/03)** — 채택 npy로 x·y 5곳 일치, z 일관. 남은 것: A의 meta 확정 반영, C의 bringup TF.
  - ⚠️ 강의 폴더 `corecode/Calibration_Tutorial/T_gripper2camera.npy`(md5 `ed3c4a6c…`, 2026-02-25)는 채택 값(`dea4dee3…`)과 다름. 이 파일로는 z가 약 31 mm 높게 계산됨 → 강의 코드로 실행할 때는 `config/calibration/`의 npy를 복사해 쓴다.
- #6: 새 원목 서랍 `drawer_top` 3점 터치 완료 (10/04, PR #56, z 정정 #58 — 측정 때 펜던트 툴 설정이 풀려 있었음). 남은 것: `drawer_approach`·`tray_view` 교시, `drawer_top_view`는 A가 교시(B는 관절값 등록·경로 안전 확인), `staging_tray` 3점 터치(작업대 위, 테두리 오른쪽 위 꼭지점이 작업판 오른쪽 끝 22.5 cm·위쪽 끝 11 cm — #6 PM 확정, 바닥 0.166 × 0.1165 m, 테두리 0.177 × 0.130 m, 높이 0.045 m), `vision_stub` 물체 4개 손끝 터치(A와).
- #8: 지우개 서랍 안 파지 3/3 성공 (10/04) → 결정 #11 높이 기준 1.0 cm 확정 제안, E 답 대기. 남은 파지 시험: 마스킹테이프·당근 펜·망치/스패너.
- 코드 (머지): `core/touch_frame.py`(#50), `core/grasp_check.py`(#51), `core/nudge_plan.py`(#52, `yaw_valid` 차단 #66). 이번 PR: `core/motion_guard.py` — 움직이기 전 확인(`TOOL_NOT_SET`·`DRAWER_NOT_AT_TRAVEL`·`YAW_INVALID`·`NOT_ON_FLOOR`), `pick_object` 입력 `target` 계약 변경(#15).

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 제어기 IP·포트 | `192.168.1.100:12345` | [실측] 강의 실행 기록, 10/03 컨테이너 접속 |
| 제어기 버전 | `DRCF version = GF02120100` → 빌드 옵션 `DRCF_VER=2` | [실측] 드라이버 로그 |
| DSR 드라이버 소스 | `ROKEY-SPARK/doosan-robot2_jazzy` @ `31750d68` (호스트 `cobot2_ws`와 같은 커밋). 두산 원본과 `libDRFL.a`가 달라 포크 사용 | [실측] |
| RG2 접속 | `192.168.1.1:502`, unit ID 65 | [문서] 강의 `robot_control.py`, [실측] 동작 |
| RG2 폭 | 열림 99.5~99.9 mm, 닫힘 0.9 mm. **빈 상태로 닫아도 `grip_detected=True`** → 파지 판정은 온톨로지 `verify`대로 폭 조건과 함께 | [실측] 10/03 |
| TF 프레임 이름 | `base_link`, `link_6` (접두어 없음). 강의 URDF·두산 URDF 모두 같음. `tool0` = `link_6`과 원점 같고 축만 다름 | [실측] 10/02·10/03 |
| `link_6` 원점 | 플랜지 면 (제어기 플랜지 `posx`와 차이 1.8 mm·0.16°) | [실측·계산] #7 |
| TCP·툴 | TCP `GripperDA_v1` (소문자 v) z 228 mm, 툴 `tool_weight` 1.420 kg | [실측] 제어기 조회, 228 mm 팀 확정 10/02 |
| `set_current_tcp` | 수동 모드(0)에서만 가능, 자동 모드에서는 거부. 잘못된 이름은 `success=False`, TCP 유지 | [실측] #7 |
| 카메라 z → 손끝 닿는 높이 | 카메라가 계산한 면 높이 + 약 10 mm(8.5·9.8 mm)에 TCP를 두면 닫힌 손끝이 면에 닿음 (#15 파지 높이 기준) | [실측] 10/03, 채택 npy, 2곳 |
| `/gripper/state` | `{"width": m, "grasp_detected": bool}`, 10 Hz | [실측] 10/03. `width` 단위(m)는 ICD에 없어 B가 정함 [팀 확정 필요] |
| PC2 | 강의장 컴퓨터 `ms-07` (RTX 4060). `wlo1` 172.24.0.3 = DDS(공유기), `enp3s0` 192.168.1.32 = 로봇 전용선(제어기 .100, RG2 .1), DDS 미사용 | [실측] 10/03 `ip neigh`. `wlo1` 고정 IP 여부 확인 필요 |
| 새 서랍 (drawer_top·bottom) | 내부 [깊이 0.205, 폭 0.295, 높이 0.07] m, 최대 인출 0.225 m, 처짐 0 | [실측 A 10/03] 정본 `config/places.yaml` |

## 막힌 점 · 필요한 도움
- `/gripper/state`의 `width` 단위(m)를 Runner(C)와 맞춰야 함.
- #37: 밀기가 의미 있으려면 집을 때 벌림 여유(열린 손가락에 필요한 틈)가 닫은 손가락 두께보다 커야 함 → 실측 항목에 "집을 때 벌림 폭" 추가 필요.

## 다음 할 일
- [ ] **#166 승인 → `place_object` 서랍 안 놓기 구현 (10/10)**: 고정 빈 자리 `places.yaml` `<서랍>.place_slots` 교시, 이웃·벽 footprint 확인(움직이기 전), 서랍 안으로 들고 내려가 놓기 → 10/11 저속 첫 실물 (#120)
- [ ] 탑뷰 이동 다시 짜기(사용자): 처음부터 180° 자세, 손목 방향, J6 회전 시간(집기 60 s)
- [ ] PC2: 놓기 직선 재전송(#156) 실물 확인, 탑뷰 빼기 250 → 150 [미결정], 트레이 칸 기억 reset [미결정]
- [ ] P1 3회 연속(AC-DEMO-01), pick 시간(`s5.1.e1~e6`)으로 60 s 예산 C·E 공유
- [ ] 관절 90°/s: PC2 같은 경로 반복 확인 + E 확인 뒤 (PM)
- [ ] 아래 서랍 실측: A 서랍 위치 → K 막힌 구역 → B 열기 → C 탑뷰 → D 넛지 → E 들고 나오기, 코드 서랍별 높이(safe_z·high_z)·앞쪽 끌기
- [ ] A 트윈 `sim/motion_check` 가짜 로봇에 `moveb_async`·`movel_async(radius)` 추가 요청 (이 PR 머지 뒤)
- [ ] #22 결과: Runner run_id·MongoDB 기록 확인, 비상정지 2회차 (C·D·E)
- [ ] 넛지 실패 → 탑뷰 다시 촬영 → 다시 끌기(Runner recovery)는 E·C (P2, #120). 스킬 서버 안 재시도는 #135
- [ ] 높이 규칙(원통 립밤): 다 닫혔을 때 손끝이 물체 높이 40%, 벌림별 손끝 높이 60/85/100 mm 실측
- [ ] #19 E-stop(펜던트·키보드) + 저속 → 정상 속도 절차
- [ ] (P2) `sim`용 DSR 드라이버·에뮬레이터 DRCF v2/v3 맞추기 (PR #40 리뷰 스레드)
