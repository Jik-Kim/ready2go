# Docker · 컨테이너 구성

> 요구사항 기준: [requirements.md](requirements.md). 이 문서는 기술 상세를 정의하며, 범위·Phase·완료 기준은 요구사항 기준 문서를 따릅니다.
>
> **Phase 범위**: 전 Phase 공통(과목 필수). `db`(MongoDB)는 [FR-LOG-01](requirements.md#fr-log-01)에 따라 **P1부터 기본 실행 이력 저장에 사용**하고, P2에서 상세 상태 로그를 추가한다. DB 장애 시 JSONL 폴백을 사용한다. `dsr-emulator`·`mock-sim`은 개발용으로 P1부터 사용.

## 4. Docker / 컨테이너 구성 (필수)

### 4.1 서비스 구성

| 서비스 | 베이스 이미지 | 프로파일 | 역할 |
| :--- | :--- | :--- | :--- |
| `ros2-core` | `ros:jazzy` 기반 커스텀 | `real`, `sim`, `dev` | Runner(상태 추적), Logger, 로봇 온톨로지, 플래너, 모션 스킬, DSR 드라이버, 그리퍼 제어 |
| `db` | `mongo:8.0` (버전 고정, 지원 2029-10까지) | `real`, `sim`, `dev` | 실행 로그·스텝 기록·상태 스냅샷 저장(JSON 문서 그대로 저장). 과목 목표 "DataBase 활용" 대응 |
| `vision` | `ros:jazzy` + ultralytics (+CUDA 선택) | `real`, `sim` | 검출, 3D 위치, 가림 순서, 인스턴스 ID 추적 |
| `realsense` | `ros:jazzy` + realsense2_camera | `real` | 손목 RealSense RGB-D 발행 (표준 토픽명으로 remap) |
| `voice` | `ros:jazzy` + 음성 스택 | `real`, `sim`, `dev` | 웨이크워드 → STT → 인텐트, TTS |
| `dsr-emulator` | `doosanrobot/dsr_emulator:3.0.1` | `sim`, `dev` | M0609 가상 제어기 |
| `mock-sim` | `ros:jazzy` + Python | `dev` | 가짜 조인트·서랍·카메라 토픽, 미리 정의한 검출 결과 |

* **Isaac Sim은 컨테이너에 넣지 않음**: 과목 필수 요소가 아닌 팀 선택 도구로, 실물 로봇·카메라처럼 외부 환경으로 취급함. PC1의 네이티브 설치본(`~/isaac-sim-5.1.0`)을 호스트 ROS 2 Jazzy + CycloneDDS를 source한 뒤 실행함. **팀 로직은 Isaac Sim 안에 두지 않고**(씬 로드·ROS 2 Bridge·조인트 미러링만), 전부 컨테이너의 ROS 노드에 둠.
* 기존 `ros:jazzy-ros-base-noble` 기반 `yolo-detection` 컨테이너를 `vision`의 시작점으로 재사용함.
* ROS 2 배포판은 **Jazzy(Ubuntu 24.04)로 확정**.

### 4.2 `docker-compose.yml` 골격

> **원본 파일**: [`compose.yaml`](../compose.yaml)

**CycloneDDS 설정 (강사 제공본 기반)**
* `config/cyclonedds.local.xml`: 강사 제공 `cyclonedds.xml` **원본 그대로** (`lo` 전용). 단일 PC 개발에 사용.
* `config/cyclonedds.multi.xml`: 강사 제공본에서 **인터페이스와 탐색 방식만 변경**한 다중 PC용. 버퍼 설정은 원본과 동일.

> **원본 파일**: [`config/cyclonedds.multi.xml`](../config/cyclonedds.multi.xml) (강사 제공 원본은 [`config/cyclonedds.local.xml`](../config/cyclonedds.local.xml))

**실행 절차 (장비별 명령 1개)**
* PC2 (실물): `docker compose --profile real up` (`.env`: `BACKEND=real`, `ROBOT_HOST=<제어기 IP>`, `DDS_MODE=multi`)
* PC1 (사전 검증): Isaac Sim 네이티브 실행 후 `docker compose --profile sim up` (`.env`: `BACKEND=sim`, `VISION_MODE=oracle`)
* PC1 (실물 미러링 트윈): Isaac Sim 네이티브만 실행 (`DDS_MODE=multi`로 PC2의 `/dsr01/joint_states` 수신)
* 개발: `docker compose --profile dev up`
* 장비별 값은 각 PC의 `.env`에 고정하여 실제 실행은 명령 1개로 유지.

### 4.3 운영 규칙 및 알려진 함정 (이미 겪은 이슈 포함)
* **RMW (확정)**: 강사 제공 **CycloneDDS**(`rmw_cyclonedds_cpp`)를 모든 컨테이너, 호스트, 네이티브 Isaac Sim에서 사용함. 호스트 `.bashrc`의 `RMW_IMPLEMENTATION`/`CYCLONEDDS_URI`/`ROS_DOMAIN_ID=70`도 컨테이너와 같은 값으로 맞춤(10/02 전 팀원 확인 완료).
* **커널 버퍼 설정**: 강사 스크립트(`a08_cyclone.sh`)의 sysctl 버퍼 설정을 **모든 PC 호스트에 적용**함. `network_mode: host` 컨테이너는 호스트 네트워크 설정을 그대로 따름.
* **다중 PC 통신**: 강사 제공 원본은 `lo` 전용이라 PC 간 통신이 되지 않으므로 다중 PC는 `multi` 설정을 사용하고, 방화벽(ufw)에서 DDS UDP 포트를 허용함. PC2는 로봇 제어기용 유선 + 팀 공유기 2개 네트워크에 연결되므로 `DDS_IFACE`를 **팀 공유기 쪽**으로 지정.
* **GUI 표시**: GUI 컨테이너(RViz 등)는 호스트에서 `xhost +local:root`, `DISPLAY`와 `/tmp/.X11-unix` 전달. **`DISPLAY` 값은 세션마다 다를 수 있음**(현재 PC1은 Xwayland `:1`).
* **오디오**: Ubuntu 24.04는 PipeWire가 ALSA 장치를 점유하므로 `/dev/snd` 직접 패스스루 대신 **PulseAudio 소켓을 마운트**함.
* **카메라 장치 독점**: `realsense2_camera`와 `cv2.VideoCapture`가 같은 장치를 동시에 열 수 없음. 항상 **ROS 토픽 구독 방식으로 통일**하고 `/dev/videoN` 번호는 하드코딩하지 않음.
* **RealSense 하드웨어 점검**: `Left MIPI error`는 USB 3.0 포트 직결 + 정품 케이블 + 재연결로 먼저 확인(10/02 재연결로 해결된 이력). 로봇 팔 움직임에 케이블이 당기지 않도록 케이블 고정.
* **비밀정보**: OpenAI API 키는 `secrets/*.env`로 분리하고 `.gitignore`에 등록.
* **재현성**: 이미지 태그 `latest` 금지, 버전 고정. 빌드 컨텍스트는 `docker/<서비스>/Dockerfile`로 관리.
