# ROKEY 웹 대시보드

> [문서] 화면은 이슈 [#112](https://github.com/Jik-Kim/ready2go/issues/112)의 PC·휴대폰 검토 목업을 기반으로 합니다. 이슈 [#267](https://github.com/Jik-Kim/ready2go/issues/267)의 1~5단계인 Flask 정적 제공, `/runner/status`·`/robot_state` 수신·잠금 캐시, 상태 REST와 약 1초 조회, 등록 온톨로지·태스크·스킬 정의의 읽기 전용 파일 스냅샷 연결을 구현했습니다. 현재 작업 진행과 실행 결과는 계속 목업이며 등록 정의와 구분합니다.

기능의 의미·Phase·수용 기준은 정본인 [FR-COM-01](../docs/requirements.md#fr-com-01), [FR-INT-02](../docs/requirements.md#fr-int-02), [FR-ONT-02](../docs/requirements.md#fr-ont-02), [FR-PLN-02](../docs/requirements.md#fr-pln-02), [FR-LOG-01–02](../docs/requirements.md#fr-log-01), [NFR-SAF-02](../docs/requirements.md#nfr-saf-02)를 참조합니다. 이 문서는 요구사항을 재정의하지 않습니다.

## 1. 이슈 #112에서 화면이 바뀐 과정

이 화면은 이슈 #112의 제안과 검토를 거쳐 다음처럼 정리됐습니다.

1. **최초 제안** — PC·휴대폰이 같은 작업 상태를 보고 연결 상태, 서랍, 준비물, 현재 작업을 표시하는 구성을 제안했습니다.
2. **두 번째 목업** — [댓글 6033300834](https://github.com/Jik-Kim/ready2go/issues/112#issuecomment-6033300834)에서 상태 블록을 작게 만들고 임시 트레이·별도 복구 영역·이벤트 기록을 제외했습니다. 모바일에는 명령 상세와 서랍 보기를 분리했습니다.
3. **작업 상세 목업** — [댓글 6037139561](https://github.com/Jik-Kim/ready2go/issues/112#issuecomment-6037139561)에서 현재 동작과 접이식 상세, 단계별 진행 표현을 구체화했습니다.
4. **연결·검토 화면 제안** — [댓글 6075167277](https://github.com/Jik-Kim/ready2go/issues/112#issuecomment-6075167277)과 [댓글 6079728121](https://github.com/Jik-Kim/ready2go/issues/112#issuecomment-6079728121)에서 서버를 통한 데이터 연결과 네 개의 읽기 전용 검토 탭을 제안했습니다.
5. **녹화 범위 정리** — [최신 PM 검토 댓글 6136644749](https://github.com/Jik-Kim/ready2go/issues/112#issuecomment-6136644749)에 따라 STT 원문과 작업 중단을 이번 목업·녹화 화면에서 제외하고, 연결 상태를 `확인 전` 중심으로 바꿨습니다. STT 원문은 기존 `source.stt_text`에서 `/runner/status.last_intent.stt_text`로 제공되는 경로가 있으며, 화면 어댑터 연결과 값 누락 처리는 후속 작업입니다. 검토 화면은 현재 상태·온톨로지를 우선 연결 대상으로, 계획 근거·실행 기록을 후속 연결로 구분했습니다.

## 2. 파일 역할과 실제 연동 시 교체 지점

| 파일 | 현재 역할 | 실제 연동 시 |
|---|---|---|
| `index.html` | 사용자 대시보드·읽기 전용 검토 화면의 HTML 구조와 CSS·JavaScript 진입점 | 화면 구조는 유지하고 `demo-data.js` 로딩을 데이터 어댑터 진입점으로 교체합니다. |
| `styles.css` | 흰색·남색·청록색 디자인, PC·모바일 배치, 서랍 모양, PC 가로·모바일 세로 단계 | 데이터 연결과 무관합니다. 상태 종류가 추가될 때 표시 스타일만 보완합니다. |
| `demo-data.js` | PC·모바일이 함께 읽는 목업 데이터와 `long`·`empty`·`error` 시나리오 | 우선 교체 대상입니다. 서버 응답을 같은 화면 모델로 변환하는 어댑터가 이 역할을 맡습니다. |
| `status-api.js` | `/api/status`를 중첩 없이 약 1초마다 조회하고 `/api/definitions`를 시작 때 한 번 읽음 | Runner 연결·기억 상태와 웹 파일 정의 스냅샷을 서로 다른 시점의 데이터로 전달합니다. |
| `runner-status-model.js` | `/runner/status.last_intent`와 `last`를 화면 표시 전 `valid`·`absent`·`invalid` 내부 모델로 검증·복사하고 실행 연결을 판정 | `decision=run`이고 두 `run_id`가 같을 때만 `linked`로 묶으며 실제 요청·결과 화면 표시는 후속 단계에서 구현합니다. |
| `app.js` | 상태 렌더링, 서랍 조회, 상세·대화상자·검토 탭 전환과 포커스 복귀 | 렌더링은 재사용하고 데이터 수신 뒤 `renderAll()` 또는 필요한 렌더 함수를 호출합니다. ROS 2나 DB에 직접 연결하지 않습니다. |
| `README.md` | 현재 구현, 실행·접속·시나리오, 실제 연동 경계를 설명 | 연결 경로가 구현된 뒤 실제 실행법과 검증 결과를 갱신합니다. |
| `ready2go_web/server.py` | 기존 정적 파일을 allowlist로 제공하고 ROS 공유 캐시의 스냅샷을 `GET /api/status`로 반환 | 응답은 캐시하지 않으며 내부 예외 세부 내용은 브라우저에 노출하지 않습니다. |
| `ready2go_web/nodes/dashboard_bridge.py` | 단일 rclpy 노드로 선택한 ROS source를 구독·관찰 | 4단계 실행에서는 `/runner/status`와 `/robot_state`를 활성화합니다. |
| `ready2go_web/core/state_cache.py` | ROS 콜백과 Flask 요청 사이의 최신 상태를 잠금으로 보호 | REST에는 깊은 복사 스냅샷만 전달합니다. |
| `ready2go_web/core/definition_catalog.py` | 공통 `ontology.load`와 `tasks/*.json`으로 등록 정의 스냅샷 생성 | Runner hot reload가 아닌 웹 시작 시 파일 조회임을 출처·시각·manifest SHA와 함께 기록합니다. |
| `ready2go_web/runtime.py` | 전용 ROS context와 별도 executor 스레드의 시작·종료를 관리 | Flask 요청 스레드와 ROS 콜백을 분리합니다. |

```text
index.html
 ├─ styles.css      화면 모양과 반응형 배치
 ├─ demo-data.js    목업 전용 원본 상태
 ├─ status-api.js   REST 상태 조회와 재시도
 ├─ runner-status-model.js  Runner 요청·결과 형식 검증
 └─ app.js          같은 상태를 PC·모바일 요소에 표시
```

`app.js`는 `window.ROKEY_DEMO_DATA` 한 객체를 읽으므로 PC와 휴대폰이 서로 다른 샘플 상태를 만들지 않습니다. 선택한 조회 서랍인 `selectedDrawerId`와 실제 작업 위치인 `task.workDrawerId`도 별도로 유지합니다.

## 3. 현재 정적 목업

### 표시 데이터

| 화면 | 목업 데이터 경로 |
|---|---|
| 목업 안내 | `meta.label`, `meta.description` |
| 연결 상태 | `connections[].status`, `statusLabel`, `description` |
| 해석·접수·처리 | `command.understood`, `interpretation`, `receipt`, `processing`, `confirmation` |
| 서랍·등록 물품 | `selectedDrawerId`, `drawers[].items` |
| 준비물과 완료 수 | `supplies[]`; `status === "delivered"`만 완료로 계산 |
| 현재 작업·단계·근거 | `task.currentAction`, `workDrawerId`, `steps[].reason`, `steps[].observation` |
| 검토 화면 현재 상태 | `adminReview.current`과 공통 `task` 상태 |
| 등록 정의 | 기본 시나리오는 `/api/definitions`; 고정 URL 시나리오는 `adminReview.ontology` 목업 |
| 후속 연결 안내 | `adminReview.plan.message`, `adminReview.history.message` |

서랍 선택은 등록 물품 조회만 바꾸며 로봇 명령을 만들지 않습니다. 작업 상세, 모바일 명령 상세·서랍 보기, 검토 화면과 탭 전환도 브라우저 안의 표시만 바꿉니다.

### 녹화 우선 연결 범위

[문서] 최신 PM 검토가 정한 우선순위에 맞춰 이후 연결 순서를 다음으로 제한해 표시합니다.

1. 정적 UI
2. `/runner/status`
3. `/robot_state`
4. 온톨로지 원본 읽기
5. PC·휴대폰의 동일 상태 표시

[문서] 1단계 정적 UI, 2단계 `/runner/status` 수신·캐시, 3단계 상태 REST·약 1초 조회, 4단계 `/robot_state` 수신·화면 반영, 5단계 등록 온톨로지·태스크·스킬 정의 로딩이 구현됐습니다. 현재 화면에는 Runner 연결·기억 상태와 웹이 시작할 때 읽은 정의 파일 스냅샷이 각각의 출처로 나타납니다. MongoDB/JSONL 실행 기록, 작업 중단·재개·초기화, 실시간 계획 근거, STT 원문과 확정되지 않은 음성·로봇 연결 판정은 제외합니다.

### 표시를 바꾼 이유

- **STT 원문 미표시**: 기존 인텐트의 `source.stt_text`는 Runner에서 `/runner/status.last_intent.stt_text`로 제공됩니다. 다만 이번 정적 목업·녹화 범위에서는 표시하지 않으며, 실제 연결 시 웹 어댑터와 값 누락 처리를 함께 구현해야 합니다.
- **작업 중단 숨김**: 실제 중단 요청 경로가 이번 범위에 없으므로 버튼과 로컬 `중단 완료` 동작을 제거했습니다.
- **장치 연결 상태**: 카메라는 `/wrist_cam/color/camera_info`의 최근 2초 수신, Voice는 `/voice/intent` publisher 존재, 로봇은 `/dsr01/joint_states`의 최근 2초 수신 여부를 표시합니다. Voice 표시는 마이크·STT 처리 성공을 뜻하지 않습니다.
- **성공 상태의 의미**: 목업의 명령 접수·전달 완료·관측 확인 표시는 시각 검토용 예시입니다. 화면 상단 안내가 실제 성공 결과가 아님을 명시합니다.

## 4. 현재 연결 경계

```text
/runner/status → DashboardBridge → StateCache → GET /api/status
/robot_state  ────────────────────┘                 ↓ 약 1초 polling
                                        Runner 연결·기억 상태 UI
온톨로지 manifest ─ common ontology.load ─┐
tasks/*.json ─────────────────────────────┼→ 시작 시 정의 스냅샷 → GET /api/definitions → 등록 정의 UI
```

[문서] 브라우저는 ROS 2·온톨로지 파일·MongoDB에 직접 연결하지 않습니다. 현재 Flask 프로세스가 별도 `SingleThreadedExecutor`에서 단일 `DashboardBridge`를 실행하며 `/runner/status`와 `/robot_state`를 활성화합니다. 두 `std_msgs/msg/String`의 JSON 객체를 source별 캐시에 저장하고 publisher 존재, 메시지 수신, 파싱 오류를 구분합니다. 브라우저는 REST 응답이 끝난 뒤 다음 조회를 예약하므로 느린 요청이 서로 겹치지 않습니다.

실제 연결 시에는 다음 순서로 교체할 수 있습니다.

1. Flask가 공유 `StateCache`의 스냅샷을 읽기 전용 REST로 반환합니다.
2. 기본 화면은 약 1초마다 API를 조회하고 Runner 연결과 기억 상태를 변환합니다.
3. `long`·`empty`·`error` 시나리오 URL은 고정 목업 검토를 위해 polling하지 않습니다.
4. `/api/definitions`는 페이지 시작 때 한 번만 읽고 상태 polling에 섞지 않습니다.
5. 정의 파일 변경은 현재 Runner나 이미 실행 중인 웹에 자동 적용되지 않으며, 두 프로세스를 각각 재기동해야 새 스냅샷을 읽습니다.

### C 확인값과 후속 단계 입력

[문서] 이슈 [#267 C 회신](https://github.com/Jik-Kim/ready2go/issues/267#issuecomment-6140239576)과 병합된 W4 구현을 기준으로 현재 Runner 동작과 아직 구현되지 않은 제안을 구분합니다.

- `/runner/status`와 `/robot_state`는 내용을 0.5초마다 비교하되 **내용이 달라졌을 때만** 발행합니다. 둘 다 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)`이며, 긴 유휴 시간에 새 메시지가 없어도 publisher가 존재하면 연결된 것으로 판단합니다.
- 현재 `/runner/status`에는 `phase`, 실행 중의 `task_id`·`current_step`, 잠금 상태의 `halt_code`, `halt`, `last`, `last_intent`, `log_store`, `state_reset_at`, `boot_id`가 포함되고 실제 발행에는 `seq`·`stamp`가 붙습니다. 재개 대기 중에는 `halt.resume`도 제공됩니다. REST는 이 원본을 그대로 전달하며 화면은 `boot_id`만 GID를 보조하는 기동 경계로 사용합니다.
- `phase`는 `idle`·`running`·`halted`이며 화면에는 각각 `대기`·`실행 중`·`정지(잠김)`으로 표시합니다. 계약에 없는 값은 `확인 전`으로 표시합니다. `task_id`와 `current_step`은 실행 중에만 있으며, `halt_code`는 잠금 상태에서만 있습니다. `current_step`은 확장 또는 fallback 단계 ID일 수 있고 `achieve_goal`의 `plan_*`은 태스크 파일에 없으므로 화면은 원본 ID를 그대로 표시합니다.
- 현재 실행과 최근 요청을 직접 연결하는 최상위 `run_id`는 없습니다. 따라서 실행 중인 `task_id`와 `current_step`을 최근 요청·결과라고 단정하지 않습니다. 아래의 `last_intent`와 `last` 사이 결합은 두 레코드가 제공하는 ID만 검사하는 별도 판정입니다.
- 화면 연결에 앞서 `last_intent`의 `intent`·`targets`·`decision`·`reason`·`task_id`·`request_id`·`run_id`와 `last`의 `task_id`·`run_id`·`overall_status`·`error_code`·`failed_step`을 독립적으로 검사합니다. `null`은 아직 기록이 없는 상태로, 키 누락·잘못된 자료형은 형식 오류로 구분하며 형식 오류의 정상 필드 일부를 화면에 재사용하지 않습니다. 이 파싱은 두 레코드를 같은 실행으로 연결하거나 결과 문구를 정하는 동작이 아닙니다.
- 파싱 뒤에는 `last_intent.decision=run`이고 요청·결과의 비어 있지 않은 `run_id`와 `task_id`가 모두 같을 때만 `linked` 결합 모델을 만듭니다. 결과 상태는 Runner의 `COMPLETED`·`FAILED`·`ABORTED`·`SUSPENDED`만 허용합니다. 다른 ID, 수락 요청의 ID 누락, 계약 밖 결과 상태, `hold`·`reject`·`cancel`·`status` 같은 비실행 결정, 한쪽 기록 없음과 형식 오류는 연결하지 않고 각각의 이유 코드를 보존합니다. 이 판정은 내부 모델까지이며 메인 화면에는 아직 요청·결과를 표시하지 않습니다.
- `/robot_state`의 현재 필드는 `robot_pose`, `gripper`, `open`, `located_in`입니다. 좌표는 없으며 모두 스킬 effect 뒤 Runner가 기억한 상태입니다. 현재 관측값이나 관측 시각으로 해석하지 않습니다.
- 4단계 UI에서 `/robot_state` 값이 없거나 예상한 형식과 다르면 목업 데이터로 대체하지 않고 모두 `확인 전`으로 표시합니다. `상태 데이터 없음`은 별도 표시 문구로 사용하지 않습니다.
- 서랍은 문자열 ID 순서가 아니라 `drawer_top`·`drawer_bottom`의 물리 순서로 표시합니다. 관리자 현재 상태 탭은 `task_id`·`current_step`·`phase`와 Runner 기억 상태를 실데이터로 표시하며, 별도 `run_id`가 없으므로 목업 실행 ID를 사용하지 않습니다.
- Runner는 기동할 때 `RUNNER_ONTOLOGY_FILE`(기본 `/knowledge/robot_ontology.jsonld`), `tasks_dir`(기본 `/tasks`), `/contracts/intent.schema.json`, `RUNNER_INTENT_TASKS`를 한 번 읽습니다. 실행 중 파일 변경은 반영되지 않고 `reset_state`도 기동 때 읽은 상태로 되돌립니다.

후속 구현은 이 현재 계약만 소비합니다. 최상위 실행 `run_id`와 아직 Runner가 제공하지 않는 `current_skill`은 별도 계약·구현 전까지 REST나 화면의 확정 필드로 만들지 않습니다.

## 5. 읽기 전용 검토 화면

상단 `검토 화면` 버튼은 인증 없이 같은 정적 페이지의 `#admin` 화면으로 이동합니다. 관리자 인증, 권한 획득, 서버 API 접근 제어가 구현된 것이 아닙니다.

- **현재 상태**: Runner 연결 진단과 기억 상태는 `/runner/status`·`/robot_state`·REST의 실제 값입니다. `/robot_state`는 관측값이 아니며 값 누락·형식 불일치는 `확인 전`으로 표시합니다.
- **온톨로지**: 서버가 공통 `ontology.load`로 읽은 등록 물품·장소·목록·스킬과 `tasks/*.json` 태스크를 표시합니다. 원본 경로·웹 로딩 시각·manifest SHA를 함께 보여 주며 Runner 내부 현재 상태나 hot reload를 뜻하지 않습니다.
- **계획 근거**: 후속 연결 예정이며 현재 제공 경로가 확정되지 않았다는 안내만 표시합니다.
- **실행 기록**: 후속 연결 예정이며 실제 MongoDB/JSONL 조회가 연결되지 않았다는 안내만 표시합니다.

실제 운영 전에 서버 인증과 접근 제어를 반드시 연결해야 합니다. 일반 사용자 로그인은 고려 단계이며 이 목업의 구현 범위가 아닙니다.

## 6. 실행과 접속

루트 [`requirements.txt`](../requirements.txt)를 설치한 프로젝트 가상환경과 ROS 2 환경을 준비한 뒤 **저장소 루트에서** 다음을 실행합니다. 아래 Domain 70·CycloneDDS 설정은 Runner와 웹 브리지가 같은 ROS graph를 사용하기 위한 필수 실행 환경입니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=70
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$PWD/config/cyclonedds.local.xml"
export ROS_LOG_DIR="$PWD/logs/ros"
# 5단계 웹 정의 스냅샷이 Runner와 같은 저장소 원본을 읽도록 절대 경로를 지정합니다.
export RUNNER_ONTOLOGY_FILE="$PWD/knowledge/robot_ontology.jsonld"
export WEB_TASKS_DIR="$PWD/tasks"
# B 로봇 연결 기준은 환경 설정으로 유지해 PC2 실측 뒤 timeout을 조정할 수 있습니다.
export WEB_ROBOT_TOPIC="/dsr01/joint_states"
export WEB_ROBOT_TIMEOUT_SEC="2.0"
export WEB_RUNTIME_PROFILE="real"
mkdir -p "$ROS_LOG_DIR"
cd web
WEB_HOST=127.0.0.1 WEB_PORT=4173 python3 -m ready2go_web
```

의존성을 아직 설치하지 않았다면 저장소 루트의 [프로젝트 의존성 설치](../README.md#프로젝트-의존성-설치)를 먼저 따릅니다. PC를 나눠 사용하는 경우에는 루트 README의 다중 PC 안내에 따라 `cyclonedds.multi.xml`, NIC와 peer IP를 사용합니다.

이 명령은 Flask 정적 서버, `/runner/status`·`/robot_state`·`/dsr01/joint_states`·`/wrist_cam/color/camera_info` 구독과 `/voice/intent` publisher 관찰, 상태 REST와 등록 정의 REST를 같은 프로세스에서 시작합니다. 같은 PC에서는 `http://localhost:4173`으로 접속합니다. 종료할 때 `Ctrl+C`를 누르면 executor, 노드, ROS context도 함께 정리됩니다. 현재 작업 진행·요청 결과는 목업이며 상태·정의와 구분됩니다.

휴대폰이나 다른 PC에서는 서버 PC와 같은 네트워크에 연결한 뒤 서버 PC에서 주소를 확인합니다. `config/cyclonedds.local.xml`은 DDS를 loopback으로 제한하므로 Runner와 웹 브리지는 같은 PC2에서 실행해야 합니다. 외부 브라우저 접속이 필요할 때만 `WEB_HOST=0.0.0.0`으로 실행하고, 실제 포트(`ss -ltnp`), PC 방화벽과 Wi-Fi AP의 단말 간 통신 차단 여부를 현장에서 확인합니다.

```bash
# PC2의 모든 네트워크 인터페이스에서 웹 접속을 받습니다.
WEB_HOST=0.0.0.0 WEB_PORT=4173 python3 -m ready2go_web

# 다른 터미널에서 PC2의 LAN 주소를 확인합니다.
hostname -I
```

Docker용 `172.17.x.x`를 제외한 와이파이·유선 LAN 주소를 골라 `http://서버_PC_IP:4173`으로 접속합니다. 모바일 전용 URL은 없으며 화면 폭에 따라 자동 전환됩니다. 접속되지 않으면 서버 실행 여부, 동일 네트워크, 방문자망의 장치 간 차단, TCP 4173 방화벽을 확인합니다.

### 3단계 REST 형식

브라우저와 같은 origin의 `GET /api/status`를 사용합니다. 성공 응답은 HTTP 200이며 `Cache-Control: no-store`가 붙습니다.

```json
{
  "schema_version": 1,
  "served_at": "2026-10-13T06:31:00Z",
  "poll_interval_ms": 1000,
  "status": "ok",
  "runtime_profile": "real",
  "robot_topic": "/dsr01/joint_states",
  "sources": {
    "runner": {
      "publisher_present": true,
      "message_received": true,
      "message_valid": true,
      "last_received_at": "2026-10-13T06:30:59Z",
      "last_valid_received_at": "2026-10-13T06:30:59Z",
      "age_sec": 0.2,
      "valid_age_sec": 0.2,
      "freshness_timeout_sec": null,
      "stale": false,
      "connection_state": "receiving",
      "last_error": null,
      "last_error_kind": null,
      "message_error": null,
      "bridge_error": null,
      "data": {
        "phase": "running",
        "task_id": "manual_test",
        "current_step": "open_drawer"
      }
    },
    "robot": {
      "publisher_present": true,
      "message_received": true,
      "message_valid": true,
      "freshness_timeout_sec": 2.0,
      "stale": false,
      "connection_state": "receiving",
      "data": {
        "joint_count": 6,
        "joint_names": ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"]
      }
    },
    "camera": {
      "publisher_present": true,
      "message_received": true,
      "message_valid": true,
      "freshness_timeout_sec": 2.0,
      "stale": false,
      "connection_state": "receiving",
      "data": {
        "frame_id": "wrist_cam_color_optical_frame",
        "width": 1280,
        "height": 720
      }
    },
    "voice": {
      "publisher_present": true,
      "message_received": false,
      "message_valid": false,
      "freshness_timeout_sec": null,
      "stale": false,
      "connection_state": "waiting",
      "data": null
    }
  }
}
```

`data`는 마지막으로 정상 해석한 `/runner/status` JSON 원본입니다. 비정상 메시지를 받으면 진단을 위해 마지막 정상 `data`는 보존하지만 `message_valid=false`, `connection_state=error`로 반환하므로 현재 정상값으로 해석하지 않습니다. Runner는 내용이 변경될 때만 상태 토픽을 발행하므로 단순히 `age_sec`이 증가했다는 이유로 끊김 처리하지 않습니다.

`sources.robot`은 `/dsr01/joint_states`의 최근 유효 수신만 나타냅니다. 기본 웹 구독은 `qos_profile_sensor_data`, 기본 무수신 기준은 환경 설정 `WEB_ROBOT_TIMEOUT_SEC=2.0`입니다. 화면 문구 `로봇 관절 상태 수신`은 모션 가능, E-stop 해제, 로봇 모드, 그리퍼 또는 스킬 서버 준비를 뜻하지 않습니다. `WEB_RUNTIME_PROFILE=sim|dev`에서 발행자가 없으면 장애로 단정하지 않고 `확인 전(시뮬레이션)`으로 표시합니다.

`sources.camera`는 `/wrist_cam/color/camera_info`를 `qos_profile_sensor_data`로 구독한 최근 수신 여부이며 기본 2초 timeout을 사용합니다. `WEB_RUNTIME_PROFILE=sim|dev`에서 한 번도 수신하지 않은 미발행은 `확인 전(시뮬레이션)`으로 표시하고, 한 번 수신한 뒤 publisher가 사라지거나 timeout을 넘긴 경우에는 `카메라 정보 수신 끊김`으로 표시합니다. `sources.voice`는 간헐적인 intent 메시지 나이를 사용하지 않고 `/voice/intent` publisher endpoint 존재 여부만 나타냅니다. 따라서 Voice 정상 표시는 해당 노드의 발행 경로가 존재한다는 뜻이며 마이크·웨이크워드·STT 처리 성공을 보장하지 않습니다.

publisher가 사라진 동안에는 마지막 값을 단절 진단용으로 보존합니다. 이후 publisher가 다시 발견되거나 graph 조회 사이에 publisher endpoint GID 집합이 바뀌면 이전 endpoint·boot의 메시지와 시각을 무효화하고, 새 유효 메시지를 받을 때까지 `connection_state=waiting`, `data=null`로 반환합니다. 새 publisher의 콜백이 graph 확인보다 먼저 도착한 경우에는 그 새 값을 보존합니다.

| HTTP | `error.code` | 의미 |
|---|---|---|
| 503 | `STATE_CACHE_UNAVAILABLE` | Flask 앱에 ROS 캐시가 연결되지 않음 |
| 500 | `STATE_SNAPSHOT_FAILED` | 서버가 일관된 캐시 복사본을 만들지 못함 |

직접 응답을 확인할 때는 다음을 사용합니다.

```bash
curl -i http://127.0.0.1:4173/api/status
```

### 5단계 등록 정의 REST 형식

브라우저는 같은 origin의 `GET /api/definitions`를 페이지 시작 때 한 번 조회합니다. 서버도 기동할 때 한 번만 파일을 읽으므로 응답의 `loaded_at`은 요청 시각 `served_at`과 구분됩니다. `snapshot_kind=web_file_snapshot`, `runner_hot_reload_applied=false`는 이 값이 Runner 내부 스냅샷이나 실행 중 갱신 결과가 아님을 뜻합니다.

```json
{
  "schema_version": 1,
  "served_at": "2026-10-13T10:01:00Z",
  "poll_interval_ms": 1000,
  "status": "ok",
  "snapshot": {
    "schema_version": 1,
    "snapshot_kind": "web_file_snapshot",
    "loaded_at": "2026-10-13T10:00:00Z",
    "runner_hot_reload_applied": false,
    "sources": {
      "ontology_manifest": {
        "path": "/knowledge/robot_ontology.jsonld",
        "sha256": "..."
      },
      "tasks_dir": {
        "path": "/tasks",
        "files": ["find_item.json"]
      }
    },
    "counts": {
      "classes": 7,
      "items": 10,
      "places": 4,
      "lists": 1,
      "skills": 5,
      "tasks": 6
    },
    "definitions": {
      "classes": [],
      "items": [],
      "places": [],
      "lists": [],
      "skills": [],
      "tasks": []
    }
  }
}
```

온톨로지는 Runner와 같은 `ready2go_knowledge.core.ontology.load()`로 manifest의 classes·world·skills·places·item_grasp를 검증하며, API는 등록 정의 요약만 반환합니다. 현재 상태 `state`는 `/robot_state`의 책임이므로 정의 응답에 포함하지 않습니다. 태스크는 `WEB_TASKS_DIR` 바로 아래의 모든 `*.json`을 읽고 비어 있거나 중복된 `task_id`를 오류로 처리합니다.

| HTTP | `error.code` | 의미 |
|---|---|---|
| 503 | `DEFINITIONS_UNAVAILABLE` | manifest·태스크 경로 누락 또는 정의 형식 오류로 서버 시작 시 스냅샷을 만들지 못함 |

직접 확인할 때는 다음 명령을 사용합니다.

```bash
curl -sS http://127.0.0.1:4173/api/definitions | python3 -m json.tool
```

### 5단계 자동 검증

저장소 루트에서 다음 명령을 실행합니다. DDS 시험은 실제 rclpy publisher와 별도 executor 사이의 `/runner/status`·`/robot_state` 전달을 확인합니다.

```bash
ROS_LOG_DIR=/tmp/ready2go-issue267-ros-logs \
CYCLONEDDS_URI=file://$PWD/config/cyclonedds.local.xml \
python3 -m pytest web/tests -q
```

주요 확인 항목은 다음과 같습니다.

- 실행 시 `runner`·`robot_state`·`robot`·`camera`·`voice` source가 한 노드에서 활성화되는지
- Runner와 같은 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)` QoS로 수신하는지
- Runner 두 JSON source의 정상 객체와 깨진 JSON·객체가 아닌 JSON을 구분하는지
- 별도 ROS context와 executor 스레드에서 실제 DDS 메시지가 캐시에 도착하는지
- JointState는 위치·속도·토크 배열을 보존하지 않고 관절 이름·개수·수신 시각만 캐시하는지
- 로봇 source가 2초 무수신 뒤 stale/disconnected가 되고 sim/dev 미발행은 `확인 전(시뮬레이션)`으로 표시되는지
- 카메라는 최근 2초 CameraInfo 수신, Voice는 intent 메시지 없이 publisher 존재만 표시하는지
- sim/dev 카메라 최초 미발행은 `확인 전(시뮬레이션)`, 과거 수신 뒤 단절은 `수신 끊김`으로 구분하는지
- 이중 시작을 거절하고 반복 종료를 안전하게 처리하는지
- REST 성공 응답에 다섯 source의 버전·시각·조회 간격·캐시 복사와 `no-store` 헤더가 있는지
- `/robot_state` 네 필드의 값 누락·형식 불일치를 목업으로 대체하지 않고 `확인 전`으로 표시하는지
- PC·모바일 서랍 선택기가 위 서랍·아래 서랍 순서이고 관리자 요약·현재 상태 값과 실데이터 배지가 두 source를 반영하는지
- 캐시 미연결 503과 스냅샷 실패 500 오류 형식
- REST 실패 뒤 UI가 이전 Runner 값을 정상으로 유지하지 않고 복구 응답을 다시 반영하는지
- 공통 `ontology.load`로 실제 manifest를 읽고 등록 물품·장소·목록·스킬을 제공하는지
- `tasks/*.json`의 태스크 ID·단계 수·파일 SHA를 제공하고 중복 ID를 거절하는지
- 정의 API가 웹 파일 스냅샷 경계·원본 경로·로딩 시각·manifest SHA를 제공하는지
- 정의 로딩 실패가 상태 REST를 중단시키지 않고 정의 영역만 `확인 전`으로 전환하는지
- 빈 정의 경로 설정도 Flask 전체 종료가 아니라 정의 API 오류로 격리되는지
- 복수 등록 목록에서 배열 첫 항목이 아닌 `commute_set`만 출근 준비물로 선택하는지
- Runner `last_intent`·`last`의 정상·미존재·필드 누락·자료형 오류를 구분하고 입력 객체를 변경하지 않는지
- 같은 `run_id`의 `run` 결정만 연결하고 다른 ID·ID 누락·비실행 결정·결과 미존재를 분리하는지
- 저장소의 `contracts/examples/runner_status.json` 모든 상태 예시가 실제 브라우저 파서를 통과하는지

실제 Runner와 함께 확인할 때는 웹 서버를 실행한 상태에서 다른 터미널에서 다음을 사용합니다.

```bash
ros2 topic info /runner/status --verbose
ros2 topic echo /runner/status --once
ros2 topic info /robot_state --verbose
ros2 topic echo /robot_state --once
ros2 topic info /dsr01/joint_states --verbose
ros2 topic echo /dsr01/joint_states --once
ros2 topic info /wrist_cam/color/camera_info --verbose
ros2 topic echo /wrist_cam/color/camera_info --once
ros2 topic info /voice/intent --verbose
```

웹 브리지가 Runner·robot_state·JointState·CameraInfo 구독자로 표시되고 `/voice/intent` publisher를 발견하면 ROS graph와 발행 측을 확인할 수 있습니다. 같은 시점의 캐시 내용은 `/api/status`로 확인합니다.

[실측] 2026-10-13 5단계까지 로컬 CycloneDDS 웹 시험 `79 passed`를 확인했습니다. 실제 저장소 원본에서 클래스 7개·물품 10개·장소 4개·목록 1개·스킬 5개·태스크 6개가 로드됐고, `/api/definitions`와 관리자/대시보드 표시에서 웹 파일 스냅샷의 출처·시각·SHA와 등록 정의 구분을 확인했습니다. 상태 REST 실패·정의 성공 순서, 정의 실패의 `확인 전` 표시, 복수 목록의 `commute_set` 선택도 브라우저에서 확인했습니다. 실제 Runner 프로세스·빠른 재기동·다중 PC·실물 장비 연결 검증은 아직 수행하지 않았습니다.

[실측] 2026-10-13 카메라·Voice source 활성화 뒤 로컬 CycloneDDS 웹 시험 `89 passed`, 계약 검사 `OK`를 확인했습니다. 시험 publisher 실행 중 `/api/status`에서 카메라 `receiving`과 Voice `publisher_present=true`, 종료 뒤 카메라 2초 초과 stale/단절과 Voice `publisher_present=false`를 확인했으며 브라우저 상단 배지도 각각 정상·끊김 상태로 전환됐습니다. 이 시험은 ROS 연결 판정 검증이며 실제 카메라 영상, 마이크 입력, 웨이크워드 또는 STT 성공 검증은 아닙니다.

[실측] 2026-10-14 PR #288 재검토 뒤 실제 Flask UI를 headless Chrome으로 열어 dev·sim 카메라 최초 미발행은 `확인 전(시뮬레이션)`, dev 과거 수신 뒤 단절과 real 최초 미발행은 `카메라 정보 수신 끊김`으로 표시되는 회귀 시험 4건을 확인했습니다. 카메라·Voice를 포함한 로컬 웹·DDS 전체 시험은 `93 passed`입니다.

[실측] 2026-10-14 `last_intent`·`last` 내부 파서를 실제 headless Chrome에서 실행해 정상·미존재·필드 누락·자료형 오류와 입력 불변을 확인하고, 저장소의 Runner 상태 계약 예시 전체가 같은 파서를 통과하는지 검사했습니다. ROS 2·CycloneDDS를 포함한 로컬 웹 전체 시험은 `96 passed`입니다. 이 결과는 요청과 결과의 `run_id` 연결 또는 메인 작업 화면 전환 완료를 뜻하지 않습니다.

[실측] 같은 날 요청·결과 연결 판정을 추가한 뒤 실제 headless Chrome에서 동일 `run_id` 연결과 다른 ID·ID 누락·`hold`·`reject`·결과 미존재의 분리를 확인했습니다. ROS 2·CycloneDDS를 포함한 로컬 웹 전체 시험은 `97 passed`입니다. 메인 작업 화면의 요청·결과 표시는 아직 목업입니다.

[실측] 같은 날 B 회신 반영 뒤 로컬 CycloneDDS 웹 시험 `89 passed`와 계약 검사 `OK`를 확인했습니다. dev 프로필에서 JointState 발행 전 `확인 전(시뮬레이션)`, 발행 뒤 `관절 상태 수신` 배지가 표시됐습니다. PC2 실물의 실제 QoS·100 Hz 주기와 제어기 LAN 분리 동작은 담당 실측 회신 뒤 확인합니다.

## 7. URL 데모 시나리오

```text
http://localhost:4173/?scenario=long
http://localhost:4173/?scenario=empty
http://localhost:4173/?scenario=error
```

- `long`: 긴 등록명·작업 문장의 줄바꿈을 확인합니다.
- `empty`: 빈 등록 물품과 빈 준비물 레이아웃을 확인합니다.
- `error`: `목업 오류 시나리오` 안내 아래 연결 확인 전, 상태 수신 실패, 오류, 데이터 없음을 확인합니다. 실제 장치 오류가 아닙니다.

각 URL 뒤에 `#admin`을 붙이면 같은 시나리오의 읽기 전용 검토 화면을 확인할 수 있습니다.

## 8. Git과 PR

공통 Git·PR 정책은 저장소 루트의 [`AGENTS.md`](../AGENTS.md)를 따릅니다.
