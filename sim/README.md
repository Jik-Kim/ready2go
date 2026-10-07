# sim — Isaac Sim 트윈 (담당 A 김병직, Phase 2~)

> 문서: [`docs/twin.md`](../docs/twin.md)

- Isaac Sim 5.1.0 **네이티브 실행**(컨테이너 아님). 환경은 `sim/isaac_env.sh`가 맞춘다 (아래).
- 팀 로직은 여기 두지 않음: 씬 로드, ROS 2 Bridge, 조인트 미러링 스크립트만.
- USD는 Git LFS(`.gitattributes`)로 관리하고 **A만 편집**. 기존 자산 출처: `~/isaac_legacy/M0609_jik` (M0609 + RG2 + 손목 카메라).
- Phase 1에는 필수 아님(씬 구성은 병행 가능).

## 실행
```bash
bash sim/run_isaac.sh          # 어느 터미널에서나 가능. 시스템 ROS가 source된 셸이어도 ROS 환경을 정리한 뒤 실행한다
```
수동으로 하려면 ROS가 source되지 않은 깨끗한 셸에서 `source sim/isaac_env.sh && ~/isaac-sim-5.1.0/isaac-sim.sh --/isaac/startup/ros_bridge_extension=isaacsim.ros2.bridge`.
- **`isaac_env.sh`는 시스템 ROS를 source한 셸에서는 스스로 중단한다**(`run_isaac.sh`는 이를 자동으로 처리). Kit의 Python은 3.11, 시스템 Jazzy `rclpy`는 3.12용이라 충돌한다 [실측 10/03]. Bridge는 번들의 내부 ROS 라이브러리(`jazzy/lib`)를 쓴다.
- DDS 값은 컨테이너와 같다: Domain 70, CycloneDDS. 다중 PC는 `DDS_MODE=multi`와 `DDS_IFACE`, `PEER_PC1`, `PEER_PC2`가 필요하다.

## Bridge 스모크 테스트 (`/clock` 발행)
```bash
source sim/isaac_env.sh && ~/isaac-sim-5.1.0/python.sh sim/scripts/bridge_smoke_test.py 120
```
다른 터미널에서 호스트의 `ros2` CLI로 확인한다 (시스템 ROS + 같은 DDS 값):
```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=70 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file://$PWD/config/cyclonedds.local.xml
timeout -s KILL 20 ros2 topic echo --once /clock
```
- `ros2` CLI는 `timeout`의 기본 종료 신호(SIGTERM)를 무시해 계속 남는다. **반드시 `timeout -s KILL`** 을 쓴다.
- 10/03 결과 [실측]: 호스트와 컨테이너(`ready2go-realsense` 이미지) 모두 `/clock`을 수신 (발행 노드 `_ClockGraph_clock`, RELIABLE/VOLATILE).

## 자산 (`sim/assets/`, Git LFS로 추적)
- `sim/assets/m0609_camera_cube/`: 기존 M0609 + 카메라 + RG2 조립본 (약 15 MB, `~/isaac_legacy/M0609_jik/Collected_m0609_camera_cube` 복사본).
- USD(`*.usd`·`*.usda`·`*.usdc`)는 `.gitattributes`로 Git LFS에 올린다. 받을 때 `git lfs install && git lfs pull`(포인터 파일만 있으면 씬이 열리지 않음). 과거 기록: 10/03까지는 `git-lfs` 설치 전이라 커밋하지 않았다

## T1 씬 (`sim/scenes/ready2go_t1.usd`)
작업대 + 받침 선반 + 원목 2단 서랍장(상자 2개 각각 Prismatic Joint 0~22.6 cm, 중간 가로막 없음) + M0609/RG2 + 손목 카메라. 월드 = 로봇 `base_link`. 서랍은 10/03에 철제 레일 + 원목 서랍으로 교체했고 기존 플라스틱 서랍장 값은 모두 삭제했다. 서랍 값이 하나라도 비면 `build_scene.py`는 서랍장 없이 만들고 이유를 출력한다.
```bash
~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py     # 씬 생성 (sim/drawer_dimensions.yaml, config/calibration/ 에서 값을 읽음)
~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py    # 검증 (9개 구조 + 카메라 변환 + 서랍 가동 범위 + 로봇 안정성), 마지막 줄 `[verify] 결과: 전부 통과`로 판정
```
GUI에서 열기: `bash sim/run_isaac.sh`로 Isaac Sim을 켠 뒤 **File ▸ Open**으로 `sim/scenes/ready2go_t1.usd`.
- 서랍 움직여 보기: Stage에서 `/World/workspace/cabinet/drawer_top_joint`(또는 `drawer_bottom_joint`) 선택 → Property ▸ Drive ▸ Linear ▸ **Target Position**(m, 0~max_travel) → Play.
- 손목 카메라 시점: 뷰포트 카메라 메뉴에서 `/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera`.
- **서랍 위치**: `config/places.yaml`의 `drawer_top.tf`(+`tf_at_travel_m`, #6 3점 터치 결과 = 최대 인출 상태의 서랍 좌표계)가 채워지면 `build_scene.py`가 그 값으로 서랍장을 놓는다(닫힘 = 원점 + `tf_at_travel_m` × 서랍 x축). `null`이면 평면도 기반 임시 배치로 만들고 출력에 이유를 남기며, `verify_scene.py`의 tf 일치 검사(원점 1 mm·회전 0.1° 이내)는 건너뛴다. 서랍 좌표계 정의는 `config/places.yaml` 첫 부분과 #6.
- 값이 오기 전 시험: `READY2GO_PLACES=<대체 places.yaml> READY2GO_SCENE=<출력 usd> bash sim/run_isaac.sh sim/scripts/build_scene.py` (verify도 같은 변수). 정본 씬을 덮어쓰지 않는다. 씬 파일을 `sim/scenes/` 밖에 두면 로봇 참조(상대 경로)가 깨져 prim 존재 검사 2건이 실패하니, 시험용 씬도 `sim/scenes/` 안에 두자.
- **생성 파일이라 USD를 직접 수정하지 말고** `build_scene.py`나 `drawer_dimensions.yaml`을 고친 뒤 다시 생성한다.

### 이 씬이 근사하는 부분 (전부 [추정], 실측되면 교체)
| 항목 | 현재 값 | 교체할 때 |
| :--- | :--- | :--- |
| 로봇과 작업대 변의 각도 | `WORKSPACE_YAW_DEG = 0` (미확인) | #6(3점 터치) 결과 |
| 로봇 축 위치 | 베이스 철판 중심 = 원점 | #6/URDF 확인 |
| `link_6` 원점 = 플랜지 면 | 가정 (손목 카메라 위치에 영향) | B 확인 |
| 상자 앞·뒤벽 두께, 바닥판 두께, 서랍장 뒤판·바닥판 두께 | 상자 옆벽과 같다고 가정(1.1 cm), 바닥판 1.0 cm, 서랍장 판 1.8~1.9 cm | 실측 |
| 아래 서랍(`drawer_bottom`) 상자 크기·위치 | 위 서랍 `drawer_top.interior_m`을 공유해 만들고 위치는 위 서랍 tf와 같은 서랍장 안(단 높이 19.5−4.8). `places.yaml`의 `drawer_bottom.interior_m`(줄자 기준, 위 서랍과 측정 기준이 다름)은 씬에서 읽지 않음 | B의 3점 터치(P3) 후 `drawer_bottom` tf·내부 치수 |
| 받침 선반 크기 | 서랍장보다 사방 2 cm 크게 (미측정) | 실측 |
| 전달 트레이(`handover_zone`) | `places.yaml` `handover_zone.tf`·`interior_m`(B 바닥 터치 10/05)으로 고정 물체로 만듦. 위로 갈수록 넓어지는 사다리꼴: `interior_m`은 닫힌 손끝 중심 범위라 바닥을 사방 10 mm 넓히고 [추정], 벽 윗면은 손끝 범위 끝에서 15.8 mm 바깥(B 실측, 한 벽만 재서 네 벽 같다고 봄) → 바닥 154×110·윗면 166×122 mm, 높이 43 mm, 벽 기울기 7.7°, 두께 4 mm [추정]. 보이는 형상은 모서리 반경 12 mm [추정] 둥근 메시 하나, 충돌은 숨긴 사다리꼴 판 4장 + 바닥판(사용자 GUI 확인 10/06). 임시 트레이(`staging_tray`)는 폐기(#6) | 트레이 외곽 실측 |

#83 반영 재생성 [실측 10/06]: 서랍 원점 −3.0 mm(`places.yaml` `drawer_top.tf`)·내부 높이 0.0711·전달 트레이. `verify_scene.py` 전부 통과 — 최대 인출 서랍 좌표계와 `drawer_top.tf` 원점 차이 0.017 mm, 트레이 원점 차이 0.00 mm, 인출 22.60 cm.

검증으로 확인된 것 [실측]: 카메라 광학 프레임이 `npy × TCP`로 직접 계산한 값과 일치(평행이동 4 µm, 회전 0.0007°), 로봇은 중력에 무너지지 않음(link_6 변화 0.5 mm). 새 서랍 씬 검증 [실측 10/03]: 맨 위 서랍이 목표 22.5 cm(당시 씬 값, 이후 22.6 cm로 변경)에서 22.49 cm, 한계 초과 목표에서도 22.50 cm에서 멈추고 다른 축 이동 없음.


## 비전 사전 검증 (트윈 렌더 → 정답 대조) [실측 10/06]
로봇 없이 `inspect_region` 계산(좌표 변환·뎁스 덩어리·yaw·`top_z`)을 검증한다. 손목 카메라를 `drawer_top_view` 자세에 두고 서랍을 최대 인출(`max_travel_m`)로 연 뒤, 서랍 안에 지우개 크기 직육면체(`world.jsonld` 치수)를 임의 위치·방향으로 놓아 컬러·뎁스를 저장한다(씬 파일은 바꾸지 않음).
```bash
ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/render_eraser_test.py --n 30 --seed 1 --out <폴더> [--margin 0.03 | --touch]
python3 tools/dev/eval_inspect_sim.py <폴더> [--yolo models/yolo11n_ready2go_v1.pt]
```
- 결과(정답 직육면체를 투영한 박스 사용, 이상적 뎁스): 벽에서 4 cm 이상 30장 위치 오차 최대 0.6 mm·yaw 0.2°·`top_z` +0.6 mm, 벽에서 3 cm까지 가까운 30장도 같은 수준. 계산 실패 0장
- 벽에 붙인 배치(`--touch`, 벽 하나 또는 모서리, 간격 0~2 mm, 32장 seed 3) [실측 10/06]: 위치 오차 최대 0.5 mm, yaw 최대 2.3°, `top_z` 최대 +3.7 mm(벽면 뎁스가 덩어리에 조금 섞임), 계산 실패 0장
- 이것은 **센서 노이즈·결손·반사와 YOLO 검출 오차가 없는 하한**이다. 실물 오차(AC-VIS-01 1.5 cm)는 별도로 재야 한다
- 학습한 YOLO가 시뮬 컬러에서 흰 직육면체를 찾은 것은 12/30장뿐이다(실물 사진으로 학습해서 합성 이미지는 잘 못 찾음). 시뮬은 검출이 아니라 **기하(좌표·높이·yaw) 검증용**이다
- 시뮬 카메라의 서랍 좌표 위치(0.1135, 0.1661, 0.3628)와 실제 이미지 FK 계산(0.1106, 0.1626, 0.3676)이 5 mm 안팎으로 같다. 로봇이 목표 자세에서 최대 0.6° 처진다(물리 시뮬레이션)

## T2 미러링 (`sim/scripts/mirror_joint_states.py`)
`/dsr01/joint_states`를 구독해 트윈의 M0609 관절을 그대로 따라가게 한다. **구독만 하고 로봇에는 어떤 명령도 보내지 않는다.**
- 입력 [실측 10/03, 에뮬레이터]: `sensor_msgs/JointState`, 이름 `joint_1`~`joint_6`, 단위 **라디안**, 약 **100 Hz** (그리퍼 관절은 이 토픽에 없음 → 스크립트가 `finger_joint`를 매 스텝 열림(0°) 목표로 붙잡는다. 안 붙잡으면 팔을 순간이동시키는 동안 손가락이 서서히 닫힌다: 4초에 42.6° [실측 10/03]. 붙잡으면 최대 0.4° 이내. 정지 상태에서는 닫히지 않음)
- 드라이버·에뮬레이터는 가상 모드로 실행: `ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=virtual host:=127.0.0.1 port:=12345 model:=m0609 gui:=false` (`~/cobot2_ws` 소스 후). 가상 모드는 에뮬레이터 컨테이너를 launch가 자동으로 띄우고 종료한다.
- DSR 모션 서비스 이름은 **`/dsr01/dsr_controller2/motion/...`** 이다 (`/dsr01/motion/...` 아님) [실측].
```bash
# GUI로 보기 (창을 닫거나 Ctrl+C로 종료)
ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/mirror_joint_states.py
# 헤드리스 시험 (--duration이 있으면 마지막에 `[mirror] 결과: 통과/실패` 줄을 출력)
ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/mirror_joint_states.py --headless --duration 30
```
- 2초마다 수신 주기, 메시지 지연(수신 시각 − `header.stamp`), 추종 오차를 출력한다.
- 시험 [실측, 별도 시험 토픽 50 Hz 발행]: 수신 50 Hz, 평균 지연 2.2 ms, 최대 추종 오차 4.2 mrad(0.24°), 매핑 안 된 이름 없음, 1249건 처리.
- 추종 오차는 위치를 설정한 뒤 물리 스텝 한 번 후 읽은 값과 받은 값의 차이다(중력·구동 목표 때문에 0이 되지는 않음).


## 스킬 흐름 궤적·특이점 검사 (`sim/motion_check/`, `sim/scripts/play_motion_trace.py`) [실측·계산 10/06]
B 모션 코드를 로봇 없이 돌려 이동 명령을 기록하고, 관절 궤적을 계산해 특이점 근처 구간을 찾은 뒤 트윈에서 재생한다. 10/06 실물에서 팔이 "확확" 움직인 구간(영상 1:14~17, 2:02~04)을 재현하려고 만들었다.
```bash
python3 sim/motion_check/trace_skill_flow.py --repo <B 저장소> --out /tmp/trace.json   # 스킬 서버 흐름 (열기→끌기→집기→놓기→닫기→홈)
python3 sim/motion_check/trace_b_demo.py --repo <B 저장소> --out /tmp/trace_demo.json  # 시연 스크립트 b_demo.py 흐름
ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/play_motion_trace.py --trace /tmp/trace.json [--segments 15-24] [--flag-slow 2] [--loop]
python3 -m pytest sim/motion_check -q   # 기구학 시험 (CI 대상 아님)
```
- `m0609_kin.py`: M0609 FK(`m0609.urdf`, rpy 1.571 → π/2) + TCP 228 mm(GripperDA_v1), 두산 posx(ZYZ), 자코비안, DLS IK. 교시 자세 4개 TCP 오차 1.3~2.2 mm [실측 비교]
- `trace_skill_flow.py`: B `skill_server` 실제 코드를 기구학 가짜 로봇에 연결(ROS·DSR·RG2 는 가짜). 직선 이동은 0.5 mm·0.25° 간격 IK, 관절 이동은 선형, 관절 스플라인(`movesj`)은 Catmull-Rom 근사. 힘 감시는 누르기 접촉만 흉내
- `trace_b_demo.py`: `scripts/b_demo.py` 를 그대로 불러 로봇 객체만 가짜로 바꿈(감시 함수·연속 확인은 b_demo 것 그대로)
- 판정 ◀: 직선 이동에서 |J3| < 15° 또는 |J5| < 10° 또는 손끝 10 mm(회전 5°)당 최대 관절 변화 > 20°. **실물 대조 [10/06]**: 튄 구간은 J3 10°(10 mm당 11.8°)·0°(63°), 튀지 않은 구간은 J3 25° 이상(집기 전 수직 복귀 12.7°, 기울이기 5.8°, 집기 하강·상승 4.6°). 10 mm당 관절 변화만으로는 가르지 못해 J3 를 주 기준으로 함(처음 기준 > 4° 는 과민)
- 재생: 매 스텝 관절 위치를 그대로 설정(텔레포트, 떨림 없음), 실제 시간에 맞춤, RG2 폭 → `finger_joint` 각도(트윈 손가락 간격 실측 표, 0° 137.3 mm … 67.6° 38.7 mm 를 폭 110…0 mm 로 선형 대응 [추정]), 서랍·지우개 움직임은 흉내
- **한계**: 기하(IK)만 본다 — 두산 제어기의 실제 보간·특이점 처리·`movesj` 곡선과 다를 수 있다 [추정]. 트윈에 손목 카메라(D435i)·케이블 형상이 없다
- main(#83 머지 뒤) [계산 10/06]: 스킬 서버 흐름·`b_demo.py` 모두 끝까지 성공, ◀ 없음 — 스킬 서버도 탑뷰에서 내려가기를 관절 이동으로 바꿈. 가짜 로봇은 조회할 때마다 경로를 한 칸씩 나아감(B 의 새 누르기 판정이 내려가는 중의 힘 변화를 보기 때문), 경로 끝 자세는 명령값 그대로(ZYZ 는 B≈180°에서 A·C 표현이 여러 개)
- 결과 [계산 10/06, #83 `1ecafb6` `b_demo.py`]: 탑뷰에서 내려가기를 관절 이동(`DOWN`)으로 바꿔 예전 직선 하강(10 mm당 11.8°, J3 10°)이 사라짐. 바뀐 기준으로 ◀ 없음 — 제자리 30° 기울이기(10 mm당 5.8°), 집기 전 수직 복귀(12.7°, J3 25°), 집기 하강·상승(4.6°)은 실물에서도 특이점 없음 [사용자 확인 10/06]. 들고 나오기(`carry_out` movesj)는 ◀ 없음. 다만 쥔 지우개가 열린 위 서랍 앞판 위를 약 12 mm로 지남(경유점 2·3 을 +30 mm 올리면 38 mm) [메시 간격 계산, 스플라인 근사]
