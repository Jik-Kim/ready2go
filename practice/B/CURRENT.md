# CURRENT — B 서동권

- **담당**: 실물 로봇 모션 (`ready2go_skills`) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- #4 완료 (10/03 실물 확인): `ros2-core` 컨테이너에서 DSR 드라이버 Real 모드 접속, `move_joint`로 실물 동작, RG2 열기·닫기·폭 읽기, `/gripper/state` 발행.
  - 컨테이너 실행: `docker compose --profile real run --rm ros2-core bash -c "colcon build --symlink-install --packages-select ready2go_interfaces ready2go_skills && source install/setup.bash && ros2 launch ready2go_skills dsr_real.launch.py"` (`.env`: `BACKEND=real`, `ROBOT_HOST=192.168.1.100`)
  - 호스트 드라이버(`cobot2_ws`)와 동시에 띄우지 않는다 — 같은 제어기에 이중 접속, 같은 이름의 토픽·서비스가 생김.
- #7: B 확인 항목(프레임 이름, `link_6` 원점, TCP·툴, `set_current_tcp`) 완료. **5점 검증 완료 (10/03)** — 채택 npy로 x·y 5곳 일치, z 일관. 남은 것: A의 meta 확정 반영, C의 bringup TF.
  - ⚠️ 강의 폴더 `corecode/Calibration_Tutorial/T_gripper2camera.npy`(md5 `ed3c4a6c…`, 2026-02-25)는 채택 값(`dea4dee3…`)과 다름. 이 파일로는 z가 약 31 mm 높게 계산됨 → 강의 코드로 실행할 때는 `config/calibration/`의 npy를 복사해 쓴다.
- #6: `config/places.yaml`을 `tf` 블록 형식으로 변경(값은 측정 전이라 null).

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

## 막힌 점 · 필요한 도움
- `/gripper/state`의 `width` 단위(m)를 Runner(C)와 맞춰야 함.

## 다음 할 일
- [x] #7 5점 `verify.py` 검증 (10/03)
- [ ] #6 (Day 2) 기준 포즈 교시, 서랍 좌표계 측정 → `poses.yaml`·`places.yaml` 값
- [ ] #8 (Day 2) 물품 RG2 파지 테스트
- [ ] #13 (Day 3) `drawer_control` 실물
- [ ] #15 (Day 4) `pick_object`·`place_object` 실물

## 철회한 결론
- ~~10/02 팀 구성에서 채택 npy 적용 확인~~ → 그때 쓴 것은 강의 폴더의 2월 파일이었을 가능성이 큼(해시 다름). 채택 값 검증은 10/03 5점 검증으로 대체.
- ~~프로젝트 TCP 이름 `GripperDA_V1`~~ → 제어기가 반환한 실제 이름은 `GripperDA_v1` (10/02).
- ~~`set_tcp`가 잘못된 이름을 조용히 무시한다~~ → 자동 모드에서는 이름과 무관하게 거부, 수동 모드에서는 잘못된 이름에 `success=False` (10/02).
- ~~#6 3점 터치 전에 손끝 돌출량 측정 필요~~ → 교시·터치한 TCP 값을 같은 기준으로 쓰면 불필요, 수업 때도 문제 없었음 (10/03).
- ~~컨테이너 드라이버로 `move_joint`가 동작하지 않는다~~ → 10° 회전이라 눈에 안 띄었을 뿐, 30°에서 동작 확인 (10/03).
