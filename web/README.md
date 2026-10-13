# ROKEY 웹 대시보드

> [문서] 화면은 이슈 [#112](https://github.com/Jik-Kim/ready2go/issues/112)의 PC·휴대폰 검토 목업을 유지합니다. 이슈 [#267](https://github.com/Jik-Kim/ready2go/issues/267)의 2단계까지 Flask 정적 파일 제공과 `/runner/status` rclpy 수신·잠금 캐시가 구현됐습니다. REST 응답과 화면 데이터 변환은 아직 연결되지 않아 브라우저 표시값은 계속 `목업 데이터`입니다.

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
| `app.js` | 상태 렌더링, 서랍 조회, 상세·대화상자·검토 탭 전환과 포커스 복귀 | 렌더링은 재사용하고 데이터 수신 뒤 `renderAll()` 또는 필요한 렌더 함수를 호출합니다. ROS 2나 DB에 직접 연결하지 않습니다. |
| `README.md` | 현재 구현, 실행·접속·시나리오, 실제 연동 경계를 설명 | 연결 경로가 구현된 뒤 실제 실행법과 검증 결과를 갱신합니다. |
| `ready2go_web/server.py` | 기존 정적 파일을 allowlist로 제공하고 ROS 공유 캐시를 Flask 앱에 보관 | 다음 단계에서 읽기 전용 REST 경로를 추가합니다. |
| `ready2go_web/nodes/dashboard_bridge.py` | 단일 rclpy 노드로 선택한 ROS source를 구독·관찰 | 2단계 실행에서는 `/runner/status`만 활성화합니다. |
| `ready2go_web/core/state_cache.py` | ROS 콜백과 Flask 요청 사이의 최신 상태를 잠금으로 보호 | REST에는 깊은 복사 스냅샷만 전달합니다. |
| `ready2go_web/runtime.py` | 전용 ROS context와 별도 executor 스레드의 시작·종료를 관리 | Flask 요청 스레드와 ROS 콜백을 분리합니다. |

```text
index.html
 ├─ styles.css      화면 모양과 반응형 배치
 ├─ demo-data.js    목업 전용 원본 상태
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
| 온톨로지 목업 | `adminReview.ontology` |
| 후속 연결 안내 | `adminReview.plan.message`, `adminReview.history.message` |

서랍 선택은 등록 물품 조회만 바꾸며 로봇 명령을 만들지 않습니다. 작업 상세, 모바일 명령 상세·서랍 보기, 검토 화면과 탭 전환도 브라우저 안의 표시만 바꿉니다.

### 녹화 우선 연결 범위

[문서] 최신 PM 검토가 정한 우선순위에 맞춰 이후 연결 순서를 다음으로 제한해 표시합니다.

1. 정적 UI
2. `/runner/status`
3. `/robot_state`
4. 온톨로지 원본 읽기
5. PC·휴대폰의 동일 상태 표시

[문서] 1단계 정적 UI 제공과 2단계 `/runner/status` 수신·캐시는 구현됐습니다. REST와 화면 반영은 다음 단계이므로 현재 화면에는 실제 수신값이 나타나지 않습니다. MongoDB/JSONL 실행 기록, 작업 중단·재개·초기화, 실시간 계획 근거, STT 원문, 확정되지 않은 음성·로봇 연결 판정은 녹화 우선 연결 범위에서 제외합니다.

### 표시를 바꾼 이유

- **STT 원문 미표시**: 기존 인텐트의 `source.stt_text`는 Runner에서 `/runner/status.last_intent.stt_text`로 제공됩니다. 다만 이번 정적 목업·녹화 범위에서는 표시하지 않으며, 실제 연결 시 웹 어댑터와 값 누락 처리를 함께 구현해야 합니다.
- **작업 중단 숨김**: 실제 중단 요청 경로가 이번 범위에 없으므로 버튼과 로컬 `중단 완료` 동작을 제거했습니다.
- **연결 상태 `확인 전`**: 웨이크워드·마이크와 로봇 드라이버의 판정 근거가 확정되지 않았습니다. 카메라는 이후 `/wrist_cam/color/camera_info`, Runner는 `/runner/status` 수신 여부로 판단할 예정이므로 목업 기본값을 각각 `확인 전`과 `상태 수신 대기`로 둡니다.
- **성공 상태의 의미**: 목업의 명령 접수·전달 완료·관측 확인 표시는 시각 검토용 예시입니다. 화면 상단 안내가 실제 성공 결과가 아님을 명시합니다.

## 4. 현재 연결 경계

```text
/runner/status → DashboardBridge → StateCache ─┐
                                               ├→ 후속 REST·화면 데이터 어댑터
/robot_state·온톨로지 원본 ─── 후속 단계 ─────┘
```

[문서] 브라우저는 ROS 2·온톨로지 파일·MongoDB에 직접 연결하지 않습니다. 현재 Flask 프로세스가 별도 `SingleThreadedExecutor`에서 단일 `DashboardBridge`를 실행하며, 2단계에서는 `/runner/status`만 활성화합니다. `std_msgs/msg/String`의 JSON 객체를 캐시에 저장하고 publisher 존재, 메시지 수신, 파싱 오류를 구분합니다.

실제 연결 시에는 다음 순서로 교체할 수 있습니다.

1. Flask가 공유 `StateCache`의 스냅샷을 반환하는 읽기 전용 REST API를 구현합니다.
2. 브라우저가 약 1초마다 API를 조회하고 화면 모델로 변환합니다.
3. 후속 단계에서 `/robot_state`와 온톨로지 원본을 순서대로 활성화합니다.
4. 미수신, 통신 중단, JSON 오류를 화면 상태로 구분합니다.

`TODO(D)`: API 서버/ROS 브리지 담당, API URL·응답 계약, 상태 갱신과 재접속 정책을 합의한 뒤 어댑터를 구현합니다. 계약을 바꿔야 하면 저장소 루트 [`AGENTS.md`](../AGENTS.md)의 승인 절차를 따릅니다.

## 5. 읽기 전용 검토 화면

상단 `검토 화면` 버튼은 인증 없이 같은 정적 페이지의 `#admin` 화면으로 이동합니다. 관리자 인증, 권한 획득, 서버 API 접근 제어가 구현된 것이 아닙니다.

- **현재 상태**: `/runner/status`와 `/robot_state` 우선 연결 예정이며 지금은 출처가 표시된 목업 데이터입니다.
- **온톨로지**: 서버가 읽은 원본 정의 연결을 우선 검토하며 지금은 목업 데이터입니다.
- **계획 근거**: 후속 연결 예정이며 현재 제공 경로가 확정되지 않았다는 안내만 표시합니다.
- **실행 기록**: 후속 연결 예정이며 실제 MongoDB/JSONL 조회가 연결되지 않았다는 안내만 표시합니다.

실제 운영 전에 서버 인증과 접근 제어를 반드시 연결해야 합니다. 일반 사용자 로그인은 고려 단계이며 이 목업의 구현 범위가 아닙니다.

## 6. 실행과 접속

ROS 2 환경을 source한 뒤 저장소 루트에서 실행합니다.

```bash
cd web
WEB_HOST=127.0.0.1 WEB_PORT=4173 python3 -m ready2go_web
```

이 명령은 Flask 정적 서버와 `/runner/status` 전용 ROS executor를 같은 프로세스에서 시작합니다. 같은 PC에서는 `http://localhost:4173`으로 접속합니다. 종료할 때 `Ctrl+C`를 누르면 executor, 노드, ROS context도 함께 정리됩니다. 현재 REST가 없으므로 화면 값은 목업입니다.

휴대폰이나 다른 PC에서는 서버 PC와 같은 네트워크에 연결한 뒤 서버 PC에서 주소를 확인합니다.

```bash
hostname -I
```

Docker용 `172.17.x.x`를 제외한 와이파이·유선 LAN 주소를 골라 `http://서버_PC_IP:4173`으로 접속합니다. 모바일 전용 URL은 없으며 화면 폭에 따라 자동 전환됩니다. 접속되지 않으면 서버 실행 여부, 동일 네트워크, 방문자망의 장치 간 차단, TCP 4173 방화벽을 확인합니다.

### 2단계 자동 검증

저장소 루트에서 다음 명령을 실행합니다. DDS 시험은 실제 rclpy publisher와 별도 executor 사이의 `/runner/status` 전달을 확인합니다.

```bash
ROS_LOG_DIR=/tmp/ready2go-issue267-ros-logs \
CYCLONEDDS_URI=file://$PWD/config/cyclonedds.local.xml \
python3 -m pytest web/tests -q
```

주요 확인 항목은 다음과 같습니다.

- 2단계 실행에서 `runner` source만 활성화되는지
- Runner와 같은 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)` QoS로 수신하는지
- 정상 JSON 객체와 깨진 JSON·객체가 아닌 JSON을 구분하는지
- 별도 ROS context와 executor 스레드에서 실제 DDS 메시지가 캐시에 도착하는지
- 이중 시작을 거절하고 반복 종료를 안전하게 처리하는지
- Flask가 같은 캐시 객체를 보관하면서 아직 REST 경로는 공개하지 않는지

실제 Runner와 함께 확인할 때는 웹 서버를 실행한 상태에서 다른 터미널에서 다음을 사용합니다.

```bash
ros2 topic info /runner/status --verbose
ros2 topic echo /runner/status --once
```

웹 브리지가 구독자로 표시되고 Runner가 발행한 JSON이 출력되면 ROS graph와 발행 측을 확인할 수 있습니다. 캐시 내용의 HTTP 조회는 다음 REST 단계에서 추가합니다.

[실측] 2026-10-13 로컬 CycloneDDS에서 전체 웹 시험 `57 passed`를 확인했습니다. 실제 진입점을 임시 포트 4174로 실행해 `/`와 `/app.js`의 `200` 응답, ROS graph의 `/runner/status: std_msgs/msg/String` 단일 구독, `Ctrl+C` 뒤 노드 제거를 확인했습니다. 실제 Runner 프로세스·다중 PC·실물 장비 연결 검증은 아직 수행하지 않았습니다.

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
