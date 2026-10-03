# ready2go_vision

- **담당**: A 김병직
- **역할**: inspect_region: 검출 · 뎁스 3D 위치 · 가림 순서 · 인스턴스 ID 추적

## 작업 전에 읽을 문서
- `docs/vision.md`
- `docs/interfaces.md`
- `docs/runner.md (7.1 inspect_region)`

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

## inspect_region stub (#18, Day 4 — B의 #15 실물 테스트용)
카메라·YOLO 없이 `config/vision_stub.yaml`의 손으로 잰 좌표를 `result_json` 형식 그대로 응답한다. 실제 구현(Day 5)도 같은 형식을 쓴다.

```bash
colcon build --packages-select ready2go_interfaces ready2go_vision && source install/setup.bash
ros2 run ready2go_vision inspect_region_stub --ros-args -p config_path:=<저장소>/config/vision_stub.yaml
ros2 service call /vision/inspect_region ready2go_interfaces/srv/InspectRegion "{region: drawer_top, search_target: watch}"
```

- 결과 예시: [`contracts/examples/inspect_region_result.json`](../../../contracts/examples/inspect_region_result.json)
- `pose` = `{frame: <region>, position: [x, y, z] m, yaw: rad}` — 서랍 좌표계 기준. 형식은 **[팀 확정 필요]**(B의 `pick_object`가 쓰는 형식과 맞출 것).
- 좌표값은 자리표시자 **[추정]**이라 설정의 `ready: false`로 배포한다. 이 상태에서는 `success=false` + `error_code=STUB_NOT_READY`로 실패해 추정 좌표가 로봇 동작에 쓰이지 않는다. B와 함께 실물을 재서 값을 덮어쓴 **뒤에** `ready: true`로 바꾼다.
- 미발견은 `success=true` + `target_found=false`, 실패는 `success=false` + `error_code`. 코드 목록은 [`docs/runner.md`](../../../docs/runner.md)의 "`inspect_region` 에러 코드" 표가 원본.
- 테스트: `python3 -m pytest --rootdir=. --confcutdir=. ros2_ws/src/ready2go_vision` (저장소 루트에서)
