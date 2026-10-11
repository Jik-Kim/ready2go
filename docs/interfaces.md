# 인터페이스 계약 (ICD)

> 관련 요구사항: [FR-COM-01–02](requirements.md#fr-com-01), [FR-INT-01–03](requirements.md#fr-int-01), [FR-VIS-02](requirements.md#fr-vis-02), [FR-LOG-01](requirements.md#fr-log-01). 인터페이스 이름·형식·호출 관계는 이 문서에서 다룹니다.

## 5. 인터페이스 계약 (ICD)

Day 1에 확정하고, 이후 변경은 전원 합의 후 이 표를 먼저 수정함. 커스텀 메시지는 `ready2go_interfaces` 패키지의 **2종(`Skill.action`, `InspectRegion.srv`)으로 제한**하고, 나머지 페이로드는 JSON 문자열로 주고받음.

| 인터페이스 | 이름 | 타입 | 제공 → 사용 |
| :--- | :--- | :--- | :--- |
| 인텐트 | `/voice/intent` | topic `std_msgs/String` (JSON) | voice → ros2-core |
| 로봇 상태 | `/robot_state` | topic `std_msgs/String` (온톨로지 `state` JSON) | **P1 구현:** Runner가 응답 기준 현재 상태를 발행하며 Runner 통합 테스트가 구독. 시연 화면·트윈·voice의 직접 구독은 후속 연결이고, 관측으로 검증된 상태라는 뜻이 아님 |
| 생성된 계획 | `/planner/plan` | topic `std_msgs/String` (7.2 형식 JSON) | **토픽 발행·시연 화면 소비 미구현.** P2 플래너 핵심과 `achieve_goal` → Runner 실행 연결은 구현됐으며, 계획은 현재 실행 기록 헤더 `plan`과 콘솔에 남음 |
| 텍스트 디버그 입력 | `/voice/text_override` | topic `std_msgs/String` | 테스트 → voice |
| TTS 요청 (`speak` 원자 동작) | `/voice/speak` | action `Skill` | ros2-core → voice |
| 인식 | `/vision/inspect_region` | service `InspectRegion` (req: `region`, `search_target` / res: `success`, `error_code`, `result_json`; 에러 코드 표는 [runner.md](runner.md)) | ros2-core → vision |
| 로봇 원자 동작 | `/skills/<action_name>` | action `Skill` (goal: `params_json` / result: `success`, `error_code`, `output_json` / feedback: `stage`) | Runner → 백엔드 |
| 로봇 조인트 상태 | `/dsr01/joint_states` | `sensor_msgs/JointState` | DSR 드라이버(real·sim) → Isaac Sim 트윈. **P2 선행 구현:** 에뮬레이터 미러링 확인, 실물 미러링 미확인([twin.md](twin.md)) |
| 그리퍼 상태 | `/gripper/state` | JSON 문자열 (`width` m, `grasp_detected`) | **P1 발행 구현:** `ready2go_skills` RG2 상태 노드 → ROS 토픽. Runner·트윈의 토픽 구독 연결은 미구현이며, P1 실물 스킬은 RG2 상태를 백엔드 안에서 직접 읽음 |
| 그리퍼 명령 (sim 전용) | `/gripper/command` | JSON 문자열 | **P2 트윈 계획, 미구현:** sim 백엔드 → Isaac Sim |
| 서랍 상태 | `/drawers/state` | JSON 문자열 (`drawer_id`, `displacement`) | **P2 트윈·관측 계획, 미구현:** 백엔드 → Runner·트윈. P1은 `drawer_control` 액션 응답의 `drawer_displacement`를 사용 |
| 카메라 | `/wrist_cam/color/image_raw`, `/wrist_cam/color/camera_info`, `/wrist_cam/aligned_depth_to_color/image_raw` (컬러에 정렬된 뎁스, 내부 파라미터는 컬러와 동일) | `sensor_msgs` | realsense / Isaac Sim → vision (결정 #24) |
| Runner 상태 · 비상정지 · 상태 초기화 | `/runner/status`, `/runner/estop`, `/runner/reset_state` | `std_msgs/String`, `std_srvs/Trigger`, `std_srvs/Trigger` | **P1 Runner 구현.** 테스트·사람의 ROS 호출 외에 Voice가 `/runner/status`를 읽어 실행 결과 안내에 사용함(PR #144). 시연 화면 #59 연결은 후속이며, Voice는 정지·초기화 서비스를 호출하지 않음 |
| TF 프레임 | `world`, `base_link`, `link_6`, `wrist_cam_link`, `wrist_cam_color_optical_frame`, `drawer_<id>`, `staging_tray`, `handover_zone` | TF2 | ros2-core: `ready2go_bringup` launch가 `config/calibration/`·`config/places.yaml`을 읽어 static TF 발행 (결정 #23). 로봇 TF는 DSR 드라이버. **`wrist_cam_link`**: 캘리브레이션 결과를 거는 프레임(`link_6 → wrist_cam_link`, bringup 발행). **`wrist_cam_color_optical_frame`**: 컬러·정렬 뎁스 이미지의 `frame_id`, `wrist_cam_link` 아래 트리는 realsense 드라이버가 `/tf_static`으로 발행(끄지 않음). Isaac Sim 트윈 카메라도 같은 `frame_id`를 사용. 강의 URDF(`m0609_rg2_bringup`)에 CAD 기반 `camera_*` 프레임이 따로 있어 TF에 카메라가 두 개 생길 수 있으나, **비전은 `wrist_cam_color_optical_frame`만 사용**(CAD 위치는 캘리브레이션과 x·y 약 1.8 cm 차이, 5점 검증에서 캘리브레이션이 맞음 [실측 B 10/03]). `base_link`·`link_6` 접두어 없음 [실측 B 10/02], `tool0`은 `link_6`과 원점이 같고 축만 회전하므로 사용하지 않음 |

**ROS 인터페이스가 아닌 호출 (같은 프로세스 또는 외부 서비스)**

| 대상 | 호출 방식 | 사용 위치 |
| :--- | :--- | :--- |
| `query_ontology` 원자 동작 | **P1 구현, ROS 인터페이스 없음.** 별도 `OntologyManager` 클래스가 아니라 Runner가 보유한 상태와 로드한 `world`를 프로세스 안에서 직접 조회. P1은 단일 `item`·`state` 경로만 지원 | Runner (7.1 ②) |
| `select_obstacle` · `find_moved` 원자 동작 (**P2, 계약 #176 머지 10/08 · E 사후 검토 대기**) | **ROS 인터페이스 없음.** Runner 가 직전 `inspect_region` 결과와 치운 기록(`restore_stack`)만으로 판단(`core/unpack.py`, 로봇 동작 없음). 입출력은 [runner.md 7.1](runner.md) | Runner (Unpacking 태스크) |
| `update_ontology` 원자 동작 | **P1 미지원(`NOT_SUPPORTED`).** P1 상태 변경은 성공 응답 뒤 스킬 `effect` 적용으로만 수행 | Runner 후속 범위 (7.1 ②) |
| 로그 저장 | **P1 구현:** Python `pymongo`로 MongoDB(`cobot2` DB: `runs`·`steps`)에 `LogStore` 경유 저장, 연결 실패 시 `logs/*.jsonl` 폴백. **P2 계획(FR-LOG-02):** `states` 컬렉션·사후 관측 상세 로그 | Runner (7.4). 별도 Logger 프로세스는 없음 |
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

<a id="p2-safety-proposal"></a>

### 5.2 P2 정지·복구·재개 계약안 — 제안·승인 대기

[문서: 현재] 기존 ICD 표·intent enum·스키마·예시는 유지합니다. [FR-SAF-01–03](requirements.md#fr-saf-01)·[AC-SAF-02–04](requirements.md#ac-saf-02)의 목표 승인은 새 wire 계약 승인이 아닙니다. 현재 core `resume()`은 잠금 해제만 합니다. 중단 단계 재개는 core `resume_run`(PR #170 병합 10/08, 기본 꺼짐 `resumable=False`) **준비만** 있고, `/runner/status`·인텐트·`/skills/recover`·그리퍼 관측 등 **노드·E 운영 연결은 미구현**입니다(C 계약안 [v0](https://github.com/Jik-Kim/ready2go/issues/152#issuecomment-6051650081)·[v1](https://github.com/Jik-Kim/ready2go/issues/152#issuecomment-6052621770) 승인 대기). reset_state 역시 안전 해제가 아닙니다.

| 흐름·담당 | 필요한 의미(확정 필드명이 아님) | 차단 조건·협의 사항 |
| :--- | :--- | :--- |
| B→C 정지·복구 | 정지 명령 수락·실제 정지 증빙·fresh state/관절/TCP 안정·원인·힘·센서/통신·컨트롤러/툴/E-stop 상태·복구 결과 | ESTOP 응답 단독·state fallback을 완전한 정지로 해석하지 않음. alarm/driver 자동 reset은 B 조사/실물 미검증. 임계값·자료 유효기간·전달 형식 승인 필요 |
| C→E 복구·질문 준비 | 현재 정지 사건·작업·중단 단계, 부팅 세대·순서·최신성, 실제 복구 성공·조건/재개점 확인 | 반복 상태 질문 1회, 재정지·다른/과거 사건·불명확 결과 차단. 결과/발화 연결·시계·취소·직렬화 방식 미확정 |
| E→C 명시적 재개 후보 | 현재 질문 완료 뒤 채취한 명시적 응답과 같은 사건/작업 식별·유효성 | TTS만으로 잠금 해제하지 않음. 무응답·거절·중복·지연·자기 음성 차단, 새 enum/토픽/서비스 이름 승인 필요 |
| C↔B 단계 재진입 | 위치/그리퍼/서랍/물체·변수·부분 실행/effect·검증된 재개 지점 | 조건 재검사 후 중단 단계부터 이어 실행 목표. 원자 동작/params/궤적 무조건 재전송·effect 중복 금지. 확인 불가 시 보류 |

[제안] `recovery_confirmation.py`의 내부 자료형·후보는 운영에 연결하지 않은 구현 준비이며 표의 의미를 확정 필드로 대신하지 않습니다. 힘·시간·유효기간 미확정 값은 후속 승인 시 config/params에 `[팀 확정 필요]`로 두며 임의 기본값을 하드코딩하지 않습니다. 새 계약은 전원 ICD 변경 합의·E 포함 2명 승인·스키마/예시/문서 같은 PR 대조가 필요합니다. 다른 담당 패키지를 수정하지 않았습니다.


<a id="request-run-contract"></a>
### 5.3 일반 요청 → 수락 → 완료 계약07 — 공동 원본 준비

[문서: E 초안] 승인 의미·책임·호환 및 중복 처리 기준은 [수락 TTS 정본](requirements.md#acceptance-tts-policy)을 참조합니다. 이 절은 E 발신 원본과 C 수신·상태 설명을 담당별로 기록합니다. C 소유 계약07 상태 예시·Runner 설명·ICD 구간은 이 head에 합류했고 C 원본 검토가 확인됐습니다. E 계약 검토/PR 병합과 실제 C 런타임 수신·생산자 연결은 별도 미완료이며, 문서 합류만으로 운영 통합을 뜻하지 않습니다.

#### E 담당 — 일반 요청 발신 원본

| 연결 | 실행 원본·예시 | 현행 구현과의 구분 |
| :--- | :--- | :--- |
| `/voice/intent` JSON 최상위 두 필드 | [intent.schema.json](../contracts/intent.schema.json)의 `properties.request_id`·`properties.accept_text` | `required`는 기존 `intent`·`confidence` 그대로이며 내부 LLM/P1 입력에 새 필드를 강제하지 않음 |
| E 실행 요청의 원본 예시 | [intent_find_item.json](../contracts/examples/intent_find_item.json), [intent_goal.json](../contracts/examples/intent_goal.json) | 공개 형식 예시이며 실제 Voice 발행·목표 실행의 증거가 아님. goal 예시의 기존 목표는 유지하며 선정 catalog 지원을 뜻하지 않음 |
| 기존 source | 같은 스키마의 `properties.source` | 로그용 자유 객체는 유지. E 발신 ID를 `source.request_id`에 중복 작성하지 않음 |
| 현재 Voice 발신/소비 | [VoiceNode](../ros2_ws/src/ready2go_voice/ready2go_voice/nodes/voice_node.py), [Session](../ros2_ws/src/ready2go_voice/ready2go_voice/core/session.py) | 이 head의 VoiceNode는 로컬 `_voice.request_id`와 내부 문장 소비를 사용합니다. 계약07의 두 최상위 필드는 스키마·예시에 정의됐지만 이 E 런타임의 공개 발신과 C 결정/결과 운영 연결은 후속 |

#### C 담당 — 수신·상태·결과

[문서: C 합류] 결정·결과 칸과 처리 규칙은 [runner.md 7.1 "요청 상관 — 계약07"](runner.md), 상태 예시는 [runner_status.json](../contracts/examples/runner_status.json)이 원본이다. 이 구간은 연결만 기록하며 Runner 수신 구현(중복 기억·`run_id` 고정·`accept_text` 1회 안내 게이트)은 계약 병합 뒤 운영 PR이다.

| 연결 | 실행 원본·예시 | 현행 구현과의 구분 |
| :--- | :--- | :--- |
| E 요청 → C 결정 | `/runner/status` `last_intent.request_id`·`run_id` — [runner_status.json](../contracts/examples/runner_status.json) `accepted_running`·`hold_low_confidence`·`reject_busy_while_other_run` | 현재 `last_intent`에는 두 칸이 없음(구현 전). 기존 `decision`·`reason`은 그대로 |
| 수락 → 최종 결과 | 기존 `last.run_id` — 같은 예시 `accepted_fast_completed`(빠른 완료에도 같은 `run_id`) | `last`는 현재 구현 그대로. E 완료 안내 조건 = `last.run_id`가 그 요청의 수락 `run_id`와 같음 |
| 실행 기록 | 실행 헤더 `intent`(받은 payload 그대로, #89) → `intent.request_id` | 이미 저장 중 — 새 칸 없음 |
| ID 없는 기존 요청 | 같은 예시 `legacy_without_request_id` — 입력에 `request_id` 필드가 **없으면** 상태 `last_intent.request_id: null`. 입력 `request_id: null`·빈 문자열은 스키마 위반 → `hold`/`BAD_INTENT` | 지금 동작 그대로 |
| 수락 문장 없음 | 입력 `accept_text` 없음·`null` → 수락된 run 의 안내는 태스크 기존 문장 | 지금 동작 그대로 |
| 중복·충돌·재기동 | runner.md 표 — 같은 ID 재전송은 같은 결정, 다른 내용은 첫 결정 유지, 기억은 이번 기동만 | 구현 전 |
