# sim — Isaac Sim 트윈 (담당 A 김병직, Phase 2~)

> 문서: [`docs/twin.md`](../docs/twin.md)

- Isaac Sim 5.1.0 **네이티브 실행**(컨테이너 아님). 환경은 `sim/isaac_env.sh`가 맞춘다 (아래).
- 팀 로직은 여기 두지 않음: 씬 로드, ROS 2 Bridge, 조인트 미러링 스크립트만.
- USD는 Git LFS(`.gitattributes`)로 관리하고 **A만 편집**. 기존 자산 출처: `~/isaac_legacy/M0609_jik` (M0609 + RG2 + 손목 카메라).
- Phase 1에는 필수 아님(씬 구성은 병행 가능).

## 실행
```bash
source sim/isaac_env.sh && ~/isaac-sim-5.1.0/isaac-sim.sh --/isaac/startup/ros_bridge_extension=isaacsim.ros2.bridge
```
- **시스템 ROS를 source한 셸에서는 실행하지 않는다**(스크립트가 막음). Kit의 Python은 3.11, 시스템 Jazzy `rclpy`는 3.12용이라 충돌한다 [실측 10/03]. Bridge는 번들의 내부 ROS 라이브러리(`jazzy/lib`)를 쓴다.
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
