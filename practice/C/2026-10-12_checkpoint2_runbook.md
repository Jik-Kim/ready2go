# 10/12 (월) P2 2차 핵심 점검 진행표 — C 작성

> 기준: [schedule.md Day 10](../../docs/schedule.md) "2차 핵심 점검: **음성 명령으로** 실물 서랍을 열고 장애물을 치우며 찾은 뒤, **성공·실패와 무관하게** 원래대로 되돌려 놓는가?" (진행·판정 E) + [AC-PLN-01](../../docs/requirements.md#ac-pln-01) 목표 5종 실물.
> 이 표는 **진행 순서·명령·기록 칸**만 정리한다. 합격 기준은 정본([AC-ACT-02·03](../../docs/requirements.md#ac-act-02), [verification-policy](../../docs/requirements.md#verification-policy))과 E 판정을 따른다. 시각은 KST.

> **갱신 10/12 12:15 (C)**: 코드 = **main**(#233 Unpacking 병합 `85492c5` 이후) · 판정 기준 **A안 확정**(3절 끝) · 준비 보완 — 호스트 방식 끄기·첫 빌드 시간·음성 노드 `r2genv`·**`/voice/speak` 없으면 첫 안내에서 실패**·DB 접속(7절). 오늘 12:00 예정이었다가 미뤄짐(시각 E 공지).
>
> 갱신 10/12 10:05 (C): 시험 브랜치 `26c0b5b` 이후(최신 main — B #226 놓기 하강 힘 감시·운용 힘·잡는 폭 포함 — + 움직이기 전 거부 코드 #232) · 점검 전 **S2 리허설 1회**(10/11 Runner 실물 미실행) · **S1 은 B 확인 배치만**(#229) · 원래 자리가 다른 물건 위였을 때 판정 기준 칸(3절 끝, E 답 대기).

## 0. 역할

| 담당 | 하는 일 |
| :--- | :--- |
| **E** | 점검 진행·판정, 음성 노드(웨이크·STT·TTS) |
| **B** | PC2 기동·설정 전부, 안전(비상정지 손 가까이), 회차 사이 물품·서랍·그리퍼 원위치, 자로 복구 오차, DB 접속 열기(7절) |
| **A** | 비전 노드(seg 가중치) 확인, 실패 시 덤프 확인 |
| **C** | Runner 확인·`reset_state`·`run_report`, 회차 기록 정리, 끝나고 DB 점검(7절) |
| **D** | 기록표 입력(회차·결과·근거 링크) |

## 1. 시작 전 준비 (PC2)

| # | 할 일 | 명령·확인 | 누가 |
| :--- | :--- | :--- | :--- |
| 0 | **호스트에서 켜 둔 것 끄기** | `roboton`·`b_flow.sh server`·호스트 `realsense2_camera` → Ctrl+C, `docker compose down` (같은 `/dsr01` 이름·카메라 단독 점유로 충돌, 제어기 이중 접속 — docker.md) | B |
| 1 | 코드 받기 | `git status`(고친 파일 있으면 멈춤) → `git fetch origin && git checkout main && git pull --ff-only origin main` → `git log --oneline -1` 이 `85492c5` 이후 | B |
| 2 | 모델 받기·확인 | `git lfs pull` → `sha256sum models/yolo11s_seg_ready2go_v1.pt` 가 `5b9527b78ebf…` (133 B 면 포인터 — 비전 노드가 꺼짐) | B·A |
| 3 | **`.env`** | `BACKEND=real` · `ROBOT_HOST`·`RG2_HOST`(B 확인, 인수인계 192.168.1.100·192.168.1.1) · `DDS_MODE=local`(PC1 트윈 안 쓸 때) · `VISION_MODE=yolo` · `MOCK_SCENE=` 비움 · 스킬 속도는 B 판단. **음성 → Unpacking**: `RUNNER_INTENT_TASKS=find_item=/tasks/find_with_unpack.json` (코드 수정 없음, [runner.md "음성으로 시작"](../../docs/runner.md)) | C |
| 4 | 사후 검증 모드 | `.env` 그대로 — `verify_mode` 는 기본 `off` (#43 트레이 확인 `enforce` 는 계약 PR 전이라 쓰지 않음) | C |
| 5 | 기동 | `docker compose --profile real up` — 처음엔 컨테이너 안 빌드(colcon)로 몇 분, 이미지 오류면 `docker compose --profile real build` 뒤 다시 `up`. 확인: DSR 드라이버·`/gripper/state` / 스킬 서버(`SKILL_START_DELAY_S` 뒤) / realsense·vision | B |
| 6 | Runner 준비 줄 확인 | 콘솔 `Runner 준비: … 인텐트 {… 'find_item': 'find_with_unpack'}` | C |
| 7 | 음성 노드 | PC2 호스트 터미널에서 **먼저 `r2genv`**(ROS_DOMAIN_ID 70·CycloneDDS — 없으면 컨테이너 Runner 와 통신 안 됨) → 로컬 YAML `audio_enabled: true` → **Runner 연동용 `evaluation_mode:=false`**(Voice README "사용자 PC 시운전 명령"). "○○ 찾아줘" 가 `find_item` 으로 나가는지. ⚠️ 음성 노드가 **`/voice/speak`(TTS)** 를 맡음 — 없으면 태스크 첫 안내 s2 "○○을 찾아 올게요"에서 바로 실패(로봇 동작 없음). 음성 입력이 안 돼도 노드는 켜 둠 | E |
| 8 | 시작 상태 | 서랍 **닫힘**, 그리퍼 **빈손**, 로봇 **홈**, 트레이 비어 있음 | B |
| 9 | **리허설 1회 (점검 전)** | **S2(아래 칸 덮개 판)** 를 2절 순서대로 1회 — 10/11 에 Runner 로 Unpacking 실물을 돌리지 못해 첫 실물 실행. 음성 대신 `RUNNER_TASK_FILE` 로 시작해도 됨. 문제 생기면 6절 → C 가 `run_report -n 1` 로 원인 확인 뒤 본 점검 | B·C |

## 2. 회차마다 순서

```
① B: 물품 배치 (아래 장면표) → 사진 1장
② C: docker compose exec ros2-core /entrypoint.sh ros2 service call /runner/reset_state std_srvs/srv/Trigger '{}'   ← Runner 기억을 시작 상태로
③ 사람: 웨이크워드 → "○○ 찾아줘"          (B 는 비상정지 손 가까이)
④ 끝나면 C: docker compose exec ros2-core /entrypoint.sh ros2 run ready2go_runner run_report -n 1
⑤ B: 자로 복구 오차 재기 (치운 물건마다 원래 자리 ↔ 지금 자리, mm)
⑥ D: 기록표 입력 → B: 원위치
```

- 말할 물품은 **B 가 파지를 확인한 물품만** (Unpacking 태스크는 등록 물품을 모두 받음).
- C 명령은 PC2 저장소 폴더에서 `docker compose exec ros2-core /entrypoint.sh …` 로 (호스트에서 `r2genv` 뒤 `ros2 …` 로 해도 됨).
- 음성이 안 될 때 직접 시작: `docker compose exec ros2-core /entrypoint.sh ros2 topic pub --once /voice/intent std_msgs/msg/String "data: '{\"intent\": \"find_item\", \"targets\": [\"eraser\"], \"confidence\": 0.95, \"source\": {\"stt_text\": \"지우개 찾아줘\"}}'"`
- 마지막에 `run_report -n 20 --check` (기록 빠짐 점검, AC-LOG-01).
- 결과 공유용 표: `ros2 run ready2go_runner run_report -n 3 --markdown`.

## 3. 장면 (성공·실패 둘 다)

| 장면 | 배치 | 기대 흐름 | "원래대로" 확인 |
| :--- | :--- | :--- | :--- |
| **S1 성공 (위 칸)** ⚠️ | 렌치 ← 캐러멜 상자 ← 차키 (A #109 시나리오) — **B #229: 3단 인식 불안정(캐러멜·몽키 미검출, 차키 집다 캐러멜까지 듦) → B 가 확인한 배치로만, S2·S3 뒤에** | 차키·상자 치움 → 렌치 트레이 → 상자·차키 되돌림 | 상자 원위치, 차키는 원래 자리가 상자와 붙어 **빈 자리 + 안내** 가능 |
| **S2 성공 (아래 칸)** | 덮개 판이 지우개를 덮음 | 판 치움 → 지우개 트레이 → 판 되돌림 | 판 원위치 |
| **S3 실패: 목표 없음** | S2 배치에서 지우개만 빼고 "지우개 찾아줘" | 못 찾음 → 위에 아무것도 없는 물건부터 치움(판 → 립밤, 최대 2) → 그래도 없음 → "지우개를 꺼내지 못했어요" → 되돌림 → 닫기 → 홈 [실측: mock] | 판·립밤 **둘 다 원위치** (밑에 목표가 없어 바닥이 빔) |
| **S4 실패: 목표 집기 실패** | (자연 발생 시에만 — 일부러 만들지 않음) | 치운 장애물이 목표 위였으면 원래 자리 막힘 → **빈 자리 + "○○은 원래 자리 대신 옆 빈 자리에 뒀어요"** | **A안 확정**: 빈 자리 + 안내 + 닫힘·빈손이면 통과 (3절 끝) |

- **S3 가 "실패해도 원래대로"의 기본 실패 회차**다(안전하게 만들 수 있음). S4 는 실물에서 생기면 기록만 한다.
- **복구를 다 못 하면** — 조건별로 다름 (#240):
  - **빈손이고 중단이 아닐 때**(되돌리기 집기 거부·다시 못 찾음 등, 쥔 물건 없음): 남은 물건도 계속 시도 → 서랍 닫기 → 홈 → 🔊 "옮긴 물건 일부를 원래 자리로 못 돌려놨어요" → `run_report` **`❌ 실패` · `RESTORE_INCOMPLETE`**(정본 137).
  - **쥔 채 멈춤**(옮기던 물건을 놓지 못함): 남은 되돌리기·서랍 닫기·홈 **모두 안 함** → 🔊 "물건을 옮기다 멈췄어요. 사람이 확인해 주세요" → B 수동 처리(6절). 결과는 앞선 실패 코드 또는 `RESTORE_INCOMPLETE`.
  - **놓침·센서 이상·집기 뒤 쥐었는지 모름(B `hand` unknown)·비상정지·"멈춰"**: 즉시 정지·잠금, 이후 로봇 동작 없음(`🛑 중단`) → 6절.
  - `RESTORE_INCOMPLETE` 는 **결과 판정**일 뿐, 실제로 하는 정리 동작은 위 조건을 따른다.
  - 원래 자리 대신 **빈 자리 + 안내**는 **A안대로 통과** — `✅ 성공` 그대로, 안내가 나왔는지 같이 기록.
- ⚠️ S3 는 태스크가 끝까지 정상 실행돼서 `run_report` 전체 결과가 **`✅ 성공`** 으로 나온다. 목표 전달 여부는 `[s8.1]` "꺼내지 못했어요" 안내(못 꺼냄) / `[s8.t2]` 놓기(전달)로 따로 적는다.
- 2단 이상 쌓인 장면은 B 가 `allow_stacked` 로 집을 수 있다고 확인한 배치만.
- **권장 순서: S2 → S3 → (S1)**. S2·S3 는 치운 물건이 모두 **바닥 원래 자리**로 돌아가 아래 판정 기준과 상관없이 정본(AC-ACT-03)으로 판정 가능.

### 판정 기준 — 원래 자리가 다른 물건 위였을 때 (A안 확정 10/12)

정본 FR-ACT-04 "원래 위치로 역순 복구"·AC-ACT-03 "위치 오차 3 cm 이하"는 **원래 위치가 다른 물건 위**인 경우를 정하지 않음. 지금 놓기는 **바닥에만**(B #166) → B·C 합의(#168)대로 **빈 자리 + 안내**. 생기는 경우: S1 성공 회차의 차키(원래 자리 = 캐러멜 위), S4 실패 회차의 덮개 판(원래 자리 = 목표 위).

| 안 | 판정 |
| :--- | :--- |
| A안 (C 추천) | 바닥 원래 자리는 3 cm 기준, 원래 자리가 다른 물건 위면 **빈 자리 + 안내 + 닫힘·빈손이면 통과** |
| B안 | 위에 다시 쌓아야 통과 (B "물건 위에 놓기" 새로 필요 — 오늘 불가) |

**결정: A안** (10/12 팀 결정, 사용자 전달) — [C 질문](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6106104519). 되돌리기를 **아예 못 한** 경우(집기 실패·다시 못 찾음·쥔 채 멈춤)는 `❌ RESTORE_INCOMPLETE` → 실패.

## 4. 회차 기록 칸 (D 기록표와 같은 이름으로)

| 칸 | 어디서 |
| :--- | :--- |
| 회차·장면(S1~S4)·물품 배치 사진 | B |
| 시작 방법 (음성 / 파일) · 말한 문장 | E |
| `run_id` · 전체 결과(`✅ 성공`·`❌ 실패`·`🛑 중단`) · 실패 스텝·코드 | `run_report` 첫 줄·둘째 줄 |
| 치운 물건 수 (`반복 · N회` [s7]) · 전달 여부 ([s8.t2]) | `run_report` |
| **복구 오차 (비전)**: 물건별 위치 mm · 방향 ° | `run_report` 머리 "복구 오차 (판정 아님)" |
| **복구 오차 (자)**: 물건별 mm | B |
| 원래 자리 대신 빈 자리 | `run_report` 머리 "원래 자리 대신 빈 자리" + 안내 음성 |
| 서랍 닫힘 · 홈 · 빈손 | `run_report` [f2]·[f3.1] + 눈 확인 |
| 관측 오류 (`REGION_NOT_VISIBLE` 등) · 다시 찍기 (`s6r`·`s7.9`) | `run_report` |
| 비고 (멈춤·사람 개입·영상 위치) | 모두 |

- 판정은 E. 복구 오차 합격 기준(정본 [AC-ACT-03](../../docs/requirements.md#ac-act-03) **위치 3 cm 이하**, 10/10 #207 로 2 cm → 3 cm, 방향은 기록)은 **코드에 없음** — 기록표에서 판정. 원래 자리가 다른 물건 위였던 물건은 3절 "판정 기준" 칸을 따름.

## 5. 목표 5종 실물 (AC-PLN-01, #150)

| # | 명령 | 시작 상태 | 기대 계획 |
| :---: | :--- | :--- | :--- |
| 1 | 지우개 트레이에 갖다 놔 | 위 서랍 닫힘·지우개 위 서랍·빈손 | 열기 → 집기 → 놓기 → 닫기 |
| 2 | 위 서랍 열어 둬 | 닫힘·빈손 | 열기 |
| 3 | 위 서랍 닫아 | **열림**·빈손 | 닫기 |
| 4 | 지우개 갖다 놓고 서랍은 열어 둬 | 1 과 같음 | 열기 → 집기 → 놓기 (닫지 않음) |
| 5 | 립밤 트레이에 갖다 놔 | 1 과 같음(립밤) | 1 과 같음 — **B 립밤 파지 확인 뒤** |

- **음성 목표 발행은 E 가 아직 막아 둠** → E 가 열지 않으면 아래 명령으로 `/voice/intent` 에 `achieve_goal` 을 직접 보낸다(PC2 호스트 터미널, Domain 70).
  [실측: ROS 노드 mock 10/11] 5종 모두 `decision: run` → 계획 → `COMPLETED`, 콘솔 `[plan]` 줄에 단계별 근거.
- 순서: **1 → (reset) → 2 → 3(이어서, reset 없이 — 2 가 연 서랍을 닫음) → (reset) → 4 → (reset) → 5**. 시작 상태는 B 가 눈으로 확인한 뒤 `reset_state`.

먼저 보내기 함수 (한 번만):
```bash
send() { ros2 topic pub --once /voice/intent std_msgs/msg/String "data: '$J'"; }
```

1 지우개 트레이에 갖다 놔
```bash
J='{"intent": "achieve_goal", "goals": [{"predicate": "located_in", "subject": "eraser", "value": "handover_zone"}], "confidence": 0.95, "source": {"stt_text": "지우개 트레이에 갖다 놔"}}'; send
```
2 위 서랍 열어 둬
```bash
J='{"intent": "achieve_goal", "goals": [{"predicate": "open", "subject": "drawer_top", "value": true}], "confidence": 0.95, "source": {"stt_text": "위 서랍 열어 둬"}}'; send
```
3 위 서랍 닫아 (2 바로 뒤, 서랍 열린 상태에서)
```bash
J='{"intent": "achieve_goal", "goals": [{"predicate": "open", "subject": "drawer_top", "value": false}], "confidence": 0.95, "source": {"stt_text": "위 서랍 닫아"}}'; send
```
4 지우개 갖다 놓고 서랍은 열어 둬
```bash
J='{"intent": "achieve_goal", "goals": [{"predicate": "located_in", "subject": "eraser", "value": "handover_zone"}, {"predicate": "open", "subject": "drawer_top", "value": true}], "confidence": 0.95, "source": {"stt_text": "지우개 갖다 놓고 서랍은 열어 둬"}}'; send
```
5 립밤 트레이에 갖다 놔 (B 립밤 파지 확인 뒤)
```bash
J='{"intent": "achieve_goal", "goals": [{"predicate": "located_in", "subject": "lip_balm", "value": "handover_zone"}], "confidence": 0.95, "source": {"stt_text": "립밤 트레이에 갖다 놔"}}'; send
```

- 확인: 콘솔 `/voice/intent: {… 'decision': 'run', 'task_id': 'plan_…'}` 와 `[plan] 1. …` 근거 줄, 끝나면 `ros2 run ready2go_runner run_report -n 1`(헤더에 계획).
  `decision: hold` 이면 `reason`: `PLAN_SATISFIED`(이미 만족 — 시작 상태 확인) / `UNPLANNABLE`(지원 범위 밖) / `BUSY`·`LOCKED`.
- 실행 기록 헤더 `plan` 에 근거가 남는지 `run_report` 로 확인.
- 사후 검증(#43)은 main 미반영 → 결과는 스킬 응답 + 사람 확인으로 기록(관측 verify 통과로 적지 않음). [planner.md 시험표](../../docs/planner.md)의 "실물 결과" 칸을 채움.

## 6. 멈췄을 때

| 상황 | 할 일 |
| :--- | :--- |
| 비상정지·"멈춰" | Runner 잠김(`/runner/status` `phase: halted`). B 가 실물 확인 → 원위치 → Runner 재시작 또는 B 절차. 자동 재개 없음 |
| 놓침·센서 이상 (`OBJECT_DROPPED`·`SENSOR_INVALID`) | 즉시 정지·잠금(#78). 사람이 물건 회수·원위치 → `reset_state` → 새 요청 |
| 쥔 채 멈춤 ("물건을 옮기다 멈췄어요") | 홈 이동 없음. B 가 그리퍼 확인 후 수동 처리 |
| 관측 오류 반복 (`REGION_NOT_VISIBLE`) | 카메라 앞 가림·케이블 확인 (A), 로그 "지역 바닥 보인 비율" |
| 음성 요청이 보류됨 | `/runner/status` `last_intent.reason` (예: `UNKNOWN_ITEM`·`LOW_CONFIDENCE`·`BUSY`·`LOCKED`·`NOT_READY`) |
| 첫 안내 "○○을 찾아 올게요" 직후 실패 | `/voice/speak` 없음 → E 음성 노드 확인 뒤 다시 |

## 7. 끝날 때 · DB 확인

| 할 일 | 명령·확인 | 누가 |
| :--- | :--- | :--- |
| 기록 빠짐 점검 | `run_report -n 20 --check` | C |
| 결과 공유용 표 | `run_report -n 5 --markdown` | C |
| 정리 | 로봇 홈·서랍 닫힘 → **컨테이너 내리기 전 로그 보존**(docker.md 4.3) → `docker compose down` | B |
| 기록표 | 정리 → #196 에 결과 링크 | D |
| **DB 접속 (C PC Compass)** | PC2 와이파이 IP `hostname -I` 공유 → 접속이 막히면 `sudo ufw allow from <C PC IP> to any port 27017` → Compass `mongodb://<PC2 IP>:27017` → DB `cobot2` → `runs`·`steps`. **점검 끝나면 허용 지우기**(DB 비밀번호 없음) | B |
| DB 점검 | C PC 에서 `run_report --uri mongodb://<PC2 IP>:27017 -n 20 --check` + 회차별 대조 → #196 보고 | C |

