# CURRENT — B 서동권

- **담당**: 실물 로봇 모션 (`ready2go_skills`) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-06 저녁

## 지금 상태
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
- [ ] 저녁 수정 실물 확인 (스킬 서버 `all`): 열기 ready 경로·손잡이 1 cm 전 저속, 집기 → 경유점 1 대각선, 블렌딩 들고 나오기·칸 위 살포시, 닫기 직행·마지막 30 mm 저속, 2배 속도
- [ ] `nudge` `NOT_REACHED`(0.3 s)·"내려가다 오른쪽으로 찌름" — 끌기 유지라 고쳐야 함. 이제 `NOT_REACHED` 이유에 단계·남은 mm 가 찍힘
- [ ] PC2 통신 설정 정리 (C·A와): PC1 stub(multi) ↔ PC2(lo) 불통 → stub 을 PC2로 or PC2 설정 통일. Runner 컨테이너 `BACKEND=sim` + `cyclonedds.local.xml` 방식 C와 확정
- [ ] #22 결과: Runner run_id·MongoDB 기록 확인, 비상정지 2회차 (C·D·E)
- [ ] 저녁 브랜치 PR 여부 결정 (`claude/amazing-lamport-81s469`)
- [ ] `b_demo` 들고 나오기 movesj → 블렌딩 맞출지
- [ ] A 실제 비전 연결 → 재인식·재시도 로직 (설계는 10/06 일지)
- [ ] 아래 서랍: 손잡이·서랍 앞·최대 인출·테두리 3점·바닥 4점·보는 자세
- [ ] 높이 규칙(원통 립밤): 다 닫혔을 때 손끝이 물체 높이 40%, 벌림별 손끝 높이 60/85/100 mm 실측
- [ ] #19 E-stop(펜던트·키보드) + 저속 → 정상 속도 절차
- [ ] (P2) `sim`용 DSR 드라이버·에뮬레이터 DRCF v2/v3 맞추기 (PR #40 리뷰 스레드)
