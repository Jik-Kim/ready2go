# 음성 · LLM

> 의미·정책·책임·Phase·수용 기준은 [requirements.md](requirements.md)에만 정의합니다. 아래는 현재 구현, 미확정 설정, 후속 설계를 구분한 기술 설명입니다. 구현 코드가 존재하는 것과 실물 연결·수용 기준 통과는 구분합니다. [문서]

> 관련 요구사항: [FR-INT-01–03](requirements.md#fr-int-01). 구현·의존성·실행 준비는 [ready2go_voice README](../ros2_ws/src/ready2go_voice/README.md), 검증 기록은 [E CURRENT](../practice/E/CURRENT.md)를 참조합니다.

## 6. 음성 · LLM 인터페이스 (필수, 담당 E)

| 구분 | 범위·정본 | 현재 상태 |
| :--- | :--- | :--- |
| P1 | [FR-INT-01–03](requirements.md#fr-int-01)·[음성 정책](requirements.md#voice-policy) | E 패키지 구현 있음. 실제 음성/API·C/D 연결·AC-INT-01~03 미검증 |
| P2 | [FR-INT-02](requirements.md#fr-int-02)·[FR-PLN-02](requirements.md#fr-pln-02) | 이 문서의 후속 설계. 현재 P1 voice 경로에서 목표 계획을 실행하지 않음 |
| P3 | [FR-INT-02](requirements.md#fr-int-02)·[FR-ONT-03](requirements.md#fr-ont-03)·[FR-PLN-03](requirements.md#fr-pln-03) | 다중 서랍·지식 확장 후속 설계. 데이터 등록과 음성/실행 연결 완료는 구분 |
| Phase 미배정 | 상태 질의, 퍼지 매칭, 이름 없는 추론 수용 등의 개선안 | SOT의 명시적 Phase 배정 없이 P2/P3 구현 약속으로 확정하지 않음 |

### 6.1 파이프라인

**P1 현재 E 구현 경로** [문서]

```text
마이크 → hello rokey 웨이크 → 고정5초 시운전/무음 종료 녹음 → whisper-1 STT
      → 제어/미지원 규칙 또는 LLM 후보 → 의미 검증·필요 시 규칙 폴백
      → 검증된 단일 find_item: 중복 확인 → 확인 TTS → /voice/intent
      → unknown/clarify: 보류 안내 / cancel·status: 규칙 제어 경로
```

현재 기본값은 [voice 설정 원본](../ros2_ws/src/ready2go_voice/params/voice.yaml)의 `evaluation_mode`·`audio_enabled`를 확인합니다. 시작 시 ROS bool 파라미터 `-p evaluation_mode:=true/false`로 지정하고, 미지정은 false입니다. 시작 값은 YAML보다 우선하므로 기존 로컬 YAML true도 미지정/CLI false에서는 실행 모드이며, parser/Session 생성 전에 같은 유효 설정을 공유합니다. 실행 중 모드 변경 기능은 없습니다. 평가 모드는 **모든 intent 발행을 금지**하고 동일 입력의 TTS·진단 반복은 허용합니다. 실제 웨이크/STT 평가에는 준비한 장치 설정에서 audio를 켜야 합니다. 텍스트 override는 같은 파서의 디버깅 입력이며 음성 평가를 대신하지 않습니다. C 수신→태스크/진행·결과 피드백 및 로그, D 화면은 담당별 인계·실측이 남아 있습니다.

| 단계 | P1 현재 구현 | 미확정 설정·미구현 후보 |
| :--- | :--- | :--- |
| 입력 | 외부 강의 `hello_rokey_8332_32.tflite` 읽기, 기본 VoiceNode는 공유 RawInputStream의 동일 reader에서 prepared 캡처 경계부터 fixed5초를 수집하며, shared_input 없는 Recorder는 기존 sd.rec→sd.wait 경로를 유지합니다. 또는 RMS 무음 종료·보호 한도 | 장치·모델 배포·임계값은 팀 확정 필요. Push-to-talk는 미구현 후보 |
| STT | OpenAI `whisper-1`, 한국어·등록 물품 이름 prompt, API 단일 호출 슬롯 | 계정/지연 실측 필요. `faster-whisper small` 오프라인 폴백은 미구현 후보 |
| 해석 | LangChain·`gpt-4o` 후보 strict JSON → 기존 계약·등록 물품·보류 문맥·요청 단서 검증; 오류/시간 초과/검증 실패 시 좁은 규칙 폴백 | 모델·프롬프트·E/D 정답표 미확정. 퍼지 매칭은 구현하지 않음 |
| 확인 | 기본 `confirmation_enabled: true`: 검증된 “지우개 가져오기 요청으로 이해했어요.” 재생 성공 뒤 find_item 발행. 실패는 clarify 보류 | [수락 TTS 결정](requirements.md#acceptance-tts-policy)의 C 계약·실제 연결 대기 |
| TTS | 사용자 선택 MeloTTS, 별도 CPU 환경의 한국어 모델 재사용/문장 캐시→PortAudio 재생, 기존 `/voice/speak` Skill 액션 | 단문 합성·첫 DAC 재생 확인. [AC-INT-03](requirements.md#ac-int-03)·청취 품질·C/D 연결 미검증. espeak는 명시 선택 호환 경로이며 자동 폴백 없음 |

사용자 확정 웨이크 기준은0.7이며 기존 점수>기준 비교입니다. 고정5초 녹음 완료 후 로컬 Silero의30ms 구간 VAD+RMS를 검사하고, 무발화/VAD불가·오류/취소는 STT·LLM 및 intent발행을 생략합니다. VAD0.5·연속0.15초는 소음/짧은 발화로 튜닝할 제안값이며 실제효과는 미검증입니다. 정상 발화는5초 전체를 STT에 보내고 발화종료를 새로 추정하지 않습니다. [문서]

[문서: #194 구현] `clarify_prompts`는 기본/실패 안내이며, [승인된 음성 정책](requirements.md#voice-policy)에 따라 현재 대상·행동·판정과 의미 일치하는 내부 LLM `response_text`를 검증해 최종 문장으로 유지합니다. 공개 `clarify_question`은 질문에만 사용하며 내부 `_voice.final_text`와 실제 `tts.speak(text)`·최종 콘솔 안내는 동일 문자열입니다. 원본/대체 사유는 E 상세 파일에 보존합니다. 현재 질문의 후보·세대/epoch·유효성을 `Conversation`이 관리하고 쉼표/복합 답의 판단 뒤 한 번 소비하며 실제 질문 TTS 완료 후 명확한 답/대상 정정을 한 번 결합합니다. 캐시 WAV를 읽거나 재시작해도 질문 권한이 복원되지 않습니다. 이 구현은 실음성/AC·C 수락 시험 결과가 아닙니다.

원본 기반 기능 시운전 기본은 recording_mode=fixed/record_duration_sec=5/timing_mode=commissioning이며 STT/LLM 유한 상한은 각각30초 제안값입니다. 기본 VoiceNode는 하나의 SharedInput RawInputStream을 WakeAudio와 Recorder가 공유하고 fixed 녹음은 동일 reader의 prepared 캡처 경계부터 같은 프레임에서 기존 5초 분량만 수집합니다. shared_input 없이 쓰는 Recorder는 기존 sd.rec→sd.wait 호환 경로를 유지합니다. commissioning은 실행·평가 모드 모두에서 기존 유한 API 상한을 사용하며 3초 AC 예산을 적용하지 않습니다. 평가 true는 모든 intent 발행을 차단하고 false는 기존 확인 TTS·무발화·취소·실패·중복 게이트를 통과한 요청을 발행합니다. 고정 녹음 완료는 실제 발화 종료가 아니므로 speech_ended_*와 확인 지연은 null/not_measured, recording_ended_*만 별도로 기록합니다. 이 모드로 AC-INT-03을 통과했다고 보고하지 않습니다.

[현재 설정 원본 voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)은 시운전 STT/LLM 상한 각각30초, silence_sec=0.4, tts_reserve_sec=0.7입니다. 이전 STT1.1초/LLM0.8초는 AC 준비 후보였으며 현재 원본 값이 아닙니다. AC 모드의 값은 별도 실측해 확정합니다. silence/ac_budget 모드에서는 [AC-INT-03](requirements.md#ac-int-03)의 예산에 무음 대기·API·TTS 준비를 포함합니다. 남은 예산에 따라 STT/LLM의 실제 제한은 더 짧아질 수 있으며, 값의 합이나 설정만으로 실제 3초 달성을 선언하지 않습니다. 늦은 API 결과는 폐기하고 재시도를 쌓지 않습니다.

Melo 모델·설정된 고정 안내/등록 물품 확인 문장 캐시 준비 완료 후 웨이크 입력을 시작합니다. 사용자 확정 엔진은 MeloTTS·속도1.2입니다. 등록 물품별 요청 확인·구체 질문과 실제 P1 찾아오기/트레이 전달/미발견 문장, “서랍을 닫았어요”, clarify·사용자 prefill을 중복 제거해 준비합니다. 닫기 성공 후 안내는 C 태스크 [#140](https://github.com/Jik-Kim/ready2go/pull/140)(merge `0c0a971`)으로 main에 반영됐습니다. E 캐시 준비·C mock 통합 확인과 PC2 실물 실행 검증은 구분합니다. 속도/worker/모델 등의 캐시 키가 바뀌면 새 합성이 필요하고 동일 환경의 기존 디스크 캐시는 재사용합니다. 과거 상태 안내7종 포함64개 문장 기준으로 cold 합성하면 기존 전체 준비상한60초를 넘을 수 있어, 최초/속도·worker 변경 시 일반 노드 재시작 반복 대신 패키지 README의 재생 없는 사전 준비 절차와 운용 PC에서 결정한 별도 유한 상한을 사용합니다. 기존 YAML·AC3초·재생 상한은 바꾸지 않습니다. PC2 재시작 캐시·실물/청취 품질·AC3초는 미검증입니다. Google Cloud TTS 도입은 철회하여 새 SDK/키를 추가하지 않습니다. 준비/합성 실패·취소·기한 초과는 재생/발행을 보류하며 기존 TTS lock·첫 DAC 시각을 유지합니다. 설치 경로·공식 revision·Python3.12 호환 의존성/한국어 전용 패치와 단문 재생 명령은 패키지 README를 참조하십시오. 과거 속도1.0의 CPU4스레드 단문 합성 약2.43~2.49초와 캐시 조회 약3ms는 합성/조회 측정이며 전체 AC-INT-03 달성 근거가 아닙니다. [실측: 로컬 단문]

기존 `/runner/status` reliable/transient-local·depth10 읽기 전용 구독과 별도 TTS worker로 P1 중단/오류 안내를 제공합니다. 현재 halt_code의 ESTOP·확인 불가·HALTED를 우선하며 정지 완료를 단정하지 않습니다. 일반 실패는 관측한 running/task와 새 마지막 결과가 맞을 때 finally 이후 관측 시점에 안내합니다. 첫 latched/동일 사건·확인한 run_id는 반복하지 않고 높은 경고/새 회차가 낡은 대기·정상 음성을 무효화합니다. 일반 FAILED를 지속 잠금으로 만들지 않아 새 음성 확인/intent는 기존 규칙으로 진행하며, 현재 halt만 정상 TTS를 억제합니다. 상태 구독만 전용 `MutuallyExclusiveCallbackGroup`으로 동시 콜백 실행을 막으며 text/action은 Reentrant 그룹을 유지합니다. 모든 입력 순서·누락 방지는 보장하지 않습니다. 상태 콜백은 TTS/정지/복구/DB를 호출하지 않고 안내는 기존 lock/cancel/timeout/첫DAC를 사용합니다. 자체 TTS 실패는 로그만 남기고 재시도/재귀 안내하지 않습니다. 문구7종은 Melo 사전캐시에 포함됩니다. 현재 계약에 활성 run_id·이벤트 시각/순번이 없어 미관측 같은 태스크 지연 결과·전환 누락을 완전 구분하거나 중간 일반 실패를 즉시 알리는 것은 미구현이며 [#138](https://github.com/Jik-Kim/ready2go/issues/138)의 C 인계입니다. 실제 정지/실물·경고 재생 지연은 미검증입니다. [문서]

실행 모드의 동일 find_item은 중복 시간창 안에서 TTS 전에 보류하고 발행 호출 정상 반환 후에만 중복 기록을 확정합니다. TTS 실패·취소·시간 초과·발행 예외 후 재시도는 가능합니다. publisher 정상 반환은 C 수신·실행 성공 확인이 아닙니다.

### 6.2 지원 인텐트 (최소 세트)

요청의 의미·보류·폴백 정책은 [FR-INT-02](requirements.md#fr-int-02)·[음성 정책](requirements.md#voice-policy)을 참조합니다. 현재 파서는 `find_item`, `cancel/status`, `unknown/clarify` 경로를 구현하며 LLM 후보와 좁은 규칙 폴백을 구분합니다. 함수의 검사 통과가 자유 한국어 전체의 의미 정확성을 보장하지 않습니다. 핵심 부정/번역/제외 모의 보완과 남은 실음성 일반화·장치 평가 상태는 [패키지 README](../ros2_ws/src/ready2go_voice/README.md#설정과-동작-경계)를 확인하십시오. [문서]

| 단계 | 정본 참조 | 현재 E 연결 |
|---|---|---|
| P2 | [FR-INT-02](requirements.md#fr-int-02)·[FR-PLN-02](requirements.md#fr-pln-02)·[AC-PLN-01](requirements.md#ac-pln-01) | E 목표 해석·발행 미지원. C Runner의 목표 계획 경로와 별개이며 [플래너 설명](planner.md)을 대조 |
| P3 | [FR-ONT-03](requirements.md#fr-ont-03)·[FR-PLN-03](requirements.md#fr-pln-03)·[AC-PLN-02](requirements.md#ac-pln-02) | 목록/클래스/복합 작업 호출 미연결. 등록만으로 음성 어휘·trigger가 추가되지 않음 |

`query_state`·퍼지 매칭·이름 없는 추론 수용·Push-to-talk·오프라인 STT/Piper·새 웨이크 학습 [#87](https://github.com/Jik-Kim/ready2go/issues/87)은 미확정 선택 제안입니다. 계약의 허용 enum과 현재 기능·착수 승인·Phase 배정은 구분합니다.

### 6.3 비기능 요구사항

수용 기준은 [AC-INT-01](requirements.md#ac-int-01)·[AC-INT-02](requirements.md#ac-int-02)·[AC-INT-03](requirements.md#ac-int-03), 평가·보류 의미는 [음성 정책](requirements.md#voice-policy)에만 정의합니다. 현재 실음성 통과 기록은 없습니다. E/D 정답표 승인·문장 동결·실음성 후속 대화 평가는 인계 사항입니다. 모의 회귀·설정값·합성 속도로 실제 음성 평가 완료를 대신하지 않습니다. [문서]

현재 `bare_item_policy` 호환 검사·`request_patterns` 미사용, STT 실패 보류·LLM 검증 실패 후 폴백, 텍스트 override는 패키지 구현 설명을 참조합니다. 일반 요청의 API 처리 중 새 웨이크 청취 제한은 유지합니다. #187 독립 정지 입력은 처리/TTS/질문·Runner 실행 중 웨이크 없는 새 무음 종료 녹음과 별도 STT 슬롯으로 작성했으며 실행 검증은 후속입니다. 음성 취소의 운용 경계는 [NFR-SAF-02](requirements.md#nfr-saf-02)와 [안전 절차](safety.md)를 따릅니다.

### 6.4 LLM 인텐트 파서 (주 경로, 담당 E)

**P1 현재 출력·검증** [문서]

강의 `keyword_extraction.py`·STT 호출 구조를 참고한 [adapters/api.py](../ros2_ws/src/ready2go_voice/ready2go_voice/adapters/api.py)는 현재 온톨로지의 **물품 키·한국어 이름·별칭**을 prompt에 넣습니다. 목록·클래스·레지스트리 intent 자동 주입은 현재 경로에 없습니다. LangChain 후보 모델은 temperature 0·strict JSON을 사용하며 런타임 targets enum은 등록 물품 키로 생성합니다.

```text
제어/미지원·모호 규칙 → 필요한 경우 STT 텍스트 + 등록 물품 어휘 → LLM 후보
  → 기존 intent 계약 + P1 허용값 + 단일 등록 대상 + 확신도 + 발화 의미 검증
  → 정상 unknown/빈 targets: 검증된 내부 사유에 맞춘 물품/요청 미지원 안내
  → 오류·시간 초과·일반 검증 실패/LLM 없음: 좁은 폴백; 미등록 find_item은 원인 보존 후 미지원 보류
  → 최종 find_item: 평가/세대/중복/확인 TTS 게이트 → /voice/intent
```

기본 P1 LLM 요청 스키마는 `intent`를 find_item/unknown/clarify로 제한하고 `targets`, `confidence`, `clarify_question`과 내부 `response_text/rejection_reason`을 받습니다. 등록키 targets enum·additionalProperties=false를 유지하며 사유도 required/유한 enum입니다. `unknown/빈 targets`의 미등록 물품과 미지원 요청 사유를 검증해 내부 `_voice.reason`으로 옮기고 최종 안내 선택에 사용합니다. find_item/clarify의 사유는 null이며 판정·등록 대상과 모순되거나 미지원 사유 값이면 검증 실패로 처리합니다. 원본 후보 문구로 사유를 추론하지 않습니다. response_text와 rejection_reason은 공개 intent의 새 필드가 아니며 response_text는 검증된 `_voice.final_text`로만 사용합니다. cancel/status는 규칙 경로입니다. 외부 출력 정본 [intent.schema.json](../contracts/intent.schema.json)은 intent/confidence가 필수이며 현재 출력에서 targets·필요한 확인 질문과 진단 source를 덧붙입니다. strict 응답 형식이 사용자 의미의 정확성을 보장하지 않아 코드가 다시 검증합니다. P1은 goals/query 실행을 허용하지 않습니다.

“지우개 찾아줘.”의 검증된 출력 예시(source 생략):

```json
{"intent": "find_item", "targets": ["eraser"], "confidence": 0.99}
```

이름 없는 추론의 실행 보류 예시:

```json
{"intent": "clarify", "targets": [], "confidence": 1.0, "clarify_question": "물품 이름과 가져오기 요청을 확인해 다시 말씀해 주세요."}
```

unknown/clarify는 정상 탈출값이며 그 자체를 LLM 검증 실패로 집계하지 않습니다. 진단 `llm_validation=passed`도 사용자 확인 완료·실행 허용을 뜻하지 않습니다. 현재 프롬프트는 생략된 부탁과 다양한 받기 요청을 의미로 해석하며 예시 문장에 한정하지 않습니다. 다만 프롬프트·정답표의 정확도는 E/D 평가로 확인해야 합니다. 모델 이름/속도 제안만으로 검증 코드나 플래너가 의미 정확성을 보장한다고 표현하지 않습니다.

**P2/P3 계약·후속 출력 설계** [문서]

- 계약 enum에는 find_list/find_class/achieve_goal/query_state도 있으나 스키마가 허용한다는 이유로 해당 기능·Phase를 자동 실행하지 않습니다. P1 런타임 허용값은 6.2와 같습니다.
- P2 achieve_goal의 실행 필드·타입은 [기존 계약](../contracts/intent.schema.json)이 원본입니다. `p2_goal_enabled` 옵트인 시 [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)의 `p2_goal_catalog`와 현재 world·발화를 대조해 내부 목표 후보를 반환합니다. 기본 P1 경로는 유지하고 Session은 선정 목표의 명시 opt-in·요청 상관 opt-in·평가/중복 검사를 적용합니다. 노드는 검증된 현재 C 연결도 확인합니다. 검증된 목표 문장은 현재 요청의 accept_text로 준비되며, E의 수락 전 중복 TTS 없이 실제 C 수락 뒤 기존 speak 경로로 재생하도록 연결했습니다. 실제 C 매핑은 미완료입니다. 명시 열림이 포함된 선정 복합 목표는 열림을 보존하며 초기 상태나 행동 순서를 생성하지 않습니다. [기존 목표 예시](../contracts/examples/intent_goal.json)의 다른 목적지는 선정 목록에 포함되지 않습니다. 계획/실행 연결은 [FR-PLN-02](requirements.md#fr-pln-02)·[FR-ONT-02](requirements.md#fr-ont-02)의 통합 선행이며 현재 E 발신 경로는 개발 단계입니다.
- P3 목록/클래스 대상 및 복합 태스크 호출은 해당 요구사항·담당 연결 검증이 필요합니다. 계약의 레지스트리 intent 런타임 추가 설명은 후속 연결 설명이며 현재 고정 enum을 임의 문자열이 통과한다는 뜻으로 사용하지 않습니다.
- `query` 객체/null은 계약이 허용하지만 상태 질의 설계의 Phase는 미확정입니다. goals/query/source를 모든 intent의 필수 출력으로 확정하지 않습니다.

<a id="voice-diagnostics-current"></a>
**현재 진단과 C/D 인계** [문서]

상세 증빙은 `diagnostic_detail=true`일 때 설정된 `diagnostic_file`의 민감정보 필터 적용 JSONL에 기록됩니다. 각 줄은 이벤트 객체이며 `voice_diagnostic` 래퍼 없이 `event`, `request_id`와 이벤트별 필드를 최상위에 둡니다. 콘솔과 `tee` 로그는 요약이므로 전체 진단 JSON을 찾는 위치로 쓰지 않습니다. D의 증빙 확인은 저장된 JSONL에서 `interpretation.intent`, `intent.published`·`intent.intent`, `tts_finished.timing`을 확인하고 request_id와 이벤트 시각으로 이어 보십시오. `published=true`는 발행 호출 반환을 뜻하며 C 수신·실행 성공 증빙은 아닙니다. 원본 LLM 응답은 `interpretation` 이벤트에 한 번 보존되고 후속 이벤트에는 반복되지 않습니다. TTS `timing`은 합성 대기 `synthesis_wait_sec`, Melo `cache_hit`·`worker_synth_sec`, 성공 시 첫 DAC→PortAudio finished callback 구간 `playback_sec`·종료 시각/기준을 구분합니다. worker 처리 시간은 캐시 조회/합성 시간이며 Runner 요청부터 종료까지의 전체 시간을 합성으로 해석하지 않습니다. 이 정보는 로그에만 추가하며 기존 Skill 액션 결과·intent source 필드와 구분합니다. source 부가 필드 수신/의미와 D의 저장 예시·수집 절차는 담당자 확인이 필요하며 C run_id/DB 실행 로그의 inputs·D 화면 자동 연결은 미검증입니다. 물리 재생·모의 시각을 구분하며 합성 시작이나 텍스트 입력 시각을 AC-INT-03 실측으로 대신하지 않습니다.

[문서: 실행 연결 대기] [부분 결과 정책](requirements.md#verification-policy)은 같은 run의 실제 단계별 검증 결과가 E에 전달되어야 구체 안내에 적용할 수 있습니다. 현재 `/runner/status.last`의 전체 상태·오류만으로 전달 검증이나 복구 실패를 추정하지 않습니다. C의 실제 결과 수신 원본이 확정되기 전에는 기존 원인 경고를 유지합니다. [빈손·신선도 승인](https://github.com/Jik-Kim/ready2go/issues/43#issuecomment-6105675499)의 값 원본·적용은 B/C 담당이며 E의 내부 모의 입력을 운영 허가로 사용하지 않습니다.

[현재 구현: E-VOICE-FLOW-20261012-01] 일반 P1의 질문 답/빈 전사 처리는 [정본 음성 정책](requirements.md#voice-policy)을 따릅니다. Conversation의 기존 질문 ID/세대/기한을 검사하고 정상 빈 SDK 결과의 내부 표식은 새 delivered/만료 갱신 없이 보존합니다. 자연스러운 답은 현재 등록 대상과 공통 parser 검증/규칙 폴백에 연결하며 대상 없음을 묻는 경로와 running/잠금 상태 안내를 구분합니다. 원래 해석/실행 보류는 내부 `_voice.original_interpretation`/`execution_hold_reason`로 기록하고 안내 발행은 C 수락과 구분합니다. 새 cue·원음/trim·silence 비교·더미 자동완료는 [사용자 시험 명령과 제한](../ros2_ws/src/ready2go_voice/README.md#통합-음성-흐름--사용자-직접-시험)을 참조하십시오. 값/문구는 voice.yaml의 voice_flow가 원본이며 실제 STT 미검출 해소·echo/첫 음절·물리 수용은 미검증입니다. #43/#152와 공개 wire는 변경하지 않았습니다.

### 6.5 (Stretch) LLM 태스크 JSON 생성

**P3 후속 계획**: [FR-PLN-03](requirements.md#fr-pln-03)·[FR-TWN-02](requirements.md#fr-twn-02), [AC-LLM-01](requirements.md#ac-llm-01)에 연결된 Stretch입니다. 현재 P1 voice 구현에 없으며 고정 Day 11 문구로 현 일정·착수 승인을 확정하지 않습니다. 착수·범위·담당 C/E/A 연결은 별도 합의가 필요합니다. [문서]

- 계획 흐름: 미정의 자연어 요청 → [Runner 7.1 원자 동작·제어 블록](runner.md)으로 태스크 JSON 생성 → [태스크 스키마 7.2](runner.md) 검증 → 조건·결과 기반 기호적 드라이런 → [트윈 10장](twin.md) 사전 검증 → 승인된 실물 운용 절차에 따른 실행. 현재 자동 연결된 기능으로 설명하지 않습니다.
- 생성 태스크의 검사/거절, while max_iter·작업 영역·E-stop 등은 후속 구현·계약 대조 항목입니다. 트윈 통과를 실물 안전 검증으로 간주하지 않습니다.
- 완료 판정은 [AC-LLM-01](requirements.md#ac-llm-01)을 참조합니다. 현재 태스크 직접 생성 경로는 미구현입니다.

<a id="p2-safety-voice"></a>

### 6.6 P2 정지·복구 후 명시적 재개 준비

[문서] 목표·정책·책임·검증 기준은 [FR-SAF-01–03](requirements.md#fr-saf-01)·[AC-SAF-02–04](requirements.md#ac-saf-02)을 참조합니다. 담당별 진행 상태·합의값 반영 여부는 [#153](https://github.com/Jik-Kim/ready2go/issues/153)을 참조하십시오.

[문서: 구현 대조 기준 `65148d4`] #144 상태 안내·Melo 캐시와 #165 내부 정책, #167 Runner 단계 재개 준비가 main에 병합됐습니다. C `resume()`은 잠금 해제이며 `resume_run()`은 별도 준비 경로입니다. 이 병합이 E 음성·장치 운영 연결이나 안전 수용 기준 완료를 뜻하지 않습니다. 기존 파서는 cancel/status와 일반 요청을 처리하며 새 복구/재개 wire enum은 없습니다. 이 병합 당시 일반 listener는 busy/speaking/TTS lock 중 입력을 제한했습니다. 현재 #187 독립 정지 입력과 #152 typed 질문/녹음 경로를 추가 작성했으며, 실제 장치/SDK와 C 재개 매핑은 미검증·미연결입니다. 항상 음성 정지를 보장하거나 실제 재개 AC가 완료된 것으로 설명하지 않습니다. B MotionState는 관절 변화와 state를 사용하지만 조회 실패 시 상태 fallback, ESTOP 상태 즉시 반환 경로가 있어 ESTOP 응답을 완전한 물리 정지 증빙으로 쓰지 않습니다.

[구현: ROS 비의존 준비] `core/recovery_confirmation.py`는 E 내부 정책이며 현재 safety_exchange와 노드 typed 경로에서 호출합니다. 실제 C 생산자 매핑은 미연결입니다. `from_config`가 E 구간 설정을 읽습니다. 현재 사건의 고유 질문 ID에 대해 `registered`의 같은 work/현재 seq ACK를 받은 뒤 `tts_started`·실제 `delivered`·`admit`·`answer`를 순서대로 검사합니다. 중복 등록은 기한을 갱신하지 않습니다. `expire`·거절·TTS/STT 실패는 질문을 무효화하며 work는 유지합니다. 명시 종료는 `TaskEndCandidate`로 구분하고 부정 종료는 받아들이지 않습니다. 두 종료 경로는 E 로컬 사건을 퇴역 처리해 같은 사건의 높은 seq 갱신으로 재개 대상을 복원하지 않습니다. 이는 C 종료 확정이나 운영 종료 요청 구현이 아닙니다. `begin_independent` 뒤 새 녹음·SDK·STT·현재 등록 확인·증빙을 통과한 요청만 일회성 후보를 반환합니다. 과거 질문의 응답을 전용하지 않습니다. 이전 독립 요청의 STT/후보 콜백은 현재 요청을 변경하지 않고 거절하며, 현재 요청 자체의 실패/만료만 현재 문맥을 무효화합니다. 같은 boot/run/halt의 최신 신뢰 상태가 기존 의미와 충돌해도 관측 seq를 순서 하한에 기록하고 현재 확인·기존 입력을 무효화합니다. 충돌 상태는 실행 대상으로 채택하지 않으며 그 seq 이하의 과거 상태/ACK로 확인을 복원할 수 없습니다. 잘못된 입력·미확인 ACK는 순서 하한을 올리지 않습니다. E 재기동은 질문/요청을 버리고 새 C 상태 확인 전 보류하며, Runner boot 변경·현재 C 완료는 보존 work를 폐기합니다. 이 입력과 후보는 실제 C 동작·잠금 해제·새 run을 생성하지 않습니다. 정책의 의미·책임은 [재개 접수 정본](requirements.md#resume-admission-policy)을 참조하십시오.

[문서·코드 대조: E-P2-SAFETY-TRIM-20261011-06] E의 등록 ACK 대기·등록 확인→TTS 완료 전용 타이머 설정과 검사는 제거했습니다. `registered`와 `independent_registered`는 유지하며 현재 유효 등록 확인 없이는 TTS/후보를 만들지 않습니다. 질문의 `valid_until`은 신뢰된 C 유효성에 대응하는 E 로컬 기한 입력이며 C 절대 monotonic 값을 넣는 필드가 아닙니다. 기한 대응·C 만료 상태와 현재 등록을 전달하는 운영 adapter는 여전히 미연결입니다. 실제 재생은 기존 `PCMTTS.speak`의 `tts_timeout_sec` 제한을 통과한 완료만 `delivered(success=True)`로 전달해야 하며 timeout/실패/취소는 실패로 전달해야 합니다. 이 core가 기존 재생 제한이나 C 질문 기한을 대신 생성하지 않습니다.

[문서·코드 대조: 검사 재사용] 녹음 순서 검사는 `admit`/`admit_independent`에서 수행하고, 같은 요청의 `AudioRequest`/`independent_audio`와 STT 분류 `independent_result`를 후속 ACK/소비에서 재사용합니다. 같은 의미의 중단 작업에서 정상 seq만 진행하면 이 입력과 ACK를 보존하고 다시 녹음/분류하지 않습니다. ACK는 같은 현재 seq 또는 같은 사건의 더 높은 seq를 받아들이며 과거 상태 갱신·중복 소비는 계속 거절합니다. 새 halt/boot·E 재시작·현재 작업 완료·더 높은 seq의 의미 충돌에는 기존 질문/요청을 무효화합니다. 소비 시점의 유효 기한·현재 작업/요청·새 안전 증빙은 매번 확인합니다. 새 범용 캐시·공개 필드·운영 발행은 추가하지 않았습니다. C/B 상태의 seq는 실제 관측 신선도 증거가 아닙니다.


[제안·계약 차단] 내부 `StoppedWork/Evidence/Question`은 wire 필드나 확정 계약이 아닙니다. 명시적 복구 의사·B 실제 정지/컨트롤러 복구 결과·C 재개점/조건·부팅 세대/순서/유효성·질문/발화 연결과 콜백 직렬화는 [승인 대기안](interfaces.md#p2-safety-proposal)에서 협의합니다. C #152 계약안 v0의 `halt_event_id`와 내부 `StoppedWork.stop`의 대응은 계약 확정 후 adapter에서 대조해야 하며 현재 승인된 wire 연결이 아닙니다. 복구 중 정지 또는 증빙 불명은 후보를 무효화해야 합니다. B/C 후속 검사의 기준은 [FR-SAF-03](requirements.md#fr-saf-03)입니다. 실제 증빙 adapter·E 후보·C 실행 보존의 연결은 미확정입니다.

[미연결] 복구 결과 ROS 수신, 질문 실제 TTS·캐시, 발화 채취/자기 음성 억제, 우선 정지 경로, C 잠금/재개 요청은 아직 연결하지 않았습니다. P2 복구 정책은 ordinary intent·Runner notice·prefill·listener 운영 경로에 연결하지 않았습니다. TTS 완료 뒤 녹음 시작 검사는 실제 스피커 자기 발화가 완전히 차단됐다는 증거가 아닙니다. 모의 정책 시험은 실제 음성 수신·로봇 정지·복구·재개 완료의 근거가 아닙니다.

### E-C W3/W4 매핑 준비 — 2026-10-13

[구현: E 작성·운영 보류] [control_mapping.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/control_mapping.py)와 VoiceNode의 선택 `bind_control_source`가 기존 pub/status 경로·요청 상관 opt-in을 재사용합니다. 설치된 계약 검증과 검증 source/boot/GID·증가 seq·현재 work/질문/요청 echo를 통과한 후보만 소비하며 실제 SDK 반환 receipt를 분류·등록·송신까지 보존합니다. 질문 실패의 expired와 END 접수·현재 정지/보존 폐기·안내 재생을 구분합니다. 실제 C 잠금/상태/로봇을 E가 변경하지 않습니다.

[문서: 통합 선행] 작업 기준 `2d6551b9`에 설치된 [intent 원본](../contracts/intent.schema.json)은 W3를 허용하지 않아 발행을 보류합니다. 이후 C 5개 PR main 병합과 E 설치/운영 연결은 구분하며, source binding·실제 GID·B/C 안전/신선도 `SafetyProof`·E-local 유효기한 provider는 기본 미설치입니다. C offered/needs·잔여초/UTC와 B empty/성공을 증빙으로 추정하지 않습니다. 재개 terminal echo가 소실되면 수락 안내/사건 종료도 보류합니다. 현재 작성 범위·사용 방법·시간 helper의 실제 경계·부족한 원본/시계·담당별 인계는 [Voice README](../ros2_ws/src/ready2go_voice/README.md#c-제어-wire-매핑-준비--2026-10-13)·[CURRENT](../practice/E/CURRENT.md#e-c-w3-wire-20261013-02)를 참조하십시오. 기준은 [FR-SAF-01/03](requirements.md#fr-saf-01)·[AC-SAF-02/04](requirements.md#ac-saf-02)·[접수 정책](requirements.md#resume-admission-policy)입니다. 아래 기존 더미/typed 준비와 당시 검증 이력은 실제 C 운영 연결 완료를 뜻하지 않습니다.

### #78 E 안내·새 실행 후보 준비

[문서] 기준은 [모션 차단·놓침 후 새 실행 정본](requirements.md#halt-motion-policy)·[일반 재개 접수](requirements.md#resume-admission-policy)입니다. `runner_notice.py`는 기존 C 상태의 `OBJECT_DROPPED`/`SENSOR_INVALID`를 각각 놓침 보고/센서 이상 보고로 분류하고 실제 정지·상태 확인을 안내합니다. `HALT_MOTION`은 이 core의 분류 상수이며 C 잠금을 구현하거나 재개를 허용하지 않습니다. 현재 상태 JSON에는 실제 정지·대상·놓침 관측을 증명하는 연결이 없습니다. `phase=halted`나 `task_id`로 물체 회수 안내를 만들지 않습니다. B의 현재 place는 `check_hold`의 센서 이상도 운반 중 놓침 코드로 반환하므로 코드만으로 실제 낙하를 확정하지 않습니다.

[구현: ROS 비의존 준비] `recovery_confirmation.py`의 `StoppedWork.cause/skill`은 현재 내부 사건의 원인/실제 스킬을 식별하는 입력이며 wire 필드가 아닙니다. `notice(HaltNoticeEvidence)`는 같은 사건·신선한 실제 정지·낙하·등록 대상 근거를 모두 받은 place 놓침에만 대상별 복원 안내를 만들고, 증거 부족/과거 사건에는 고정 미확인 안내를 반환합니다. 센서 이상 안내는 빈손·낙하를 확답하지 않습니다. 이 입력을 채우는 B/C 관측 adapter와 실제 안내 재생은 미연결입니다.

[구현: ROS 비의존 준비] place 놓침에는 `NewStartEvidence`의 같은 사건·기존 실행 종료·물리 복원·그리퍼/물체/서랍/작업영역 확인·C 상태 동기화·B/C 조건·신선도 입력을 검사합니다. 일반 `Evidence`로는 질문을 만들지 않으며 검증 뒤 질문도 재개 질문과 다른 `new_start` 후보입니다. 명시적 새 시작 응답만 `NewStartCandidate`를 1회 반환합니다. 이는 기존 작업 식별을 감사용으로 보존하는 내부 자료형으로 새 run을 생성하거나 기존 place/pick·좌표/effect를 실행하지 않습니다. “다시 넣었어”와 “재개해”는 이 후보를 내지 않습니다. 같은 기존 run의 재정지·취소·TTS 실패로 재개 경로를 되살리지 않고, `SENSOR_INVALID`의 일반 재개에는 추가 `sensor_normal` 증빙을 요구합니다. 기존 질문/녹음/실제 SDK 경계·유한 만료 검사는 내부 보호로 재사용하며 새 실행의 운영 접수 계약을 확정한 것이 아닙니다.

[문서·코드 대조: 2026-10-10] C의 [PR #202](https://github.com/Jik-Kim/ready2go/pull/202) 병합 원본은 놓침·센서 이상을 기존 `HALT_CODES`로 처리해 `ABORTED`·잠금, 비모션 finally만 허용, 잠금 중 새 요청 거절을 적용합니다. 두 오류는 재개 대기 보존에서 제외합니다. C 코드의 차단과 E 내부 후보의 검증은 별개이며 실물 정지 증거로 대체하지 않습니다.

[미연결/인계] `runner_notice.blocked`는 정상 안내 억제 상태이며 E 별도 글로벌 모션 잠금이 아닙니다. TTS 실패는 내부 질문을 폐기하고 원인/후보 제한을 유지하지만 C 잠금의 지속을 E 모의 시험으로 증명할 수 없습니다. B handover place의 센서/놓침 반환 구분·보유 확실성·실제 정지/신선 관측, C 관측 기반 상태 동기화·안전한 잠금 해제·명시적 새 run 운영 연결, 신규 wire/예시/ICD의 E 포함 2인 승인이 남아 있습니다. `reset_state()`는 시작 스냅샷 복원이며 잠금 해제·실제 상태 검증이 아닙니다. 남은 B/C 협의·운영 adapter·실물 검증은 [#78](https://github.com/Jik-Kim/ready2go/issues/78)·[#152](https://github.com/Jik-Kim/ready2go/issues/152)·[#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 추적합니다.

[문서: 게시 상태 2026-10-10] 선행 [PR #193](https://github.com/Jik-Kim/ready2go/pull/193)·[PR #198](https://github.com/Jik-Kim/ready2go/pull/198)·[PR #202](https://github.com/Jik-Kim/ready2go/pull/202)는 main에 병합됐습니다. #198 병합 커밋은 `667f0b8a0e59a459ac0e1fb1bcf5b100413edaab`이며 [PR #203](https://github.com/Jik-Kim/ready2go/pull/203)의 현재 base는 main입니다. E 변경·검증 및 게시 기록은 [CURRENT](../practice/E/CURRENT.md#203-병합-상태-현행화--e-203-merged-status-20261010-02)를 참조하십시오. 선행 코드 병합과 위의 운영 연결·실물 검증 후속은 구분합니다.

### #43·#152 E 내부 정책과 C v2 회신안 (미승인 계약)

[문서: E 통합 준비·검증 이력] 아래 호출은 E 내부 모의·회귀/격리 ROS 검증 이력이 있습니다. 원격73ba549의 직접41건·38800a8의 전체CI2632 passed/41 skipped, 로컬12e0c29의 리뷰 회귀와079232/940c1f83의 검사는 각각 이전 대상의 근거입니다. 이번 통합의 새 최종SHA 전체CI는 아직 미실행이며 수치를 합산하거나 전용하지 않습니다. 실패/부분 검사·실제C 운영 미연결·실음성/실물 미검증은 [E CURRENT](../practice/E/CURRENT.md#pr227-final-integration-20261012-01)에서 구분합니다. 정책은 [사후 검증](requirements.md#verification-policy)·[재개 접수](requirements.md#resume-admission-policy), 실행 구간은 [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)을 참조합니다.

| E 생산자·수신자 | 현재 작성한 호출 | 실제 통합 선행 |
| :--- | :--- | :--- |
| #43 입력 → VoiceNode 질문 작업 → Session.confirm_audio → 기존 publisher | asked 후보 송신·현재 등록 관측·TTS 증빙·새 capture·SDK 접수·답/한 번 재질문, 같은 실행 검증 결과 안내 | place_input의 question/registered/result는 개발 가정입니다. 실제 질문 출력·confirm 수신·등록/시계·단계 결과를 매핑해야 합니다. |
| #150 parser → Session → RequestRun → VoiceNode._deliver/speak | 선정 목표와 최종 문장 재검증·요청 payload 보존·계약07 요청 ID/intent/run 결정/run ID 상관(goals echo 없음)·현재 수락 run에 문장 한 번 재생·같은 run 완료 안내 | 실제 현재 C 생산자 확인과 수락/first gate, B 파지 및 C 계획·검증 결과 |
| #187 독립 무음 종료 녹음/별도 STT·control 및 질문 STT → 기존 cancel publisher | 처리/TTS/질문·Runner 실행 중 웨이크 없는 새 입력, LLM/P1 STT 슬롯/TTS 종료 대기 없음, 동일 세대 발신·취소 우선 | 단일 SharedInput·기존 임계값을 재사용하며 녹음/별도 STT/기존 cancel 발행은 모의로 확인했습니다. 일시 AUDIO_OVERFLOW는 손상 reader/PCM을 버리고 새 reader로 재청취하며, close·stop_event·비복구 입력 오류는 청취를 종료합니다. 진단 실패는 기존 오류 보고로 표시합니다. 실제 장치 경합·overflow 복구는 미검증입니다. 클라우드 지연/실패·자기 TTS 문구 대조 한계·실제 정지 AC는 후속입니다. 실제 정지·잠금·그리퍼 동작은 B/C 소유입니다. |
| #152 typed 상태 → SafetyExchange → 질문 작업/Session.safety_audio → typed sender | 기존 RecoveryConfirmation의 등록·TTS·새 녹음·SDK·질문 답, 독립 새 발화의 등록 확인·재개/종료 후보, 복구 요청·일반 cancel 작업 보존 | 안전 상태/증빙·유효기간을 C/B 입력에 대응하고 typed sender를 승인된 공개 규약에 연결해야 합니다. |

[문서: 종료940c 통합] 일반·독립 stop SDK의 명시 종료는 현재 run/검증된 boot/세대에 묶어 기존 cancel과 현재 typed 정지 확인 뒤 종료 후보·TTS proof·명시 수락으로 연결합니다. 원발화는 새 SDK/독립 재개 등록 증빙으로 재사용하지 않습니다. 동일 heartbeat는 유효 안내를 유지하고 재정지/타run/boot·미확인/TTS 실패는 잘못된 idle을 차단합니다. 정확 “중지”, 제어4문장 공통 prefill과 stop/safety `stt_control_prompt`는 [Voice README](../ros2_ws/src/ready2go_voice/README.md#종료중지-최소-연결--2026-10-12)를 참조하십시오. 기존 cap256/startup60/prepare120과 일반 물품 힌트를 유지합니다. 실제 C 종료 wire/수락·보존 폐기 adapter와 실음성·실물 검증은 선행 미완료이며 더미 종료는 COMPLETED/effect/잠금 해제가 아닙니다.

[문서: 복구 입력 경계] [safety_exchange.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/safety_exchange.py)는 기존 core를 호출하며 공개 intent를 추가하지 않습니다. VoiceNode의 safety_stopped/offer/registered/independent_registered/completed는 실제 통합 매핑용 typed 입력입니다. valid_state와 Evidence는 호출자가 실제 원본으로 확인해야 하며 seq나 발화만으로 채우지 않습니다. bind_safety_sender의 작업 이름은 E 내부 호출 구분으로서 공개 enum/ACK 규약이 아닙니다. 새 웨이크 녹음은 녹음 당시 보존 work에 연결하며, 열린 질문·현재 독립 요청을 새 begin으로 덮지 않습니다. 명시 종료 후보는 C 종료 확정·잠금 해제·새 작업 허가가 아닙니다.

[문서: 경합·의존성] 일반 listener와 질문 capture는 같은 audio_lock을 사용하고 두 질문 작업은 dialog_lock으로 직렬화합니다. 정지/cancel·닫기는 현재 취소 신호와 발신 lock을 통해 오래된 결과를 차단합니다. audio_enabled=false이면 질문의 마이크/재생 처리를 진행하지 않습니다. Python은 기존 표준 라이브러리·numpy·jsonschema·PyYAML, ROS는 기존 rclpy/std_msgs/ready2go_interfaces, 실제 오디오는 선택 sounddevice·PortAudio, API는 선택 OpenAI와 기존 LangChain, Melo는 기존 선택 환경을 사용합니다. 새 import를 package.xml/setup.py와 대조했으며 새 의존성·entrypoint는 추가하지 않았습니다. C 입력은 기존 E typed 호출/메시지 fixture로 모의했고 별도 범용 서비스는 추가하지 않았습니다. 기존 격리 ROS 시험을 재사용했으며 실제 장치·C 통합은 후속입니다.

[실측: E-P2-VERIFY-20261011-01] #43/#150+07/#187/#152 변경 관련 직접8파일 검사510 passed/9 skipped(sounddevice 미설치), 기존 격리 ROS test_node.py48 passed입니다. 신규 stop/shared-input·safety-exchange 시험은 기존 실제 node AST fixture를 재사용해 순서/상관/기한/취소/발신 경계를 모의합니다. safety_audio 질문 stop의 source 누락으로 cancel 발신이 실패하던 결함을 최소 수정했습니다. 이전 목표 안내 기대·seq 반례 가정·기존 오디오/노드 fixture 정합성은 실제 코드결함과 구분해 수정했습니다. 모의 DAC/완료/typed B·C 입력은 실음향/관측 증거가 아니며 실제 C 생산자·공개 매핑/장치/API/로봇 AC는 남아 있습니다. 이 수치는 당시 변경 대상의 결과입니다. 이후 원격 a412169의 전체 CI/PR 게시와 이번 로컬 변경의 검사를 구분하며, 실제 운영·실물 후속을 대신하지 않습니다. 대상·환경·실패/skip 및 재사용 근거는 [E CURRENT](../practice/E/CURRENT.md#p2-모의회귀-검증--e-p2-verify-20261011-01)를 참조합니다.

[문서: #43 독립 준비] [place_exchange.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/place_exchange.py)는 기존 PlaceConfirmation을 재사용해 boot/run/step/question_id와 내부·메시지 질문 차수를 연결합니다. asked와 PlaceReply.message는 승인08에 맞춘 E 메시지 후보이며 C 등록 성공·발행·effect를 확정하지 않습니다. 중복 질문은 현재 객체와 최초 구간을 유지하고 재질문은 새 식별자를 사용합니다. 현재 객체와 일회성 녹음 예약을 검사해 과거 작업자와 중복 녹음이 현재 질문을 소비하지 못하게 합니다.

[문서: 호출 경로] [VoiceSession.confirm_audio](../ros2_ws/src/ready2go_voice/ready2go_voice/core/session.py)는 TTS 완료 뒤의 새 Recording을 받아 기존 WAV·Whisper·DeadlineCall로 STT만 수행합니다. before_request에서 실제 SDK 직전 시각을 접수 검사에 넘기며, 접수 객체와 결과 시각을 확인한 뒤 분류 후보를 반환합니다. 일반 명령의 LLM/P1 처리 예산을 사용하지 않습니다. 고정 길이 녹음의 음성 존재 검사, 녹음 누락·중단·늦은 결과·중복 작업자도 검사합니다. [직접 시험](../ros2_ws/src/ready2go_voice/test/test_place_exchange.py)은 모의 시계·STT로 교환과 Session 경계를 확인하며 실제 마이크·SDK·TTS 재생 증거가 아닙니다.

[문서: 연결 선행] 현재 노드에는 명시적인 개발 입력을 통해 질문 작업과 confirm_audio를 호출하는 경로를 작성했습니다. 개발 입력의 기본값은 빈 문자열입니다. C의 실제 질문 발신·confirm 수신·등록 관측과 시계 대응, 같은 run의 검증된 전달 및 복구 결과 출력이 아직 연결되지 않았습니다. 승인09의 구체 안내는 그 실제 단계 결과를 확인한 뒤 기존 안내 경로에 연결해야 합니다. 전체 FAILED만으로 전달 검증을 추정하지 않습니다. 공통 스키마·예시·ICD 및 실제 C 등록/결과 매핑은 연결 작업으로 남아 있습니다. E 내부 입력에서 TTS 완료·새 녹음·응답 발신·결과 안내 호출을 작성했으며 실행 검증은 후속입니다.

[문서] 정책 정본은 [사후 검증](requirements.md#verification-policy)·[재개 접수](requirements.md#resume-admission-policy)입니다. E 내부 모듈은 [skill_confirmation.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/skill_confirmation.py)·[recovery_confirmation.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/recovery_confirmation.py)입니다. Whisper adapter의 optional before_request는 SDK 초기화·WAV 열기 뒤 create 직전 로컬 monotonic 시각으로 접수를 거절할 수 있습니다. 녹음 자료형에 시작/끝 로컬 시각을 보존합니다. P1 Session은 SDK 직전 callback을 시각 진단에만 사용하며 #152 접수창/재개 정책과 새 wire는 연결하지 않습니다. 일반 요청의 TTS 완료·취소·busy/wake 제한은 유지합니다. 정책 질문 TTS/녹음과 독립 stop 입력은 별도 E 작업 경로로 작성했으며 실제 C 입력 매핑은 미완료입니다. 승인된 내부 구간값은 [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)에서 읽으며 null이면 해당 내부 접수를 보류합니다. place는 같은 run/step의 절차와 종료 상태를 보존해 중복 begin으로 재질문 횟수를 초기화하지 않습니다. `PlaceAudioRequest`는 실제 TTS 완료 이후 녹음·SDK 접수와 별도 STT 만료를 결합합니다. `PlaceConfirmation.asked`는 호출자가 제공하는 승인된 전체 구간을 E 로컬 시계로 보관하며 재질문·중복 등록에서 최초 시각/기한을 보존합니다. `delivered`·`admit`·`answer`·`expire`는 같은 구간을 대조합니다. 원격 monotonic 시각을 직접 비교하지 않으며 실제 C 등록/ACK의 로컬 시계 대응과 C 최종 판정은 운영 수신 연결이 필요합니다. 기존 asked 없는 P1/내부 비전 검증 경로는 유지하며 이 준비를 운영 등록 증빙으로 사용하지 않습니다. 서랍 검증은 이 사용자 확인 core가 처리하지 않습니다.

[승인 정책·미승인 wire] 질문 등록 ACK·시간 구간·작업 수명은 [정본](requirements.md#resume-admission-policy)의 사용자 결정에 따라 내부 구현했습니다. 구체 메시지·새 토픽/서비스/enum·프로세스별 clock 대응은 [계약안](interfaces.md#p2-safety-proposal)에 남아 있습니다. [#43 승인08](https://github.com/Jik-Kim/ready2go/issues/43#issuecomment-6105498776)의 confirm·asked/응답 필드 구성은 승인됐으며 이 독립 E 구현에서는 공통 스키마·예시·ICD나 운영 발신을 추가하지 않았습니다. #152 구체 wire 전체의 승인으로 확대하지 않습니다. C 등록을 나타내는 내부 시험 입력은 운영 ACK가 아닙니다. C 후보/질문/독립 요청의 시계·실행 직전 B/pre 검사·최종 effect는 C 영역이며, E의 구간 설정으로 대신하지 않습니다. 스키마·예시·ICD 동시 반영과 E 포함 승인 뒤 운영 adapter를 연결해야 합니다. 정확 포함 여부가 미확정인 시간 경계는 안전측 보류하며 확정된 접수 경계만 재사용합니다.

[인계] B: 실제 grip 완료/실측폭/expected_width 개선·lift 유지·외력 없음/신선도/확인 모드. A/B: handover inspect/TF/ROI·촬영 자세. C: verify evaluator/대기/최종 effect·상태/로그/성공 안내·재개 노드/hold·질문 등록. 실제 연결/실물 AC를 E 모의 시험 결과로 대체하지 않습니다.

[문서] E-local Question.valid_until은 접수10초와 별개의 사건/증빙 유효상한으로 접수·최종 답 시점 모두 검사합니다. C hold_until을 이 값에 복사하지 않으며 C 사건/만료를 무효화하는 adapter도 현재 미연결입니다. 기한 내 STT의 늦은 결과 허용은 E-local 상한과 별도 처리 예산 안으로 제한합니다.


### #194 요청/질문·진단 연결과 #138 bounded 캐시

[문서] 실행 원본은 [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)·[IntentParser](../ros2_ws/src/ready2go_voice/ready2go_voice/core/intent.py)·[Conversation](../ros2_ws/src/ready2go_voice/ready2go_voice/core/conversation.py)·[response.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/response.py)·[DiagnosticFile](../ros2_ws/src/ready2go_voice/ready2go_voice/core/diagnostics.py)입니다. 내부 LLM response_text는 공개 intent schema의 신규 필드가 아니며 `_voice`는 발행에서 제외합니다. 기존 source 소비 필드를 유지하며 비밀값은 제거합니다. 요청 확인은 실행 시작/완료 안내가 아니고 발행은 수락이 아닙니다.

[문서] 일반 질문의 `dialogue_timeout_sec`는 제안 설정이며 null이면 후속 결합을 보류합니다. 질문 TTS 실패는 질문 권한을 만들지 않고, 후속 답은 후보 생성 때 소비합니다. TTS/발행 실패 후 과거 답을 자동 재시도하지 않으며 새 독립 요청이 필요합니다. 관측된 running/잠금/경고·취소는 epoch/세대를 무효화하고, 상태 변경과 발행 게이트를 E 로컬 submit_lock으로 직렬화합니다. 수락 여부/요청 상관성·실물 준비 판정은 이 lock으로 보장하지 않습니다.

[문서] `diagnostic_detail=true`는 전체 민감정보 필터 후 E 로컬 JSONL 파일을 선택하며 콘솔에 전체 JSON을 출력하지 않습니다. `diagnostic_file` 상대 경로는 실행 cwd 기준, 크기·백업 개수·bounded 큐는 YAML 원본입니다. 각 JSONL 줄은 `event`와 이벤트별 필드가 최상위에 있는 객체이며 `voice_diagnostic` 래퍼가 없습니다. 예를 들어 `intent` 이벤트의 발행 결과는 최상위 `published`, intent 내용은 최상위 `intent`에서 확인하고 `tts_finished`의 상세 시각은 최상위 `timing`에서 확인합니다. 원본 LLM은 interpretation 이벤트에 한 번 보존하고 후속 이벤트에는 반복하지 않습니다. wake/녹음 시작·끝→submit/work→STT SDK 호출/결과→LLM→최종 문장/TTS→발행을 로컬 request_id로 연결하며 question_ready/후속 답은 question_id로 연결합니다. 콘솔과 `tee` 파일은 요약이며 상세 파일을 대신하지 않습니다. source 공개 필드는 기존 의미를 유지합니다. 파일 열기/쓰기/회전·필터/직렬화·큐 실패는 경고하고 음성/취소 경로로 예외를 전파하지 않습니다. 큐 포화/정체 시 증빙 손실을 경고하며 C DB 로그나 worker JSON pipe를 대신하지 않습니다. 회전 상한보다 큰 단일 원본 기록은 분할하지 않고 보존한 뒤 다음 기록에서 회전합니다.

[문서·코드 대조: 2026-10-10, #198 리뷰 보완] 기준은 기존 [음성 정책](requirements.md#voice-policy)입니다. `LangChainIntent.schema`를 통과하는 unknown/빈 targets/내부 사유 응답으로 물품 미등록 안내를 확인합니다. 실행 enum에 없는 키를 반환하는 오류 모의는 별도 방어 시험이며 정상 LLM 경로의 증거로 대신하지 않습니다. 내부 응답은 parser에서 문장/사유 필드를 분리하고, 사유는 검증 후 `_voice` 안에서만 사용합니다. `_voice`와 새 내부 필드는 기존 node 발행 필터로 제외하며 원본은 기존 `source.llm_raw` 진단 필드에 보존합니다. 새로운 공개 source 필드를 추가하지 않습니다.

[구현] Conversation과 parser guard는 동의/대명사 응답 판별을 공유합니다. 현재 유효 질문으로 대상이 확정된 답/정정만 전달 요청으로 결합하고, 질문 없음·만료·취소·세대 변경·경고·busy/잠금 뒤에는 원문 그대로 clarify/빈 targets와 대상 재확인 안내로 처리합니다. 이 보류는 LLM 호출 전에 적용하므로 LLM 정상/실패/없음과 무관하며 과거 대상이나 질문 권한을 복원하지 않습니다. 재확인 TTS 완료 후 만들어지는 질문은 새 ID/대상 미정이고 기존 질문의 재사용이 아닙니다. `test_voice_ux.py`·`test_config_api.py`는 실제 내부 스키마와 의미 분류를, `test_voice_ux_node.py`는 저장된 node 메서드의 모의 실행으로 최종 콘솔/TTS·기존 wire 모양·평가 차단을 확인합니다. 실제 API/마이크/ROS 송수신·C 수락·로봇 시험 결과는 아닙니다.

[문서] 초기 필수 문장과 실제 성공 재생된 검증 문장의 사용 빈도를 분리해 선준비합니다. `validated_phrases.json`은 문장/사용횟수만 제한된 수·길이·용량으로 보존하며 질문 권한/대화 원본을 저장하지 않습니다. worker의 miss→WAV 저장·identity 기반 재사용은 기존 경로입니다. 모델/설정/내용/worker 코드 변경에 따른 무효화는 유지하며 이번 worker 시간 진단 수정도 identity를 바꿉니다. 기존 WAV를 삭제하지 않으므로 첫 준비 재합성이 필요할 수 있습니다. 선준비의 필수 목록이 설정 한도를 넘으면 실패하고, 선택 이력 실패는 경고 후 필수 목록만 준비합니다. model_prepare_sec, prefill_prepare_sec, prepare_total_sec와 첫 합성/히트의 worker_synth_sec·재생 구간은 구분합니다. 일반 startup60초·prepare 명령120초·Melo1.2·AC3초는 유지하며 이번 실제 합성 시간은 미측정입니다.

[인계: 미연결] [#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 C는 기존 상태/last_intent의 과거 latched·동일 문장 결과와 현재 요청을 연결할 식별/순서·수락/거절·TTS 실패·timeout/단절/취소 책임을 협의합니다. 고유 요청/boot/seq가 없는 현재 상태로 수락 음성을 만들지 않습니다. D는 [#20](https://github.com/Jik-Kim/ready2go/issues/20)의 사전 정답표에 두 전언 요청·번역/부정/제외·현재 질문 응답/무문맥 응답·가능 여부·미지원 사례와 정책 버전을 대조해야 합니다. E가 C/D 파일을 수정하지 않았으며 협의 전달은 수락/계약 승인이 아닙니다. [#194](https://github.com/Jik-Kim/ready2go/issues/194)·[#138](https://github.com/Jik-Kim/ready2go/issues/138)·[#195](https://github.com/Jik-Kim/ready2go/issues/195)는 P1 기반 개선/검토로 유지합니다. #23 과거 결과·P1 미달을 종료/AC 면제로 바꾸지 않습니다.

### #195 녹음 방식 비교 — 기본 전환 보류

[문서·코드 대조] fixed는 공유 입력에서 기존5초 PCM16kHz/int16/mono 길이만 수집하며 공유 입력을 사용하지 않는 Recorder는 기존 sd.rec→sd.wait를 유지합니다. 두 경우 모두 끝난 뒤30ms VAD+RMS의 최소 연속 음성량만 검사합니다. 무음/취소/VAD 불가·오류는 STT·LLM을 생략하지만 실제 발화 끝을 측정하지 않습니다. silence는 웨이크 스트림의 RMS 기준으로 음성 시작·마지막 유성 프레임을 잡고 무음 상한 뒤 반환합니다. 마지막 프레임 시각은 발화 끝의 추정이며 조용한 발화/중간 휴지/웨이크 잔음/잡음에 영향을 받습니다. silence 경로는 현재 fixed 후처리 VAD를 사용하지 않습니다. 일반 요청의 두 경로 모두 시작/최대 보호 한도·취소/TTS 중단을 검사하고 잘린 요청을 실행하지 않습니다. 독립 stop은 일반 fixed 설정과 구분해 기존 RMS/무음 종료를 사용하며 TTS 중에도 새 녹음을 받습니다. 실제 재생과 겹친 문구 대조는 echo 제거를 보장하지 않으며 같은 문구의 실제 사용자 정지도 보수적으로 보류할 수 있습니다. 클라우드 STT 실패/지연·자기 TTS 변형/잔음·새 입력 시각·소비자 경합/overflow/close는 후속 시험 대상입니다.

[제안: 별도 실측 승인 필요] 같은 표본에서 짧거나 작은 정상음성·중간 휴지·무음/잡음·웨이크 잔음·최대 길이·취소·자기 TTS를 비교합니다. 실제 발화 끝→녹음 끝→SDK 호출/결과→첫 DAC를 구분해 누락/오탐/잘림·지연을 기록합니다. 모의 PCM/VAD 검사와 실제 청취/API는 구분하고 적정 임계값/채택 판단은 실측 후 결정합니다. 이번 기본 fixed5/commissioning·무음/VAD 임계값을 변경하지 않았고 기본 전환을 권고할 실음성 근거는 없습니다.


<a id="acceptance-tts-preparation"></a>
### #196 요청 발행·수락·완료 — E 연결 로직과 운영 보류

[문서] 의미·책임·완료 조건은 [요구사항 정본](requirements.md#acceptance-tts-policy), 실행 필드는 [intent 스키마](../contracts/intent.schema.json)와 [Runner 상태 예시](../contracts/examples/runner_status.json), 공동 참조는 [ICD 5.3](interfaces.md#request-run-contract)입니다. 공동 계약 [#221](https://github.com/Jik-Kim/ready2go/pull/221)의 `e9edaf8` 원본을 합류했으며 새 계약 필드·enum·타이머는 추가하지 않았습니다.

| 단계 | E 현재 실행 원본·호출 관계 | 확인 범위·선행 조건 |
| :--- | :--- | :--- |
| 문장 준비 | [Session](../ros2_ws/src/ready2go_voice/ready2go_voice/core/session.py)의 `prepare_request_payload` | 현재 원본 객체·confidence·검증 문장 signature·generation/epoch·큐 ID를 검사해 공개 사본을 만듭니다. LLM 최상위 ID/문장은 제거합니다. 내부 `_voice.prepared_request` 진단 후보를 발행 권한으로 사용하지 않습니다. |
| 실제 발행 | [VoiceNode](../ros2_ws/src/ready2go_voice/ready2go_voice/nodes/voice_node.py) `_deliver` → 준비 재검사 → [RequestRun](../ros2_ws/src/ready2go_voice/ready2go_voice/core/request_run.py) 등록 → `_publish` | 검증된 C 연결을 주입한 모의에서 find_item은 수락 전 동일 문장을 재생하지 않고 큐 ID/검증 문장을 발행합니다. 실제 노드는 C 근거 연결 전 opt-in 실행 발행을 보류합니다. 발행 실패는 연결을 폐기하며 자동 재전송하지 않습니다. 평가는 전체 발행을 차단하며 선정 목표도 두 명시 opt-in과 현재 C 연결 확인을 통과해야 합니다. |
| 실제 수락 관측 | `/runner/status` → 필수 2인자 `_runner_status_with_info` → `_runner_status` | 검증된 C 연결의 결정이 현재 발행 요청에 대한 `run`일 때만 run을 기억하는 로직을 구현했습니다. 실제 상태 콜백은 C 근거 연결 전 상관 처리를 호출하지 않습니다. 보류·거절은 수락으로 바뀌지 않고 같은 ID 결정 충돌은 연결을 폐기합니다. 다른 요청이 last_intent를 덮어써도 이미 수락된 run은 보존합니다. |
| 재생 결과 | `/voice/speak` → 기존 [PCMTTS](../ros2_ws/src/ready2go_voice/ready2go_voice/adapters/tts.py) → Skill 결과 | opt-in은 실제 DAC 시작·finished_callback 종료 시각과 non-mock 반환을 확인한 뒤 성공합니다. no-op/mock·실패·취소·노드 종료·C 연결 보류는 성공하지 않습니다. 실제 opt-in 액션 수락도 C 연결 전 거절합니다. 새 재생 타이머는 없습니다. C의 요청별 speak 호출·s2 중복 제거·첫 동작 전 안전 재검사와 수락/재기동 근거는 C 운영 선행입니다. |
| 완료 안내 | 수락된 run과 `last.run_id` 대조 → 기존 notice worker | 같은 run의 `COMPLETED`, idle, halt 없음에만 일반 완료 문장을 한 번 대기시킵니다. 빠른 수락/완료 한 표본도 처리합니다. 다른 run·FAILED/ABORTED·정지에는 성공 안내하지 않습니다. 경고와 cancel이 우선하며 전달/복구의 개별 성공은 추정하지 않습니다. |

[운용] [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)의 `request_run_enabled` 기본값은 `false`이며 ROS bool override로 명시 opt-in할 수 있습니다. false에서는 기존 P1 확인 TTS·ID 없는 발행을 유지하고 `confirmation_enabled`·`evaluation_mode`의 기존 의미를 바꾸지 않습니다. **true 설정 전에 C의 실제 구현 ref, 계약 원본 동기화, 수락 ID/run 고정·중복 처리·speak 성공 후 첫 동작 게이트를 확인해야 합니다.** 단일 발행자의 idle 상태를 관측했다는 사실은 C의 계약07 구현 준비를 증명하지 않습니다.

[문서: 현재 연결 경계] bind_request_source는 실제 현재 C 생산자·재기동 경계를 검사하는 함수를 받습니다. _request_run_connected는 매번 그 검사를 호출하며 실패·단절 시 현재 상관을 폐기합니다. 기본 미설치 상태와 설정만 켠 상태는 발신/수락/완료/speak를 보류합니다. JSON·Jazzy 시각/sequence·graph를 생산자 근거로 대체하지 않습니다. 이 호출 경계 작성은 실제 C 연결 증명이 아니며 실제 생산자 검증 함수와 C first gate의 통합은 후속입니다.

[실측: Jazzy API 조사] 로봇과 무관한 임시 토픽 probe에서 필수 2인자 콜백은 정상 수신됐지만 metadata는 dict의 source_timestamp·received_timestamp·publication_sequence_number·reception_sequence_number 네 키뿐이었습니다. 최초 객체 속성 가정은 AttributeError, dict의 publisher_gid 조회도 KeyError였습니다. graph의 endpoint_gid는 조회됐으나 개별 표본 발신 근거로 전용하지 않았습니다. 지원되지 않는 GID 연결 코드는 제거했으며 같은 endpoint의 Runner 재기동 감지·영구 잠금·운영자 강제 재시작·새 boot/epoch 필드를 만들지 않았습니다. 실제 wrapper는 metadata를 C 수락/재기동 증거로 쓰지 않고 기존 경고 관측을 보존합니다.

[문장 수명] 발행 전에는 Session의 현재 질문/세대/변조 검사를 유지합니다. 발행한 사본의 문장은 C가 해당 요청에 연결해 사용하며 E의 시험용 `consume_acceptance_text`를 C 수락 증거로 사용하지 않습니다. 캐시나 latched 상태로 소비 권한을 복원하지 않습니다. PR207–209의 초기 내부 준비는 main 이력으로 상속했습니다.

[검증·미완료] E core 및 실제 노드 메서드 모의는 공개 payload, 실제 수락 상관, 중복/충돌/빠른 완료, 실패/취소, 명시 연결 무효화 뒤 과거 run 차단, 미결정/진행 run의 후속 요청 덮어쓰기 방지, 근거 누락 보류와 halt 경고, evaluation/P1 보존을 검사합니다. PCM 형태의 시험 반환은 제어 흐름 검사이며 실제 청취 증거가 아닙니다. C 운영 수신·first gate, 실음성·로봇·실물 AC와 relay 재기동은 미검증입니다. #43 개발 입력 발신·#150 선정 목표 요청·#152 typed 후보의 노드 호출을 후속 연속 개발에서 작성했으며, 그 새 경로의 시험과 실제 C 공개 규약 매핑은 미완료입니다.

[현재 구현: E-VOICE-DIALOGUE-HOTFIX-20261012-02] 가능 질문은 [기존 음성 정책](requirements.md#voice-policy)에 따라 실행하지 않고 등록 지원/실재고·파지 미확인과 대상 확인을 안내합니다. 위치/열림은 기존 load/get의 초기 state를 읽기만 하고 실제 현재 상태라고 주장하지 않습니다. 현재상태 공급자와 C 정지/복구/재개/종료 매핑은 미연결입니다. 더미의 현재 run 보존·typed 증빙은 모의 가정이며 실제 B/C 증거가 아닙니다. 독립 stop은 기존 cancel_phrases와 정확 정지 표현을 공유합니다. 사용자 재실행/옵션/미검증은 [패키지 핫픽스 안내](../ros2_ws/src/ready2go_voice/README.md#대화-핫픽스--오후-통합-전-사용자-확인)를 참조하십시오.

[현재 구현: E-VOICE-STOP-CANCEL-HOTFIX-20261012-03] 기존 [음성 정책](requirements.md#voice-policy)·[FR-SAF-01](requirements.md#fr-saf-01)의 범위에서 Recorder 판정의 DC 성분만 제외하고 원본 PCM·임계값·기한을 유지합니다. 더미의 생성자 revision/취소/완료는 같은 잠금에서 처리하며 중단 작업 complete를 거절하고 executor 실패는 시험 불능으로 표시합니다. 문형 밖 현재 질문 답도 의미 판정 전에 문맥을 넘기고 판정 뒤 소비합니다. 은/는 안내·초기 위치/서랍 및 Runner 기록 문장 핵심 prefill·같은 요청 수락 로그 순서·비프 gain과 사용자 재시작 옵션은 [패키지 후속 안내](../ros2_ws/src/ready2go_voice/README.md#정지더미-후속--2026-10-12)를 참조하십시오. 실제 마이크/정지/청취·C 공급자 바인딩·복구/재개/종료/모션은 미검증·미연결이며 모의 fixture와 로그로 실물 완료를 주장하지 않습니다.
