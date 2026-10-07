# 인터페이스 계약 (ICD)

> 관련 요구사항: [FR-COM-01–02](requirements.md#fr-com-01), [FR-INT-01–03](requirements.md#fr-int-01), [FR-VIS-02](requirements.md#fr-vis-02), [FR-LOG-01](requirements.md#fr-log-01). 인터페이스 이름·형식·호출 관계는 이 문서에서 다룹니다.

## 5. 인터페이스 계약 (ICD)

Day 1에 확정하고, 이후 변경은 전원 합의 후 이 표를 먼저 수정함. 커스텀 메시지는 `ready2go_interfaces` 패키지의 **2종(`Skill.action`, `InspectRegion.srv`)으로 제한**하고, 나머지 페이로드는 JSON 문자열로 주고받음.

| 인터페이스 | 이름 | 타입 | 제공 → 사용 |
| :--- | :--- | :--- | :--- |
| 인텐트 | `/voice/intent` | topic `std_msgs/String` (JSON) | voice → ros2-core |
| 로봇 상태 | `/robot_state` | topic `std_msgs/String` (온톨로지 `state` JSON) | ros2-core → 시연 화면·트윈·voice(상태 질의) |
| 생성된 계획 | `/planner/plan` | topic `std_msgs/String` (7.2 형식 JSON) | ros2-core → 시연 화면 |
| 텍스트 디버그 입력 | `/voice/text_override` | topic `std_msgs/String` | 테스트 → voice |
| TTS 요청 (`speak` 원자 동작) | `/voice/speak` | action `Skill` | ros2-core → voice |
| 인식 | `/vision/inspect_region` | service `InspectRegion` (req: `region`, `search_target` / res: `success`, `error_code`, `result_json`; 에러 코드 표는 [runner.md](runner.md)) | ros2-core → vision |
| 로봇 원자 동작 | `/skills/<action_name>` | action `Skill` (goal: `params_json` / result: `success`, `error_code`, `output_json` / feedback: `stage`) | Runner → 백엔드 |
| 로봇 조인트 상태 | `/dsr01/joint_states` | `sensor_msgs/JointState` | DSR 드라이버(real·sim) → Isaac Sim 트윈 |
| 그리퍼 상태 | `/gripper/state` | JSON 문자열 (`width` m, `grasp_detected`) | 백엔드 → Runner·트윈 |
| 그리퍼 명령 (sim 전용) | `/gripper/command` | JSON 문자열 | sim 백엔드 → Isaac Sim |
| 서랍 상태 | `/drawers/state` | JSON 문자열 (`drawer_id`, `displacement`) | 백엔드 → Runner·트윈 |
| 카메라 | `/wrist_cam/color/image_raw`, `/wrist_cam/color/camera_info`, `/wrist_cam/aligned_depth_to_color/image_raw` (컬러에 정렬된 뎁스, 내부 파라미터는 컬러와 동일) | `sensor_msgs` | realsense / Isaac Sim → vision (결정 #24) |
| Runner 상태 · 비상정지 · 상태 초기화 | `/runner/status`, `/runner/estop`, `/runner/reset_state` | `std_msgs/String`, `std_srvs/Trigger`, `std_srvs/Trigger` | ros2-core ↔ 전체 (초기화는 사람·시연 화면 #59 → Runner) |
| TF 프레임 | `world`, `base_link`, `link_6`, `wrist_cam_link`, `wrist_cam_color_optical_frame`, `drawer_<id>`, `staging_tray`, `handover_zone` | TF2 | ros2-core: `ready2go_bringup` launch가 `config/calibration/`·`config/places.yaml`을 읽어 static TF 발행 (결정 #23). 로봇 TF는 DSR 드라이버. **`wrist_cam_link`**: 캘리브레이션 결과를 거는 프레임(`link_6 → wrist_cam_link`, bringup 발행). **`wrist_cam_color_optical_frame`**: 컬러·정렬 뎁스 이미지의 `frame_id`, `wrist_cam_link` 아래 트리는 realsense 드라이버가 `/tf_static`으로 발행(끄지 않음). Isaac Sim 트윈 카메라도 같은 `frame_id`를 사용. 강의 URDF(`m0609_rg2_bringup`)에 CAD 기반 `camera_*` 프레임이 따로 있어 TF에 카메라가 두 개 생길 수 있으나, **비전은 `wrist_cam_color_optical_frame`만 사용**(CAD 위치는 캘리브레이션과 x·y 약 1.8 cm 차이, 5점 검증에서 캘리브레이션이 맞음 [실측 B 10/03]). `base_link`·`link_6` 접두어 없음 [실측 B 10/02], `tool0`은 `link_6`과 원점이 같고 축만 회전하므로 사용하지 않음 |

**ROS 인터페이스가 아닌 호출 (같은 프로세스 또는 외부 서비스)**

| 대상 | 호출 방식 | 사용 위치 |
| :--- | :--- | :--- |
| `query_ontology` · `update_ontology` 원자 동작 | **ROS 인터페이스 없음.** `ros2-core` 프로세스 안에서 Runner가 `OntologyManager` 메서드를 직접 호출 | Runner (7.1 ②) |
| 로그·상태 저장 | Python `pymongo`로 MongoDB(`cobot2` DB: `runs`·`steps`·`states`) 직접 연결, `LogStore` 인터페이스 경유. 연결 실패 시 `logs/*.jsonl` 폴백 | Runner·Logger (7.4) |
| STT · LLM | HTTPS로 OpenAI API 호출 (`secrets/voice.env`의 키 사용) | `voice` 컨테이너 (6장) |

### 5.1 물품 식별자·좌표·조회 결과의 공유 규칙

| 항목 | 의미·제공자·사용자 |
| :--- | :--- |
| 물품 키 | `world.items` 키(예: `eraser`). voice의 `targets`, vision의 `search_target`·검출 `class`에서 사용. 온톨로지 종류 `Item/Key/Obstacle`와 구분 |
| 인스턴스 ID | A가 관측한 물체에 부여한 `eraser#1` 등. B의 `pick_object` 입력으로 사용(서랍: `target`을 통째로, 트레이: `object_id`). 클래스 키를 인스턴스 ID로 임의 변환하지 않음 |
| `pose` | `{frame, position, yaw}` 형식 유지. 위치·yaw·`top_z` 의미는 병합된 PR #61의 [runner.md 7.1](runner.md#71-원자-동작primitive-action-정의-규격)을 참조함. 서랍 좌표계 정의는 [`config/places.yaml` 첫 부분](../config/places.yaml)이 정본. 규칙 함수·예시 검사는 제공되지만 실제 비전 추론·B 실행 경로 연결 완료를 뜻하지 않음 |
| `size_m` | 물체 로컬 x 긴 변·y 짧은 변·z 높이 순서의 외접 박스(m). 치수 원본은 E의 `world.jsonld`. 스패너·망치 머리 폭을 파지 손잡이 폭으로 해석하지 않음 |
| `top_z` | 관측 시 지지면·배치를 포함한 물체 윗면의 프레임 z 높이(m). 바닥에 놓인 예시에서만 물품 높이와 같을 수 있음. 항상 `size_m[2]`로 대체하지 않음 |
| 물품 조회 | E 공통 로더의 `world.items.<key>`: 기존 이름·종류·별칭·치수와 `roles`, `grip_force`(양수 또는 null), `grasp_verified`(bool). 물품 등록과 파지 승인은 별개 |
| 초기 위치 | `initial_state.json`은 배치 예시. 실제 위치라고 발행하려면 확인·초기화가 필요하며, 현재 상태와 개별 인스턴스 위치는 C가 관리 |
| 인식 결과 | `target_found/target/candidates/visible_count` 형식 유지. 미발견은 `success=true, target_found=false`; 통신·관측 실패와 구분. 예시 좌표는 실측 증빙이 아님 |

**실행 전 인계**: B·C는 `require_grasp_settings()` 또는 동등한 검증으로 미확정 파지 힘·검증 상태를 확인하고 실행 불가를 반환해야 함. null을 임의 기본 힘으로 대체하지 않음. 기존 `query_ontology` 결과에도 이 상태를 전달하는 연결은 C 담당이며, 에러 코드·질문/TTS 응답 계약은 해당 담당과 확정 필요.

**학습 인계**: A의 데이터셋 도구는 병합된 PR #45에서 `sources.world`를 따라 `world.jsonld`의 물품 목록을 조회함. 전체 E 로더를 호출하지 않아 학습 도구에 PyYAML 의존성을 추가하지 않음. PR #45의 고정 클래스 목록은 `config/yolo_classes.txt`(0부터 시작하는 줄 순서)이며 이번 PR에서 `--init-classes`로 11종의 최초 번호(0–10)를 생성함. 이후 재정렬하지 않음. 번호 고정 후 새 클래스는 끝에 추가하고 데이터셋·가중치와 목록 버전을 연결함. 기존 라벨의 유무·번호는 A가 확인함.
