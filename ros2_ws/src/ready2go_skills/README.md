# ready2go_skills

- **담당**: B 서동권
- **역할**: 실물/시뮬/목 백엔드의 모션 원자 동작(DSR·RG2) — 로봇을 움직이는 유일한 패키지

## 작업 전에 읽을 문서
- `docs/runner.md (7.1 원자 동작)`
- `docs/domain.md (8.4 서랍 개폐)`
- `docs/safety.md`
- `docs/interfaces.md`

## 구조

| 폴더 | 내용 |
| :--- | :--- |
| `ready2go_skills/core/` | ROS에 의존하지 않는 로직. **단위 테스트 대상** (`pytest`로 ROS 없이 실행) |
| `ready2go_skills/nodes/` | rclpy 노드 (ROS 토픽·서비스·액션 연결만) |
| `ready2go_skills/adapters/` | 장치·외부 서비스 연결 (DSR, RG2, RealSense, OpenAI, MongoDB 등) |
| `test/` | `core/` 테스트 |

## 규칙
- 다른 담당의 패키지는 수정하지 않음. 필요하면 GitHub Issue로 요청.
- 계약(`ready2go_interfaces`, `contracts/`)을 바꾸면 스키마·예시·문서를 같은 PR에서 함께 수정.

## 조그 창 `jog_gui` (교시·측정용 도구)
강의 `rokey_cobot2 jog` 화면을 바탕으로, 직접교시나 다른 도구로 로봇을 옮긴 뒤 +/- 를 누르면 **옛 위치로 돌아가던 문제**를 고친 창입니다. 태스크 실행 경로가 아니라 사람이 포즈를 교시하고 좌표를 재는 데 씁니다.

- +/- 짧게: **지금 위치**에서 Increment만큼 / 꾹(0.35초 이상): 누르는 동안 연속 이동, 떼면 정지 (최대 5초)
- 입력칸·맨 아래 실시간 좌표 0.3초 갱신 + copy (`posx([...])`, `posj([...])`)
- 축 정렬 x / y / z / r (TCP 위치 고정, 20° 조각, 돌기 전 확인창, 정렬 후 직접교시 선택). 계산은 `core/pose_math.py`
- grip(힘 칸) / release / 폭만큼 열기, 직접교시 ON/OFF, gohome(`config/poses.yaml` home, 확인창), 정지
- 시작할 때와 **이동 직전마다** 펜던트 TCP·툴 이름이 `config/calibration/calibration_meta.yaml`과 다르면 이동 버튼을 막음
- 한 칸이 10° 또는 20 mm보다 크면 확인창 (입력 실수로 크게 도는 것 방지)

실행 (PC2 호스트, DSR 드라이버 실행 중, `dsr_msgs2`가 있는 워크스페이스를 source 한 터미널):
```bash
cd ~/ready2go/ros2_ws/src/ready2go_skills && python3 -m ready2go_skills.nodes.jog_gui --rg2-ip 192.168.1.1
# colcon 빌드 후에는: ros2 run ready2go_skills jog_gui --rg2-ip 192.168.1.1
```
- `--config-dir`: 저장소 `config` 폴더 (기본: 자동 탐색, 환경변수 `READY2GO_CONFIG_DIR`)
- `--rg2-ip`: 생략하면 환경변수 `RG2_HOST`, 둘 다 없으면 그리퍼 버튼만 동작하지 않음
- 필요 패키지: `python3-tk`, `python3-yaml`
- **RG2 이중 접속 주의**: 이 창은 RG2 Modbus에 직접 붙는다. `docker compose --profile real up`의 그리퍼 노드(`/gripper/state`, 10 Hz 읽기)와 동시에 써도 되는지 확인 전이므로 **같이 띄우지 않는다** [팀 확정 필요, #69 PM 검토]

## 스킬 서버 (`skill_server`, BACKEND=real)
Runner 의 원자 동작을 `/skills/<동작>`(`Skill` 액션)으로 받는다. 이름·형식은 `docs/interfaces.md`·`runner.md` 7.1, C 의 `ready2go_runner/nodes/mock_backend.py`와 같다.

| 동작 | 상태 |
| :--- | :--- |
| `move_to_named_pose` | 구현: `config/poses.yaml` 관절각으로 `movej`, 도착 확인 |
| `drawer_control`·`nudge_object`·`pick_object`·`place_object` | TODO(B) 10/06 실측 후. 지금은 움직이지 않고 `NOT_IMPLEMENTED` |

- 공통 (`core/skill_flow.py`): 취소 요청 → 정지 → `canceled`(그리퍼는 그대로), 안전·비상정지 → `ESTOP`, 움직이기 전 펜던트 TCP·툴 확인 → `TOOL_NOT_SET`
- 서버 쪽 에러 코드: `UNKNOWN_POSE`·`POSE_NOT_TAUGHT`·`MOVE_REJECTED`·`MOTION_TIMEOUT`·`NOT_REACHED`·`NOT_IMPLEMENTED`·`BAD_PARAMS`·`BACKEND_ERROR` — `runner.md` 7.1 표 반영은 10/06 실물 연결 확인 후
- 파라미터: `joint_vel_deg_s`(기본 20, 처음은 저속), `joint_acc_deg_s2`, `move_timeout_s`(30), `reach_tol_deg`(0.5), `config_dir`, `dsr_prefix`

```bash
ros2 run ready2go_skills skill_server --ros-args -p joint_vel_deg_s:=10.0     # PC2, DSR 드라이버 실행 중
ros2 action send_goal /skills/move_to_named_pose ready2go_interfaces/action/Skill "{params_json: '{\"pose_name\": \"home\"}'}"
```
