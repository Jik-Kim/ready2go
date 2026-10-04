# Docker · 컨테이너 구성

> 관련 요구사항: [NFR-ENV-01](requirements.md#nfr-env-01), [FR-COM-02](requirements.md#fr-com-02), [FR-LOG-01–02](requirements.md#fr-log-01), [NFR-DB-01](requirements.md#nfr-db-01). 컨테이너·네트워크 구현 상세는 이 문서에서 다룹니다.

## 4. Docker / 컨테이너 구성 (필수)

### 4.1 서비스 구성

| 서비스 | 베이스 이미지 | 프로파일 | 역할 |
| :--- | :--- | :--- | :--- |
| `ros2-core` | `ros:jazzy` 기반 커스텀 | `real`, `sim`, `dev` | Runner(상태 추적), Logger, 로봇 온톨로지, 플래너, 모션 스킬, DSR 드라이버, 그리퍼 제어 |
| `db` | `mongo:7.0` (버전 고정, 지원 2027-08-31까지. 8.0은 커널 6.19+ 비호환, 이슈 #34) | `real`, `sim`, `dev` | 실행 로그·스텝 기록·상태 스냅샷 저장(JSON 문서 그대로 저장). 과목 목표 "DataBase 활용" 대응 |
| `vision` | `ros:jazzy` + ultralytics (+CUDA 선택) | `real`, `sim` | 검출, 3D 위치, 가림 순서, 인스턴스 ID 추적 |
| `realsense` | `ros:jazzy` + realsense2_camera | `real` | 손목 RealSense RGB-D 발행 (표준 토픽명으로 remap) |
| `voice` | `ros:jazzy` + 음성 스택 | `real`, `sim`, `dev` | 웨이크워드 → STT → 인텐트, TTS |
| `dsr-emulator` | `doosanrobot/dsr_emulator:3.0.1` | `sim`, `dev` | M0609 가상 제어기 |
| `mock-sim` | `ros:jazzy` + Python | `dev` | 가짜 조인트·서랍·카메라 토픽 (예정). 로봇 원자 동작 mock 은 우리 작업공간이 필요해 `ros2-core` 안의 `mock_backend`가 맡음(`BACKEND=mock`, #10) |

* **Isaac Sim은 컨테이너에 넣지 않음**: 과목 필수 요소가 아닌 팀 선택 도구로, 실물 로봇·카메라처럼 외부 환경으로 취급함. PC1의 네이티브 설치본(`~/isaac-sim-5.1.0`)을 `sim/isaac_env.sh`로 환경을 맞춘 뒤 실행함. **시스템 ROS를 source하지 않고** Isaac Sim 번들의 내부 ROS 라이브러리 + CycloneDDS(Domain 70)를 씀 [실측 10/03]: Kit의 Python은 3.11이고 시스템 Jazzy `rclpy`는 3.12용이라 시스템 ROS를 source하면 `rclpy`를 불러오지 못함. **팀 로직은 Isaac Sim 안에 두지 않고**(씬 로드·ROS 2 Bridge·조인트 미러링만), 전부 컨테이너의 ROS 노드에 둠.
* 기존 `ros:jazzy-ros-base-noble` 기반 `yolo-detection` 컨테이너를 `vision`의 시작점으로 재사용함.
* ROS 2 배포판은 **Jazzy(Ubuntu 24.04)로 확정**.

### 4.2 `docker-compose.yml` 골격

> **원본 파일**: [`compose.yaml`](../compose.yaml)

**CycloneDDS 설정 (강사 제공본 기반)**
* `config/cyclonedds.local.xml`: 강사 제공 `cyclonedds.xml` **원본 그대로** (`lo` 전용). 단일 PC 개발에 사용.
* `config/cyclonedds.multi.xml`: 강사 제공본에서 **인터페이스와 탐색 방식만 변경**한 다중 PC용. 버퍼 설정은 원본과 동일.

> **원본 파일**: [`config/cyclonedds.multi.xml`](../config/cyclonedds.multi.xml) (강사 제공 원본은 [`config/cyclonedds.local.xml`](../config/cyclonedds.local.xml))

**실행 절차 (장비별 명령 1개)**
* PC2 (실물): `docker compose --profile real up` (`.env`: `BACKEND=real`, `ROBOT_HOST=<제어기 IP>`, `RG2_HOST=<RG2 IP>`, `DDS_MODE=multi`) — DSR 드라이버·`/gripper/state`가 함께 기동
* PC1 (사전 검증): Isaac Sim 네이티브 실행 후 `docker compose --profile sim up` (`.env`: `BACKEND=sim`, `VISION_MODE=oracle`)
* PC1 (실물 미러링 트윈): Isaac Sim 네이티브만 실행 (`DDS_MODE=multi`로 PC2의 `/dsr01/joint_states` 수신)
* 개발: `docker compose --profile dev up` — `ros2-core`가 Runner 노드와 mock 백엔드를 띄움. 시험 태스크는 `.env`의 `RUNNER_TASK_FILE=/contracts/examples/task_skill_steps.json`, 실패 시험은 `MOCK_FAIL`·`MOCK_NOT_VISIBLE` ([runner.md](runner.md) 7.1 "Runner 노드")
* 장비별 값은 각 PC의 `.env`에 고정하여 실제 실행은 명령 1개로 유지.

### 4.3 운영 규칙 및 알려진 함정 (이미 겪은 이슈 포함)
* **RMW (확정)**: 강사 제공 **CycloneDDS**(`rmw_cyclonedds_cpp`)를 모든 컨테이너, 호스트, 네이티브 Isaac Sim에서 사용함. 호스트 `.bashrc`의 `RMW_IMPLEMENTATION`/`CYCLONEDDS_URI`/`ROS_DOMAIN_ID=70`도 컨테이너와 같은 값으로 맞춤(10/02 전 팀원 확인 완료). 단 PC1(A)의 새 로그인 셸에는 이 변수들이 설정돼 있지 않았음 [실측 10/03] — Isaac Sim은 `sim/isaac_env.sh`가 지정하고, `ros2` CLI는 `sim/README.md`의 환경으로 사용.
* **커널 버퍼 설정**: 강사 스크립트(`a08_cyclone.sh`)의 sysctl 버퍼 설정을 **모든 PC 호스트에 적용**함. `network_mode: host` 컨테이너는 호스트 네트워크 설정을 그대로 따름.
* **다중 PC 통신**: 강사 제공 원본은 `lo` 전용이라 PC 간 통신이 되지 않으므로 다중 PC는 `multi` 설정을 사용하고, 방화벽(ufw)에서 DDS UDP 포트를 허용함. PC2는 로봇 제어기용 유선 + 팀 공유기 2개 네트워크에 연결되므로 `DDS_IFACE`를 **팀 공유기 쪽**으로 지정.
* **호스트에서 다중 PC 통신 쓰기** [실측 10/03, #3]: 호스트 `~/.config/cyclonedds/cyclonedds.xml`(강사 원본, `lo` 전용)은 수업 코드에 영향이 가므로 **바꾸지 않고**, 다중 PC가 필요한 터미널에서만 저장소의 multi 설정을 씀. CycloneDDS가 설정 파일의 `${DDS_IFACE}`·`${PEER_PC1}`·`${PEER_PC2}`를 환경 변수에서 채움. 설정을 바꾼 뒤에는 `ros2 daemon stop`.
  ```bash
  source /opt/ros/jazzy/setup.bash && export ROS_DOMAIN_ID=70 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    CYCLONEDDS_URI=file://<이 PC의 저장소 경로>/config/cyclonedds.multi.xml DDS_IFACE=<NIC> PEER_PC1=<IP> PEER_PC2=<IP> && ros2 daemon stop
  ```
  * 저장소 경로는 PC마다 다름. 다른 PC의 경로를 쓰면 `can't open configuration file`로 노드 생성 실패.
  * `ros2 topic echo <토픽> --once`는 **타입을 지정**해야(예: `std_msgs/msg/String`) 다른 PC의 발행자를 기다림. 없으면 발견 전에 `Could not determine the type`로 끝남.
  * **안전**: multi 설정이면 다른 PC에서도 실물 로봇 명령 토픽(`/dsr01/...`)이 보임. 시험 토픽 외에는 보내지 말고, 실물을 움직이는 명령은 PC2에서 E-stop 담당자가 있을 때만.
* **와이파이 다중 PC** [실측 10/03, #3]: 강의장 공용 와이파이에서 PC1↔PC2 송수신은 되지만 `/dsr01/joint_states`(PC2 100 Hz)가 PC1에서 86~96 Hz로 간헐적으로 늦음(무선 절전을 끈 뒤 기준, 켜면 63~67 Hz). 다중 PC 노트북은 무선 절전을 끄고(`nmcli connection modify <연결> 802-11-wireless.powersave 2`), IP가 바뀌면 `.env`의 `PEER_*`를 다시 맞출 것. 로봇 제어는 PC2 안에서 끝나 영향 없음.
* **GUI 표시**: GUI 컨테이너(RViz 등)는 호스트에서 `xhost +local:root`, `DISPLAY`와 `/tmp/.X11-unix` 전달. **`DISPLAY` 값은 세션마다 다를 수 있음**(현재 PC1은 Xwayland `:1`).
* **오디오**: Ubuntu 24.04는 PipeWire가 ALSA 장치를 점유하므로 `/dev/snd` 직접 패스스루 대신 **PulseAudio 소켓을 마운트**함.
* **`real` 기동 전 호스트 드라이버 종료**: 호스트에서 DSR 드라이버(`cobot2_ws` 등)나 `realsense2_camera`를 띄운 채 `docker compose --profile real up` 하면, 같은 `/dsr01` 이름 때문에 컨테이너의 spawner가 호스트 controller_manager에 붙어 `Controller already loaded` → `Failed to configure controller`로 실패하고 제어기에도 이중 접속됨. 카메라도 장치 단독 점유라 충돌함. **호스트 드라이버·카메라 노드를 끄고 올릴 것** [실측 10/03, PC2, PR #40].
* **카메라 장치 독점**: `realsense2_camera`와 `cv2.VideoCapture`가 같은 장치를 동시에 열 수 없음. 항상 **ROS 토픽 구독 방식으로 통일**하고 `/dev/videoN` 번호는 하드코딩하지 않음.
* **RealSense 하드웨어 점검**: `Left MIPI error`는 USB 3.0 포트 직결 + 정품 케이블 + 재연결로 먼저 확인(10/02 재연결로 해결된 이력). 로봇 팔 움직임에 케이블이 당기지 않도록 케이블 고정.
* **비밀정보**: OpenAI API 키는 `secrets/*.env`로 분리하고 `.gitignore`에 등록.
* **재현성**: 이미지 태그 `latest` 금지, 버전 고정. 빌드 컨텍스트는 `docker/<서비스>/Dockerfile`로 관리.
