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
| 입력 | 외부 강의 `hello_rokey_8332_32.tflite` 읽기, 원본 sd.rec→sd.wait 고정5초 시운전, 또는 RMS 무음 종료·보호 한도 | 장치·모델 배포·임계값은 팀 확정 필요. Push-to-talk는 미구현 후보 |
| STT | OpenAI `whisper-1`, 한국어·등록 물품 이름 prompt, API 단일 호출 슬롯 | 계정/지연 실측 필요. `faster-whisper small` 오프라인 폴백은 미구현 후보 |
| 해석 | LangChain·`gpt-4o` 후보 strict JSON → 기존 계약·등록 물품·보류 문맥·요청 단서 검증; 오류/시간 초과/검증 실패 시 좁은 규칙 폴백 | 모델·프롬프트·E/D 정답표 미확정. 퍼지 매칭은 구현하지 않음 |
| 확인 | 기본 `confirmation_enabled: true`: 검증된 “지우개 가져오기 요청으로 이해했어요.” 재생 성공 뒤 find_item 발행. 실패는 clarify 보류 | C 태스크 시작/기존 speak와 확인 책임 분담은 인계 사항 |
| TTS | 사용자 선택 MeloTTS, 별도 CPU 환경의 한국어 모델 재사용/문장 캐시→PortAudio 재생, 기존 `/voice/speak` Skill 액션 | 단문 합성·첫 DAC 재생 확인. [AC-INT-03](requirements.md#ac-int-03)·청취 품질·C/D 연결 미검증. espeak는 명시 선택 호환 경로이며 자동 폴백 없음 |

사용자 확정 웨이크 기준은0.7이며 기존 점수>기준 비교입니다. 고정5초 녹음 완료 후 로컬 Silero의30ms 구간 VAD+RMS를 검사하고, 무발화/VAD불가·오류/취소는 STT·LLM 및 intent발행을 생략합니다. VAD0.5·연속0.15초는 소음/짧은 발화로 튜닝할 제안값이며 실제효과는 미검증입니다. 정상 발화는5초 전체를 STT에 보내고 발화종료를 새로 추정하지 않습니다. [문서]

[문서: #194 구현] `clarify_prompts`는 기본/실패 안내이며, [승인된 음성 정책](requirements.md#voice-policy)에 따라 현재 대상·행동·판정과 의미 일치하는 내부 LLM `response_text`를 검증해 최종 문장으로 유지합니다. 공개 `clarify_question`은 질문에만 사용하며 내부 `_voice.final_text`와 실제 `tts.speak(text)`·최종 콘솔 안내는 동일 문자열입니다. 원본/대체 사유는 E 상세 파일에 보존합니다. 현재 질문의 후보·세대/epoch·유효성을 `Conversation`이 관리하고 실제 질문 TTS 완료 후 명확한 답/대상 정정을 한 번 결합합니다. 캐시 WAV를 읽거나 재시작해도 질문 권한이 복원되지 않습니다. 이 구현은 실음성/AC·C 수락 시험 결과가 아닙니다.

원본 기반 기능 시운전 기본은 recording_mode=fixed/record_duration_sec=5/timing_mode=commissioning이며 STT/LLM 유한 상한은 각각30초 제안값입니다. 웨이크 스트림을 닫은 뒤 동일 입력으로 16kHz/int16/mono 고정 녹음을 시작합니다. commissioning은 실행·평가 모드 모두에서 기존 유한 API 상한을 사용하며 3초 AC 예산을 적용하지 않습니다. 평가 true는 모든 intent 발행을 차단하고 false는 기존 확인 TTS·무발화·취소·실패·중복 게이트를 통과한 요청을 발행합니다. 고정 녹음 완료는 실제 발화 종료가 아니므로 speech_ended_*와 확인 지연은 null/not_measured, recording_ended_*만 별도로 기록합니다. 이 모드로 AC-INT-03을 통과했다고 보고하지 않습니다.

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

현재 `bare_item_policy` 호환 검사·`request_patterns` 미사용, STT 실패 보류·LLM 검증 실패 후 폴백, 텍스트 override는 패키지 구현 설명을 참조합니다. API 처리 중 새 웨이크 청취가 일시 중지되는 한계가 있으며 음성 취소의 운용 경계는 [NFR-SAF-02](requirements.md#nfr-saf-02)와 [안전 절차](safety.md)를 따릅니다.

### 6.4 LLM 인텐트 파서 (주 경로, 담당 E)

**P1 현재 출력·검증** [문서]

강의 `keyword_extraction.py`·STT 호출 구조를 참고한 [adapters/api.py](../ros2_ws/src/ready2go_voice/ready2go_voice/adapters/api.py)는 현재 온톨로지의 **물품 키·한국어 이름·별칭**을 prompt에 넣습니다. 목록·클래스·레지스트리 intent 자동 주입은 현재 경로에 없습니다. LangChain 후보 모델은 temperature 0·strict JSON을 사용하며 런타임 targets enum은 등록 물품 키로 생성합니다.

```text
제어/미지원·모호 규칙 → 필요한 경우 STT 텍스트 + 등록 물품 어휘 → LLM 후보
  → 기존 intent 계약 + P1 허용값 + 단일 등록 대상 + 확신도 + 발화 의미 검증
  → 오류·시간 초과·일반 검증 실패/LLM 없음: 좁은 폴백; 미등록 find_item은 원인 보존 후 미지원 보류
  → 최종 find_item: 평가/세대/중복/확인 TTS 게이트 → /voice/intent
```

LLM 요청 스키마는 `intent`를 find_item/unknown/clarify로 제한하고 `targets`, `confidence`, `clarify_question`과 내부 `response_text`를 받습니다. response_text는 공개 intent 필드가 아니며 검증된 `_voice.final_text`로만 사용합니다. cancel/status는 규칙 경로입니다. 외부 출력 정본 [intent.schema.json](../contracts/intent.schema.json)은 intent/confidence가 필수이며 현재 출력에서 targets·필요한 확인 질문과 진단 source를 덧붙입니다. strict 응답 형식이 사용자 의미의 정확성을 보장하지 않아 코드가 다시 검증합니다. P1은 goals/query 실행을 허용하지 않습니다.

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
- P2 achieve_goal은 `goals: [{predicate, subject, value}]` 배열이며 계약의 predicate는 located_in/open입니다. [기존 목표 예시](../contracts/examples/intent_goal.json)의 lip_balm→drawer_bottom은 후속 설계 예시로 P1 출력이 아닙니다. 목표를 받으면 [온톨로지 7.5](ontology.md) 조건·결과와 [플래너 7.7](planner.md)에서 순서를 도출하는 계획이며 LLM이 동작 순서를 직접 생성하는 경로와 구분합니다.
- P3 목록/클래스 대상 및 복합 태스크 호출은 해당 요구사항·담당 연결 검증이 필요합니다. 계약의 레지스트리 intent 런타임 추가 설명은 후속 연결 설명이며 현재 고정 enum을 임의 문자열이 통과한다는 뜻으로 사용하지 않습니다.
- `query` 객체/null은 계약이 허용하지만 상태 질의 설계의 Phase는 미확정입니다. goals/query/source를 모든 intent의 필수 출력으로 확정하지 않습니다.

**현재 진단과 C/D 인계** [문서]

STT 원문·LLM 응답·검증·폴백·실행 허용·지연과 발화 종료/첫 PortAudio DAC 재생 시각은 ROS 상세 진단 로그 또는 intent의 source에 제공합니다. 발행 여부 `published`는 진단 이벤트의 최상위 필드이며 `/voice/intent`의 `source`에는 없습니다. D가 상세 콘솔 JSON을 읽을 때 발행 여부는 `voice_diagnostic.published`, intent는 `voice_diagnostic.intent`에서 확인합니다. `published=true`는 발행 호출 반환을 뜻하며 C 수신·실행 성공 증빙은 아닙니다. 기본 콘솔은 한 줄 진행 표시이며 `-p diagnostic_detail:=true`로 voice_diagnostic 원본을 유지합니다(실행/보존 명령은 패키지 README). TTS 상세 로그의 `voice_diagnostic.timing`은 합성 대기 `synthesis_wait_sec`, Melo `cache_hit`·`worker_synth_sec`, 성공 시 첫 DAC→PortAudio finished callback 구간 `playback_sec`·종료 시각/기준을 구분합니다. worker 처리 시간은 캐시 조회/합성 시간이며 Runner의 요청→종료 전체를 합성으로 해석하지 않습니다. 이 정보는 로그에만 추가하며 기존 Skill 액션 결과·intent source 필드와 구분합니다. source 부가 필드 수신/의미는 C/D 협의 대상입니다. 이를 C run_id/DB 실행 로그의 inputs·D 화면에 자동 기록하는 연결은 미검증입니다. 물리 재생·모의 시각을 구분하며 합성 시작이나 텍스트 입력 시각을 AC-INT-03 실측으로 대신하지 않습니다.

### 6.5 (Stretch) LLM 태스크 JSON 생성

**P3 후속 계획**: [FR-PLN-03](requirements.md#fr-pln-03)·[FR-TWN-02](requirements.md#fr-twn-02), [AC-LLM-01](requirements.md#ac-llm-01)에 연결된 Stretch입니다. 현재 P1 voice 구현에 없으며 고정 Day 11 문구로 현 일정·착수 승인을 확정하지 않습니다. 착수·범위·담당 C/E/A 연결은 별도 합의가 필요합니다. [문서]

- 계획 흐름: 미정의 자연어 요청 → [Runner 7.1 원자 동작·제어 블록](runner.md)으로 태스크 JSON 생성 → [태스크 스키마 7.2](runner.md) 검증 → 조건·결과 기반 기호적 드라이런 → [트윈 10장](twin.md) 사전 검증 → 승인된 실물 운용 절차에 따른 실행. 현재 자동 연결된 기능으로 설명하지 않습니다.
- 생성 태스크의 검사/거절, while max_iter·작업 영역·E-stop 등은 후속 구현·계약 대조 항목입니다. 트윈 통과를 실물 안전 검증으로 간주하지 않습니다.
- 완료 판정은 [AC-LLM-01](requirements.md#ac-llm-01)을 참조합니다. 현재 태스크 직접 생성 경로는 미구현입니다.

<a id="p2-safety-voice"></a>

### 6.6 P2 정지·복구 후 명시적 재개 준비

[문서] 목표·정책·책임·검증 기준은 [FR-SAF-01–03](requirements.md#fr-saf-01)·[AC-SAF-02–04](requirements.md#ac-saf-02)을 참조합니다. 담당별 진행 상태·합의값 반영 여부는 [#153](https://github.com/Jik-Kim/ready2go/issues/153)을 참조하십시오.

[문서: 구현 대조 기준 `65148d4`] #144 상태 안내·Melo 캐시와 #165 내부 정책, #167 Runner 단계 재개 준비가 main에 병합됐습니다. C `resume()`은 잠금 해제이며 `resume_run()`은 별도 준비 경로입니다. 이 병합이 E 음성·장치 운영 연결이나 안전 수용 기준 완료를 뜻하지 않습니다. 기존 파서는 cancel/status와 일반 요청을 처리하며 새 복구/재개 wire enum은 없습니다. listener는 busy/speaking/TTS lock 중 입력을 제한합니다. 따라서 현재 항상 음성 정지를 받거나 TTS 뒤 음성 재개를 실제 수신·실행하는 기능으로 설명하지 않습니다. B MotionState는 관절 변화와 state를 사용하지만 조회 실패 시 상태 fallback, ESTOP 상태 즉시 반환 경로가 있어 ESTOP 응답을 완전한 물리 정지 증빙으로 쓰지 않습니다.

[구현: ROS 비의존 준비] `core/recovery_confirmation.py`는 운영에서 호출하지 않는 내부 정책입니다. 명확한 정지/복구/재개 표현만 내부 후보로 분류합니다. 새로운 intent는 발행하지 않습니다. 같은 세션·정지 사건·작업·중단 단계에 대해 정지→검증된 복구/재개점→질문 후보 1회를 준비하며 TTS 완료·완료 뒤 채취한 발화·현재 유효 증빙·명시적 재개가 모두 있을 때만 일회성 작업 식별 후보를 반환합니다. 질문 자체·TTS 성공·외력 소멸은 실행 허가가 아닙니다. 질문 TTS 실패 시 `asked` 기록으로 같은 사건에는 다시 질문하지 않으며 자동 재시도·재개도 하지 않습니다. 후속 운용 복구 절차는 미확정이며 새 정지/재시작으로 이를 우회하라는 안내가 아닙니다. 재정지·기한 초과·불명확한 증빙·거절·중복·재기동/다른 사건 응답은 보류합니다. 질문 유효기간·시계·순서·입력 진위는 승인된 후속 adapter 정책으로 제공해야 하며 임의 임계값을 정하지 않습니다.

[제안·계약 차단] 내부 `StoppedWork/Evidence/Question`은 wire 필드나 확정 계약이 아닙니다. 명시적 복구 의사·B 실제 정지/컨트롤러 복구 결과·C 재개점/조건·부팅 세대/순서/유효성·질문/발화 연결과 콜백 직렬화는 [승인 대기안](interfaces.md#p2-safety-proposal)에서 협의합니다. C #152 계약안 v0의 `halt_event_id`와 내부 `StoppedWork.stop`의 대응은 계약 확정 후 adapter에서 대조해야 하며 현재 승인된 wire 연결이 아닙니다. 복구 중 정지 또는 증빙 불명은 후보를 무효화해야 합니다. B/C 후속 검사의 기준은 [FR-SAF-03](requirements.md#fr-saf-03)입니다. 실제 증빙 adapter·E 후보·C 실행 보존의 연결은 미확정입니다.

[미연결] 복구 결과 ROS 수신, 질문 실제 TTS·캐시, 발화 채취/자기 음성 억제, 우선 정지 경로, C 잠금/재개 요청은 아직 연결하지 않았습니다. P2 복구 정책은 ordinary intent·Runner notice·prefill·listener 운영 경로에 연결하지 않았습니다. TTS 완료 뒤 녹음 시작 검사는 실제 스피커 자기 발화가 완전히 차단됐다는 증거가 아닙니다. 모의 정책 시험은 실제 음성 수신·로봇 정지·복구·재개 완료의 근거가 아닙니다.

### #43·#152 E 내부 정책과 C v2 회신안 (미승인 계약)

[문서] 정책 정본은 [사후 검증](requirements.md#verification-policy)·[재개 접수](requirements.md#resume-admission-policy)입니다. E 내부 모듈은 [skill_confirmation.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/skill_confirmation.py)·[recovery_confirmation.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/recovery_confirmation.py)입니다. Whisper adapter의 optional before_request는 SDK 초기화·WAV 열기 뒤 create 직전 로컬 monotonic 시각으로 접수를 거절할 수 있습니다. 녹음 자료형에 시작/끝 로컬 시각을 보존합니다. P1 Session은 SDK 직전 callback을 시각 진단에만 사용하며 #152 접수창/재개 정책과 새 wire는 연결하지 않습니다. 노드의 실제 TTS 완료·취소·busy/listener 경계는 그대로이며 아직 정책 질문 TTS/녹음 연결은 없습니다. STT 별도 처리 예산·place 대기/재확인 값은 설정 null로 미정 표시하고 내부 접수를 안전측 보류합니다.

[제안: C 회신안] [C v1 수락+v2 제안](https://github.com/Jik-Kim/ready2go/issues/152#issuecomment-6059657040)의 일반 cancel 보존·질문 포기 구분·사건별 일회성·재개 직전 B 확인 요구와 책임 방향은 대조했습니다. `answer: asked`는 제안 enum resume/decline/expired와 충돌하므로 기존 enum에 임의 추가하지 않습니다. 질문 등록 메시지/수신 확인 방식·등록 전 답 거절·멱등성은 별도 합의가 필요하며 새 토픽/서비스/enum을 확정하지 않습니다. E는 같은 Voice 프로세스 시계에서 TTS 실제 완료·녹음 시작/끝·실제 SDK 호출·STT 만료와 질문/boot/run/halt를 결합해 검증한 결과만 전달하는 구체안을 제안합니다. C는 사건/질문 식별자·seq·등록 상태와 **자신의 시계**로 유한 hold 상한을 검사하고 실행 직전 B/pre를 재확인합니다. 서로 다른 프로세스 monotonic 값의 직접 대소 비교는 하지 않으며 요청 시각 하나로 녹음 시각을 증명하지 않습니다. E 처리 예산과 C hold 값은 미정입니다. 스키마·예시·ICD 동시 반영과 E 포함2명 승인 전 운영 연결은 보류합니다. 이 회신안은 GitHub 게시나 계약 승인 자체가 아닙니다.

[인계] B: 실제 grip 완료/실측폭/expected_width 개선·lift 유지·외력 없음/신선도/확인 모드. A/B: handover inspect/TF/ROI·촬영 자세. C: verify evaluator/대기/최종 effect·상태/로그/성공 안내·재개 노드/hold·질문 등록. 실제 연결/실물 AC를 E 모의 시험 결과로 대체하지 않습니다.

[문서] E-local Question.valid_until은 접수10초와 별개의 사건/증빙 유효상한으로 접수·최종 답 시점 모두 검사합니다. C hold_until을 이 값에 복사하지 않으며 C 사건/만료를 무효화하는 adapter도 현재 미연결입니다. 기한 내 STT의 늦은 결과 허용은 E-local 상한과 별도 처리 예산 안으로 제한합니다.


### #194 요청/질문·진단 연결과 #138 bounded 캐시

[문서] 실행 원본은 [voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)·[IntentParser](../ros2_ws/src/ready2go_voice/ready2go_voice/core/intent.py)·[Conversation](../ros2_ws/src/ready2go_voice/ready2go_voice/core/conversation.py)·[response.py](../ros2_ws/src/ready2go_voice/ready2go_voice/core/response.py)·[DiagnosticFile](../ros2_ws/src/ready2go_voice/ready2go_voice/core/diagnostics.py)입니다. 내부 LLM response_text는 공개 intent schema의 신규 필드가 아니며 `_voice`는 발행에서 제외합니다. 기존 source 소비 필드를 유지하며 비밀값은 제거합니다. 요청 확인은 실행 시작/완료 안내가 아니고 발행은 수락이 아닙니다.

[문서] 일반 질문의 `dialogue_timeout_sec`는 제안 설정이며 null이면 후속 결합을 보류합니다. 질문 TTS 실패는 질문 권한을 만들지 않고, 후속 답은 후보 생성 때 소비합니다. TTS/발행 실패 후 과거 답을 자동 재시도하지 않으며 새 독립 요청이 필요합니다. 관측된 running/잠금/경고·취소는 epoch/세대를 무효화하고, 상태 변경과 발행 게이트를 E 로컬 submit_lock으로 직렬화합니다. 수락 여부/요청 상관성·실물 준비 판정은 이 lock으로 보장하지 않습니다.

[문서] `diagnostic_detail=true`는 전체 민감정보 필터 후 E 로컬 JSONL 파일을 선택하며 콘솔에 전체 JSON을 출력하지 않습니다. `diagnostic_file` 상대 경로는 실행 cwd 기준, 크기·백업 개수·bounded 큐는 YAML 원본입니다. 원본 LLM은 interpretation에서 한 번 보존하고 후속 이벤트에는 반복하지 않습니다. wake/녹음 시작·끝→submit/work→STT SDK 호출/결과→LLM→최종 문장/TTS→발행을 로컬 request_id로 연결하며 question_ready/후속 답은 question_id로 연결합니다. source 공개 필드는 기존 의미를 유지합니다. 파일 열기/쓰기/회전·필터/직렬화·큐 실패는 경고하고 음성/취소 경로로 예외를 전파하지 않습니다. 큐 포화/정체 시 증빙 손실을 경고하며 C DB 로그나 worker JSON pipe를 대신하지 않습니다. 회전 상한보다 큰 단일 원본 기록은 분할하지 않고 보존한 뒤 다음 기록에서 회전합니다.

[문서] 초기 필수 문장과 실제 성공 재생된 검증 문장의 사용 빈도를 분리해 선준비합니다. `validated_phrases.json`은 문장/사용횟수만 제한된 수·길이·용량으로 보존하며 질문 권한/대화 원본을 저장하지 않습니다. worker의 miss→WAV 저장·identity 기반 재사용은 기존 경로입니다. 모델/설정/내용/worker 코드 변경에 따른 무효화는 유지하며 이번 worker 시간 진단 수정도 identity를 바꿉니다. 기존 WAV를 삭제하지 않으므로 첫 준비 재합성이 필요할 수 있습니다. 선준비의 필수 목록이 설정 한도를 넘으면 실패하고, 선택 이력 실패는 경고 후 필수 목록만 준비합니다. model_prepare_sec, prefill_prepare_sec, prepare_total_sec와 첫 합성/히트의 worker_synth_sec·재생 구간은 구분합니다. 일반 startup60초·prepare 명령120초·Melo1.2·AC3초는 유지하며 이번 실제 합성 시간은 미측정입니다.

[인계: 미연결] [#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 C는 기존 상태/last_intent의 과거 latched·동일 문장 결과와 현재 요청을 연결할 식별/순서·수락/거절·TTS 실패·timeout/단절/취소 책임을 협의합니다. 고유 요청/boot/seq가 없는 현재 상태로 수락 음성을 만들지 않습니다. D는 [#20](https://github.com/Jik-Kim/ready2go/issues/20)의 사전 정답표에 두 전언 요청·번역/부정/제외·현재 질문 응답/무문맥 응답·가능 여부·미지원 사례와 정책 버전을 대조해야 합니다. E가 C/D 파일을 수정하지 않았으며 협의 전달은 수락/계약 승인이 아닙니다. [#194](https://github.com/Jik-Kim/ready2go/issues/194)·[#138](https://github.com/Jik-Kim/ready2go/issues/138)·[#195](https://github.com/Jik-Kim/ready2go/issues/195)는 P1 기반 개선/검토로 유지합니다. #23 과거 결과·P1 미달을 종료/AC 면제로 바꾸지 않습니다.

### #195 녹음 방식 비교 — 기본 전환 보류

[문서·코드 대조] fixed는 sd.rec→sd.wait의5초 PCM16kHz/int16/mono 전체를 수집하고 끝난 뒤30ms VAD+RMS의 최소 연속 음성량만 검사합니다. 무음/취소/VAD 불가·오류는 STT·LLM을 생략하지만 실제 발화 끝을 측정하지 않습니다. silence는 웨이크 스트림의 RMS 기준으로 음성 시작·마지막 유성 프레임을 잡고 무음 상한 뒤 반환합니다. 마지막 프레임 시각은 발화 끝의 추정이며 조용한 발화/중간 휴지/웨이크 잔음/잡음에 영향을 받습니다. silence 경로는 현재 fixed 후처리 VAD를 사용하지 않습니다. 두 경로 모두 시작/최대 보호 한도·취소/TTS 중단을 검사하고 잘린 요청을 실행하지 않습니다.

[제안: 별도 실측 승인 필요] 같은 표본에서 짧거나 작은 정상음성·중간 휴지·무음/잡음·웨이크 잔음·최대 길이·취소·자기 TTS를 비교합니다. 실제 발화 끝→녹음 끝→SDK 호출/결과→첫 DAC를 구분해 누락/오탐/잘림·지연을 기록합니다. 모의 PCM/VAD 검사와 실제 청취/API는 구분하고 적정 임계값/채택 판단은 실측 후 결정합니다. 이번 기본 fixed5/commissioning·무음/VAD 임계값을 변경하지 않았고 기본 전환을 권고할 실음성 근거는 없습니다.
