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
작업대 + 받침 선반 + 3단 서랍장(맨 위 단은 Prismatic Joint 0~0.17 m) + M0609/RG2 + 손목 카메라. 월드 = 로봇 `base_link`.
```bash
~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py     # 씬 생성 (sim/drawer_dimensions.yaml, config/calibration/ 에서 값을 읽음)
~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py    # 검증 (9개 구조 + 카메라 변환 + 서랍 가동 범위 + 로봇 안정성), 통과 시 종료 코드 0
```
GUI에서 열기: `bash sim/run_isaac.sh`로 Isaac Sim을 켠 뒤 **File ▸ Open**으로 `sim/scenes/ready2go_t1.usd`.
- 서랍 움직여 보기: Stage에서 `/World/workspace/cabinet/drawer_top_joint` 선택 → Property ▸ Drive ▸ Linear ▸ **Target Position**(m, 0~0.17) → Play.
- 손목 카메라 시점: 뷰포트 카메라 메뉴에서 `/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera`.
- **생성 파일이라 USD를 직접 수정하지 말고** `build_scene.py`나 `drawer_dimensions.yaml`을 고친 뒤 다시 생성한다.

### 이 씬이 근사하는 부분 (전부 [추정], 실측되면 교체)
| 항목 | 현재 값 | 교체할 때 |
| :--- | :--- | :--- |
| 로봇과 작업대 변의 각도 | `WORKSPACE_YAW_DEG = 0` (미확인) | #6(3점 터치) 결과 |
| 서랍장 위치 | 평면도 기준 (앞면이 작업대 변에서 0.4 cm 바깥) | #6 결과 |
| 로봇 축 위치 | 베이스 철판 중심 = 원점 | #6/URDF 확인 |
| 트레이 벽·바닥 두께 | 옆벽 2.5 mm, 앞뒤 1.5 mm, 바닥 4 mm | 실측 |
| 손잡이 | 2 × 1.5 × 2 cm 박스 (돌출 길이 미측정) | 지름·돌출 길이 실측 |
| 아래 두 단 높이 | 같은 높이로 가정 | 실측 |
| `link_6` 원점 = 플랜지 면 | 가정 (손목 카메라 위치에 영향) | B 확인 |
| 스테이징·전달 트레이 | 아직 없음 (크기 미측정) | 실측 후 추가 |

검증으로 확인된 것 [실측]: 카메라 광학 프레임이 `npy × TCP`로 직접 계산한 값과 일치(평행이동 4 µm, 회전 0.0007°), 서랍은 목표 17 cm에서 16.99 cm, 한계 초과 목표(30 cm)에서도 17.00 cm에서 멈추고 다른 축 이동 없음, 로봇은 중력에 무너지지 않음(link_6 변화 0.5 mm).

