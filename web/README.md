# Ready2Go 웹 대시보드

> [문서] 화면은 이슈 [#112](https://github.com/Jik-Kim/ready2go/issues/112)의 PC·휴대폰 검토 목업을 기반으로 합니다. 이슈 [#267](https://github.com/Jik-Kim/ready2go/issues/267)의 1~5단계인 Flask 정적 제공, `/runner/status`·`/robot_state` 수신·잠금 캐시, 상태 REST와 약 1초 조회, 등록 온톨로지·태스크·스킬 정의의 읽기 전용 파일 스냅샷 연결을 구현했습니다. 기본 화면은 확인 전으로 시작하며 최근 요청의 해석·접수 결정과 같은 실행으로 연결된 결과를 표시합니다. 현재 작업은 Runner의 phase·task_id·current_step만 표시합니다. 저장소를 설정하면 최근 요청에 연결된 종료 기록의 물품 순서·단계·전달 결과를 별도로 표시합니다. 실행 중 전체 순서·현재 child 연결·작업 장소·목적지는 확인 전입니다.

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
| `assets/items/*.svg` | 물품 식별용 그림 10종. `app.js`의 ID 매핑과 Flask allowlist로 제공 | 물품 등록·실제 위치·전달 성공을 판정하지 않습니다. |
| `index.html` | 사용자 대시보드·읽기 전용 검토 화면의 HTML 구조와 CSS·JavaScript 진입점 | 화면 구조는 유지하고 `demo-data.js` 로딩을 데이터 어댑터 진입점으로 교체합니다. |
| `styles.css` | 흰색·남색·청록색 디자인, PC·모바일 배치, 서랍 모양, PC 가로·모바일 세로 단계 | 데이터 연결과 무관합니다. 상태 종류가 추가될 때 표시 스타일만 보완합니다. |
| `demo-data.js` | PC·모바일 공통 확인 전 초기값과 명시적 `preview`·`long`·`empty`·`error` 예시 | 일반 접속·알 수 없는 시나리오는 예시 실행을 사용하지 않습니다. |
| `status-api.js` | `/api/status`를 중첩 없이 약 1초마다 조회하고 `/api/definitions`를 시작 때 한 번 읽으며 `vision_overlay` 메타데이터를 검증 | Runner 연결·기억 상태, 최신 촬영 메타데이터와 웹 파일 정의 스냅샷을 서로 다른 시점의 데이터로 전달합니다. |
| `runner-status-model.js` | `/runner/status.last_intent`와 `last`를 화면 표시 전 `valid`·`absent`·`invalid` 내부 모델로 검증·복사하고 실행 연결을 판정 | `decision=run`이고 비어 있지 않은 `run_id`·`task_id`가 모두 같을 때만 `linked`로 묶고 `commandView()`가 명령 표시 모델로 변환합니다. |
| `app.js` | 상태 렌더링, 서랍 조회, 최근 촬영 revision별 JPEG 표시, 상세·대화상자·검토 탭 전환과 포커스 복귀 | 렌더링은 재사용하고 데이터 수신 뒤 `renderAll()` 또는 필요한 렌더 함수를 호출합니다. ROS 2나 DB에 직접 연결하지 않습니다. |
| `README.md` | 현재 구현, 실행·접속·시나리오, 실제 연동 경계를 설명 | 연결 경로가 구현된 뒤 실제 실행법과 검증 결과를 갱신합니다. |
| `ready2go_web/server.py` | 기존 정적 파일을 allowlist로 제공하고 ROS 공유 캐시의 상태와 최신 촬영 JPEG를 REST로 반환 | `GET /api/status`의 `vision_overlay`는 JPEG를 제외한 메타데이터이며 사진은 `GET /api/vision/overlay.jpg?cache_id=C&revision=N`으로 조회합니다. 현재 캐시 ID나 revision과 다르면 409를 반환합니다. |
| `ready2go_web/nodes/dashboard_bridge.py` | 단일 rclpy 노드로 선택한 ROS source를 구독·관찰 | 4단계 실행에서는 `/runner/status`와 `/robot_state`를 활성화합니다. |
| `ready2go_web/core/state_cache.py` | ROS 콜백과 Flask 요청 사이의 최신 상태를 잠금으로 보호 | REST에는 깊은 복사 스냅샷만 전달합니다. |
| `ready2go_web/core/definition_catalog.py` | 공통 `ontology.load`와 `tasks/*.json`으로 등록 정의 스냅샷 생성 | Runner hot reload가 아닌 웹 시작 시 파일 조회임을 출처·시각·manifest SHA와 함께 기록합니다. |
| `ready2go_web/runtime.py` | 전용 ROS context와 별도 executor 스레드의 시작·종료를 관리 | Flask 요청 스레드와 ROS 콜백을 분리합니다. |

```text
index.html
 ├─ styles.css      화면 모양과 반응형 배치
 ├─ demo-data.js    확인 전 초기값·명시적 미리보기 예시
 ├─ status-api.js   REST 상태 조회와 재시도
 ├─ runner-status-model.js  Runner 요청·결과 형식 검증
 └─ app.js          같은 상태를 PC·모바일 요소에 표시
     └─ assets/items/*.svg  물품 ID에 매핑된 그림 10종
```

[문서] 물품 그림은 `app.js`의 `itemImagePaths`가 온톨로지 물품 ID를 고정 SVG 경로에 연결합니다. 목업의 `car-key` 별칭은 `car_key`로 정규화하며, 스패너 ID는 `toy_wrench`입니다. 매핑이 없거나 이미지 로드가 실패하면 기존 기호로 표시합니다. 서랍 표·준비물·모바일 서랍 목록·현재 작업이 공통 `makeItemVisual()`을 사용하며 Flask는 `PUBLIC_ASSETS`에 명시한 파일만 제공합니다.

[문서] 관리자 요약 3종·상태 항목 5종은 `adminIconPaths`의 고정 path로 생성하는 인라인 SVG이며 물품 이미지 파일과 구분합니다. 총 18종 중 현재 작업 제목은 기존 태스크 아이콘, 현재 물품은 기존 지우개 그림을 재사용합니다.

[문서] 목업 요청·준비물·작업 진행은 차 키·지우개·시계 시나리오로 맞추며, `empty`·`error`는 빈 목록·오류 표시를 확인하는 별도 시나리오입니다. 기본 화면의 준비물은 정의 API 수신 후 실제 `commute_set`으로 교체되므로 현재 작업의 실행 대상이나 결과를 나타내지 않습니다. 서버 시작 시 읽는 실제 정의 파일은 이 목업 변경의 대상이 아닙니다.

`app.js`는 `window.ROKEY_DEMO_DATA` 한 객체를 읽으므로 PC와 휴대폰이 서로 다른 샘플 상태를 만들지 않습니다. 선택한 조회 서랍인 `selectedDrawerId`와 실제 작업 위치인 `task.workDrawerId`도 별도로 유지합니다.

## 3. 화면 데이터와 미리보기

### 표시 데이터

| 화면 | 화면 모델 경로 |
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

[문서] 1단계 정적 UI, 2단계 `/runner/status` 수신·캐시, 3단계 상태 REST·약 1초 조회, 4단계 `/robot_state` 수신·화면 반영, 5단계 등록 온톨로지·태스크·스킬 정의 로딩이 구현됐습니다. 현재 화면에는 Runner 연결·기억 상태와 웹이 시작할 때 읽은 정의 파일 스냅샷이 각각의 출처로 나타납니다. 전체 MongoDB/JSONL 실행 기록 검색, 작업 중단·재개·초기화, 실시간 계획 근거, STT 원문과 확정되지 않은 음성·로봇 연결 판정은 제외합니다.

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
/vision/inspect_overlay → OverlayCache ┬→ GET /api/status의 vision_overlay 메타데이터
                                      └→ GET /api/vision/overlay.jpg?cache_id=C&revision=N → 최근 촬영 UI
온톨로지 manifest ─ common ontology.load ─┐
tasks/*.json ─────────────────────────────┼→ 시작 시 정의 스냅샷 → GET /api/definitions → 등록 정의 UI
```

[문서] 브라우저는 ROS 2·온톨로지 파일·MongoDB에 직접 연결하지 않습니다. 현재 Flask 프로세스가 별도 `SingleThreadedExecutor`에서 단일 `DashboardBridge`를 실행하며 `/runner/status`와 `/robot_state`를 활성화합니다. 두 `std_msgs/msg/String`의 JSON 객체를 source별 캐시에 저장하고 publisher 존재, 메시지 수신, 파싱 오류를 구분합니다. 브라우저는 REST 응답이 끝난 뒤 다음 조회를 예약하므로 느린 요청이 서로 겹치지 않습니다.

[코드] 최근 촬영 영역은 `/api/status.vision_overlay`의 `cache_id`와 `revision`을 한 쌍으로 비교하고 새 식별자를 확인했을 때만 같은 식별자의 JPEG를 요청합니다. 새 Flask 프로세스에서 revision이 다시 1이 되어도 `cache_id`가 달라 이전 사진을 재사용하지 않습니다. 촬영 시각은 KST, 경과 시간은 서버 메타데이터 기준으로 표시하며, 상태와 JPEG 사이에 새 촬영이나 서버 교체가 들어와 HTTP 409가 발생하면 같은 식별자를 반복 요청하지 않고 다음 상태 polling에서 다시 확인합니다. 사진 없음·오래된 사진·확인 불가를 구분하되, 사진 상태는 `/wrist_cam/color/camera_info` 기반 상단 카메라 배지 판정에 사용하지 않습니다.

[코드] JPEG 형식·`frame_id`·메시지 형식이 계약과 달라 사진을 거부하면 `vision_overlay`의 누적 횟수, 마지막 사유·시각·frame ID로 진단합니다. 사진이 한 장도 없고 마지막 사유가 `frame_id_mismatch`이면 최근 촬영 영역에 `촬영 사진 확인 전 · 카메라 프레임 불일치`를 표시하며, 기존 정상 사진이 있으면 그 사진을 지우지 않습니다.

[운영 제한] 최신 사진은 촬영 stamp 순서로 정렬하므로 이전 stamp는 거부하고, 같은 stamp의 Vision 재발행은 수정된 JPEG로 보고 새 revision으로 교체합니다. 시뮬레이터 재시작으로 sim time이 이전 값으로 돌아가면 현재 웹 기동의 캐시보다 stamp가 작아 새 사진이 과거 촬영으로 거부될 수 있습니다. 이 경우 웹 Runtime을 재기동해 사진·거부 진단 캐시를 초기화한 뒤 다시 수신합니다. 실물의 UTC epoch 촬영 시각에는 이 sim time 제한이 적용되지 않습니다.

실제 연결 시에는 다음 순서로 교체할 수 있습니다.

1. Flask가 공유 `StateCache`의 스냅샷을 읽기 전용 REST로 반환합니다.
2. 기본 화면은 약 1초마다 API를 조회하고 Runner 연결과 기억 상태를 변환합니다.
3. `preview`·`long`·`empty`·`error` 시나리오 URL은 고정 목업 검토를 위해 polling하지 않습니다.
4. `/api/definitions`는 페이지 시작 때 한 번만 읽고 상태 polling에 섞지 않습니다.
5. 정의 파일 변경은 현재 Runner나 이미 실행 중인 웹에 자동 적용되지 않으며, 두 프로세스를 각각 재기동해야 새 스냅샷을 읽습니다.

### C 확인값과 후속 단계 입력

[문서] 이슈 [#267 C 회신](https://github.com/Jik-Kim/ready2go/issues/267#issuecomment-6140239576)과 병합된 W4 구현을 기준으로 현재 Runner 동작과 아직 구현되지 않은 제안을 구분합니다.

- `/runner/status`와 `/robot_state`는 내용을 0.5초마다 비교하되 **내용이 달라졌을 때만** 발행합니다. 둘 다 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)`이며, 긴 유휴 시간에 새 메시지가 없어도 publisher가 존재하면 연결된 것으로 판단합니다.
- 현재 `/runner/status`에는 `phase`, 실행 중의 `task_id`·`current_step`, 잠금 상태의 `halt_code`, `halt`, `last`, `last_intent`, `log_store`, `state_reset_at`, `boot_id`가 포함되고 실제 발행에는 `seq`·`stamp`가 붙습니다. 재개 대기 중에는 `halt.resume`도 제공됩니다. REST는 이 원본을 그대로 전달하며 화면은 `boot_id`만 GID를 보조하는 기동 경계로 사용합니다.
- `phase`는 `idle`·`running`·`halted`이며 화면에는 각각 `대기`·`실행 중`·`정지(잠김)`으로 표시합니다. 계약에 없는 값은 `확인 전`으로 표시합니다. `task_id`와 `current_step`은 실행 중에만 있으며, `halt_code`는 잠금 상태에서만 있습니다. `current_step`은 확장 또는 fallback 단계 ID일 수 있고 `achieve_goal`의 `plan_*`은 태스크 파일에 없으므로 화면은 원본 ID를 그대로 표시합니다.
- 현재 실행과 최근 요청을 직접 연결하는 최상위 `run_id`는 없습니다. 따라서 실행 중인 `task_id`와 `current_step`을 최근 요청·결과라고 단정하지 않습니다. 아래의 `last_intent`와 `last` 사이 결합은 두 레코드가 제공하는 ID만 검사하는 별도 판정입니다.
- 화면 연결에 앞서 `last_intent`의 `intent`·`targets`·`decision`·`reason`·`task_id`·`request_id`·`run_id`와 `last`의 `task_id`·`run_id`·`overall_status`·`error_code`·`failed_step`을 독립적으로 검사합니다. `null`은 아직 기록이 없는 상태로, 키 누락·잘못된 자료형은 형식 오류로 구분하며 형식 오류의 정상 필드 일부를 화면에 재사용하지 않습니다. 이 파싱은 두 레코드를 같은 실행으로 연결하거나 결과 문구를 정하는 동작이 아닙니다.
- 파싱 뒤에는 `last_intent.decision=run`이고 요청·결과의 비어 있지 않은 `run_id`와 `task_id`가 모두 같을 때만 `linked` 결합 모델을 만듭니다. 결과 상태는 Runner의 `COMPLETED`·`FAILED`·`ABORTED`·`SUSPENDED`만 허용합니다. 다른 ID, 수락 요청의 ID 누락, 계약 밖 결과 상태, `hold`·`reject`·`cancel`·`status` 같은 비실행 결정, 한쪽 기록 없음과 형식 오류는 연결하지 않고 각각의 이유 코드를 보존합니다. 메인 화면과 모바일 명령 상세는 이 판정의 `commandView()`를 함께 사용합니다. `recover`·`resume`·`end`·`registered`·`closed`도 접수 결정으로 구분하되 실행 성공으로 해석하지 않습니다. 인텐트와 사유는 각각 `인텐트:`·`사유 코드:`로 원본임을 표시합니다. 미지의 결정은 접수 상태 확인 전으로 남깁니다.
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
- **실행 기록**: 후속 연결 예정이며 관리자 탭의 전체 기록 검색은 미연결입니다. 최근 요청의 종료 상세 단건 조회는 작업 카드에서 별도로 제공합니다.

실제 운영 전에 서버 인증과 접근 제어를 반드시 연결해야 합니다. 일반 사용자 로그인은 고려 단계이며 이 목업의 구현 범위가 아닙니다.

## 6. 실행과 접속

루트 [`requirements.txt`](../requirements.txt)를 설치한 프로젝트 가상환경과 ROS 2 환경을 준비한 뒤 **새 터미널에서 저장소 루트부터** 다음을 실행합니다. `ros2_ws/install/setup.bash`를 함께 읽어야 `ready2go_knowledge` 등 workspace 패키지를 찾을 수 있습니다. 파일이 없다면 먼저 루트 README의 빌드 절차를 실행합니다. 아래 Domain 70·CycloneDDS 설정은 Runner와 웹 브리지가 같은 ROS graph를 사용하기 위한 필수 실행 환경입니다.

```bash
cd /home/rokey/ready2go
source /opt/ros/jazzy/setup.bash
[ -f .venvs/project/bin/activate ] && source .venvs/project/bin/activate
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

이 명령은 Flask 정적 서버, `/runner/status`·`/robot_state`·`/dsr01/joint_states`·`/wrist_cam/color/camera_info`·`/vision/inspect_overlay` 구독과 `/voice/intent` publisher 관찰, 상태·정의·최근 촬영 REST를 같은 프로세스에서 시작합니다. 같은 PC에서는 `http://127.0.0.1:4173/`로 접속하고 다음 명령으로 REST 기동도 확인합니다. 종료할 때 `Ctrl+C`를 누르면 executor, 노드, ROS context도 함께 정리됩니다. 최근 요청과 연결된 실행 결과를 표시하며, 현재 작업은 수신한 실행 상태·현재 단계만 표시하고 물품별 전달 결과는 확인 전입니다.

```bash
curl -sS http://127.0.0.1:4173/api/status | python3 -m json.tool
```

휴대폰이나 다른 PC에서는 서버 PC와 같은 네트워크에 연결한 뒤 서버 PC에서 주소를 확인합니다. `config/cyclonedds.local.xml`은 DDS를 loopback으로 제한하므로 Runner와 웹 브리지는 같은 PC2에서 실행해야 합니다. 외부 브라우저 접속이 필요할 때만 `WEB_HOST=0.0.0.0`으로 실행하고, 실제 포트(`ss -ltnp`), PC 방화벽과 Wi-Fi AP의 단말 간 통신 차단 여부를 현장에서 확인합니다.

```bash
# 위와 같은 환경 설정을 마친 서버 터미널에서 Flask를 모든 인터페이스에 바인딩합니다.
cd /home/rokey/ready2go/web
WEB_HOST=0.0.0.0 WEB_PORT=4173 python3 -m ready2go_web

# 새 터미널에서 서버 PC의 LAN 주소와 4173 listen 상태를 확인합니다.
hostname -I
ss -ltnp | grep ':4173'
```

`0.0.0.0`은 서버의 수신 주소이므로 브라우저 주소로 사용하지 않습니다. Docker용 `172.17.x.x`를 제외한 와이파이·유선 LAN 주소를 골라 다른 PC나 휴대폰에서 `http://서버_PC_IP:4173/`으로 접속합니다. 예를 들어 `hostname -I`의 LAN 주소가 `172.24.1.176`이면 접속 주소는 `http://172.24.1.176:4173/`입니다. 모바일 전용 URL은 없으며 화면 폭에 따라 자동 전환됩니다. 접속되지 않으면 서버 실행 여부, 동일 네트워크, 방문자망의 장치 간 차단, TCP 4173 방화벽을 확인합니다. Flask 내장 서버는 개발·시연용이며 운영 배포 서버로 사용하지 않습니다.

<a id="pc2-overlay-check"></a>
### PC2 실물 연결 확인 — 최근 촬영 UI (2026-10-15)

[실측] 학원 공용 PC2(MSI)에서 A 김병직이 직접 실행하고 D 김민준이 화면을 함께 확인했습니다. 코드는 PC2 main `d28fd55`(#368 웹·#370 비전 포함)이며, PC1은 HTTP로만 접속했습니다(DDS는 PC2 `local` 그대로). 비전 쪽 절차·회차 기록은 [practice/A/2026-10-15_practice.md](../practice/A/2026-10-15_practice.md)에 있습니다.

| 확인 항목 | 결과 |
| :--- | :--- |
| 카메라 배지 (`/wrist_cam/color/camera_info`) | 정상 수신, `frame_id` `wrist_cam_color_optical_frame` |
| 촬영 한 장 뒤 `/api/status.vision_overlay` | `image_available: true`, `frame_id: wrist_cam_color_optical_frame`, `revision: 1`, `rejected_count: 0` |
| PC1 → `GET /api/vision/overlay.jpg` | HTTP `200`, 136,544 B JPEG |
| PC1 브라우저 작업 상세 '최근 촬영' 칸 | 분할 사진과 KST 촬영 시각 표시 |
| 실제 회차 S2 (run `0d8e38`, 129 s, ✅ 성공) | 비전 호출 5번 모두 수신 → `revision: 6`, `rejected_count: 0`, 촬영마다 사진 실시간 갱신 |

확인 순서(PC2 저장소 루트, 로봇이 멈춘 상태에서):

```bash
bash tools/dev/pc2_up.sh --p2                       # 터미널 ①
# 터미널 ③: 비전 오버레이 시작 줄과 실제 카메라 frame_id
docker compose --profile real --profile pc2 logs vision-node | grep "inspect_region 시작" | tail -1 | grep -o "오버레이 [^)]*"
docker compose exec ros2-core /entrypoint.sh ros2 topic echo --once --field header.frame_id /wrist_cam/color/camera_info
# 터미널 ④: 위 6절 환경 설정 뒤 WEB_HOST=0.0.0.0 WEB_PORT=4173 python3 -m ready2go_web
# 터미널 ③: 탑뷰 자세에서 촬영만 한 번(로봇 이동 없음) → 웹 수신 확인
docker compose exec ros2-core /entrypoint.sh ros2 service call /vision/inspect_region ready2go_interfaces/srv/InspectRegion "{region: drawer_top, search_target: ''}"
curl -sS http://127.0.0.1:4173/api/status | python3 -c 'import json,sys; v=json.load(sys.stdin)["vision_overlay"]; print({k: v.get(k) for k in ("image_available","captured_at","frame_id","revision","rejected_count","last_rejection_reason")})'
# 다른 PC: curl -sS -o /tmp/overlay.jpg -w "%{http_code}\n" http://<PC2 와이파이 IP>:4173/api/vision/overlay.jpg
```

학원 공용 MSI에서 처음 실행할 때 확인한 차이입니다.

- 저장소 위치는 `/home/rokey/ready2go`가 아니라 `~/ready2go`입니다. 위 6절 명령의 첫 `cd`를 바꿔 실행합니다.
- `hostname -I`의 `192.168.1.x`는 로봇·그리퍼 쪽 유선망이라 다른 PC에서 열리지 않습니다. 와이파이 주소(`172.24.x.x`)로 접속합니다.
- `.venvs/project`에 Flask가 없으면 `python3 -m pip install -r web/requirements.txt`로 설치합니다.
- `ros2_ws/install`이 컨테이너에서 빌드된 것이면 호스트 `colcon`이 경로 불일치로 실패합니다. 기존 폴더는 두고 `--build-base ~/ready2go_host_ws/build --install-base ~/ready2go_host_ws/install --packages-up-to ready2go_knowledge`로 따로 빌드한 뒤 `source ~/ready2go_host_ws/install/setup.bash`를 사용합니다. 저장소 `logs/`가 root 소유일 수 있어 `ROS_LOG_DIR="$HOME/ready2go_pc2_logs/ros"`로 실행했습니다.

미확인: PC1↔PC2 multi DDS, 휴대폰 접속, S1·S3 회차 중 표시.

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

[실측] 같은 날 요청·결과 연결 판정을 추가한 뒤 실제 headless Chrome에서 동일 `run_id` 연결과 다른 ID·ID 누락·`hold`·`reject`·결과 미존재의 분리를 확인했습니다. ROS 2·CycloneDDS를 포함한 로컬 웹 전체 시험은 `97 passed`입니다. 이는 당시 내부 모델 검증 결과이며, 이후 추가된 명령 화면 연결의 검증 결과와 구분합니다.

[실측] 같은 날 B 회신 반영 뒤 로컬 CycloneDDS 웹 시험 `89 passed`와 계약 검사 `OK`를 확인했습니다. dev 프로필에서 JointState 발행 전 `확인 전(시뮬레이션)`, 발행 뒤 `관절 상태 수신` 배지가 표시됐습니다. PC2 실물의 실제 QoS·100 Hz 주기와 제어기 LAN 분리 동작은 담당 실측 회신 뒤 확인합니다.

### 기동·응답 순서와 현재 작업 표시

[문서] `boot_id`·안전한 정수 `seq`가 없는 상태는 확인 전으로 표시합니다. 같은 기동의 낮은 seq와 이미 떠난 기동의 응답은 폐기하며, 같은 seq의 동일 상태는 반복 REST 조회로 허용합니다. 같은 seq인데 내용이 다르면 형식 불일치로 처리합니다. 단절 시 표시값은 지우되 순서 경계는 보존합니다. REST 종료 후 늦은 응답은 반영하지 않습니다.

[문서] 기동 변경 시 이전 명령·작업·선택 상세를 비웁니다. `/robot_state`는 기동 ID가 없으므로 재기동 당시의 캐시는 확인 전이며 이후 새 수신값만 Runner 기억 상태로 표시합니다. 이 별도 토픽의 새 수신만으로 현재 관측 또는 동일 기동 소속을 증명하지는 않습니다. 실제 작업 위치에는 사용하지 않습니다.

[문서] 현재 작업의 제목과 단일 현재 단계는 `/runner/status`에서만 가져오며, 조회 서랍·선택 물품이나 최근 요청의 targets에서 만들지 않습니다. 앞 단계의 성공·전달 완료를 추정하지 않습니다. 상세 조회는 최근 요청과 연결된 종료 run에만 허용하고 기동/run/세대 토큰을 실제 응답 반영 경로에서 검사합니다. 현재 상위/child run 식별과 진행 중 순서·결과 갱신은 아직 연결하지 않았습니다.

## 7. URL 데모 시나리오

```text
http://localhost:4173/
http://localhost:4173/?scenario=preview
http://localhost:4173/?scenario=long
http://localhost:4173/?scenario=empty
http://localhost:4173/?scenario=error
```

- 기본 URL·알 수 없는 시나리오: 확인 전으로 시작하고 실제 상태 API를 조회합니다. API 실패 시 예시 성공 상태로 대체하지 않습니다.
- `preview`: 물품 선택·단계·결과를 확인하는 명시적 예시 데이터입니다. 실제 실행 결과가 아닙니다.
- `long`: 긴 등록명·작업 문장의 줄바꿈을 확인합니다.
- `empty`: 빈 등록 물품과 빈 준비물 레이아웃을 확인합니다.
- `error`: `목업 오류 시나리오` 안내 아래 연결 확인 전, 상태 수신 실패, 오류, 데이터 없음을 확인합니다. 실제 장치 오류가 아닙니다.

각 URL 뒤에 `#admin`을 붙이면 같은 시나리오의 읽기 전용 검토 화면을 확인할 수 있습니다.

## 8. Git과 PR

공통 Git·PR 정책은 저장소 루트의 [`AGENTS.md`](../AGENTS.md)를 따릅니다.


### 읽기 전용 종료 기록 상세

[문서] `GET /api/execution-detail/<run_id>?boot_id=...&seq=...`는 현재 상태 캐시에서 최근 요청과 연결된 종료 run만 허용합니다. 저장소 조회 전후 기동·seq·요청 연결을 확인합니다. 잘못된 ID/기동/seq 쿼리는 400, 상태 전환은 409, 종료 기록 미수신은 404, 형식 오류는 422, 저장소 미설정·조회 실패는 503입니다. 임의 실행 기록 검색이나 쓰기 API는 제공하지 않습니다.

웹 프로세스 시작 전에 아래 저장소를 하나 또는 둘 다 명시합니다. 미설정이면 기존 상태 화면은 유지하고 상세는 확인 전입니다.

- JSONL: `WEB_RUN_JSONL_DIR`에 Runner 기록 디렉터리를 지정합니다. 해당 run 파일과 상위 종료 기록이 참조한 child 파일만 읽습니다.
- MongoDB: `WEB_RUN_MONGO_URI`, `WEB_RUN_MONGO_DB`, `WEB_RUN_MONGO_TIMEOUT_MS`를 모두 지정합니다. 웹 계정에는 조회 권한만 부여합니다. 어댑터는 find만 수행하며 인덱스·문서 쓰기를 하지 않습니다. Mongo 사용 시에만 `pip install -r web/requirements-mongo.txt`로 추가 의존성을 설치합니다.

[문서·코드 확인] Runner 상위 시작 기록에는 `inputs.semantic`이 있고 단계 로그는 단계 종료 시 저장됩니다. 물품 그룹의 확정 순서·제외 항목·전달 결과인 상위 `items`와 계획 구간 `segments`는 종료 기록에 있습니다. D는 items 순서를 보존하고 `DELIVERED`만 집계하며 EXCLUDED는 실행 대상 분모에서 제외합니다. `semantic.items` 순서와 클래스 경로를 재계산하지 않습니다. 물품의 `semantic.evidence`가 있을 때만 근거로 표시합니다. `items.drawer`는 기록 당시 대상 서랍이며 현재 작업 위치로 사용하지 않습니다.

상세에는 “최근 요청 종료 기록”과 run ID를 표시합니다. 선택 물품의 종료 단계·결과가 바뀌어도 현재 실행 제목·위치는 바뀌지 않습니다. 두 저장소를 함께 설정하면 각 run마다 JSONL 기록을 먼저 찾고 없으면 Mongo를 조회합니다. 부모와 child가 다른 저장소에 있어도 연결하며, 한 run의 단계들을 서로 다른 저장소에서 섞지는 않습니다. 두 곳 모두 없는 child는 단계 미수신입니다. 누락 단계를 성공으로 채우지 않습니다. 실제 Runner/DB·PC2 통합 연결은 별도 검증이 필요합니다.


[문서] 같은 기동/run/요청/종료 상태의 상세 조회가 성공하면 화면 수명 동안 그 스냅샷을 재사용합니다. 미수신/조회 실패는 같은 key에서 최대 3회 시도하며, 재기동·요청 전환·상태 단절로 해당 key가 무효화되면 초기화합니다. 성공 스냅샷의 누락 child를 자동으로 계속 조회하지는 않습니다.

[문서] JSONL 파일명은 Runner `JsonlLogStore._path`, Mongo 조회는 `MongoLogStore.read_run`을 재사용합니다. ROS 실행 환경에는 `ready2go_runner`가 설치되어 있어야 하며 소스 환경에서는 `ros2_ws/src/ready2go_runner`를 Python import 경로에 추가합니다. JSONL은 C처럼 파싱 불가능한 잘린 줄을 건너뛰되 완전한 줄의 잘못된 구조·식별자는 422로 구분합니다. 저장소 오구성은 웹을 종료하지 않고 서버 로그에 예외 종류와 WEB_RUN_* 점검 안내를 남깁니다. URI·암호·외부 예외 전문은 기록하지 않습니다.

[문서·실측] 상위/child/단계/semantic의 저장 시점, 기존 PC2 기록의 한계와 모의 JSONL 확인 결과는 [실행 기록 저장 시점 확인](execution-record-timing.md)을 참조합니다.
