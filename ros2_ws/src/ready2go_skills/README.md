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
- 축 정렬 x / y / z / r (TCP 위치 고정, 중간 멈춤 없이 한 번에 — 170° 넘으면 2번, 돌기 전 확인창, 정렬 후 직접교시 선택). 계산은 `core/pose_math.py`
- 그리퍼 회전 +/− (r 정렬 옆, 각도 칸 기본 90°, 최대 180°): 그리퍼 축(툴 z) 둘레, TCP 위치 고정. + = 수직 아래 자세에서 위에서 볼 때 시계 방향 (`pose_math.roll_target`)
- 기울이기 왼(−x)·오른(+x)·앞(+y)·뒤(−y)·수직 (서동권 자리 기준): TCP 위치 고정, 수직 아래에서 각도 칸(기본 30°, 최대 45°)만큼 손끝을 그쪽으로. 다시 눌러도 누적되지 않음. 끌기 자세 시험용 (`pose_math.tilt_target`)
- 회전은 도착(1 mm·0.5°)으로 끝을 확인 (실물에서 '이동 중' 상태가 늦거나 안 뜸, 10/06). 회전 시간 + 5초 안에 못 오면 정지
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
| `move_to_named_pose` | `config/poses.yaml` 관절각으로 `movej`, 도착 확인. 낮은 곳(서랍·트레이 안)이면 먼저 수직으로 `transit.safe_z_mm`까지 올림 |
| `drawer_control` (`drawer_top`·`drawer_bottom`) | 열기: **손잡이 앞(`drawer_approach`)에서만 시작**(아니면 `NOT_AT_START_POSE`) → 손잡이 직선 접근 → 잡기(폭 확인, 못 잡으면 열고 60 mm 빼기) → 당기기(걸림 감시, 끝 10 mm 안 걸림은 스토퍼) → 놓고 물러남 → 홈. 닫기: 교시한 45° 자세(`close_push`)로 앞판 중앙을 y 로 밀기 → 60 mm 빼기 (아래 칸은 수직 불가, 위 칸은 교시 전이면 수직 밀기). 상세 `docs/domain.md` 8.4 |
| `nudge_object` | 옆벽에 붙어 짧은 변으로 못 잡을 때만: 그리퍼를 벽 쪽 손끝으로 20° 기울여 위에서 내려가 힘 5 N 접촉(멈춘 채 3번 확인) → 0.1 mm씩 올려 1.5~2.5 N → 누른 z 그대로 **서랍 옆(y)으로만** `shift_mm`(40 mm, 10/07 저녁) 끌기 → 올라감. 끌기 전(누르기·힘 맞추기) 실패는 같은 자리에서 다시(`press_attempts` 3), 끌기 시작 뒤는 다시 안 함 (상세 `docs/domain.md` 8.5). 결과 `target_after` = 끈 뒤 예상 위치(**성공일 때만**, 실패면 `null`). `check_only: true`는 움직이지 않고 판단만 — 아직 끌어야 하거나 끌어도 못 잡으면 `PUSH_LIMIT` (`core/motion_plan.py` `plan_drag`, 트러블슈팅 2) |
| `pick_object` (서랍) | 짧은 변 잡기(`pick_plan`), 벌림 = 짧은 변 + 13 mm, 폭 확인(`check_grasp`: 닫은 폭 > `gripper.pick_min_width_m` 10 mm [사용자 결정 10/08, #43] 그리고 기대 폭 ± 3 mm — 기대 폭은 `pick.grasp_width_m`(실제로 잡는 부위, 망치 손잡이 12.5 mm), 없으면 짧은 변), 들어 올린 뒤 놓침 확인(`check_hold`). 접근: `drag_down` 교시된 서랍은 그리퍼 닫고 서랍 중앙 경유점(= `carry_line` 1) movej → **경유점 도착 뒤 그 손목 기준으로** 잡는 방향을 정함 → 서랍 안 옆 이동 높이(테두리 + `transit.in_drawer_clear_mm`)로 목표 바로 위까지 수평 → 목표 위(`grasp` + 최대 30 mm)로 수직(`_over_then_down`, 블렌딩 한 번) → 벌리고 내려감. **옆 물체**(10/09, 입력 `scan` 이 있을 때): 벌린 손가락 자리(넛지는 끄는 길)에 다른 물체가 겹치면 움직이기 전 `NEIGHBOR_TOO_CLOSE`(`core/neighbor_check.py`, params `neighbor`). **쌓인 물체**(`pick.allow_stacked`, 10/09): 받침 = 비전 `top_z` − 물체 높이 위에서 바닥과 같은 높이 규칙으로 집고, 쥔 물체 높이는 자기 바닥 기준으로 기억(놓을 땐 바닥에). 윗면이 테두리 − `stack_top_clear_m` 넘으면 `NOT_ON_FLOOR`(움직이기 전). 목표 위가 옆 이동 높이보다 높으면 그 높이로 옆 이동. 집은 뒤 수직으로 그 높이 → 경유점 1 로 수평 (10/08, 쌓인 물건 대비 — 탑뷰에서 바로 가면 특이점, 10/07). 교시 전 서랍은 safe_z 경로 (`docs/domain.md` 8.5) |
| `place_object` (`handover_zone`) | 빈 칸(트레이 x로 3칸), 집을 때 높이 + 1.5 mm에서 놓음, 옮기기 전 놓침 확인 |
| `place_object` (서랍 안, #166) | **구현 10/08, 실물 미확인.** `pose` 또는 `slot`(`places.yaml` `place_slots`, 교시 전 = `PLACE_NOT_CONFIGURED`) + `scan`. 움직이기 전: 쥔 물체 `id`가 `scan`에 있는지, 인출 거리, 이웃(`target`·`candidates`) → 벽 footprint 겹침(`core/place_plan.py`, 여유 `place.footprint_margin_mm` [팀 확정 필요]). 길: `drag_down` 경유점 → 테두리 + `transit.in_drawer_clear_mm` 높이로 수직 → 수평으로 놓을 자리 위 → 수직으로 내려 놓침 확인 → 집을 때 높이 + 1.5 mm에서 벌림 → 수직으로 올라 경유점 위. `placed_pose` 는 벌린 뒤에만 |

**아래 서랍(`drawer_bottom`)**: 코드는 공통. 열기 교시(손잡이 파지·손잡이 앞·최대 인출)는 10/08 실측으로 채움. 닫기는 `skills.yaml` `close_push.drawer_bottom` — 끝 posx 실측, 시작은 위 칸 시작에서 z 만 내린 **계산값**, 사용자 보고 실물 1회 성공(10/08, AC 반복 미완료). 넛지·집기·들고 나오기(`drag_down`·`carry_line`)와 서랍 안 이동 높이 상한은 교시 전

**쥔 물체 기억 (재시작)** [10/08]: `pick_object` 성공 때 쥔 물체(`class`·`id`·폭·서랍·높이)를 `held_file`(파라미터, 기본 `/tmp/r2g_skill_held.json`)에 저장하고, 놓거나 놓치면 지움. 서버가 시작할 때 이 파일이 있고 **그리퍼 폭이 저장한 폭과 `gripper.slip_tolerance_m`(2 mm) 안(HELD)**이면 쥔 상태로 되살림 → 재시작 뒤에도 `place_object` 가능. 폭이 다르면(활짝 열림·빈손 닫힘·다른 물체) 파일을 지우고 빈손으로 시작, 그리퍼를 못 읽으면 빈손으로 시작하되 파일은 남겨 다음 시작 때 다시 확인. 호스트 실행(`b_flow.sh server`)은 프로세스만 다시 켜면 파일이 남지만, 컨테이너(`ros2-core`)를 **다시 만들면** 컨테이너 `/tmp` 가 비어 기억이 없어짐. 서랍 인출 거리(`disp`)는 파일에 남기지 않음 — 재시작 뒤엔 늘 닫힘으로 시작(아래 시작 조건).

**시작 조건**: 서버를 띄울 때 서랍이 **닫혀 있어야** 한다 (서버는 인출 거리를 기억만 함). 재시작 뒤 열린 서랍을 닫으려면 `drawer_control`에 `displacement`(m)를 같이 준다 — 없으면 `DRAWER_STATE_UNKNOWN`(움직이지 않음). 닫기에 `then_home: true`를 주면 앞판에서 빼는 끝 `home_blend_mm`(10 mm) 안에서 멈추지 않고 홈까지 간다 — `B close` 전용, Runner 태스크는 쓰지 않음.
값: `params/skills.yaml` (그리퍼 기하·속도·끌기 — 10/05~06 로봇 실측), 장소 `config/places.yaml`, 물체 크기 `knowledge/world.jsonld`, 잡는 힘 `config/item_grasp.yaml`.
추가 에러 코드: `GRASP_FAILED`·`NOT_HOLDING`·`HOLDING_OBJECT`·`TRAY_FULL`·`PLACE_NOT_CONFIGURED`·`UNSUPPORTED_PARAMS`·`DRAWER_NOT_CONFIGURED`·`DRAWER_STATE_UNKNOWN`·`DRAWER_ALREADY_OPEN`·`NO_OBJECT_CONTACT`·`PUSH_BLOCKED`·`PUSH_LIMIT`·`NO_PUSH_ACCESS`·`DRAWER_STUCK`·`CLOSE_NOT_CONFIRMED`·`SENSOR_INVALID`

- 안전 오류 보존: 동작 실패·성공 뒤 복귀 이동(올리기·후퇴)도 결과를 확인하고, 둘 중 더 심각한 쪽(잠금 > `ESTOP` > 취소 > 일반)을 돌려준다. 안전 정지·취소 뒤에는 복귀 이동·그리퍼 동작을 보내지 않는다 (`skill_flow.worse`, #37 E 검토 10/06)
- 공통 (`core/skill_flow.py`): 취소 요청 → 정지 → **정지 확인되면** `canceled`(그리퍼는 그대로), 안전·비상정지 → `ESTOP`, 움직이기 전 펜던트 TCP·툴 확인 → `TOOL_NOT_SET`
- **정지를 확인하지 못하면**(정지 명령 실패·상태 조회 실패·정지 확인 3초 초과) `STOP_UNCONFIRMED`로 끝내고 서버를 **잠근다** — 이후 모든 동작은 `LOCKED`로 거부. 펜던트에서 로봇 상태를 확인한 뒤 `skill_server`를 다시 띄워야 풀린다. 이동 중 상태 조회가 1초 넘게 실패해도 정지 후 잠금(`STATE_UNKNOWN`). 이동 명령 응답이 없으면(수락 여부 모름) 정지·확인 후 `MOVE_UNCONFIRMED`로 잠금 — 늦게 도착한 요청으로 움직일 수 있어서
- **한 번에 한 동작**: 5개 액션 전체에서 실행 중인 동작이 있으면 새 goal을 거절하고, 수락과 실행 사이에 겹치면 `BUSY`(로봇 동작 없음)
- 서버 쪽 에러 코드: `UNKNOWN_POSE`·`POSE_NOT_TAUGHT`·`MOVE_REJECTED`·`MOTION_TIMEOUT`·`NOT_REACHED`(멈췄는데 목표 관절각·TCP와 다름 — 관절·직선 이동 모두)·`NOT_IMPLEMENTED`·`BAD_PARAMS`·`STOP_UNCONFIRMED`·`STATE_UNKNOWN`·`MOVE_UNCONFIRMED`·`MOVE_NOT_STARTED`(수락됐는데 3 s 안에 움직이지도 도착하지도 않음 → 정지)·`LOCKED`·`BUSY`·`SKILL_EXCEPTION`(서버 안 예외, 움직인 뒤일 수 있음 — Runner의 `BACKEND_ERROR`와 구분) — `runner.md` 7.1 표 반영은 10/06 실물 연결 확인 후
- 파라미터: `joint_vel_deg_s`(기본 20, 처음은 저속), `joint_acc_deg_s2`, `move_timeout_s`(30), `reach_tol_deg`(0.5), `config_dir`, `dsr_prefix`

```bash
ros2 run ready2go_skills skill_server --ros-args -p joint_vel_deg_s:=10.0     # PC2, DSR 드라이버 실행 중
ros2 action send_goal /skills/move_to_named_pose ready2go_interfaces/action/Skill "{params_json: '{\"pose_name\": \"home\"}'}"
```

**B 시험 명령 (현재)**: `scripts/b_sk.py` — `B <동작> [서랍]`, 서랍 = `top`|`bottom`(= `drawer_top`|`drawer_bottom`). 서랍 필요: `ready open opened close view scan rescan nudge all dragtest find`(`rescan` = 끌기 뒤 다시 인식, 그 좌표로 `B pick` / `find` = 손으로 연 서랍에서 잡을 때까지 다시 넛지 → 트레이), 없음: `home pick place`. Runner 와 같은 `/skills/<동작>` 요청을 보냄. 세팅·순서는 `practice/B/HANDOVER.md`.

**과거 단독 시험 (10/06, 현재 P1 경로 아님)** — 위 서랍, 세로 지우개를 서동권 쪽-오른쪽 모서리에. 이때는 넛지 **예상 위치**(`target_after`)로 바로 집었음. **현재 공통 `pick` 은 끈 뒤 탑뷰에서 다시 찍은 `scan.target` 으로 집는다**(`knowledge/skills/pick.jsonld`, `docs/domain.md` 8.5). 하나씩 보내고 결과 확인 (`--feedback`로 단계 표시):
```bash
S="ros2 action send_goal --feedback"
$S /skills/drawer_control ready2go_interfaces/action/Skill "{params_json: '{\"drawer_id\": \"drawer_top\", \"state\": \"open\"}'}"
T='{\"id\": \"eraser#1\", \"class\": \"eraser\", \"top_z\": 0.0115, \"pose\": {\"frame\": \"drawer_top\", \"position\": [0.1769, 0.2895, 0.0], \"yaw\": 0.0, \"yaw_valid\": true}}'
$S /skills/nudge_object ready2go_interfaces/action/Skill "{params_json: '{\"drawer_id\": \"drawer_top\", \"target\": $T}'}"
# (과거 10/06) pick 의 target 은 nudge 결과 target_after 를 그대로 — 현재는 재관측 scan.target (위 설명)
$S /skills/pick_object ready2go_interfaces/action/Skill "{params_json: '{\"drawer_id\": \"drawer_top\", \"target\": <target_after>}'}"
$S /skills/place_object ready2go_interfaces/action/Skill "{params_json: '{\"location\": \"handover_zone\"}'}"
$S /skills/drawer_control ready2go_interfaces/action/Skill "{params_json: '{\"drawer_id\": \"drawer_top\", \"state\": \"close\"}'}"
```
