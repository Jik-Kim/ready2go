# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-06

## 지금 상태
- #1·#8 최신 결정에 따라 hardware·metrics_risks의 서랍 재질/레일·높이 기준 문구를 정정함. 작업 브랜치 `codex/hardware-doc-alignment`, 기준 main `f6c2aa4`. 사용자께서 문서 수정·로컬 커밋·push·새 PR 생성을 승인함. [문서]
- 일반 후보 높이 1.5 cm 유지, 지우개만 예외. 새 서랍 가운데 파지 3/3은 해당 조건의 결과이며 전체 배치·모든 물품 검증 완료가 아님. [#8 결정](https://github.com/Jik-Kim/ready2go/issues/8#issuecomment-5980582810) [문서]
- PR #46은 병합됨. #70~#73은 이번 확인 시점에 미병합이며 승인·병합·추가 변경은 본 문서 작업 범위 밖임. `DRAWER_NOT_AT_TRAVEL`의 실제 노드 연결·실물 검증은 후속 확인 사항임. [문서]
- `f123f50` head의 [원격 CI 실행 127](https://github.com/Jik-Kim/ready2go/actions/runs/37179524578)은 contracts-and-core·ros-build·compose 모두 성공했습니다. 아래 로컬 검증 기록과 구분하며, 후속 커밋의 CI 결과를 대신하지 않습니다. [문서]
- PR #46 재검토 수정과 main `5350bd9`(#58 TF 정정·#61 pose 규칙 포함) 통합을 완료했습니다. 작업 브랜치: `codex/ontology-review-fixes`. 사용자 승인 후 지정 PR 세션을 통해 커밋 `f123f50`의 push·기존 [PR #46](https://github.com/Jik-Kim/ready2go/pull/46) 갱신·Draft 해제를 완료했습니다. 당시 PR은 Open·Ready for review였으며 이후 병합됐습니다. [문서]
- 시연 최소 표시·터미널 대체와 D 담당·C 검토·E 데이터 인계를 복원하고 이슈 #59 참조를 17.4·17.5·17.6으로 갱신했습니다. 실제 담당별 데이터 연결·수락·완료는 별도 확인 사항입니다. [문서]
- #8의 실측/외접박스 표 11종·12개를 world 원본에 반영했습니다. 등록 물품 전체가 P1 단일 요청 대상이며 최종 파지 승인은 별도입니다. [문서]
- 파지 힘은 item_grasp.yaml의 null, 승인 상태는 false로 두었습니다. 미확정 설정 거절 함수 제공과 B/C 실물 경로 연결은 구분합니다. [문서]
- 공용 ontology/interfaces/hardware/README와 연관 예시·프리셋을 갱신했습니다. 높이 1.0 cm 일괄 변경이나 실물 위치·시험 성공을 임의 확정하지 않았습니다. [문서]
- 온톨로지 작성 원본을 classes·world·스킬 파일로 분리하고, `robot_ontology.jsonld`는 공통 context와 참조 목록으로 구성했습니다. [문서]
- E 로더가 분리 파일·초기 상태 프리셋·장소 YAML을 연결하고 기존 `classes/world/state/skills` 조회 구조를 반환합니다. [문서]
- 장소 설정의 정본은 `config/places.yaml`이며 공통 식별자로 결합합니다. 미측정 null은 유지합니다. [문서]
- 기존 복합 스킬 이름을 `handover_with_unpack`으로 변경했습니다. 태스크 경로와 동작 정의는 유지했습니다. [문서]
- 초기 상태 프리셋은 `knowledge/snapshots/initial_state.json` 하나로 유지합니다. 실제 상태 확인·적용·저장은 Runner 책임입니다. [문서]

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 장소 설정 정본 | `config/places.yaml` | [문서] 사용자 합의 |
| 연결 식별자 | `world.places`와 YAML의 동일 장소 키 | [문서] 사용자 합의 |
| 복합 스킬 이름 | `handover_with_unpack` | [문서] 사용자 지정 |
| 물품 치수 순서 | `size_m = [긴 변, 짧은 변, 높이]`, m | [문서] #6·PR #46 PM 코멘트·병합된 #61 대조 |

## 막힌 점 · 필요한 도움
- 구매 기록에서 실제 제품명은 확인하지 못함. PR 구매 기록은 “제품명 미확인 / 철제 고정대 + 원목 2단 서랍장(금속 레일)”로 보고하며 제품명 확인이 필요함. [문서]
- E 포함 2명 계약 승인은 미확인입니다. 사용자 수정·push 승인을 팀 계약 승인으로 대신하지 않습니다. [문서]
- TODO(A): lip_balm 외접박스 높이 20.0 mm/이전 20.2 mm 보고의 차이를 확인해야 합니다. size_m 로컬 축/yaw 기준은 #6·#61에 맞춰 정렬했습니다. [문서]
- TODO(B·E): 물품별 힘·파지점·반복성·실물 실행 검증(일반 높이 기준 유지·지우개 예외는 #8에서 확정); TODO(C): require_grasp_settings와 실제 실행·TTS·인스턴스 상태 연결. [문서]
- TODO(C 이영훈): 태스크 스킬 호출·실패 상태 계약 및 로그의 전체 구성 해시 기록 연결이 필요합니다. [문서]
- TODO(B 서동권): 접근 동작 책임과 미측정 설정의 실행 전 검사 계약 확인이 필요합니다. [문서]

## 다음 할 일
- [x] 사용자 승인 후 지정 PR 세션 인계, `f123f50` push·PR #46 갱신·Draft 해제 및 해당 head의 원격 CI 성공 확인
- [ ] E 포함 2명 계약 승인과 #59 D/C/E 데이터 연결 확인
- [ ] A가 고정된 클래스 번호를 사용해 촬영·라벨링 시작
- [ ] C·B와 실행 계약 보완 사항 확정

## 철회한 결론
- ~~drawer_top TF는 항상 null~~: #56·#58 실측/정정에 따라 원본 YAML 값과 비교하고 null은 독립 fixture로 검증합니다. [문서]
- ~~size_m = [폭, 길이, 높이]~~: #6·#61의 긴 변 방향 yaw에 맞춰 앞 두 치수를 정렬했습니다. [문서]
- 진입점 JSON을 직접 읽으면 전체 정의가 나온다는 기존 가정은 파일 분리 후 사용할 수 없습니다. [문서]

## PR #46 문서 정합성 보완
- requirements.md를 기준으로 ontology·시연·인덱스·일정의 참조와 구현/계획 구분을 정리했습니다. [문서]
- 최신 main 통합: PR #45의 manifest 호환 데이터셋 로더·학습 README와 PR #48의 새 서랍 YAML 설정을 유지했습니다. [문서]
- 최초 번호 파일은 10/04 아래 조치로 생성했습니다. 촬영·라벨링은 A, 파지 실행 연결·실패 상태 계약은 B/C 인계 사항입니다. [문서]
- 검증 기준은 문서 정합성·참조·충돌 해결이며 전체 코드 테스트를 완료 근거로 사용하지 않습니다. [문서]
- 이번 확인: 변경 문서의 파일 링크·요구사항 앵커·미구현 설명, 충돌 표식 제거, JSON 파싱 통과. PR #45의 sources.world 조회로 새 물품 11종 확인(클래스 번호 생성 없음). 전체 테스트·빌드는 수행하지 않았습니다. [문서]

## 2026-10-04 FR-ML-01 클래스 번호 정본 준비
- PR head의 world.items 순서로 공식 `build_dataset.py --init-classes`를 실행하여 config/yolo_classes.txt 11종(0–10)을 생성했습니다. 순서 변경 금지·신규 클래스 끝에 추가 규칙을 유지합니다. [문서]
- load_classes(): 11종·경고 없음. 임시 두 세션의 각 11개 라벨 fixture로 일반 CLI 데이터셋 생성(allow-ontology-order 없이) 성공, nc=11·classes.txt·train/val 각11개 확인. 실제 영상·학습·성능을 검증한 것은 아닙니다. [실측]
- 번호 파일 준비 당시 changelog.md는 사용자 해결 내용을 유지하기 위해 수정하지 않았습니다. 이번 재검토에서는 최신 main 기록과 기존 E 기록을 모두 보존해 충돌을 해결했습니다. [문서]

## 2026-10-04 PR #46 재검토 수정 검증
- 치수 정렬과 hardware·ontology·interfaces 설명을 정정했습니다. A의 pose 규칙 함수·B 밀기 계산과 대조했으며 타 담당 코드는 main 내용을 보존했습니다. [문서]
- 계약 검증 OK, core 테스트 229 passed. 원본 YAML과 로더 TF 대조 및 독립 null fixture를 포함합니다. [실측]
- 11종 치수와 문서 표 일치, 클래스 번호·파지 설정·main 장소 설정 및 main 전용 변경 30개 파일 보존을 확인했습니다. 변경 문서 파일 링크·앵커와 diff 공백 검사도 통과했습니다. [실측]
- 위 로컬 검증에는 ROS/Docker 빌드, 실물 실행, 실제 영상 라벨링·YOLO 학습, MongoDB/JSONL 표시 연결을 포함하지 않았습니다. ROS 빌드·compose 검사는 별도로 위 원격 CI에서 성공했으며 실물·학습·표시 연결 완료를 뜻하지 않습니다. [문서]

## 2026-10-05 하드웨어 문서 정합성 작업
- 관련 범위: P1 FR-ACT-01·02·03, NFR-SAF-01·02. 요구사항·완료 기준은 변경하지 않음. [문서]
- 근거: [#1 최신 요청](https://github.com/Jik-Kim/ready2go/issues/1#issuecomment-5980612526), [#8 최신 결정](https://github.com/Jik-Kim/ready2go/issues/8#issuecomment-5980582810), [#15 인출 거리 요청](https://github.com/Jik-Kim/ready2go/issues/15#issuecomment-5976855710). 실측 설정은 config/places.yaml 한 곳을 참조함. [문서]
- 설정·코드·계약·트레이 역할은 변경하지 않음. OBJECT_DROPPED는 #78 별도 협의 범위이며, PR #70~#73의 승인·병합이나 실제 노드 연결 완료를 뜻하지 않음. [문서]
- PR 생성·push 결과는 지정 PR 세션의 실제 PR 링크·원격 head로 확인함. 제품명·실물 인계 미확인 사항은 별도 유지함. [문서]
- 검증: #1·#8·#15 결정/요청 및 관련 P1 요구사항과 문구 대조, 기존 일반 재질 기준 보존, 실측·미확정 연결 구분, 로컬 파일 링크/앵커 및 승인된 3개 파일 범위·diff 공백 검사 통과. 코드 변경이 없어 전체 테스트·빌드·실물 시험은 수행하지 않음. [문서]

## 2026-10-06 P1 목표 10/08 일정 조율
- 사용자 지시에 따라 P1 음성 L1 목표를 Day 8(10/10) → Day 6(10/08 목)로 변경함. docs/schedule.md·본 CURRENT 2개 파일만 수정. 기준 main c6967b9, 브랜치 codex/p1-oct08-schedule. 기존 codex/ontology-demo-pick 및 PR #85 작업은 보존하며 병합/검증 완료를 이번 일정 작업에서 단정하지 않음. [문서]
- A 10/07 08:00~09:00 카메라/TF·첫 위치 오차 측정 슬롯 확정. 10/06 저녁 #80 보완/리뷰는 조건부, 10/08 AC-VIS-01 반복 측정·튜닝/실제 비전 연결과 P1 음성 통합 우선. 새 바닥 카메라 측정은 A 제안임. [문서: 전달된 일정 결정]
- B 개폐20회(18/20 이상)·파지/안전, C/E 음성 통합, D 상태/로그·측정·녹화 준비는 10/07~08 목표로 조율. A 확정 슬롯 외 시간·담당자 수락은 미확정. 10/09 A 작업 불가·필수 작업 배치 금지. 10/10 시설/로봇 사용 가능은 사용자 확인이며 후속 재점검/녹화는 제안. [문서]
- #22 10/06 stub/예상 target_after 첫 실물 점검과 #23 P1 실제 비전·웨이크/STT·단일 물품→태스크→Runner·TTS·상태/로그·안전 통합을 구분. P1 완료는 요구사항과 관련 수용 기준·AC-DEMO-01 3회 연속 기록으로 판정하며 한 바퀴 성공으로 낮추지 않음. [문서]
- V3 지속 ID·BFS·Unpacking/원위치복구는 P2, T3 사전검증·목록은 P3로 P1 필수에서 제외. 후속 Phase 담당 확인 필요, 이후 일정을 임의 재배정하지 않음. [문서]
- 타 문서 인계: A docs/vision.md의 V3 Day6~7, docs/twin.md의 T3 Day6~7·Day5 중단 기준; 결정권자 docs/overview.md의 Day5/8 슬롯·체크포인트, docs/domain.md의 L1(Day8), docs/metrics_risks.md의 Day5 트윈 중단 기준. 해당 파일은 편집하지 않음. [문서]
- 검증: 두 파일 diff/공백, Day 번호·요일, 상단/표/체크포인트/중간 녹화의 Day6 10/08 일치, P1 요구사항/완료 기준 및 문서 제목·링크·앵커 대조. archive 제외 날짜 검색으로 위 인계 확인. 코드 변경 없어 전체 테스트/빌드·실물 시험은 수행하지 않음. [문서]
- #80/#83/#85 병합·검증 및 팀 계약 승인 완료는 이번 작업에서 미확인. 로컬 커밋까지만 승인, push/PR 미승인. [문서]

## 2026-10-06 #22 시연용 pick_demo 연결
- 사용자 승인 범위: E 파일 4개 작성·관련 최소 검증·로컬 커밋. 기준 main `e05a2f5cde29874600d789b8f12d00dd448d01bc`, 작업 브랜치 `codex/ontology-demo-pick`. push·PR·병합은 미승인. [문서]
- `knowledge/robot_ontology_demo.jsonld`는 open_drawer/close_drawer/pick_demo/place 4종으로 구성. 공통 manifest/pick/초기 상태는 유지함. `pick_demo`는 기존 pre/hold/effect/오류·verify 선언을 보존하고 nudge → 반환 전체 target_after로 pick을 연결함. approach_offset=[0,0,0.1]. [문서]
- 실제 E 로더의 참조 결합·4종/중복 없음, 기본 ontology/pick 보존, 모의 태스크의 task schema 확인 통과. 실제 C Runner + MemoryLogStore로 11사례 통과: 정상, target_after 누락(VAR_UNDEFINED), pick GRASP_FAILED, nudge GRASP_FAILED, 안전 오류 5종, pre 불충족, target 입력 누락(TASK_INVALID). 마지막 입력 누락은 최신 C 사전 검증이 실행 전 거절함을 확인하고 검사 기대값을 바로잡음. [실측: 로컬 모의]
- nudge 입력 전체 target 및 pick 입력 전체 target_after 전달, inspect_region 1회, nudge 1회(retry=0), 성공 시에만 gripper/located_in 효과, 실패/출력 누락 시 pick 미호출·집기 효과 없음, nudge/pick 각각의 params/result/status·실패 단계 로그를 확인함. 정상 pick 후 place/close 실물 연결 검증은 포함하지 않음. [실측: 로컬 모의]
- 임시 검증 스크립트 `/tmp/verify_e_pick_demo.py`는 저장소 커밋에 포함하지 않음. ROS·Docker 전체 빌드, 실제 로봇·MongoDB/JSONL 저장·배포 검증은 수행하지 않음. [문서]
- C 제안 실행 조합: ontology_file=/knowledge/robot_ontology_demo.jsonld, task_file=/tasks/p1_demo_eraser.json. 기준 main에는 해당 태스크 없음: C 반영·실행 조합 확인 대기. 호출 태스크 retry 생략/0, place 실패 시 쥔 상태의 종료·복구 정책은 C/B 인계임. [문서]
- B #83 head25e97ef 배열 지원·lift 오류 보존의 13사례 통과는 검토 세션 전달 결과이며 E의 재검증이 아님. check_only PUSH_LIMIT 보완, target_after 계약 출력 예시·E 포함2명 승인은 별도 인계. A stub·B 보정 TF/실물 준비·C 패키지는 수정하지 않음. [문서]
- target_after는 이동량 기반 예상값이며 FR-ACT-05/AC-ACT-05 재인식 완료가 아님. P1 FR-ONT-01/FR-PLN-01 연결의 시연 한정 구성. domain 상세는 시연 후 계획으로 유지하며 출력 계약 승인이나 실물 배포 완료를 대신하지 않음. [문서]

## 2026-10-06 #16 P1 음성 패키지 구현
- 검토 세션에서 전달된 사용자 직접 승인 “구현 승인. 이 코드 참고하도록 넘겨.”에 따라 E voice 패키지/설정/관련 검증·본 CURRENT·로컬 커밋 범위 구현. 기준 main `64399e638e6b1293ac0a692a39f8e9cb4b0d4212`, 브랜치 `codex/voice-p1-implementation`. 기존 일정/시연 브랜치는 보존함. push/PR/병합·타 담당/공통 계약 편집은 제외. [문서]
- 참고 원본 STT/keyword_extraction/audio_device/wakeup_word는 읽기만 수행. SciPy 대신 표준 wave, 기존 온톨로지 전체 물품/별칭, LangChain strict JSON+의미 검증·규칙 폴백·unknown/clarify 보류를 구현. 고정5초 녹음은 RMS 무음 종료/최대 한도로 변경함. 키는 환경에서 읽으며 출력하지 않음. 모델 원본 복제/수정 없음. [문서]
- 웨이크→녹음→whisper-1 후보 전사, gpt-4o 후보 해석, espeak-ng 후보 WAV→PortAudio DAC 재생, 기존 voice intent/text_override/speak ROS 연결을 구현. 모델/장치/임계값/예산은 패키지 params의 팀 확정 필요 설정으로 구분. default evaluation_mode=true·audio_enabled=false: 평가에서는 제어 intent 포함 모든 intent 발행 없음. [문서]
- 실제 실행 결과: 빠른 compileall·JSON/YAML/XML/README 링크·diff 공백 검사 통과. colcon packages-up-to ready2go_voice 빌드 최종1회(interfaces/knowledge/voice3개) 성공. 실제 ROS/생성 Skill을 source한 패키지 검사47개 통과, skip0. core/SDK 모의·기록 종료·PCM/장치오류·TTS취소·API시간초과/늦은응답·평가/중복/취소 게이트 및 독립ROS도메인166 topic/action 연결 포함. DDS 인터페이스 열거가 샌드박스에서 차단되어 승인된 검증을 독립도메인/임시로그 경로의 격리된 로컬 실행으로 확인함. [실측: 로컬·API/오디오 모의]
- 강의 hello_rokey_8332_32.tflite는 현재 환경에서 tflite runtime 초기화·무음1280프레임 추론 성공. 실제 웨이크 발화·모델 배포/PC 설정 검증이 아님. 입력/출력 장치0개, espeak-ng 실행기 없음. 실제 한국어 음성 가용성/물리재생/API 계정·지연은 미검증이며 유료API 호출하지 않음. [실측: 로컬 환경 확인]
- TTS 시작은 요청/합성시각 대신 첫 PortAudio DAC 재생 시각으로 진단하며 실제 어댑터와 mock 시각을 구분. 물리 스피커 지연은 별도 실측. 무음 대기/STT/LLM/TTS준비를3초예산에 포함하고 늦은API결과·취소된요청은 추가발행하지 않음. TTS실패는find_item을clarify로보류. 시간예산설정이실제로3초를충족하는지는미검증. [문서]
- C #17 인계: intent→P1태스크·cancel/status·중복/모호/미지원보류, 확인TTS↔태스크시작 책임, source→run_id/로그. Docker/compose의패키지/계약/모델배포·기동은별도C/E협의/승인. E는로봇제어/ESTOP·관측상태/DB로거를추가하지않음. [문서]
- D #20 인계: 20지우개/10모호/10미등록미지원(자유표현10포함/화자2명이상), cancel/status보조유지. 문장별정답·대상단독clarify/unknown정책·필드수신경로는미합의. 기존ROS로그와source에STT/LLM원문·검증/폴백·실행허용/발행·발화종료/재생시각출력 제공. 정상unknown/clarify를LLM검증실패로세지않음. [문서]
- 실음성40문장≥36정답·LLM검증실패≤5%/잘못된실행0·실제확인TTS≤3초(AC-INT-01~03)는미측정. 장치/API/TTS·C/D·모션없는평가·운용조건확인후10/08목16:00P1테스트를준비함. 시작시각은준비완료/성공보장이아님. [문서]
- 벽면배치·nudge는사용자지정P1테스트범위이며기존pick_demo예상target_after/재조회없음연결은유지. 실제재인식→pick/NO_PUSH_ACCESS정합성은별도A/B/C/E인계. FR-ACT-05재인식완료로판정하지않음. 새OntologyManager/BFS/목록/목표계획/LLM태스크생성은제외. [문서]

## 2026-10-06 #16 인텐트 의미 검증 회귀 보완
- 기존 승인 범위의 기능 오류 수정: E voice core/테스트/README/params 및 본 CURRENT만 변경. FR-INT-02(P1), AC-INT-02 기준. 계약·타 담당 코드·Docker·공통 문서·시연 구조는 변경하지 않음. [문서]
- 이름/별칭이 없는 발화에 LLM이 등록 물품을 추론해도 clarify/빈 targets/실행 보류. 등록 이름도 긍정 요청 문장 전체가 맞아야 실행하며, 부정·정보 질문·인용·불명확한 문맥은 부분 request_patterns나 LLM confidence로 실행하지 않음. 규칙 폴백과 LLM 의미 검증에 동일한 조건 적용. [문서]
- 연필 찾아줘/이름 없는 자유 표현, 지우개 가져다주지 마/안 찾아도 돼/가격 질문 재현 보류 및 실행 모드 노드의 비집기 intent/확인 안내 검증. 긍정 지우개20표현(LLM/규칙 경로), 등록된 비모호 이름/별칭 유지. core·node 관련 검사92개 통과, 기존 실제 ROS topic/action 검사1개는 이번 수정에서 제외. compileall/YAML/README 링크/diff 검사 통과. 이번 보완은 전체 빌드·무관 어댑터 검사·실제 DDS 연결을 반복하지 않음. [실측: 로컬, API/오디오 모의]
- 문형 밖의 자유 표현은 확인 안내로 보류하며 일반 한국어 의미 이해 완료가 아님. E/D 실제40문장 정답표·후속 확인 정책은 미확정, 회귀20표현은 실제 평가 정답표가 아님. source.llm_validation=passed와 실행 허용은 구분. 물리 음성/API/3초/실제 C 수신 검증은 계속 미완료. [문서]
- push/PR/병합은 이번 보완 승인에 포함되지 않음. 기존 미추적 :memory:.ses는 작업 범위 밖으로 보존하고 커밋에 포함하지 않음. [문서]

## 2026-10-06 #16 사용자 정상 예시 회귀 보완
- 검토 세션이 확인한 동일 승인 범위에서 위 서랍 한정 수식과 `지우개가 필요한데 가져다줄래?` 긍정 복합 요청을 좁게 허용. 임의 문맥/부정 제거와 허용 문형 무제한 확장은 하지 않음. E core·관련 테스트·README·본 CURRENT만 수정. [문서]
- 사용자 예시4개(지우개 찾아줘./지우개 좀 가져다줘./위 서랍에 있는 지우개 꺼내줘./지우개가 필요한데 가져다줄래?)를 정상 LLM/규칙 폴백 두 경로에서 find_item/eraser/실행 허용으로 검증. 기존 연필 추론·부정·가격 질문 보류 및 추가 수식/복합 요청의 부정·질문 변형 보류 유지. [실측: 로컬 모의]
- 영향 core·node 검사104개 통과, 기존 실제 ROS topic/action 검사1개 제외. compileall/README 링크/diff 검사 통과. 이전20표현 통과를 정상 요청 전체 충족으로 간주하지 않으며 실제 E/D40문장·장치/API·3초·C/D 연결 검증은 계속 남음. 전체 빌드/실물/유료 API/push/PR은 수행하지 않음. [문서]

## 2026-10-06 PR #88 제어 문장부호·중복 확인 안내 회귀 보완
- 기준 HEAD e80f398, 기존 사용자 승인 내 E core intent/session·voice_node·관련 test·패키지 README·본 CURRENT만 수정. FR-INT-01~03(P1), AC-INT-02~03 관련 회귀. 공통 docs/voice_llm·계약·타 담당·Docker·PR 메타데이터는 수정하지 않음. [문서]
- 발화/설정의 끝 .!?。？！만 정규화한 정확 비교로 취소/상태 인식. parse/fallback/validate 및 node._text 빠른 경로에서 API 없이 제어 intent 처리. 부정/중간 문맥 삭제·부분 일치 전환 없음. [문서]
- 실행 find_item 중복 조회를 TTS 앞으로 이동, 조회와 실제 발행 기록을 분리. submit_lock 안에서 세대/중복 확인·발행 호출 정상 반환 후 기록하고 TTS 중에는 락을 해제해 즉시 취소 경로 유지. TTS 실패·취소·지연 폐기·발행 예외는 find_item 중복 기록을 확정하지 않음. 평가 반복 TTS/진단 및 모든 intent 발행 금지, unknown/clarify 안내·기존 발행 중복 정책 유지. [문서]
- core/node 영향 검사120개 통과, 실제 ROS topic/action 검사1개 제외. 문장부호/전각종결기호·설정 동일 정규화·부정/중간 제어 발화 보류, 노드 즉시 취소 세대 갱신, 동일 요청 확인1/발행1, TTS 첫 실패 후 재시도, 시간창 경과 재허용, 평가 반복 안내/발행0, 발행 예외·취소·시간초과 후 재시도 및 기존 의미검증/사용자 예시4개 유지 확인. compileall/README 링크/diff 검사 통과. [실측: 로컬 API/오디오 모의]
- publisher 정상 반환은 실제 C 수신/실행 확인이 아님. 실제 웨이크/STT/한국어 TTS·API·40문장/3초·C/D/Docker 검증은 미완료이며 P1 전체 또는 AC-INT 통과로 판정하지 않음. 전체 빌드/실물/유료API/subagent/push/PR 변경/병합은 수행하지 않음. 미추적 :memory:.ses 보존·커밋 미포함. [문서]

## 2026-10-06 PR #88 음성 공통 문서 Phase 정합성
- 사용자 추가 승인 “확인. 문서 내용 페이즈별로 구분해서 적어둬.”에 따라 docs/voice_llm.md와 본 CURRENT만 수정. 기준 HEAD f00c316, 최신 origin/main 33aef5c와 해당 문서 차이 없음 확인. 기존 6.1~6.5 제목·절번호 유지, 패키지 README/코드/설정/계약 정본으로 연결. 다른 변경/미추적 :memory:.ses 보존. [문서]
- P1 FR-INT-01~03 현재 웨이크/STT·단일 물품/제어·검증/폴백·확인TTS·평가발행금지와 미확정 모델/장치/예산·E/D 정답표·실측/수신 인계 구분. LLM저신뢰 자체 거절 뒤 검증된 규칙 폴백은 실행 후보가 될 수 있음, 퍼지매칭/오프라인STT/PTT/Piper는 미구현. 자유표현10포함40문장/2화자/90%, 실패≤5%·오실행0, 확인TTS3초의 P1 SOT 유지. [문서]
- P2 FR-INT-02 목표 추출→FR-PLN-02 자동계획/AC-PLN-01, P3 목록·분류/FR-ONT-03·복합작업FR-PLN-03/AC-PLN-02와 FR-TWN-02·AC-LLM-01 Stretch를 후속 계획으로 분리. query_state·퍼지매칭·이름없는추론수용/선택모델·#87학습은 Phase 미배정 미확정 과제로 구분하고 P1 평가를 미루는 근거로 쓰지 않음. [문서]
- 요구사항 관련ID/완료기준만 확인, 실제 core/adapters/node/params/패키지README와 계약 원본·온톨로지 물품/장소·기존 예시 대조. 문서 내 JSON 예시2개와 연결된 기존 목표 예시의 계약 검증, 6.1~6.5 제목 유지·문서 내 링크/앵커/절번호·diff 검사 통과. 테스트/전체빌드/장치/유료API/subagent/push/PR변경/병합 없음. [문서]
- ROS진단/source 제공과 C run_id/DB/D화면 자동연결은 구분. 실웨이크/STT/한국어TTS/API·40문장·3초/C-D-Docker는 계속 미검증. 정답 합의/확인정책/담당별 수신 인계가 남으며 문서 정합성 완료를 P1 또는 AC-INT 통과로 판정하지 않음. root 읽기전용 검토·기존PR88 게시조율 대기. [문서]

## 2026-10-06 PR #88 CI NumPy 수정 #90 main 통합
- 사용자 “PR #90 main에 병합됐어 #88 ci 오류 해결 후 push 해” 승인에 따라 기존 E voice 브랜치에 최신 main d6c3007(#90 merge)을 충돌 없이 merge. 병합 커밋5460cb0의 부모는 기존HEAD0336120/main d6c3007. CI·일정·C/E CURRENT의 승인된 main 변경 그대로 통합, 별도 CI/타 담당 코드 수정 없음. [문서]
- NumPy setup.py와 CI 설치 범위 numpy>=1.24,<2 일치, 계약 검증OK·diff 검사 통과. Python3.12.3/NumPy1.26.4의 임시 격리 venv(CI 기본 의존성만 설치, PYTHONPATH 제거·ROS/API/장치SDK 없음)에서 core pytest796 passed/22 skipped. MongoDB 연결 없음10개, ROS5/cv2 1/sounddevice4/API2개 미설치로12개 skip. 로컬은 REQUIRE_MONGO를 설정하지 않음; Mongo 서비스를 제공하고 REQUIRE_MONGO=1인 최신 원격CI의 확인이 남음. [실측: 로컬 격리]
- 기존 P1 FR-INT-01~03 검사 지원이며 AC/NFR 전체 달성 아님. 로봇 전체빌드/실물/API/문장평가 추가 없음. 이번 세션은 로컬 통합/CURRENT 커밋까지만 수행하며 root 게시조율 후 새 head CI 성공 확인 대기. 기존 미추적 :memory:.ses 보존/미포함. [문서]

## 2026-10-06 #20 평가 기준 판별 정책 보완(미커밋)
- 사용자 지시 “issue20_voice_evaluation.json 이 기준에 맞춰서 판별 기준 수정, 모호한 요청은 clarify로 처리” 승인 범위. 기존 PR88 merged main06f8e9e 기반 새 E 브랜치 codex/voice-evaluation-policy에서 구현/검증만 진행, 커밋/push/PR/병합 미승인·미수행. FR-INT-01~03(P1), AC-INT-01~03 유지. [문서]
- D 원본 /home/jonny/Downloads/issue20_voice_evaluation.json SHA256 5995fc225c0a2cc78aa1c9264eee6a07518ad674ed4923763acf5017377aec84 읽기 전용 대조, 최신 TC008 “지우개 찾아서 건네줘.” 포함. normal20/ambiguous10/unsupported10, 자유표현10/화자20씩. 원본 pending_e_d_review 상태 유지하며 자료 승인 완료로 간주하지 않음. [문서]
- 등록 물품/별칭 전체에 전체 긍정 문형을 확장: 찾아서/꺼내서→가져오기·건네기·전달트레이, 부탁/내게/있으면/필요한데. 건네기는 기존 P1 트레이 흐름이며 직접손/타목적지/반납/정리/던지기/다중요청은 미지원. 생산 코드에 40문장 또는 지우개 전용 분기 없음. [문서]
- 모호 대상단독/대명사/일반대상/대상불명 행동 요청은 guard/validate/규칙폴백에서 clarify·targets[]·실행허용false 고정. 기존 bare_item_policy=clarify 및 request_patterns 호환 유지, unknown 정책만 명시거절. 미사용 request_patterns로 실행하지 않음. 프롬프트와 패키지README/공통문서P1설명 정합성 보완. 새 확인 대화 프로토콜은 추가하지 않음. [문서]
- 관련 voice 검사343 passed/0 skipped, 기존 실제ROS topic/action1 deselected. 최신40 텍스트 각 규칙/모의LLM/예외폴백40/40(정상20find_item/eraser/허용, 모호10clarify/빈대상/보류, 미지원10unknown또는clarify/보류), 등록 이름·별칭 치환/별칭충돌보류·부정/질문/인용/직접손/타목적지·일반자유문형/LLM환각·저신뢰·시간초과·제어·중복·평가발행차단 회귀 확인. compileall/YAML/문서링크·앵커·기존절제목·JSON예시/참조SHA·diff검사 통과. [실측: 로컬 텍스트·API/오디오 모의]
- 실제 웨이크/STT/한국어TTS·API·40음성/90%·실제검증실패율/3초·C/D연결·안전운용은 미검증. D자료 승인/정답표 동결·진단과D결과필드 대응·후속확인정책은 인계, 로컬결과를 실제평가/AC달성으로 기록하지 않음. D원본/수집기/계약/타담당/로봇동작 변경 및 전체저장소빌드/실물/유료API/subagent 없음. 기존 :memory:.ses 보존/미포함. [문서]

## 2026-10-07 실제 실행 폴더 원본 기반 음성 시운전 복구 (미커밋)
- 사용자 원본 기반 수정 지시에 따라 /home/jonny/rokey_proj/VLA/ready2go, images/demo/HEADa59c4ec의 E voice 코드/설정/검사/문서/CURRENT와 로컬 logs/voice_eval/voice.local.yaml만 수정. 기존 .gitignore/:memory:.ses 및 aa39 미커밋 작업 보존, 브랜치 전환·커밋·push·PR 없음. FR-INT-01~03(P1), AC-INT-01~03 유지. [문서]
- STT.py/audio_device.py/wakeup_word.py/keyword_extraction.py 읽기 대조. 동일 마이크 선택·웨이크 스트림 close→sd.rec 5초/16kHz/int16/mono→sd.wait→표준WAV→whisper1/기존P1LLM 유지. 원본/모델/키 미변경·미복제, 모델 자동 다운로드 없음. RECORD_LIMIT 로그만으로 마이크/노이즈 원인을 확정하지 않음. [문서]
- 기본 fixed/commissioning 기능 시험, STT/LLM각30초 유한상한 제안. fixed 발화 종료와 확인 지연은 null/not_measured, 녹음 완료 시각은 별도. silence/ac_budget 기존 호환 유지, 신규 키 미지정 과거파일은 기존모드. 취소/overflow/상한/늦은결과폐기·모호clarify/대상검증·평가全발행차단 유지. [문서]
- 기본 한줄 단계 로그, 감지시에만 점수, 상세 voice_diagnostic은 diagnostic_detail ROS파라미터/YAML로 제공. D 원본 보존 명령을 README에 유지. 로컬 설정 root/모델 경로 유지, /usr/bin/espeak-ng 존재 확인·정식경로 적용, VOICE_MIC_DEVICE/명시입력/16k 자동선택 공유. [문서]
- 실제 녹음/외부API 실행은 수행하지 않음. 실제 웨이크→전사/한국어재생/LLM·40음성/3초·C/D연결/안전운용은 사용자 재시험과 인계가 남음. 전체로봇빌드/타담당/계약 변경 없음. [문서]
- 검증: 음성 모의 회귀356 passed/실제ROStopic-action1 deselected. 이후 상세로그/실제ready모드/STT·TTS오류유형 보완에 노드30개 및 추가로그4개 관련검사 통과. compileall/설정모드·root자산경로/YAML·문서링크·diff검사 통과. 프로젝트 ros2_ws에서 ready2go_voice만 빌드 성공; 최초 최종빌드 후 추가 로그 수정 지시가 도착해 voice만 1회 재빌드 성공. 전체로봇빌드 아님. [실측: 모의·로컬빌드]
- 재시험은 프로젝트 install source 후 python3+dotenv.load_dotenv('secrets/voice.env')로 node main을 실행하도록 README에 제공. 외부API/마이크는 사용자 직접 실행, 키 값 출력 없음. 기본 짧은 실패로그는 예외유형만 표시, 상세diagnostic_detail=true로 원본정보 보존. 시운전 기능 성공·40음성/3초AC실측은 아직 확인하지 않음. [문서]

## 2026-10-07 P2 서랍 내부 이동 문서 정합성
- 사용자 승인 및 #6 최종 승인(issuecomment-6006660678)에 따라 UC-P2·FR-ACT-04(P2)의 가림 물체 이동을 같은 서랍 내부 빈 공간→재관측→목표 handover_zone 전달→장애물 LIFO 원위치 복구로 정정. FR-VIS-03·FR-ONT-02·FR-PLN-02·FR-LOG-02 연결과 AC-ACT-02(10회/80%)·AC-ACT-03(2cm/위치·방향 기록)은 유지. 요구사항·domain·시연·하드웨어·플래너·Runner·일정·온톨로지 문서, knowledge README, 태스크 description 및 본 기록만 변경. [문서]
- E 문서/온톨로지 범위와 승인된 공통 문서 정정. 기존 절 제목 유지, 외부 임시 트레이 필수 배치/구매·TRAY_FULL 시연 가정·서랍이 비워진다는 설명 정정. 실행 태스크는 이전 예시로 표시하고 sequence/params/inputs/등록 이름은 유지. JSON description 표시는 실행을 차단하는 기능이 아님. [문서]
- 원본 world/초기상태·composite/task·config/places·계약·Runner/skills/vision_stub 소비 경로를 대조. 내부 이동 장애물의 located_in은 서랍 유지; pose/재식별·restore_stack 및 pre/effect 계약은 C·E, 배치/관측 호출·안전/오류·실패취소 복구는 B·C·E 인계. staging_tray/tray_view/로그 예시 삭제는 소비자와 계약 동시 정리·승인2명(그중E) 전 보류. 타 담당 코드/CURRENT·계약 스키마는 미수정. [문서]
- 검증: 수용 기준 변경 없음, 기존 제목 및 로컬 링크 대상 존재, 태스크 description 제외 실행 필드 동일, JSON/schema 보조 검사, diff 공백 검사 통과. 기존 음성·사용자 변경 해시 보존 확인. 문서 정합성은 코드 테스트 성공으로 대신하지 않음. 전체 빌드/pytest/실물 동작/자동 상태 갱신·실행 차단/복구 성공 검증 없음. [문서]
- 작업 경로 /home/jonny/rokey_proj/VLA/ready2go, images/demo 기준HEADa59c4ec. 이번 문서 변경만 로컬 커밋 대상이며 기존 음성 미커밋 기록·코드와 이미지 작업은 제외. 담당 문서 정정 완료, 계약·태스크 구현/실물 검증은 인계 대기. push/PR/병합은 수행하지 않음. [문서]

## 2026-10-07 P1 MeloTTS 교체 (미커밋)
- 조율 세션의 사용자 직접 승인 “MeloTTS 좋은 것 같아 이걸로 진행하자” 및 전달된 E 계획에 따라 실제 /home/jonny/rokey_proj/VLA/ready2go, images/demo/HEADc46ad85에서 구현. FR-INT-03(P1)·AC-INT-03(발화종료→확인TTS3초) 유지. 기존 FR-INT-01~02·평가/clarify·원본5초 녹음/STT/LLM·intent계약 유지. 기존 사용자·음성 미커밋·발표자료·:memory:.ses 보존. 이번 지시상 커밋/push/PR/브랜치전환/subagent 금지·미수행. [문서]
- E adapters/tts·melotts/worker/설치기, core/config·voice_node, voice params/실제 logs/voice_eval/voice.local.yaml·TTS검사, package.xml/setup.py 의존성·데이터 포함, voice README/docs/voice_llm·본CURRENT/.gitignore만 변경. 기존 audio/session/intent/API 및 기존검사 내용은 작업 전 바이트와 일치. 타 담당/계약/전체compose 미수정. [문서]
- .venvs/melotts의 Python3.12.3 CPU 환경과 models/tts/melotts 모델/소스/캐시 사용(둘 다 Git 제외). 공식 Melo209145371cff8fc3bd60d7be902ea69cbdb7965a, 한국어모델0207e5adfc90129a51b6b03d89be6d84360ed323, 한국어BERT1779cc0982ada0216dd6de0dd4e86fb78201926d 기록. 공식원본 고정tokenizers는 Python3.12 wheel 없음 확인. transformers4.41.2/tokenizers0.19.1/librosa0.10.2.post1·torch/torchaudio2.5.1+cpu 등 별도 실측환경을 params/melotts_requirements.txt로 고정. 한국어 전용 import/로컬BERT/외부URL폴백차단 패치를 params/melotts_kr.patch로 기록, 설치기에서 revision·패치·공개HF/PyPI/공식CPU index 재현. ROS환경에 설치하지 않으며 실행은 offline, 비밀키/외부음성전송 없음. [문서]
- 지속 worker 모델 재사용·실제WAV mono/int16/44.1kHz→기존PortAudio lock/speak(cancel,on_start,timeout,start_deadline)/첫DAC 유지. 준비 완료 전에 등록11물품 확인문장+설정4보류문장을 캐시하며 voice ready/웨이크를 시작하지 않음. 문장·모델파일/리비전·소스/worker·의존성/화자/속도/스레드 변경은 캐시무효화. 실패는 자동espeak전환 없이 보류, 합성 중 취소/기한초과는 worker종료/늦은응답폐기, 준비Ctrl+C와 중복close/watchdog 정리. [문서]
- 실측: 첫CPU2스레드 단문합성3.37~6.18초, 동일문장1/2/4스레드비교1=9.79/7.59,2=3.99/4.23,4=2.49/2.43초(첫BERT 로딩 포함). 4스레드를 제안 설정에 반영. 초기15문장캐시 준비49.09초, 기존캐시준비3.87초; 최종 모델파일해시 반영 후 동일확인문장 WAV/실제첫DAC재생 성공, 요청→첫DAC0.165초. 실제재생취소·만료요청보류·lock해제 확인. logs/voice_eval/melotts_runtime_0.wav는 시험 음성. [실측: CPU단문/이PC출력장치]
- 검증: 음성 핵심모의345통과(ROS 경로 누락으로 노드1모듈 제외 후 별도 노드33통과/실제ROS통합1deselected). 준비중Ctrl+C 보완 후 Melo핵심18통과, 합성중취소/시간초과 추가핵심검사 별도 확인. AST/XML/YAML·기존문서제목/로컬링크·diff 검사, 격리pip check/기록패치일치 확인. 프로젝트 ready2go_voice만 최종1회빌드 성공(1패키지2.10초). 전체로봇빌드/실제ROStopic-action/마이크/웨이크/외부API/로봇 실행 없음. [실측: 모의·voice빌드]
- 실제 청취 품질은 사용자 확인 필요. STT/LLM 포함 발화종료→첫DAC3초·40음성/정확도90%·검증실패율/C-D연결은 미검증. CPU합성·캐시·단문재생 결과를 전체AC달성으로 판정하지 않음. 장치/속도/준비상한60초·재생상한20초는 [팀 확정 필요] 제안, AC start_deadline3초 완화 없음. 담당교체/단문시험 완료·전체음성평가/통합 인계대기. [문서]

## 2026-10-07 웨이크0.7·무발화 보류·clarify 캐시 후속 보완 (미커밋)
- 조율 세션에서 확인한 사용자 직접 지시(영상 clarify 지연·wake threshold0.7·무발화STT 이상)와 승인된 E 후속 계획 범위. 실제 /home/jonny/rokey_proj/VLA/ready2go, images/demo/HEADc46ad85 유지, FR-INT-01~03(P1)·AC-INT-03 정본 유지. 기존 Melo 설치/코드·음성 미커밋·.gitignore·영상/발표자료·:memory:.ses 보존. 커밋/push/PR/브랜치전환/subagent/타파트/계약 변경 없음. [문서]
- 수정: E adapters/speech.py 추가·melotts.py 진행 로그, core/config·intent·session, voice_node, params/voice.yaml·로컬voice.local.yaml, 관련 test_intent/test_node/test_voice_followup, README/docsvoice_llm/본CURRENT. 원본 audio.py의 sd.rec→sd.wait 고정5초/16kint16mono·마이크선택/취소/overflow 정리는 유지. wake_threshold0.7은 사용자 확정이며 기존strict > 비교 유지. [문서]
- 정상 고정녹음 완료 PCM에 설치된 openwakeword Silero ONNX 로컬 검사,30ms프레임 VAD≥0.5+RMS≥speech_rms 연속0.15초 기준. VAD0.5/길이0.15초는 [팀 확정 필요] 제안이며 음량만으로 음성 단정/전체5초평균 사용 없음. 통과 시5초전체 전송·추가대기/자르기 없음. NO_SPEECH/VAD불가·오류/취소는 STT·LLM0호출/intent발행금지(실행모드도), source.record_error·llm_validation=not_called·execution_allowed=false 유지, LLM/STT실패로 잘못 집계하지 않음. fixed 발화종료/AC지연은 계속null/not_measured. [문서]
- clarify_prompts 단일 설정 원본에서 규칙/무발화/오류별 의미 유지, 자유LLM질문은 일반 고정 안내로 정규화해 최종clarify_question·실제안내 일치, source.llm_raw 원문 보존. 질문전체 사전합성캐시 후 ready/웨이크 시작(부팅질문재생 없음). unknown/find/control·D40판별정답·대상단독clarify 유지, 새로운 확인대화 없음. 기본로그에 발화검사/무발화/STT생략·TTS준비→cache사용/새합성→실제첫DAC시작/종료 구분, 상세진단 원문/tts_mock 유지. [문서]
- 검증: voice모의회귀406통과/실제ROS통합1deselected, 추가노드 실행모드 발행차단3통과. 빈PCM·무음·미세잡음·짧은음성·VAD오류/취소·설정·wake0.7경계·LLM원문/고정질문·기존5초전체전송/평가/취소 검사. 90ms순간구간 거절/180ms구간 허용은 모의이며180ms이상 웨이크잔음도 통과가능. AST/YAML/문서제목·링크/diff 및 기존변경보존·install코드일치 통과. ready2go_voice만 최종1회빌드 성공(1패키지1.71초), 전체로봇빌드 없음. [실측: 모의·로컬빌드]
- 실제 설치 Silero 모델의 합성 무음/미세·큰임의잡음/200Hz 정현파=False, 출처확인된 기존Melo시험WAV를16k로변환한 입력=True. 초기VAD 로딩포함무음0.738초·이후비음성약0.035초, 생성음성약0.002초. 새고정질문 캐시준비36.26초, 일반clarify캐시히트 응답5~7ms(실제DAC/LLM지연 측정아님). logs/voice_eval/clarify_fixed.wav 기록. 외부API/실제마이크/로봇 실행 없음. 로컬검증 최초자동심사시간초과 후 허용된1회재시도로 수행. [실측: 합성입력·캐시]
- 영상의4.406초 clarify지연은 조율세션 관측, 캐시미스원인 추정은 정확한원문/당시히트부재로 미확정. 영상에마이크PCM없음. 실제마이크의무발화/순간소음/잔음/짧은정상발화·오탐, STT/LLM포함40음성·전체3초·청취/C-D연동은 사용자재시험/인계대기. 패키지README의 현재사용자실행명령과 기본로그·diagnostic_detail=true로 재시험. 구현/담당검증 완료이며 실물문제완전해소/AC달성으로 보고하지 않음. [문서]

## 2026-10-07 사용자 승인 로컬 커밋
- 사용자 “커밋해” 승인으로 위 실제 실행 폴더 음성 시운전 복구·MeloTTS 교체·웨이크0.7/무발화/clarify 후속 변경을 로컬 커밋. 앞선 “미커밋” 기록은 당시 상태의 이력입니다. 최신 모의406+추가발행차단3 통과와 voice 최종1회빌드·설치코드일치 결과 재사용, 추가 코드 변경/재시험 없음. [문서]
- E voice 코드·설정·검사·의존성/재현자료와 docs/voice_llm·본CURRENT·Melo용 ignore만 포함. 기존 wakeword ignore 수정·발표자료·:memory:.ses 및 다운로드모델/venv·ignored 로컬 설정/시험WAV는 제외. images/demo 유지, push/PR/병합은 이번 승인에 포함하지 않음. [문서]
