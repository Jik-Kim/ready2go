# ready2go

음성 명령으로 실물 **Doosan M0609 + OnRobot RG2**가 서랍 속 물건을 찾아 꺼내고 원상 복구하는 시스템.
로봇의 동작·상태를 **JSON 온톨로지**로 정의하고, 명령에 맞춰 조합하며, 모든 동작의 성공 여부를 기록한다.

- 문서: [`docs/README.md`](docs/README.md) (인덱스부터) · 요구사항·Phase 기준 원본: [`docs/requirements.md`](docs/requirements.md)
- 스택: ROS 2 Jazzy · CycloneDDS(`ROS_DOMAIN_ID=70`) · Docker Compose · Python · MongoDB · Isaac Sim 5.1.0(트윈, 네이티브)

## 실행

[문서] 현재 Compose·launch·노드 진입점 기준의 실행 안내입니다. P1 음성(FR-INT-01~03), Runner(FR-PLN-01), 실행 기록(FR-LOG-01), Docker(NFR-ENV-01)에 해당하며, 아래 명령의 정적 확인과 실제 장치 연동·완료 기준 통과는 구분합니다.

### 1. 실행 전 준비

저장소 루트에서 실행합니다. `.env.example`을 참고해 `.env`에 `BACKEND`, `ROBOT_HOST`, `RG2_HOST`, DDS 설정을 채웁니다. 기존 `.env`·로컬 음성 설정·키·모델은 덮어쓰지 않습니다.

- 호스트·컨테이너 준비, DDS 버퍼·다중 PC 설정: [Docker 안내](docs/docker.md).
- 실행자·비상정지 대기자, TCP·툴·교시값·배치 확인: [안전 절차](docs/safety.md), [B 패키지 안내](ros2_ws/src/ready2go_skills/README.md).
- 카메라·모델·보정 파일과 의존성: [A 패키지 안내](ros2_ws/src/ready2go_vision/README.md).
- 마이크·API·웨이크 모델·MeloTTS 설치: [E 음성 패키지 안내](ros2_ws/src/ready2go_voice/README.md). 키는 `secrets/voice.env`, 로컬 모델은 `models/`에 두며 Git에 올리지 않습니다.

#### 프로젝트 의존성 설치

[문서] [requirements.txt](requirements.txt)는 음성뿐 아니라 전체 프로젝트의 Python 의존성 입구입니다. 공통 호스트 라이브러리와 테스트 도구를 설치하며, 충돌하는 Vision GPU·Melo CPU·Isaac 번들 환경은 아래 보조 설치 경로로 분리합니다. 패키지의 실제 import, `setup.py`, `package.xml`, Docker 선언과 tools/sim 실행 안내를 기준으로 구분했습니다. 범위 제한은 설치 안내이며 새 기능이나 Phase 완료 선언이 아닙니다.

| 구분 | 설치 대상·범위 |
|---|---|
| 공통 Python | PyYAML·jsonschema·numpy, Runner pymongo, Skills pymodbus, Vision/tools OpenCV·SciPy, Voice OpenAI/LangChain·sounddevice·dotenv, 웨이크의 비-TFLite 의존성 |
| 테스트/빌드 | pytest·setuptools는 requirements, colcon/rosdep는 ROS 개발 도구 |
| ROS | rclpy·launch/launch_ros·ament_index_python·std_msgs/std_srvs·sensor_msgs·tf2·cv_bridge·메시지 생성. apt/rosdep 및 프로젝트 colcon 빌드로 준비; pip 설치 대상 아님 |
| 시스템/서비스 | PortAudio·libsndfile·FFmpeg·오디오 서버/장치 권한·Tk, Git/LFS. espeak 선택 시 espeak-ng. Docker/Compose·MongoDB 서버·NVIDIA 드라이버는 별도 준비 |
| 벤더 | DSR 소스/overlay는 B 안내 및 `docker/ros2-core/Dockerfile` 기준. Isaac Sim 5.1/omni/pxr는 [sim 안내](sim/README.md)의 번들 Python 사용; Jazzy Python 3.12와 섞지 않음 |
| 환경별/자산 | Vision CUDA/YOLO와 Melo CPU는 아래 별도 설치. 웨이크 TFLite·전처리/VAD·TTS 모델 및 API 키는 코드 pull만으로 준비되지 않음 |
| 선택/향후 | faster-whisper·Piper는 현재 음성 실행 경로 없음. SAM2·P2~ 트윈 준비를 P1 필수 설치/완료로 간주하지 않음 |

아래 모든 프로젝트 명령의 작업 경로는 **저장소 루트**입니다. Ubuntu 24.04, 시스템 Python 3.12, ROS 2 Jazzy apt 저장소/설치가 준비되어 있어야 합니다. 기존 설정·가상환경은 삭제하거나 덮어쓰지 않습니다. 시스템/모델 설치 명령은 사용자가 해당 PC에서 실행하며, 이 문서 수정에서 실행하지 않았습니다.

```bash
sudo apt-get update
sudo apt-get install -y ros-jazzy-ros-base ros-dev-tools python3-venv python3-pip \
  python3-tk git git-lfs portaudio19-dev libportaudio2 libsndfile1 ffmpeg \
  ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-cv-bridge
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages .venvs/project
source .venvs/project/bin/activate
python3 -m pip install -r requirements.txt
# Linux/Python 3.12에서 audio extra의 tflite-runtime 자동 설치를 피합니다.
python3 -m pip install --no-deps openwakeword==0.6.0
```

웨이크 본체와 비-TFLite 의존성 설치까지의 절차입니다. **Python 3.12 TFLite 호환 런타임은 아직 저장소에 배포되지 않았습니다.** 현재 PC의 별도 호환 파일로 실행한 결과를 새 PC 설치 성공으로 간주하지 않습니다. 런타임/모델 확인과 남은 조치는 [음성 의존성 안내](ros2_ws/src/ready2go_voice/README.md#실행-준비와-의존성)를 따릅니다. espeak를 선택하면 별도로 `sudo apt-get install -y espeak-ng`를 실행하고 한국어 음성을 확인합니다.

rosdep은 최초 1회 `sudo rosdep init`(이미 초기화된 PC에서는 생략), 이어서 아래 명령을 실행합니다. DSR 패키지는 벤더 overlay를 먼저 준비/source해야 하며, rosdep이 알 수 없는 `dsr_*` 의존성을 무시한 채 실물 준비 완료로 처리하지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
rosdep update
rosdep install --from-paths ros2_ws/src --ignore-src -r -y --rosdistro jazzy
```

Vision/YOLO는 공통 호스트 환경과 별도로 준비합니다. 아래 조합은 [Vision Dockerfile](docker/vision/Dockerfile)의 선언값이며, 기존 PC1 컨테이너 실측과 새 PC/GPU·새 이미지 설치 검증은 구분합니다. NVIDIA 드라이버/GPU 호환 확인은 A 담당입니다.

```bash
python3 -m venv --system-site-packages .venvs/vision
.venvs/vision/bin/python -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 \
  torch==2.11.0 torchvision==0.26.0 ultralytics==8.4.170 \
  numpy==1.26.4 opencv-python==4.9.0.80 PyYAML
```

이 환경에서 비전/tools를 실행하는 절차는 [A 안내](ros2_ws/src/ready2go_vision/README.md)·[YOLO 도구](tools/yolo/README.md)를 따릅니다. ROS 노드 실행 파일이 사용하는 Python도 해당 환경과 일치해야 하며, 기존 host install을 source하는 것만으로 GPU 환경 전환이 되지는 않습니다. Melo는 기존 [설치기·고정 목록·단독 합성 안내](ros2_ws/src/ready2go_voice/README.md#melotts-설치재생-p1-e-사용자-선택)에 따라 `.venvs/melotts`에만 설치합니다. 두 Torch 버전을 한 환경에 설치하지 않습니다. Compose는 이 호스트 requirements를 자동 적용하지 않으며, 현재 voice/vision 서비스는 노드 자동 기동과 완전한 모델/runtime 준비를 보장하지 않습니다.

호스트 노드를 쓸 경우 필요한 ROS·Python·장치 의존성을 먼저 준비하고 **프로젝트 안에 빌드**합니다. DSR 드라이버를 호스트에서 실행할 경우 벤더 워크스페이스도 준비합니다.

```bash
cd /home/jonny/rokey_proj/VLA/ready2go
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
cd ros2_ws
python3 /usr/bin/colcon build --symlink-install
cd ..
source ros2_ws/install/setup.bash
```

**호스트 노드를 실행하는 새 터미널마다** 아래 환경을 적용합니다. MeloTTS 상대 경로 때문에 음성 노드도 저장소 루트에서 시작합니다.

```bash
cd /home/jonny/rokey_proj/VLA/ready2go
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=70
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$PWD/config/cyclonedds.local.xml"
export ROS_LOG_DIR="logs/ros"
mkdir -p "$ROS_LOG_DIR"
```

호스트 노드의 스키마·온톨로지 진입점·설정·모델·로그 및 기록 조회 경로는 저장소 루트 기준 상대 경로입니다. 온톨로지 내부 `sources`는 로더가 진입점 파일의 폴더 기준으로 해석합니다. `CYCLONEDDS_URI`는 `file://` URI에 올바른 절대 파일 위치가 필요하므로 실행 시 `$PWD`로 생성합니다. `/opt/ros/jazzy`·`/opt/dsr_ws`는 시스템/벤더 설치 위치, `/colcon` 및 컨테이너 명령의 `/config`·`/knowledge`·`/tasks`·`/models`·`/logs`는 컨테이너 설치/마운트 위치이며 호스트 프로젝트 상대 경로와 구분합니다. 기본 `~/.ros/log`는 ROS 사용자 로그 위치입니다.

`local`은 같은 PC 내 통신입니다. PC를 나누면 `.env`의 `DDS_MODE=multi`와 NIC·양쪽 IP를 맞춥니다. 호스트에도 같은 `DDS_IFACE`·`PEER_PC1`·`PEER_PC2`를 export하고 `CYCLONEDDS_URI`를 `cyclonedds.multi.xml`로 바꿉니다. 음성과 Runner의 Domain ID도 같아야 합니다.

### 2. 전체 실행 순서

실물은 **DB·TF·DSR·그리퍼 상태·Runner → 스킬 서버 → 카메라·비전 → 음성** 순입니다. 음성의 실행 모드로 전환하기 전에 각 서버의 준비와 대상·배치를 확인합니다.

| 실행 방법 | 자동 시작하는 노드 | 추가로 실행할 노드 |
| :--- | :--- | :--- |
| `BACKEND=real`의 `ros2-core` | 고정 TF, DSR, `gripper_state`, `runner` | `skill_server`, 비전, 음성 |
| `BACKEND=mock`의 `ros2-core` | 고정 TF, `runner`, `mock_backend` | 모의 플로우만 시험하면 불필요 |
| `realsense` 서비스 | RealSense 카메라 | `inspect_region`은 별도로 필요 |
| `vision`·`voice` 서비스 | 현재는 대기 컨테이너 | 각 패키지의 노드는 자동 시작하지 않음 |

현재 Compose에서는 실물 스킬을 `ros2-core` 안에서 추가 실행하고, 비전·음성은 준비된 호스트에서 실행하는 절차를 아래에 적었습니다. 같은 Runner·스킬·비전·TTS 서버를 중복 실행하지 않습니다.

**실물(PC2)**: `.env`의 실제 장비 IP·DDS 설정 확인 후 실행합니다. `RUNNER_TASK_FILE`은 비워 음성 입력을 기다립니다.

```bash
BACKEND=real RUNNER_TASK_FILE= docker compose --profile real up -d --build db ros2-core realsense
docker compose logs -f ros2-core realsense
```

빌드 완료·DSR 연결·Runner 준비를 확인한 뒤 별도 터미널에서 스킬 서버를 실행합니다. 아래 10°/s는 B의 첫 저속 실행 예이며, 실물 운용 한계는 안전 절차를 따릅니다.

```bash
mkdir -p logs/skills
SKILL_CONSOLE_LOG=$(mktemp "logs/skills/console.XXXXXX.log")
set -o pipefail
docker compose exec -T ros2-core bash -lc '
  source /opt/ros/jazzy/setup.bash
  source /opt/dsr_ws/install/setup.bash
  source /colcon/install/setup.bash
  export ROS_LOG_DIR=/logs/ros
  ros2 run ready2go_skills skill_server --ros-args -p config_dir:=/config -p joint_vel_deg_s:=10.0
' 2>&1 | tee "$SKILL_CONSOLE_LOG"
```

이어서 아래 노드별 실비전과 음성 명령을 별도 터미널에서 실행합니다. 카메라는 Compose에서 시작됐으므로 호스트에서 중복 실행하지 않습니다.

**로봇 없는 모의 플로우**: 모의 서버로 `find_item.json`을 한 번 실행합니다. 웨이크워드·STT·실물 동작 검사는 아닙니다.

```bash
BACKEND=mock RUNNER_TASK_FILE=/tasks/find_item.json docker compose --profile dev up --build db ros2-core
```

`mock_backend`는 `/voice/speak`도 제공하므로 같은 Domain에서 실음성 노드를 함께 실행하지 않습니다. 실음성 단독 평가는 뒤의 평가 모드로 별도 실행합니다. 일반 입력 대기로 돌아갈 때는 `RUNNER_TASK_FILE`을 비웁니다.

프로파일 전체 서비스의 실행 명령은 아래와 같습니다. 프로파일만으로 `BACKEND`가 바뀌거나 `vision`·`voice`의 노드가 시작되지는 않습니다.

```bash
docker compose --profile real up   # .env: BACKEND=real. 카메라·GPU 등의 준비 필요
docker compose --profile sim up    # Isaac Sim 실행·연결은 별도. P2 이후 검증 경로
docker compose --profile dev up    # .env: BACKEND=mock
```

Isaac Sim은 네이티브 실행이며 [트윈 안내](docs/twin.md)를 참조합니다. 컨테이너의 팀 빌드 경로는 `/colcon/build`·`/colcon/install`, 호스트는 `ros2_ws/build`·`ros2_ws/install`로 구분합니다.

### 3. 노드별 실행 명령

아래는 위 실행 전 준비 환경을 적용한 **호스트 개별 실행**입니다. Compose에서 이미 시작한 노드를 동시에 실행하는 목록이 아닙니다. 각 명령은 별도 터미널에서 실행합니다.

**Runner**: 저장소 루트 기준 상대 경로를 지정하고 음성 입력을 기다립니다. `BACKEND` 표시만 바꿔 실제 연결 서버가 바뀌지는 않습니다.

```bash
ros2 run ready2go_runner runner --ros-args \
  -p schema_file:="contracts/task.schema.json" \
  -p intent_schema_file:="contracts/intent.schema.json" \
  -p ontology_file:="knowledge/robot_ontology.jsonld" \
  -p tasks_dir:="tasks" -p log_dir:="logs/runner"
```

`-p task_file:="tasks/find_item.json"`를 추가하면 시작 직후 해당 태스크를 한 번 실행합니다. 일반 음성 경로에서는 지정하지 않습니다. 현재 `/voice/intent`의 `find_item`을 `tasks/find_item.json`에 연결하는 구현이 있습니다. 발행 로그만으로 Runner 수신·로봇 완료를 증명하지 않습니다.

**모의 백엔드**: 실물 스킬·비전·음성을 대신해 응답합니다.

```bash
ros2 run ready2go_runner mock_backend
```

**DSR 드라이버**: 호스트의 벤더 오버레이를 source하고 `ROBOT_HOST`에 실제 장비 IP를 export한 후 실행합니다. 고정 TF는 Compose 통합 launch가 `config/`에서 읽어 발행합니다.

```bash
ros2 launch ready2go_skills dsr_real.launch.py host:="$ROBOT_HOST"
```

**그리퍼 상태·실물 스킬**: 호스트에서는 `RG2_HOST`를 export합니다(Compose용 `.env`만으로 호스트 환경 변수가 설정되지는 않음). DSR·TCP·툴·실측 설정이 준비된 후 실행합니다.

```bash
ros2 run ready2go_skills gripper_state --ros-args -p rg2_ip:="$RG2_HOST"
```

```bash
ros2 run ready2go_skills skill_server --ros-args \
  -p config_dir:="config" -p joint_vel_deg_s:=10.0
```

**RealSense 카메라**: Compose의 `realsense` 대신 호스트에서 실행할 때의 동일 설정입니다. `realsense2_camera` 설치가 필요합니다.

```bash
ros2 run realsense2_camera realsense2_camera_node --ros-args \
  -r __ns:=/ -r __node:=wrist_cam -p camera_name:=wrist_cam \
  -p enable_color:=true -p enable_depth:=true -p align_depth.enable:=true \
  -p enable_infra1:=false -p enable_infra2:=false \
  -p enable_accel:=false -p enable_gyro:=false \
  -p rgb_camera.color_profile:=1280x720x30 -p depth_module.depth_profile:=848x480x30
```

**실비전**: 모델 가중치 파일 이름은 A가 제공하는 모델에 맞춥니다. 영상·깊이·카메라 내부 파라미터·TF가 필요합니다. `device:=0`이 기본이며 CPU 검사는 `-p device:=cpu`를 추가합니다.

```bash
ros2 run ready2go_vision inspect_region --ros-args \
  -p config_dir:="config" -p world_path:="knowledge/world.jsonld" \
  -p weights:="models/yolo11n_ready2go_v1.pt" \
  -p dump_dir:="logs/vision" -p code_sha:="$(git rev-parse HEAD)"
```

**비전 stub**: 실비전과 동시에 실행하지 않고 시험용 실측 파일을 지정합니다. 아래 기본 파일은 `ready: false`라 그대로 쓰면 `STUB_NOT_READY`입니다. 고정 좌표의 성공을 실제 인식 검증으로 취급하지 않습니다.

```bash
ros2 run ready2go_vision inspect_region_stub --ros-args \
  -p config_path:="config/vision_stub.yaml" -p places_path:="config/places.yaml"
```

`ready2go_knowledge`는 Runner·음성이 사용하는 함수 모음, `ready2go_interfaces`는 메시지·서비스·액션 정의이므로 단독 실행 노드는 없습니다. [Knowledge README](ros2_ws/src/ready2go_knowledge/README.md)를 참조합니다.

### 4. 음성 평가·실행 전환

`logs/voice_eval/voice.local.yaml`에 마이크·`audio_enabled: true`·저장소 루트 기준 웨이크 모델 경로·MeloTTS 설정을 준비합니다. 모델 파일명은 실제 배치한 것으로 지정합니다. `secrets/voice.env`는 Python dotenv로 읽고 키는 명령이나 로그에 출력하지 않습니다.

**음성만 평가하는 명령**입니다. 시작 파라미터 `evaluation_mode:=true`로 모든 intent의 발행을 차단하고, 상세 결과를 매번 새 파일에 저장합니다.

```bash
mkdir -p logs/voice_eval
VOICE_CONSOLE_LOG=$(mktemp logs/voice_eval/console.XXXXXX.log)
set -o pipefail
python3 -u - <<'PYTHON' 2>&1 | tee "$VOICE_CONSOLE_LOG"
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main

load_dotenv('secrets/voice.env')
main(args=['--ros-args',
           '-p', 'config_file:=logs/voice_eval/voice.local.yaml',
           '-p', 'evaluation_mode:=true',
           '-p', 'diagnostic_detail:=true'])
PYTHON
```

**로봇 연동**은 준비·접속 확인 후 같은 명령의 `'evaluation_mode:=true'`를 `'evaluation_mode:=false'`로 바꿔 실행합니다. 시작 인자의 기본은 false이며 YAML보다 우선합니다. 실행 중 `ros2 param set`으로 전환하는 기능은 없습니다. 다른 노드에서 시작한 태스크를 평가 모드가 중단시키는 것도 아닙니다.

기존 `recording_mode`·`timing_mode`·웨이크 기준 등은 이 전환으로 변경하지 않습니다. 고정 5초 녹음·commissioning 설정은 발화 종료부터 3초 응답(AC-INT-03)의 측정 근거가 아닙니다. 판별 제약·미해결 사항과 기록의 의미는 [음성 README](ros2_ws/src/ready2go_voice/README.md)에 적혀 있습니다.

### 5. 연결·결과·로그 확인

같은 DDS 환경에서 확인합니다. 토픽 존재만으로 연결 성공이라 하지 않고 내용·Runner 시작과 종료·동일한 `run_id`의 스텝 기록을 대조합니다.

```bash
ros2 node list
ros2 action list
ros2 service list
ros2 topic echo /voice/intent
```

```bash
ros2 topic echo /runner/status
```

```bash
ros2 topic echo /robot_state
```

| 기록 | 위치·확인 방법 |
| :--- | :--- |
| 호스트 ROS 로그 | 위 공통 환경은 `logs/ros/`. 미설정 시 보통 `~/.ros/log/`(`ROS_HOME` 설정 시 해당 경로 아래 `log/`) |
| 실물 스킬 추가 실행 | 위 명령은 ROS 로그를 호스트 `logs/ros/`, 콘솔을 `logs/skills/console.*.log`에 저장 |
| Compose 자동 시작 노드 | 표준 출력은 `docker compose logs`. 기본 ROS 로그는 컨테이너 안 `~/.ros/log/`이며 호스트 자동 저장 설정은 없음 |
| Runner 실행·스텝 | MongoDB `cobot2.runs`·`cobot2.steps`. DB 장애 시 `log_dir` 아래 `<run_id>.jsonl`로 폴백 |
| JSONL 호스트 위치 | Compose의 `/logs`는 호스트 `logs/`. 위 호스트 Runner는 `logs/runner/`. DB가 정상이면 JSONL이 없는 것은 정상 |
| 음성 상세 평가 | 위 명령의 `logs/voice_eval/console.*.log`. 평가 결과 JSON이나 녹음 파일이 자동 생성된다는 의미는 아님 |
| 비전 입력·결과 | `dump_dir`를 지정하면 `logs/vision/`의 `.npz`. ROS 로그와 별개 |

컨테이너 ROS 로그 위치 확인과 Compose 콘솔 저장 예입니다. `docker compose exec`로 추가 실행한 노드 출력은 해당 실행 터미널의 `tee`로 저장합니다.

```bash
docker compose exec ros2-core bash -lc 'ls -lt ~/.ros/log'
mkdir -p logs
CORE_CONSOLE_LOG=$(mktemp "logs/ros2-core.console.XXXXXX.log")
docker compose logs --no-color ros2-core > "$CORE_CONSOLE_LOG" 2>&1
```

Runner 기록의 요약(호스트 MongoDB 조회는 `pymongo` 의존성 필요):

```bash
ros2 run ready2go_runner run_report -n 2
```

```bash
ros2 run ready2go_runner run_report --jsonl "logs/runner" -n 2
```

### 6. 종료·다음 회차 준비

실물은 B 안전 절차로 정지를 확인한 뒤 개별 노드 터미널을 `Ctrl+C`로 종료합니다. `Ctrl+C`나 컨테이너 종료만으로 안전 정지를 확인한 것으로 취급하지 않습니다. Compose 종료는 사용한 프로파일로 실행합니다(아래는 real 예).

```bash
docker compose --profile real stop
```

컨테이너 제거는 `docker compose --profile real down`을 사용합니다. 컨테이너 안에만 있는 ROS 로그는 먼저 회수합니다. MongoDB 데이터는 호스트 `db_data/`에 남습니다.

회차 사이에는 사람이 물품·서랍·그리퍼 원상 복구를 확인하고 Runner가 대기 상태일 때 상태 초기화를 요청할 수 있습니다. 정지나 실물 상태 확인·안전 잠금 해제를 대신하는 기능은 아닙니다.

```bash
ros2 service call /runner/reset_state std_srvs/srv/Trigger '{}'
```

## 저장소 구조
| 경로 | 내용 |
| :--- | :--- |
| `docs/` | 요구사항 기준 원본과 주제별 기술 문서. `archive/`는 과거 스냅샷 |
| `contracts/` | JSON Schema 계약 + `examples/` |
| `knowledge/` | 로봇 온톨로지(`robot_ontology.jsonld`), 상태 스냅샷 |
| `tasks/` | 태스크(복합 스킬) JSON |
| `config/` | 장비·실측값: DDS, 기준 포즈, 서랍 좌표계, 캘리브레이션 |
| `ros2_ws/src/` | ROS 2 패키지 `ready2go_*` |
| `docker/` | 서비스별 Dockerfile |
| `sim/` | Isaac Sim 스크립트 (USD는 Git LFS) |
| `tools/` | 검증·측정 스크립트 |
| `practice/` | 담당별 현재 상태(`CURRENT.md`) |

## 팀
| 코드 | 이름 | 담당 |
| :--- | :--- | :--- |
| A | 김병직 | 비전 · Isaac Sim 트윈 |
| B | 서동권 | 실물 로봇 모션 |
| C | 이영훈 | Runner · 플래너 · 로그 · 기술 통합 |
| D | 김민준 | 기록 · 문서 · 평가 자료 |
| E | 고희태 (조장) | 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 |
