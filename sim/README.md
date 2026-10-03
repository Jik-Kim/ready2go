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

## 자산 (`sim/assets/`, 아직 커밋하지 않음)
- `sim/assets/m0609_camera_cube/`: 기존 M0609 + 카메라 + RG2 조립본 (약 15 MB, `~/isaac_legacy/M0609_jik/Collected_m0609_camera_cube` 복사본).
- `git-lfs`가 설치되기 전에는 USD를 커밋하지 않는다.

## T1 씬 (`sim/scenes/ready2go_t1.usd`)
작업대 + M0609/RG2 + 손목 카메라. 월드 = 로봇 `base_link`. **서랍은 10/03에 철제 고정대 + 원목 서랍으로 교체하기로 해 기존 플라스틱 서랍장 값을 모두 삭제했고, 현재 씬에는 서랍장이 없다.** 새 서랍을 설치해 `sim/drawer_dimensions.yaml`과 `config/places.yaml`의 서랍 값을 채우고 `build_scene.py`를 다시 실행하면 받침 선반 + 서랍장(맨 위 단 Prismatic Joint)이 만들어진다.
```bash
~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py     # 씬 생성 (sim/drawer_dimensions.yaml, config/calibration/ 에서 값을 읽음)
~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py    # 검증 (9개 구조 + 카메라 변환 + 서랍 가동 범위 + 로봇 안정성), 마지막 줄 `[verify] 결과: 전부 통과`로 판정
```
GUI에서 열기: `bash sim/run_isaac.sh`로 Isaac Sim을 켠 뒤 **File ▸ Open**으로 `sim/scenes/ready2go_t1.usd`.
- 서랍 움직여 보기(서랍장이 있을 때): Stage에서 `/World/workspace/cabinet/drawer_top_joint` 선택 → Property ▸ Drive ▸ Linear ▸ **Target Position**(m, 0~max_travel) → Play.
- 손목 카메라 시점: 뷰포트 카메라 메뉴에서 `/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera`.
- **생성 파일이라 USD를 직접 수정하지 말고** `build_scene.py`나 `drawer_dimensions.yaml`을 고친 뒤 다시 생성한다.

### 이 씬이 근사하는 부분 (전부 [추정], 실측되면 교체)
| 항목 | 현재 값 | 교체할 때 |
| :--- | :--- | :--- |
| 로봇과 작업대 변의 각도 | `WORKSPACE_YAW_DEG = 0` (미확인) | #6(3점 터치) 결과 |
| 로봇 축 위치 | 베이스 철판 중심 = 원점 | #6/URDF 확인 |
| `link_6` 원점 = 플랜지 면 | 가정 (손목 카메라 위치에 영향) | B 확인 |
| 스테이징·전달 트레이 | 아직 없음 (크기 미측정) | 실측 후 추가 |

검증으로 확인된 것 [실측]: 카메라 광학 프레임이 `npy × TCP`로 직접 계산한 값과 일치(평행이동 4 µm, 회전 0.0007°), 로봇은 중력에 무너지지 않음(link_6 변화 0.5 mm). (서랍 가동 범위 검증은 기존 플라스틱 서랍장 기준이었고 서랍 교체로 삭제됨 — 새 서랍 씬에서 다시 확인)

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

