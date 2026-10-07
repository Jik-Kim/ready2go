# 음성 · LLM

> 요구사항·Phase·완료 기준의 정본은 [requirements.md](requirements.md)입니다. 아래는 현재 구현, 미확정 설정, 후속 설계를 구분한 기술 설명입니다. 구현 코드가 존재하는 것과 실물 연결·수용 기준 통과는 구분합니다. [문서]

> 관련 요구사항: [FR-INT-01–03](requirements.md#fr-int-01). 구현·의존성·실행 준비는 [ready2go_voice README](../ros2_ws/src/ready2go_voice/README.md), 검증 기록은 [E CURRENT](../practice/E/CURRENT.md)를 참조합니다.

## 6. 음성 · LLM 인터페이스 (필수, 담당 E)

| 구분 | 범위·정본 | 현재 상태 |
| :--- | :--- | :--- |
| P1 | FR-INT-01~03: 웨이크/STT, 단일 물품 해석·폴백, 음성 피드백 | E 패키지 구현 있음. 실제 음성/API·C/D 연결·AC-INT-01~03 미검증 |
| P2 | FR-INT-02 구조화 목표 추출 → [FR-PLN-02](requirements.md#fr-pln-02) 조건·결과 기반 자동 계획 | 이 문서의 후속 설계. 현재 P1 voice 경로에서 목표 계획을 실행하지 않음 |
| P3 | FR-INT-02 목록·분류, [FR-ONT-03](requirements.md#fr-ont-03) 클래스/관계 조회, [FR-PLN-03](requirements.md#fr-pln-03) 복합 작업 등록 | 다중 서랍·지식 확장 후속 설계. 데이터 등록과 음성/실행 연결 완료는 구분 |
| Phase 미배정 | 상태 질의, 퍼지 매칭, 이름 없는 추론 수용 등의 개선안 | SOT의 명시적 Phase 배정 없이 P2/P3 구현 약속으로 확정하지 않음 |

### 6.1 파이프라인

**P1 현재 E 구현 경로** [문서]

```text
마이크 → hello rokey 웨이크 → 고정5초 시운전/무음 종료 녹음 → whisper-1 STT
      → 제어/미지원 규칙 또는 LLM 후보 → 의미 검증·필요 시 규칙 폴백
      → 검증된 단일 find_item: 중복 확인 → 확인 TTS → /voice/intent
      → unknown/clarify: 보류 안내 / cancel·status: 규칙 제어 경로
```

사용자 확정 기본 `evaluation_mode: false`, `audio_enabled: false`입니다. 시작 시 ROS bool 파라미터 `-p evaluation_mode:=true/false`로 지정하고, 미지정은 false입니다. 시작 값은 YAML보다 우선하므로 기존 로컬 YAML true도 미지정/CLI false에서는 실행 모드이며, parser/Session 생성 전에 같은 유효 설정을 공유합니다. 실행 중 모드 변경 기능은 없습니다. 평가 모드는 **모든 intent 발행을 금지**하고 동일 입력의 TTS·진단 반복은 허용합니다. 실제 웨이크/STT 평가에는 준비한 장치 설정에서 audio를 켜야 합니다. 텍스트 override는 같은 파서의 디버깅 입력이며 음성 평가를 대신하지 않습니다. C 수신→태스크/진행·결과 피드백 및 로그, D 화면은 담당별 인계·실측이 남아 있습니다.

| 단계 | P1 현재 구현 | 미확정 설정·미구현 후보 |
| :--- | :--- | :--- |
| 입력 | 외부 강의 `hello_rokey_8332_32.tflite` 읽기, 원본 sd.rec→sd.wait 고정5초 시운전, 또는 RMS 무음 종료·보호 한도 | 장치·모델 배포·임계값은 팀 확정 필요. Push-to-talk는 미구현 후보 |
| STT | OpenAI `whisper-1`, 한국어·등록 물품 이름 prompt, API 단일 호출 슬롯 | 계정/지연 실측 필요. `faster-whisper small` 오프라인 폴백은 미구현 후보 |
| 해석 | LangChain·`gpt-4o` 후보 strict JSON → 기존 계약·등록 물품·보류 문맥·요청 단서 검증; 오류/시간 초과/검증 실패 시 좁은 규칙 폴백 | 모델·프롬프트·E/D 정답표 미확정. 퍼지 매칭은 구현하지 않음 |
| 확인 | 기본 `confirmation_enabled: true`: “지우개 가져다드리겠습니다.” 재생 성공 뒤 find_item 발행. 실패는 clarify 보류 | C 태스크 시작/기존 speak와 확인 책임 분담은 인계 사항 |
| TTS | 사용자 선택 MeloTTS, 별도 CPU 환경의 한국어 모델 재사용/문장 캐시→PortAudio 재생, 기존 `/voice/speak` Skill 액션 | 단문 합성·첫 DAC 재생 확인. 전체 음성3초·청취 품질·C/D 연결 미검증. espeak는 명시 선택 호환 경로이며 자동 폴백 없음 |

사용자 확정 웨이크 기준은0.7이며 기존 점수>기준 비교입니다. 고정5초 녹음 완료 후 로컬 Silero의30ms 구간 VAD+RMS를 검사하고, 무발화/VAD불가·오류/취소는 STT·LLM 및 intent발행을 생략합니다. VAD0.5·연속0.15초는 소음/짧은 발화로 튜닝할 제안값이며 실제효과는 미검증입니다. 정상 발화는5초 전체를 STT에 보내고 발화종료를 새로 추정하지 않습니다. [문서]

P1 clarify는 설정 `clarify_prompts`의 규칙별 고정 질문 또는 일반 고정 안내를 사전캐시합니다. 임의 LLM질문은 일반 안내로 정규화하여 최종 clarify_question과 실제 재생이 일치하며 원문은 source.llm_raw에 보존합니다. unknown/find/control·대상단독clarify 판별은 유지하고 새 확인 대화는 만들지 않습니다. 설치된 모델의 합성입력 무발화 검사·캐시 응답5~7ms는 실제마이크 오탐/전체3초 달성 근거가 아닙니다. 웨이크 잔음이 음성구간 기준을 넘으면 통과할 가능성이 남습니다. [문서·로컬 검사]

원본 기반 기능 시운전 기본은 recording_mode=fixed/record_duration_sec=5/timing_mode=commissioning이며 STT/LLM 유한 상한은 각각30초 제안값입니다. 웨이크 스트림을 닫은 뒤 동일 입력으로 16kHz/int16/mono 고정 녹음을 시작합니다. commissioning은 실행·평가 모드 모두에서 기존 유한 API 상한을 사용하며 3초 AC 예산을 적용하지 않습니다. 평가 true는 모든 intent 발행을 차단하고 false는 기존 확인 TTS·무발화·취소·실패·중복 게이트를 통과한 요청을 발행합니다. 고정 녹음 완료는 실제 발화 종료가 아니므로 speech_ended_*와 확인 지연은 null/not_measured, recording_ended_*만 별도로 기록합니다. 이 모드로 AC-INT-03을 통과했다고 보고하지 않습니다.

[현재 설정 원본 voice.yaml](../ros2_ws/src/ready2go_voice/params/voice.yaml)은 시운전 STT/LLM 상한 각각30초, silence_sec=0.4, tts_reserve_sec=0.7입니다. 이전 STT1.1초/LLM0.8초는 AC 준비 후보였으며 현재 원본 값이 아닙니다. AC 모드의 값은 별도 실측해 확정합니다. silence/ac_budget 모드에서는 마지막 유성 프레임부터 확인 TTS 시작까지 3초 예산에 무음 대기·API·TTS 준비를 포함합니다. 남은 예산에 따라 STT/LLM의 실제 제한은 더 짧아질 수 있으며, 값의 합이나 설정만으로 실제 3초 달성을 선언하지 않습니다. 늦은 API 결과는 폐기하고 재시도를 쌓지 않습니다.

Melo 모델·설정된 고정 안내/등록 물품 확인 문장 캐시 준비 완료 후 웨이크 입력을 시작합니다. 사용자 확정 엔진은 MeloTTS·속도1.2입니다. 등록 물품별 기존 확인 문장과 실제 P1 찾아오기/트레이 전달/미발견 문장, “서랍을 닫았어요”, clarify·사용자 prefill을 중복 제거해 준비합니다. 닫기 안내의 성공 판정·태스크 연결은 [#138](https://github.com/Jik-Kim/ready2go/issues/138)의 C 후속이며 캐시 준비만으로 연결 완료를 뜻하지 않습니다. 속도/worker/모델 등의 캐시 키가 바뀌면 새 합성이 필요하고 동일 환경의 기존 디스크 캐시는 재사용합니다. 현재 상태 안내7종 포함64개 문장을 cold 합성하면 기존 전체 준비상한60초를 넘을 수 있어, 최초/속도·worker 변경 시 일반 노드 재시작 반복 대신 패키지 README의 재생 없는 사전 준비 절차와 운용 PC에서 결정한 별도 유한 상한을 사용합니다. 기존 YAML·AC3초·재생 상한은 바꾸지 않습니다. PC2 재시작 캐시·실물/청취 품질·AC3초는 미검증입니다. Google Cloud TTS 도입은 철회하여 새 SDK/키를 추가하지 않습니다. 준비/합성 실패·취소·기한 초과는 재생/발행을 보류하며 기존 TTS lock·첫 DAC 시각을 유지합니다. 설치 경로·공식 revision·Python3.12 호환 의존성/한국어 전용 패치와 단문 재생 명령은 패키지 README를 참조하십시오. 과거 속도1.0의 CPU4스레드 단문 합성 약2.43~2.49초와 캐시 조회 약3ms는 합성/조회 측정이며 전체 AC-INT-03 달성 근거가 아닙니다. [실측: 로컬 단문]

기존 `/runner/status` 읽기 전용 구독과 별도 TTS worker로 P1 중단/오류 안내를 제공합니다. 현재 halt_code의 ESTOP·확인 불가·HALTED를 우선하며 정지 완료를 단정하지 않습니다. 일반 실패는 관측한 running/task와 새 마지막 결과가 맞을 때 finally 이후 관측 시점에 안내합니다. 첫 latched/동일 사건·확인한 run_id는 반복하지 않고 높은 경고/새 회차가 낡은 대기·정상 음성을 무효화합니다. 일반 FAILED를 지속 잠금으로 만들지 않아 새 음성 확인/intent는 기존 규칙으로 진행하며, 현재 halt만 정상 TTS를 억제합니다. 상태 콜백은 TTS/정지/복구/DB를 호출하지 않고 안내는 기존 lock/cancel/timeout/첫DAC를 사용합니다. 자체 TTS 실패는 로그만 남기고 재시도/재귀 안내하지 않습니다. 문구7종은 Melo 사전캐시에 포함됩니다. 현재 계약에 활성 run_id·이벤트 시각/순번이 없어 미관측 같은 태스크 지연 결과·전환 누락을 완전 구분하거나 중간 일반 실패를 즉시 알리는 것은 미구현이며 [#138](https://github.com/Jik-Kim/ready2go/issues/138)의 C 인계입니다. 실제 정지/실물·경고 재생 지연은 미검증입니다. [문서]

실행 모드의 동일 find_item은 중복 시간창 안에서 TTS 전에 보류하고 발행 호출 정상 반환 후에만 중복 기록을 확정합니다. TTS 실패·취소·시간 초과·발행 예외 후 재시도는 가능합니다. publisher 정상 반환은 C 수신·실행 성공 확인이 아닙니다.

### 6.2 지원 인텐트 (최소 세트)

**P1 현재 지원** [문서]

| intent | 처리·예시 |
| :--- | :--- |
| `find_item` | 등록 이름/별칭이 직접 확인된 단일 물품의 받기/가져오기 요청을 LLM이 의미 해석하고 공통 검증을 통과한 후보. “지우개 찾아줘.”, “지우개 좀”, “지우개 좀요.”, “혹시 지우개를 받을 수 있을까요?” |
| `cancel` / `status` | “멈춰.” / “지금 뭐 해?”를 규칙으로 직접 처리. 끝 `.!?。？！`만 정규화해 정확 비교; API 없이 처리하며 텍스트 cancel은 진행 중 결과의 추가 발행도 취소 |
| `unknown` / `clarify` | 미지원·미등록·모호 요청의 실행 보류. 사용자 확정: 대상 단독·그거/저거·일반 물건·대상불명 요청은 clarify/빈 targets/실행 보류 |

정상 LLM 경로는 문장 전체 정규식과 일치하지 않아도 요청 의미를 해석합니다. 동사가 생략된 이름+좀/좀요는 사용자 승인된 가져오기 부탁이며 모든 등록 이름·별칭에 적용합니다. 이름 단독·그거 좀처럼 대상불명·다중 대상·부정·정보 질문·인용·명백한 불명확 문맥·미지원 행동은 선제 보류하고, 직접 손 전달·다른 목적지·반납·정리·던지기는 실행 후보가 될 수 없습니다. 건네기는 기존 전달 트레이 흐름입니다.

LLM 후보는 계약·P1 허용값·단일 등록 대상·발화 이름/별칭과의 일치·유한 확신도/최소값·보류 문맥을 다시 검사합니다. find_item에는 요청/필요/받기/축약 부탁의 단서가 필요하며, 이름만 또는 요청 단서만으로 실행하지 않습니다. 정상 후보에 전체 폴백 문형을 재적용하지 않습니다. 오류·시간 초과·검증 실패/LLM 없음의 **폴백만** 기존 긍정 전체 문형과 단일 물품+좀/좀요를 수용하고, 그 밖의 이름 있는 표현은 clarify로 보류합니다. 정상 LLM unknown/clarify는 그대로 보류합니다. 자유 한국어 전체의 의미 정확성·안전을 보장하는 검사기는 아니며 실제 음성 평가가 필요합니다.

40문장은 평가용 정답표이며 허용 문장 목록·학습 자료가 아닙니다. 프롬프트와 실제 발화를 함께 모델에 제공하고, 프로젝트의 별도 파인튜닝이나 사용 중 자동 재학습은 없습니다. **자유 표현 10개를 포함한 P1 평가는 그대로 요구됩니다.** 코드의 모의 회귀와 실제 E/D 정답표 승인·음성 정확도 실측은 구분합니다.

**P2/P3 후속 설계** [문서]

| Phase | intent·예시 | 연결·완료 기준 |
| :--- | :--- | :--- |
| P2 | `achieve_goal`: “립밤은 아래 서랍에 넣어 둬” → 구조화 goals | FR-INT-02 → FR-PLN-02, [플래너 7.7](planner.md). 목표형 명령 5종 이상 계획·실물 결과 기록([AC-PLN-01](requirements.md#ac-pln-01)); 현재 P1 파서는 거절 |
| P3 | `find_list`: “출근 준비물 찾아줘”; `find_class`: “귀중품 다 찾아줘” | FR-INT-02·FR-ONT-03의 목록/분류·클래스 계층/관계 조회. 현재 P1 해석·발행 경로는 미지원 |
| P3 | 등록된 원자 스킬 조합의 새 복합 작업 | FR-PLN-03, [온톨로지 7.6](ontology.md). Python 변경 없이 2종 이상 등록·실행([AC-PLN-02](requirements.md#ac-pln-02)). 등록만으로 trigger→음성 intent 자동 추가/어휘 주입이 완료되지 않음 |

**미확정 설계/선택 과제(Phase 미배정)** [제안]

- `query_state` (“지금 뭐 들고 있어?”)는 계약에 허용되지만 실제 상태 수신·응답 연결은 현재 E voice에서 구현하지 않습니다. P1 status 규칙은 현재 로봇 상태 조회를 대신하지 않습니다.
- 퍼지 매칭, 이름 없는 추론 수용, 프롬프트/정답 정책 개선은 별도 설계·승인이 필요합니다. 이 개선안의 Phase 미배정은 P1 자유 표현 평가 요구를 미루는 근거가 아닙니다.
- Push-to-talk·오프라인 STT/Piper는 선택 후보이며 필수 추가 구현으로 확정하지 않습니다. 새 웨이크 모델 학습 [#87](https://github.com/Jik-Kim/ready2go/issues/87)은 우선순위가 낮은 선택 후속으로 마감일·Phase 미배정입니다. 기존 P1 웨이크 실측 의무는 유지합니다.

### 6.3 비기능 요구사항

- **P1 수용 기준 유지**: [AC-INT-01](requirements.md#ac-int-01) 실제 한국어 음성 40문장, 화자 2명 이상, 자유 표현 10개 포함, 정확도 90% 이상. [AC-INT-02](requirements.md#ac-int-02) LLM 검증 실패율 5% 이하·형식/대상 검증 실패에 따른 잘못된 실행 0건. [AC-INT-03](requirements.md#ac-int-03) 발화 종료→확인 TTS 시작 3초 이내. 현재 실측 통과 기록은 없습니다.
- E/D 평가 구성안은 지우개 요청20/모호10/미등록·미지원10(자유 표현10은 전체40 안에 포함), cancel/status 별도 보조 시험입니다. 모호 요청의 clarify 보류는 사용자 확정입니다. D 첨부의 승인 상태는 pending_e_d_review이며 자료 승인·문장별 정답표 동결·후속 확인 대화는 별도 인계입니다. 기존 bare_item_policy=clarify 설정은 호환 유지하고 unknown은 거절합니다. request_patterns는 미사용 호환 설정으로 LLM 의미 해석·공통 검증·좁은 폴백을 대신하지 않습니다. 로컬 모의 회귀 통과를 전체 평가나 이름 없는 자유 표현 수용 완료로 대신하지 않습니다.
- STT 실패는 clarify 보류입니다. LLM 저신뢰 응답 자체는 거절하지만 **그 뒤 규칙 폴백이 명확한 단일 요청을 검증하면 실행 후보가 될 수 있습니다**. 폴백도 보류면 재확인/미지원 안내만 제공합니다. 저신뢰 결과의 직접 실행과 검증된 폴백 실행을 구분합니다.
- `/voice/text_override`는 디버깅/테스트 보조 경로이며 시연·AC 평가는 실제 웨이크/STT 음성으로 수행합니다.
- 음성 취소는 보조 수단입니다. API 처리 중 새 웨이크 청취가 일시 정지되는 한계가 있으며 E voice가 로봇 ESTOP을 대신하지 않습니다. 1차 정지·실물 운용은 [안전 11장](safety.md)을 따릅니다.

### 6.4 LLM 인텐트 파서 (주 경로, 담당 E)

**P1 현재 출력·검증** [문서]

강의 `keyword_extraction.py`·STT 호출 구조를 참고한 [adapters/api.py](../ros2_ws/src/ready2go_voice/ready2go_voice/adapters/api.py)는 현재 온톨로지의 **물품 키·한국어 이름·별칭**을 prompt에 넣습니다. 목록·클래스·레지스트리 intent 자동 주입은 현재 경로에 없습니다. LangChain 후보 모델은 temperature 0·strict JSON을 사용하며 런타임 targets enum은 등록 물품 키로 생성합니다.

```text
제어/미지원·모호 규칙 → 필요한 경우 STT 텍스트 + 등록 물품 어휘 → LLM 후보
  → 기존 intent 계약 + P1 허용값 + 단일 등록 대상 + 확신도 + 발화 의미 검증
  → 오류·시간 초과·검증 실패/LLM 없음: 긍정 전체 문형·이름+좀/좀요로 좁은 폴백
  → 최종 find_item: 평가/세대/중복/확인 TTS 게이트 → /voice/intent
```

LLM 요청 스키마는 `intent`를 find_item/unknown/clarify로 제한하고 `targets`, `confidence`, `clarify_question`을 받습니다. cancel/status는 규칙 경로입니다. 외부 출력 정본 [intent.schema.json](../contracts/intent.schema.json)은 intent/confidence가 필수이며 현재 출력에서 targets·필요한 확인 질문과 진단 source를 덧붙입니다. strict 응답 형식이 사용자 의미의 정확성을 보장하지 않아 코드가 다시 검증합니다. P1은 goals/query 실행을 허용하지 않습니다.

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
- 완료 기준은 자연어 요청 3건 이상에서 생성 태스크의 스키마·트윈 사전 검증 및 실물 실행 성공입니다. P2 목표 추출/자동 계획과 P3 Stretch 태스크 직접 생성의 범위를 구분합니다.
