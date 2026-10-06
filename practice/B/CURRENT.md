# CURRENT — B 서동권

- **담당**: 실물 로봇 모션 (`ready2go_skills`) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-04

## 지금 상태
- #4 완료 (10/03 실물 확인): `ros2-core` 컨테이너에서 DSR 드라이버 Real 모드 접속, `move_joint`로 실물 동작, RG2 열기·닫기·폭 읽기, `/gripper/state` 발행.
  - 컨테이너 실행 (PR #40 머지 후): `docker compose --profile real up` — bringup이 DSR 드라이버·`/gripper/state`·고정 TF를 함께 띄움 (`.env`: `BACKEND=real`, `ROBOT_HOST=192.168.1.100`, `RG2_HOST=192.168.1.1`). 빌드 산출물은 컨테이너 전용 `/colcon`, `entrypoint.sh`가 `/colcon/install`을 source.
  - 스킬만 따로: `docker compose --profile real run --rm ros2-core bash -c "colcon --log-base /colcon/log build --symlink-install --build-base /colcon/build --install-base /colcon/install --packages-select ready2go_interfaces ready2go_skills && source /colcon/install/setup.bash && ros2 launch ready2go_skills dsr_real.launch.py"`
  - 호스트 드라이버(`cobot2_ws`)·호스트 `realsense2_camera`와 동시에 띄우지 않는다 — 같은 `/dsr01` 이름으로 spawner가 호스트 controller_manager에 붙어 실패하고 제어기에 이중 접속됨 [실측 10/03, PR #40].
- #3 완료 (10/03): PC2 `real` 5개 서비스 기동, `tf2_echo base_link wrist_cam_color_optical_frame` 값 수신(계산값과 1 mm 이내), PC1↔PC2 양방향 송수신.
- #7: B 확인 항목(프레임 이름, `link_6` 원점, TCP·툴, `set_current_tcp`) 완료. **5점 검증 완료 (10/03)** — 채택 npy로 x·y 5곳 일치, z 일관. 남은 것: A의 meta 확정 반영, C의 bringup TF.
  - ⚠️ 강의 폴더 `corecode/Calibration_Tutorial/T_gripper2camera.npy`(md5 `ed3c4a6c…`, 2026-02-25)는 채택 값(`dea4dee3…`)과 다름. 이 파일로는 z가 약 31 mm 높게 계산됨 → 강의 코드로 실행할 때는 `config/calibration/`의 npy를 복사해 쓴다.
- #6: 새 원목 서랍 `drawer_top` 3점 터치 완료 (10/04, PR #56, z 정정 #58 — 측정 때 펜던트 툴 설정이 풀려 있었음). 남은 것: `drawer_approach`·`tray_view` 교시, `drawer_top_view`는 A가 교시(B는 관절값 등록·경로 안전 확인), `staging_tray` 3점 터치(서랍장 윗면 앞 모서리에서 5 cm 이상 뒤, 바닥 0.166 × 0.1165 m, 테두리 0.177 × 0.130 m, 높이 0.045 m), `vision_stub` 물체 4개 손끝 터치(A와).
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
- [x] #7 5점 `verify.py` 검증 (10/03)
- [x] #3 PC2 `real` 기동·TF 연결·PC1↔PC2 통신 (10/03)
- [x] #8 지우개 서랍 안 3/3 (10/04) — 결정 #11 확정은 E 답 후 `hardware.md`·`metrics_risks.md` 수정
- [x] `drawer_top` 3점 터치 (#56·#58), touch_frame·grasp_check·nudge_plan PR 머지
- [ ] #6 (10/04) `drawer_approach`·`tray_view` 교시, `drawer_top_view` 등록, `staging_tray` 3점 터치, `vision_stub` 4개 측정 → `poses.yaml`·`places.yaml`
- [ ] #15 `pick_object` `target` 계약 + `motion_guard` PR (10/04, 10/05 공휴일로 당김)
- [ ] #13 `drawer_control` 실물 — 10/04 저녁 착수, 못 끝내면 10/06 오전
- [ ] #15 `pick_object`·`place_object` 실물 — 10/06 오후. 노드 연결 때 `motion_guard` 호출(`yaw_valid` 기본값 넣지 않기)
- [ ] #37 (Day 5~6) `nudge_object` 실물 — 손가락 두께·벌림 폭·바닥 감지 힘 임계 실측
- [ ] #19 E-stop(펜던트·키보드) + 저속 → 정상 속도 절차
- [ ] (P2) `sim`용 DSR 드라이버·에뮬레이터 DRCF v2/v3 맞추기 (PR #40 리뷰 스레드)

## 철회한 결론
- ~~10/02 팀 구성에서 채택 npy 적용 확인~~ → 그때 쓴 것은 강의 폴더의 2월 파일이었을 가능성이 큼(해시 다름). 채택 값 검증은 10/03 5점 검증으로 대체.
- ~~프로젝트 TCP 이름 `GripperDA_V1`~~ → 제어기가 반환한 실제 이름은 `GripperDA_v1` (10/02).
- ~~`set_tcp`가 잘못된 이름을 조용히 무시한다~~ → 자동 모드에서는 이름과 무관하게 거부, 수동 모드에서는 잘못된 이름에 `success=False` (10/02).
- ~~#6 3점 터치 전에 손끝 돌출량 측정 필요~~ → 교시·터치한 TCP 값을 같은 기준으로 쓰면 불필요, 수업 때도 문제 없었음 (10/03).
- ~~컨테이너 드라이버로 `move_joint`가 동작하지 않는다~~ → 10° 회전이라 눈에 안 띄었을 뿐, 30°에서 동작 확인 (10/03).
