# ROKEY 웹 대시보드 정적 목업

> [문서] 이 폴더는 이슈 [#112](https://github.com/Jik-Kim/ready2go/issues/112)의 PC·휴대폰 화면과 녹화 범위를 검토하기 위한 정적 목업입니다. Flask·rclpy 웹 서버, 실제 음성·Runner·ROS 2·온톨로지·MongoDB·로봇 연결은 아직 구현하지 않았습니다. 화면에 표시되는 값은 모두 `목업 데이터`이며 실제 관측이나 기능 완료를 뜻하지 않습니다.

기능의 의미·Phase·수용 기준은 정본인 [FR-INT-02](../docs/requirements.md#fr-int-02), [FR-ONT-02](../docs/requirements.md#fr-ont-02), [FR-PLN-02](../docs/requirements.md#fr-pln-02), [FR-LOG-01–02](../docs/requirements.md#fr-log-01), [NFR-SAF-02](../docs/requirements.md#nfr-saf-02)를 참조합니다. 이 문서는 요구사항을 재정의하지 않습니다.

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

이번 정적 목업에는 위 데이터의 실제 수신도 아직 없습니다. MongoDB/JSONL 실행 기록, 작업 중단·재개·초기화, 실시간 계획 근거, STT 원문, 확정되지 않은 음성·로봇 연결 판정은 녹화 우선 연결 범위에서 제외합니다.

### 표시를 바꾼 이유

- **STT 원문 미표시**: 기존 인텐트의 `source.stt_text`는 Runner에서 `/runner/status.last_intent.stt_text`로 제공됩니다. 다만 이번 정적 목업·녹화 범위에서는 표시하지 않으며, 실제 연결 시 웹 어댑터와 값 누락 처리를 함께 구현해야 합니다.
- **작업 중단 숨김**: 실제 중단 요청 경로가 이번 범위에 없으므로 버튼과 로컬 `중단 완료` 동작을 제거했습니다.
- **연결 상태 `확인 전`**: 웨이크워드·마이크와 로봇 드라이버의 판정 근거가 확정되지 않았습니다. 카메라는 이후 `/wrist_cam/color/camera_info`, Runner는 `/runner/status` 수신 여부로 판단할 예정이므로 목업 기본값을 각각 `확인 전`과 `상태 수신 대기`로 둡니다.
- **성공 상태의 의미**: 목업의 명령 접수·전달 완료·관측 확인 표시는 시각 검토용 예시입니다. 화면 상단 안내가 실제 성공 결과가 아님을 명시합니다.

## 4. 향후 실제 연결 경계

```text
/runner/status ──┐
/robot_state ────┼→ 웹 API 서버/ROS 브리지 → 화면 데이터 어댑터 → PC·휴대폰 UI
온톨로지 원본 ──┘
```

[문서] 이 구조는 이슈 #112의 연결 제안이며 현재 구현이 아닙니다. 브라우저에서 ROS 2·온톨로지 파일·MongoDB에 직접 연결하지 않습니다. Flask·rclpy 서버, 응답 형식, 갱신 주기, 오류·재접속 처리와 담당은 실제 계약을 확인해 별도 구현해야 합니다.

실제 연결 시에는 다음 순서로 교체할 수 있습니다.

1. 서버가 `/runner/status`, `/robot_state`, 온톨로지 원본을 읽어 제공하는 API를 구현합니다.
2. `demo-data.js` 대신 API 응답을 현재 화면 모델로 변환하는 어댑터를 로드합니다.
3. 미수신은 `확인 전` 또는 `상태 수신 대기`, 통신 중단은 `연결 끊김`, 오류 응답은 `오류`로 구분합니다.
4. `app.js` 렌더 함수가 변환된 공통 상태를 PC·휴대폰에 다시 표시하도록 연결합니다.

`TODO(D)`: API 서버/ROS 브리지 담당, API URL·응답 계약, 상태 갱신과 재접속 정책을 합의한 뒤 어댑터를 구현합니다. 계약을 바꿔야 하면 저장소 루트 [`AGENTS.md`](../AGENTS.md)의 승인 절차를 따릅니다.

## 5. 읽기 전용 검토 화면

상단 `검토 화면` 버튼은 인증 없이 같은 정적 페이지의 `#admin` 화면으로 이동합니다. 관리자 인증, 권한 획득, 서버 API 접근 제어가 구현된 것이 아닙니다.

- **현재 상태**: `/runner/status`와 `/robot_state` 우선 연결 예정이며 지금은 출처가 표시된 목업 데이터입니다.
- **온톨로지**: 서버가 읽은 원본 정의 연결을 우선 검토하며 지금은 목업 데이터입니다.
- **계획 근거**: 후속 연결 예정이며 현재 제공 경로가 확정되지 않았다는 안내만 표시합니다.
- **실행 기록**: 후속 연결 예정이며 실제 MongoDB/JSONL 조회가 연결되지 않았다는 안내만 표시합니다.

실제 운영 전에 서버 인증과 접근 제어를 반드시 연결해야 합니다. 일반 사용자 로그인은 고려 단계이며 이 목업의 구현 범위가 아닙니다.

## 6. 실행과 접속

저장소 루트에서 실행합니다.

```bash
python3 -m http.server 4173 --directory web
```

같은 PC에서는 `http://localhost:4173`으로 접속합니다. 포트가 사용 중이면 기존 서버를 종료하거나 다른 포트(예: `4174`)를 선택합니다. 이 명령은 파일만 제공하며 API·ROS 브리지·인증 서버를 실행하지 않습니다.

휴대폰이나 다른 PC에서는 서버 PC와 같은 네트워크에 연결한 뒤 서버 PC에서 주소를 확인합니다.

```bash
hostname -I
```

Docker용 `172.17.x.x`를 제외한 와이파이·유선 LAN 주소를 골라 `http://서버_PC_IP:4173`으로 접속합니다. 모바일 전용 URL은 없으며 화면 폭에 따라 자동 전환됩니다. 접속되지 않으면 서버 실행 여부, 동일 네트워크, 방문자망의 장치 간 차단, TCP 4173 방화벽을 확인합니다.

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
