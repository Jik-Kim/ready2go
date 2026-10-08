# ready2go_vision

- **담당**: A 김병직
- **역할**: inspect_region: 검출 · 뎁스 3D 위치 · 가림 순서 · 인스턴스 ID 추적

## 작업 전에 읽을 문서
- `docs/vision.md`
- `docs/interfaces.md`
- `docs/runner.md (7.1 inspect_region)`

## 데이터 수집·학습 도구
실물 데이터 촬영·라벨 세션 분할·YOLO 학습·평가: [`tools/yolo/README.md`](../../../tools/yolo/README.md)

## 구조

| 폴더 | 내용 |
| :--- | :--- |
| `ready2go_vision/core/` | ROS에 의존하지 않는 로직. **단위 테스트 대상** (`pytest`로 ROS 없이 실행) |
| `ready2go_vision/nodes/` | rclpy 노드 (ROS 토픽·서비스·액션 연결만) |
| `ready2go_vision/adapters/` | 장치·외부 서비스 연결 (DSR, RG2, RealSense, OpenAI, MongoDB 등) |
| `test/` | `core/` 테스트 |

## 규칙
- 다른 담당의 패키지는 수정하지 않음. 필요하면 GitHub Issue로 요청.
- 계약(`ready2go_interfaces`, `contracts/`)을 바꾸면 스키마·예시·문서를 같은 PR에서 함께 수정.

## inspect_region 실제 노드 (실물)
실물에서 검증한 실행 경로는 `ready2go-vision` 컨테이너 + [`tools/dev/vision_real_check.sh`](../../../tools/dev/vision_real_check.sh) (`check` → `node` → `call`) [실측 PC2 10/07, main `55829e3`]. 새 PC 준비(이미지·모델 LFS·`BACKEND=real`·카메라 하나)와 확인 기준은 [저장소 README "실비전"](../../../README.md#3-노드별-실행-명령), 상세 사용법·`replay`는 [`tools/yolo/README.md`](../../../tools/yolo/README.md) "inspect_region 실제 노드 실행". 아래 stub 과 동시에 실행하지 않는다.

## inspect_region stub (#18, Day 4 — B의 #15 실물 테스트용)
카메라·YOLO 없이 `config/vision_stub.yaml`의 손으로 잰 좌표를 `result_json` 형식 그대로 응답한다. 실제 구현(Day 5)도 같은 형식을 쓴다.

호스트에서는 [저장소 README "실행 전 준비"](../../../README.md#1-실행-전-준비)의 공통 호스트 환경(`.venvs/project`)을 쓴다(stub은 YOLO·Torch가 필요 없음). 모든 명령은 **저장소 루트**에서 시작하고, 새 터미널마다 같은 절의 ROS 환경(`ROS_DOMAIN_ID`·`RMW_IMPLEMENTATION`·`CYCLONEDDS_URI`)을 적용한다. 두 파라미터의 기본값 `/config/...`는 컨테이너 마운트 경로라 호스트에서는 둘 다 넘긴다 — `places_path`가 없으면 노드가 시작 중 파일을 못 찾아 종료된다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
(cd ros2_ws && python3 /usr/bin/colcon build --symlink-install --packages-select ready2go_interfaces ready2go_vision)
source ros2_ws/install/setup.bash
ros2 run ready2go_vision inspect_region_stub --ros-args \
  -p config_path:="$PWD/config/vision_stub.yaml" -p places_path:="$PWD/config/places.yaml"
# 다른 터미널 (같은 환경)
ros2 service call /vision/inspect_region ready2go_interfaces/srv/InspectRegion "{region: drawer_top, search_target: eraser}"
```

실제 노드를 호스트에서 돌리는 절차(전용 `.venvs/vision`·별도 빌드)는 [저장소 README "호스트 실비전"](../../../README.md#host-vision)에 있다. stub과 실제 노드는 서비스 이름이 같으므로 동시에 실행하지 않는다.

- 결과 예시: [`contracts/examples/inspect_region_result.json`](../../../contracts/examples/inspect_region_result.json)
- `pose` = `{frame: <region>, position: [x, y, z] m, yaw: rad, yaw_valid: bool}` — 서랍 좌표계 기준. **확정**(사용자·B 합의 10/04): `position` = YOLO 박스 중심의 서랍 좌표 x·y, `position.z` = 0(높이는 `top_z`), `yaw` = 긴 변 방향 (−π/2, π/2]·위에서 본 모양이 정사각형이거나 둥근 대칭 물체(판정: `pose_rules.is_symmetric`, `docs/vision.md` V2)는 0. `yaw_valid` = yaw를 믿어도 되는지(덩어리 비정상이면 false + yaw 0 자리표시, runner.md 7.1). 정의는 `docs/runner.md` 7.1과 `config/places.yaml` 첫 부분, 규칙 코드는 `ready2go_vision/core/pose_rules.py`. yaw 산출은 서랍 바닥 위 뎁스 덩어리 윤곽의 긴 변 방향(`minAreaRect`)으로 **확정**(사용자 10/04, 상세 `docs/vision.md` V2, 비교 실험 #62·#63). 투영 높이 평면은 `top_z/2`로 확정. 스텁은 `yaw_valid: true`를 내고(설정에서 `yaw_valid: false`를 지정해 시험 가능), 정답 yaw 기록법(#62)만 남음.
- 좌표값은 자리표시자 **[추정]**이라 설정의 `ready: false`로 배포한다. 이 상태에서는 `success=false` + `error_code=STUB_NOT_READY`로 실패해 추정 좌표가 로봇 동작에 쓰이지 않는다. B와 함께 실물을 재서 값을 덮어쓴 **뒤에** `ready: true`로 바꾼다.
- 미발견은 `success=true` + `target_found=false`, 실패는 `success=false` + `error_code`. 코드 목록은 [`docs/runner.md`](../../../docs/runner.md)의 "`inspect_region` 에러 코드" 표가 원본.
- 콘솔 로그(#98): 요청마다 `[stub] 요청 region=… target=…` 한 줄, 응답 한 줄(`응답 성공 target_found=true <ID> (x, y, z) m frame=… yaw … top_z …` / `target_found=false (… 없음)` / 실패는 WARN `응답 실패 error=<코드>`). 응답 내용은 바꾸지 않는다. 형식 함수: `core/stub_inspect.py`의 `format_request`·`format_response`
- 테스트: `python3 -m pytest --rootdir=. --confcutdir=. ros2_ws/src/ready2go_vision` (저장소 루트에서)
