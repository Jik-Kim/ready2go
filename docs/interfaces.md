# 인터페이스 계약 (ICD)

> 관련 요구사항: [FR-COM-01–02](requirements.md#fr-com-01), [FR-INT-01–03](requirements.md#fr-int-01), [FR-VIS-02](requirements.md#fr-vis-02), [FR-LOG-01](requirements.md#fr-log-01). 인터페이스 이름·형식·호출 관계는 이 문서에서 다룹니다.

## 5. 인터페이스 계약 (ICD)

Day 1에 확정하고, 이후 변경은 전원 합의 후 이 표를 먼저 수정함. 커스텀 메시지는 `ready2go_interfaces` 패키지의 **2종(`Skill.action`, `InspectRegion.srv`)으로 제한**하고, 나머지 페이로드는 JSON 문자열로 주고받음.

| 인터페이스 | 이름 | 타입 | 제공 → 사용 |
| :--- | :--- | :--- | :--- |
| 인텐트 | `/voice/intent` | topic `std_msgs/String` (JSON) | voice → ros2-core |
| 로봇 상태 | `/robot_state` | topic `std_msgs/String` (온톨로지 `state` JSON) | **P1 구현:** 현재 필드는 `robot_pose`·`gripper`·`open`·`located_in`이며 좌표와 관측 시각은 없음. Runner가 스킬 effect 뒤 기억한 상태로, 관측으로 검증된 현재 상태라는 뜻이 아님. Voice는 직접 구독해 기존 위치·개폐 질의에 Runner 기록 기준으로 답함([현재 연결·미검증](voice_llm.md#voice-runtime-322)). 시연 화면·트윈의 직접 구독은 후속 연결 |
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
| Runner 상태 · 비상정지 · 상태 초기화 | `/runner/status`, `/runner/estop`, `/runner/reset_state` | `std_msgs/String`, `std_srvs/Trigger`, `std_srvs/Trigger` | **P1 Runner 구현.** `/runner/status`는 내용 변경 때만 발행하며 현재 `phase`·`task_id`·`current_step`·`halt_code`·`halt`·`last`·`last_intent`·`log_store`·`state_reset_at`·`boot_id`를 제공하고, 실제 발행마다 `seq`·`stamp`를 붙임. 테스트·사람의 ROS 호출 외에 Voice가 실행 결과 안내에 사용하며(PR #144), Voice는 정지·초기화 서비스를 호출하지 않음. **계약(E 대화 승인 10/13, 사용자 전달 — #259)**: `/runner/status` `halt.stop`은 정지 요청과 실제 정지 확인(`requested`·`confirmed`·`unconfirmed`·`none`)을 구분, [runner.md](runner.md)·[예시](../contracts/examples/runner_status.json), #152·#187. **P2 W3·W4 구현(#271·#286)**: `/voice/intent` 제어 인텐트 `recover`·`resume_register`·`resume_answer`·`resume`·`end_task`([intent 스키마](../contracts/intent.schema.json)·예시 `intent_*.json`)와 재개 대기 때의 `/runner/status` `halt.resume` — [runner.md 제어 인텐트](runner.md) |
| B 안전 상태 조회 · B 복구 (계약안 W1·W2, #297 B 제안 · #152) | `/skills/check_state`, `/skills/recover` | service `std_srvs/Trigger` (요청 비어 있음, 응답 `success` + `message` JSON) | **제안, E 포함 2명 승인 전 · 실물 미확인.** B 스킬 서버 → Runner. 둘 다 로봇·그리퍼 명령 없음. W1 `success` = 값을 다 읽음(값이 좋은지와 무관), `message` = `stopped`·`estop_active`·`controller_ready`·`tcp_tool_ok`·`comm_ok`·`sensors_ok`·`gripper {state, held_id, …}`·`drawers`(B 서버가 기억한 서랍별 인출 거리 m)·`b_locked`·`external_force`·`stamp` 등, 모르는 값 `null`. W2 `success` = `recovered`, `message` = `{recovered, code, cleared, blockers, state}`. Runner 사용: `recover` 때 W1 조회 → `core/recovery.py` fail-closed 판정(`recover_check: b`, 기준 `params/recovery.yaml`), W2 는 `recover_call_b: true` 일 때 먼저(호출 주체 E·B 결정 대기) — [runner.md 제어 인텐트](runner.md) |
| TF 프레임 | `world`, `base_link`, `link_6`, `wrist_cam_link`, `wrist_cam_color_optical_frame`, `drawer_<id>`, `staging_tray`, `handover_zone` | TF2 | ros2-core: `ready2go_bringup` launch가 `config/calibration/`·`config/places.yaml`을 읽어 static TF 발행 (결정 #23). 로봇 TF는 DSR 드라이버. **`wrist_cam_link`**: 캘리브레이션 결과를 거는 프레임(`link_6 → wrist_cam_link`, bringup 발행). **`wrist_cam_color_optical_frame`**: 컬러·정렬 뎁스 이미지의 `frame_id`, `wrist_cam_link` 아래 트리는 realsense 드라이버가 `/tf_static`으로 발행(끄지 않음). Isaac Sim 트윈 카메라도 같은 `frame_id`를 사용. 강의 URDF(`m0609_rg2_bringup`)에 CAD 기반 `camera_*` 프레임이 따로 있어 TF에 카메라가 두 개 생길 수 있으나, **비전은 `wrist_cam_color_optical_frame`만 사용**(CAD 위치는 캘리브레이션과 x·y 약 1.8 cm 차이, 5점 검증에서 캘리브레이션이 맞음 [실측 B 10/03]). `base_link`·`link_6` 접두어 없음 [실측 B 10/02], `tool0`은 `link_6`과 원점이 같고 축만 회전하므로 사용하지 않음 |

**ROS 인터페이스가 아닌 호출 (같은 프로세스 또는 외부 서비스)**

| 대상 | 호출 방식 | 사용 위치 |
| :--- | :--- | :--- |
| `query_ontology` 원자 동작 | **P1 구현, ROS 인터페이스 없음.** 별도 `OntologyManager` 클래스가 아니라 Runner가 보유한 상태와 로드한 `world`를 프로세스 안에서 직접 조회. P1은 단일 `item`·`state` 경로만 지원 | Runner (7.1 ②) |
| `select_obstacle` · `find_moved` 원자 동작 (**P2, 계약 #176 머지 10/08 · E 사후 검토 대기**) | **ROS 인터페이스 없음.** Runner 가 직전 `inspect_region` 결과와 치운 기록(`restore_stack`)만으로 판단(`core/unpack.py`, 로봇 동작 없음). 입출력은 [runner.md 7.1](runner.md) | Runner (Unpacking 태스크) |
| `update_ontology` 원자 동작 | **P1 미지원(`NOT_SUPPORTED`).** P1 상태 변경은 성공 응답 뒤 스킬 `effect` 적용으로만 수행 | Runner 후속 범위 (7.1 ②) |
| 로그 저장 | **P1 구현:** Python `pymongo`로 MongoDB(`cobot2` DB: `runs`·`steps`)에 `LogStore` 경유 저장, 연결 실패 시 `logs/*.jsonl` 폴백. **P2 계획(FR-LOG-02):** `states` 컬렉션·사후 관측 상세 로그 | Runner (7.4). 별도 Logger 프로세스는 없음 |
| STT · LLM | HTTPS로 OpenAI API 호출 (`secrets/voice.env`의 키 사용) | `voice` 컨테이너 (6장) |
| 웹 상태 조회 | `GET /api/status`, 같은 origin의 JSON·`Cache-Control: no-store` | **이슈 #267 구현:** Flask 웹 브리지 → PC·휴대폰 브라우저. 약 1초 polling이며 ROS 발행 주기나 실시간 보장이 아님. `sources.runner`·`sources.robot_state`·`sources.robot`·`sources.camera`·`sources.voice`를 활성화하고 REST 오류 뒤 이전 값을 정상으로 표시하지 않음. 상세 실행·시험은 [web README](../web/README.md#3단계-rest-형식)를 참조 |
| 웹 등록 정의 조회 | `GET /api/definitions`, 같은 origin의 JSON·`Cache-Control: no-store` | **이슈 #267 5단계 구현:** Flask → PC·휴대폰 브라우저. 서버 시작 때 공통 `ontology.load`와 `tasks/*.json`을 한 번 읽은 `web_file_snapshot`이며 Runner 내부 snapshot·hot reload·현재 상태가 아님. 원본 경로·웹 로딩 시각·manifest SHA와 등록 물품·장소·목록·스킬·태스크 요약을 제공. 상세 형식은 [web README](../web/README.md#5단계-등록-정의-rest-형식)를 참조 |

<a id="web-status-rest"></a>
#### 웹 상태 REST — 이슈 #267 3단계

성공 응답은 `schema_version=1`, UTC `served_at`, 권장 `poll_interval_ms=1000`, `status=ok`, `runtime_profile`, `robot_topic`, `sources`를 포함한다. `sources.<name>`은 publisher 존재, 메시지 수신·유효 여부, 마지막 전체·정상 수신 시각, 나이, freshness·stale, 연결 요약, 메시지/브리지 오류와 마지막 정상 `data`를 구분한다. 현재 실행 source는 `runner`·`robot_state`·`robot`·`camera`·`voice`다. `robot`은 기본 `/dsr01/joint_states`의 수신 진단이며 2초 기본 timeout을 환경 설정으로 관리하고, `robot_topic`은 실행 시 실제 선택한 토픽을 나타낸다. `camera`는 `/wrist_cam/color/camera_info`의 최근 2초 수신 여부이며 sim/dev 최초 미수신은 `확인 전(시뮬레이션)`, 과거 수신 뒤 단절은 `수신 끊김`으로 구분한다. `voice`는 `/voice/intent` publisher 존재 여부를 나타낸다. 로봇 표시는 모션 가능·E-stop 해제·그리퍼·스킬 서버 준비를, Voice 표시는 마이크·STT 처리 성공을 뜻하지 않는다. UI는 `/robot_state`의 네 map 필드가 없거나 형식이 다르면 목업을 사용하지 않고 `확인 전`으로 표시한다.

`/runner/status`와 `/robot_state`는 0.5초 비교 뒤 내용이 바뀔 때만 발행하고 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)`을 사용한다. 따라서 웹 연결 판정은 메시지 나이에 대한 freshness timeout을 두지 않고 publisher 존재와 마지막 보존 메시지를 사용한다. 현재 최상위 실행 `run_id`가 없어 실행 중 상태와 `last_intent`를 항상 확정적으로 연결할 수 없으며, 불명확한 경우 화면은 `확인 전`으로 표시한다. Runner가 제공하는 `boot_id`·`seq`·`stamp`·`halt.resume`은 REST 원본 `sources.runner.data`에 그대로 포함되며, 웹은 `boot_id`를 GID 보조 기동 경계로 사용하지만 `seq`·`stamp`·`halt.resume`은 아직 화면 의미로 변환하지 않는다. `current_skill`은 Runner가 제공하지 않는 미구현 제안이므로 현재 REST 계약과 화면에 추가하지 않는다.

캐시가 없으면 HTTP 503 `STATE_CACHE_UNAVAILABLE`, 스냅샷 생성에 실패하면 HTTP 500 `STATE_SNAPSHOT_FAILED`를 반환한다. 두 오류 모두 `status=error`와 안정된 `error.code`·`error.message`를 사용하며 내부 예외 상세는 응답에 넣지 않는다. 브라우저는 HTTP 오류·JSON 형식 오류·지원하지 않는 버전을 REST 연결 오류로 표시하고, 이전 성공 응답을 현재 정상 상태로 계속 사용하지 않는다.

<a id="web-definitions-rest"></a>
#### 웹 등록 정의 REST — 이슈 #267 5단계

`GET /api/definitions`는 상태 polling과 분리해 브라우저 시작 때 한 번 조회한다. 응답의 `snapshot.schema_version=1`, `snapshot_kind=web_file_snapshot`, `loaded_at`, `runner_hot_reload_applied=false`, `sources`, `counts`, `definitions`가 웹이 읽은 원본과 시점을 구분한다. `definitions`에는 classes·items·places·lists·skills·tasks 요약만 포함하며 Runner 현재 `state`는 `/robot_state`와 혼동하지 않도록 제외한다.

서버는 `RUNNER_ONTOLOGY_FILE`(기본 `/knowledge/robot_ontology.jsonld`)과 `WEB_TASKS_DIR`(Runner `tasks_dir` 기본값과 같은 `/tasks`)를 시작 때 읽는다. 온톨로지는 `ready2go_knowledge.core.ontology.load()`를 재사용하며 태스크는 바로 아래 `*.json`의 고유하고 비어 있지 않은 `task_id`를 검사한다. 파일 변경은 실행 중인 Runner나 웹에 자동 반영되지 않는다. 정의 로딩 실패는 HTTP 503 `DEFINITIONS_UNAVAILABLE`로 해당 API에만 표시하고 `/api/status`와 정적 UI는 계속 제공한다.

### 5.1 물품 식별자·좌표·조회 결과의 공유 규칙

| 항목 | 의미·제공자·사용자 |
| :--- | :--- |
| 물품 키 | `world.items` 키(예: `eraser`). voice의 `targets`, vision의 `search_target`·검출 `class`에서 사용. 온톨로지 종류 `Item/Key/Obstacle`와 구분 |
| 인스턴스 ID | A가 관측한 물체에 부여한 `eraser#1` 등. B의 `pick_object` 입력으로 사용(서랍: `target`을 통째로, 트레이: `object_id`). 클래스 키를 인스턴스 ID로 임의 변환하지 않음 |
| `pose` | `{frame, position, yaw}` 형식 유지. 위치·yaw·`top_z` 의미는 병합된 PR #61의 [runner.md 7.1](runner.md#71-원자-동작primitive-action-정의-규격)을 참조함. 서랍 좌표계 정의는 [`config/places.yaml` 첫 부분](../config/places.yaml)이 정본. 규칙 함수·예시 검사는 제공되지만 실제 비전 추론·B 실행 경로 연결 완료를 뜻하지 않음 |
| `size_m` | 물체 로컬 x 긴 변·y 짧은 변·z 높이 순서의 외접 박스(m). 치수 원본은 E의 `world.jsonld`. 스패너·망치 머리 폭을 파지 손잡이 폭으로 해석하지 않음 |
| `top_z` | 관측 시 지지면·배치를 포함한 물체 윗면의 프레임 z 높이(m). 바닥에 놓인 예시에서만 물품 높이와 같을 수 있음. 항상 `size_m[2]`로 대체하지 않음 |
| 물품 조회 | E 공통 로더의 `world.items.<key>`: 기존 이름·종류·별칭·치수와 `roles`, `grip_force`(양수 또는 null), `grasp_verified`(bool), 선택 `grasp_width_m`·`grasp_width_long_m`(실제 RG2 파지 폭, m; 각각 짧은 변 잡기·긴 변 양끝 잡기. 외접 박스 `size_m`와 다른 물품에서만 설정; [원본 설정](../config/item_grasp.yaml)). 물품 등록과 파지 승인은 별개 |
| 초기 위치 | `initial_state.json`은 배치 예시. 실제 위치라고 발행하려면 확인·초기화가 필요하며, 현재 상태와 개별 인스턴스 위치는 C가 관리 |
| 인식 결과 | `target_found/target/candidates/visible_count` 형식 유지. 미발견은 `success=true, target_found=false`; 통신·관측 실패와 구분. 예시 좌표는 실측 증빙이 아님 |

**실행 전 인계**: B·C는 `require_grasp_settings()` 또는 동등한 검증으로 미확정 파지 힘·검증 상태를 확인하고 실행 불가를 반환해야 함. null을 임의 기본 힘으로 대체하지 않음. 기존 `query_ontology` 결과에도 이 상태를 전달하는 연결은 C 담당이며, 에러 코드·질문/TTS 응답 계약은 해당 담당과 확정 필요.

**학습 인계**: A의 데이터셋 도구는 병합된 PR #45에서 `sources.world`를 따라 `world.jsonld`의 물품 목록을 조회함. 전체 E 로더를 호출하지 않아 학습 도구에 PyYAML 의존성을 추가하지 않음. PR #45의 고정 클래스 목록은 `config/yolo_classes.txt`(0부터 시작하는 줄 순서)이며 이번 PR에서 `--init-classes`로 11종의 최초 번호(0–10)를 생성함. 이후 재정렬하지 않음. 번호 고정 후 새 클래스는 끝에 추가하고 데이터셋·가중치와 목록 버전을 연결함. 기존 라벨의 유무·번호는 A가 확인함.

<a id="p2-safety-proposal"></a>

### 5.2 P2 정지·복구·재개 계약안 — 제안·승인 대기

[문서: 현재] 기존 ICD 표·intent enum·스키마·예시는 유지합니다. [FR-SAF-01–03](requirements.md#fr-saf-01)·[AC-SAF-02–04](requirements.md#ac-saf-02)의 목표 승인은 새 wire 계약 승인이 아닙니다. 현재 core `resume()`은 잠금 해제만 합니다. 중단 단계 재개는 core `resume_run`(PR #170 병합 10/08, 기본 꺼짐 `resumable=False`) **준비만** 있고, Runner 노드 쪽 `/runner/status` `halt`·`halt.resume`, 제어 인텐트(`recover`·`resume_register`·`resume_answer`·`resume`·`end_task`, #271 계약·#285~#291 머지 10/13)와 B 조회·복구 호출(`/skills/check_state`·`/skills/recover`, B #297 제안 위 C 연결)은 구현됐고, **E 음성 발행 연결·B 서비스 머지·실물 확인은 남았습니다**([runner.md 제어 인텐트](runner.md)). reset_state 역시 안전 해제가 아닙니다.

| 흐름·담당 | 필요한 의미(확정 필드명이 아님) | 차단 조건·협의 사항 |
| :--- | :--- | :--- |
| B→C 정지·복구 | 정지 명령 수락·실제 정지 증빙·fresh state/관절/TCP 안정·원인·힘·센서/통신·컨트롤러/툴/E-stop 상태·복구 결과 | ESTOP 응답 단독·state fallback을 완전한 정지로 해석하지 않음. alarm/driver 자동 reset은 B 조사/실물 미검증. 임계값·자료 유효기간·전달 형식 승인 필요 |
| C→E 복구·질문 준비 | 현재 정지 사건·작업·중단 단계, 부팅 세대·순서·최신성, 실제 복구 성공·조건/재개점 확인 | 반복 상태 질문 1회, 재정지·다른/과거 사건·불명확 결과 차단. 결과/발화 연결·시계·취소·직렬화 방식 미확정 |
| E→C 명시적 재개 후보 | 현재 질문 완료 뒤 채취한 명시적 응답과 같은 사건/작업 식별·유효성 | TTS만으로 잠금 해제하지 않음. 무응답·거절·중복·지연·자기 음성 차단, 새 enum/토픽/서비스 이름 승인 필요 |
| C↔B 단계 재진입 | 위치/그리퍼/서랍/물체·변수·부분 실행/effect·검증된 재개 지점 | 조건 재검사 후 중단 단계부터 이어 실행 목표. 원자 동작/params/궤적 무조건 재전송·effect 중복 금지. 확인 불가 시 보류 |

[제안] `recovery_confirmation.py`의 내부 자료형·후보는 운영에 연결하지 않은 구현 준비이며 표의 의미를 확정 필드로 대신하지 않습니다. 힘·시간·유효기간 미확정 값은 후속 승인 시 config/params에 `[팀 확정 필요]`로 두며 임의 기본값을 하드코딩하지 않습니다. 새 계약은 전원 ICD 변경 합의·E 포함 2명 승인·스키마/예시/문서 같은 PR 대조가 필요합니다. 다른 담당 패키지를 수정하지 않았습니다.


<a id="request-run-contract"></a>
### 5.3 일반 요청 → 수락 → 완료 계약07 — 공동 원본 준비

[문서: E 초안] 승인 의미·책임·호환 및 중복 처리 기준은 [수락 TTS 정본](requirements.md#acceptance-tts-policy)을 참조합니다. 이 절은 E 발신 원본과 C 수신·상태 설명을 담당별로 기록합니다. C 소유 계약07 상태 예시·Runner 설명·ICD 구간은 이 head에 합류했고 C 원본 검토가 확인됐습니다. [PR #221](https://github.com/Jik-Kim/ready2go/pull/221)·[PR #225](https://github.com/Jik-Kim/ready2go/pull/225)는 병합됐으며 실제 C 런타임 수신·생산자 연결과 운영 통합 완료는 별도로 확인해야 합니다. 문서 합류나 PR 병합만으로 운영 연결 완료를 뜻하지 않습니다.

#### E 담당 — 일반 요청 발신 원본

| 연결 | 실행 원본·예시 | 현행 구현과의 구분 |
| :--- | :--- | :--- |
| `/voice/intent` JSON 최상위 두 필드 | [intent.schema.json](../contracts/intent.schema.json)의 `properties.request_id`·`properties.accept_text` | `required`는 기존 `intent`·`confidence` 그대로이며 내부 LLM/P1 입력에 새 필드를 강제하지 않음 |
| E 실행 요청의 원본 예시 | [intent_find_item.json](../contracts/examples/intent_find_item.json), [intent_goal.json](../contracts/examples/intent_goal.json) | 공개 형식 예시이며 실제 Voice 발행·목표 실행의 증거가 아님. goal 예시의 기존 목표는 유지하며 선정 catalog 지원을 뜻하지 않음 |
| 기존 source | 같은 스키마의 `properties.source` | 로그용 자유 객체는 유지. E 발신 ID를 `source.request_id`에 중복 작성하지 않음 |
| 현재 Voice 발신/소비 | [VoiceNode](../ros2_ws/src/ready2go_voice/ready2go_voice/nodes/voice_node.py), [Session](../ros2_ws/src/ready2go_voice/ready2go_voice/core/session.py) | Session의 `prepare_request_payload`는 계약07 공개 payload 후보를 만들고 RequestRun/VoiceNode는 검증된 C source mapper가 주입된 모의에서 상관 경로를 검사합니다. 실제 노드는 source mapper 미설치 시 연결을 거절하고 `request_run_enabled` 기본값도 false이므로 공개 발신·C 결정/결과 운영 연결은 보류됩니다 |

#### C 담당 — 수신·상태·결과

[문서: C 합류] 결정·결과 칸과 처리 규칙은 [runner.md 7.1 "요청 상관 — 계약07"](runner.md), 상태 예시는 [runner_status.json](../contracts/examples/runner_status.json)이 원본이다. 이 구간은 연결만 기록하며 Runner 수신 구현(중복 기억·`run_id` 고정·`accept_text` 1회 안내 게이트)은 계약 병합 뒤 운영 PR이다.

| 연결 | 실행 원본·예시 | 현행 구현과의 구분 |
| :--- | :--- | :--- |
| E 요청 → C 결정 | `/runner/status` `last_intent.request_id`·`run_id` — [runner_status.json](../contracts/examples/runner_status.json) `accepted_running`·`hold_low_confidence`·`reject_busy_while_other_run` | C 운영 구현(Runner, 모의 시험 — 계약 #221 뒤 운영 PR) — 수락 때 `run_id` 고정. 기존 `decision`·`reason`은 그대로 |
| 수락 → 최종 결과 | 기존 `last.run_id` — 같은 예시 `accepted_fast_completed`(빠른 완료에도 같은 `run_id`) | `last`는 현재 구현 그대로. E 완료 안내 조건 = `last.run_id`가 그 요청의 수락 `run_id`와 같음 |
| 실행 기록 | 실행 헤더 `intent`(받은 payload 그대로, #89) → `intent.request_id` | 이미 저장 중 — 새 칸 없음 |
| ID 없는 기존 요청 | 같은 예시 `legacy_without_request_id` — 입력에 `request_id` 필드가 **없으면** 상태 `last_intent.request_id: null`. 입력 `request_id: null`·빈 문자열은 스키마 위반 → `hold`/`BAD_INTENT` | 지금 동작 그대로 |
| 수락 문장 없음 | 입력 `accept_text` 없음·`null` → 수락된 run 의 안내는 태스크 기존 문장 | 지금 동작 그대로 |
| 중복·충돌·재기동 | runner.md 표 — 같은 ID 재전송은 같은 결정, 다른 내용은 첫 결정 유지, 기억은 이번 기동만 | C 운영 구현 (Runner, 모의 — 계약 #221 뒤 운영 PR) |
