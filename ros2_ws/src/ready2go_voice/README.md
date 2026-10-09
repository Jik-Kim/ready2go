# ready2go_voice

- **담당**: E 고희태. 웨이크워드·STT·P1 단일 물품 LLM 해석/검증·규칙 폴백·TTS.
- **정본**: [requirements.md](../../../docs/requirements.md)의 [FR-INT-01–03](../../../docs/requirements.md#fr-int-01)·[음성 정책](../../../docs/requirements.md#voice-policy)·[AC-INT-01–03](../../../docs/requirements.md#ac-int-01), P2 [FR-SAF-01–03](../../../docs/requirements.md#fr-saf-01), P3 [FR-INT-02](../../../docs/requirements.md#fr-int-02). 의미·정책·책임·Phase·수용 기준을 이 문서에서 재정의하지 않습니다. [voice_llm.md](../../../docs/voice_llm.md)·[interfaces.md](../../../docs/interfaces.md)·[ontology.md](../../../docs/ontology.md)는 연결 참조입니다.
- [문서] 이 패키지 구현과 실제 장치/API·C 수신·D 평가 완료는 구분합니다. P2 목표 계획/BFS, P3 목록, 새 OntologyManager, 실행 상태 저장소/DB 로거는 구현 범위 밖입니다.

## 현재 구현과 파일 역할

| 경로 | 역할 |
|---|---|
| `core/config.py`, `params/voice.yaml` | YAML 설정과 범위 검사. 장치/모델/정답 정책·시간예산의 미확정 값 표시 |
| `core/intent.py` | 기존 온톨로지 전체 물품·별칭, P1 JSON·대상·확신도 검증, 규칙 폴백, 모호/미지원 보류 |
| `core/deadline.py`, `core/session.py` | API 단일 호출 슬롯·시간 초과 결과 폐기, 임시 WAV 정리, 평가/중복 발행 게이트 |
| `adapters/audio.py` | 강의 tflite 웨이크 모델 읽기, int16 mono 16kHz 녹음, 원본 고정5초 시운전 또는 RMS 무음 종료/최대 한도 |
| `adapters/api.py` | LangChain 프롬프트→gpt-4o 후보의 strict JSON, whisper-1 녹음 전사. SDK 재시도 없음 |
| `adapters/tts.py`, `adapters/melotts.py`, `adapters/melotts_worker.py` | 사용자 선택 MeloTTS 격리 CPU 합성/캐시→mono/int16 WAV→기존 PortAudio 재생. 명시 선택 espeak 호환 유지, 자동 폴백 없음 |
| `nodes/voice_node.py` | 기존 `/voice/text_override` 입력·`/voice/intent` 발행·`/voice/speak` Skill 액션·ROS 진단 로그 |
| `test/` | 해석/실패/지연·기록 종료·재생/취소·노드 평가 게이트의 모의 검사 |

[문서] 참고 코드 `keyword_extraction.py`·`STT.py`의 프롬프트/호출·녹음→Whisper 구조를 사용했습니다. 원본 `sd.rec`→`sd.wait`의 고정 5초 녹음을 시운전 기본으로 적용했습니다. 고정 도구 목록, `/` 문자열 분해, import 시 dotenv, 임시파일 누수는 옮기지 않았습니다. SciPy 대신 표준 `wave`를 사용합니다. 웨이크 모델 원본을 복제/수정하거나 모델을 자동 다운로드하지 않습니다.

## 현재 지원 명령

[문서·코드 대조: 2026-10-09] `7f96771`에서 분리한 이번 #194 구현의 Voice와 기존 계약·태스크·Runner 라우팅 원본을 대조했습니다. 타 파트 원본은 수정하지 않았습니다. 표는 **코드의 해석/라우팅 범위**이며 실제 마이크/API·Runner 수신·실물 실행 시험 결과가 아닙니다. 발화 예시는 허용 표현 전체 목록이나 성공 보장이 아닙니다. 정상 LLM 해석과 오류 후 좁은 규칙 폴백을 구분하며 폴백 문형만으로 지원 범위를 제한하지 않습니다.

| 명령 종류·연결 상태 | 발화/입력 예시 | 현재 처리 | 제한·운영 연결 | 근거 원본 |
|---|---|---|---|---|
| 단일 물품 가져오기 — 음성 해석 `find_item` | “지우개 찾아줘”, “지우개 가져다줘”, “지우개 좀”; 다른 등록 이름/별칭의 단일 요청 | 등록 단일 대상·발화 일치·요청 단서·확신도를 검증하고 확인 TTS 뒤 발행 게이트 적용 | 해석 대상은 등록 물품이며 현재 기본 `find_item` 태스크의 `trigger.targets`는 `eraser`만. 다른 등록 대상은 Runner에서 `UNSUPPORTED_ITEM` 보류. 실행 중/잠김/서버 미준비도 거절. 직접 태스크 실행은 trigger 제한을 거치지 않아 별도 입력 확인 필요 | [파서](ready2go_voice/core/intent.py)·[노드](ready2go_voice/nodes/voice_node.py)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py)·[태스크](../../../tasks/find_item.json) |
| 취소 — 음성/텍스트 제어 `cancel` | “멈춰”, “정지”, “취소”, “그만”; “멈춰.” | 설정 문구와 공백 정규화·끝 문장부호 제거 후 정확 비교. E가 기존 intent를 발행하며 텍스트 취소는 진행 중 해석 결과도 취소. Runner는 실행 중이면 `halt()` | 실행 중이 아니면 `NOT_RUNNING`. 실제 정지 확인·하드웨어 E-stop 대체가 아님. busy/TTS 중 새 웨이크 청취는 제한되며 텍스트 제어의 큐 우회와 음성 상시 수신은 다름. P2 안전 정지/복구/재개 완료와 구분 | [문구 설정](params/voice.yaml)·[파서](ready2go_voice/core/intent.py)·[Voice 노드](ready2go_voice/nodes/voice_node.py)·[Runner 노드](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| 상태 요청 — 음성/텍스트 제어 `status` | “지금 뭐 해”, “지금 뭐해”, “상태 알려”, “진행 상황”; “지금 뭐 해?” | 설정 문구와 같은 정확 비교로 E intent 발행. Runner는 `/runner/status`를 다시 발행 | 실제 현재 상태를 조회하여 음성으로 읽어주는 기능은 연결되지 않음. 기존 오류/중단 안내는 별도. 새 웨이크 청취 제한은 취소와 동일 | [문구 설정](params/voice.yaml)·[파서](ready2go_voice/core/intent.py)·[Runner 노드](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| 보류 응답 — `clarify`/`unknown`, 실행 명령 아님 | “지우개”, “그거 가져줘”, 여러 대상·미등록·미지원 요청 | 단독/모호/복수 대상은 확인 요청, 미지원은 보류 안내. 오류 후 폴백과 정상 unknown/clarify는 구분 | 실행 후보로 확정하지 않음. 실행 모드에서 보류 intent 자체가 발행될 수 있으나 Runner는 `NEEDS_CLARIFY`로 실행하지 않음. 부정/번역/제외·현재 질문 문맥의 핵심 모의 검사는 아래 #194 절에서 구분; 자유 실음성 일반화는 미검증 | [파서](ready2go_voice/core/intent.py)·[게이트](ready2go_voice/core/session.py)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py) |
| 목표형 `achieve_goal` — Runner 구조화 입력 지원, 음성 미지원 | 음성 미지원/구조화 JSON의 `goals` 입력 | Runner는 계약·신뢰도·목표·물품·실행/잠김을 검사하고 현재 상태에서 플래닝. 만족/계획 불가는 실행 보류 | Voice P1 필터는 목표형 intent·goals를 거절. Runner의 계획/서버/`plan_limits` 조건은 별도이며 실물 완료 의미가 아님. 기준은 [FR-PLN-02](../../../docs/requirements.md#fr-pln-02)·[AC-PLN-01](../../../docs/requirements.md#ac-pln-01) 참조 | [계약](../../../contracts/intent.schema.json)·[Voice 필터](ready2go_voice/core/intent.py)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py)·[Runner 노드](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| `find_list`/`find_class`/`query_state` — 현재 음성 미지원 | 음성 미지원/계약 enum만 존재 | Voice P1 필터에서 거절. 현재 `tasks/`에는 대응 trigger 태스크가 없어 기본 Runner 라우팅은 `UNSUPPORTED_INTENT` | 계약 enum 존재만으로 지원/실행 가능이라 판정하지 않음. 확장 기준·Phase는 [FR-INT-02](../../../docs/requirements.md#fr-int-02) 참조 | [계약](../../../contracts/intent.schema.json)·[Voice 필터](ready2go_voice/core/intent.py)·[태스크 목록](../../../tasks/)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py) |
| 레지스트리 태스크 `return_items` — 파일 존재, 현재 intent 연결 미지원 | 음성 미지원; 파일의 `examples_ko`는 지원 발화 근거 아님 | Runner loader는 `trigger.intent`를 등록하고 `intent_tasks` override를 우선하지만 `return_items`는 현재 계약 enum 밖이라 intent 입력은 `BAD_INTENT`. Voice도 미지원 | 레지스트리 로딩이 schema enum이나 음성 파서를 자동 확장하지 않음. 파일은 트레이 관측 단계만 있어 반납 완성 기능이 아님. `p1_demo_eraser`는 trigger.intent 없이 override/직접 실행용 | [예시 태스크](../../../tasks/return_items.json)·[시연 태스크](../../../tasks/p1_demo_eraser.json)·[계약](../../../contracts/intent.schema.json)·[로딩](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| P2 `stop`/`recover`/`resume` — 내부 후보·운영 미연결 | 내부 정책 예: “정지해”, “복구해”, “재개해”; 현재 운영 명령 아님 | 내부 표현 후보와 사건/질문/응답 정책만 준비 | ROS/TTS/listener/Runner 경로·새 wire 계약·실물 검증 미완료. 기존 cancel과 동일 기능으로 보지 않음. [P2 내부 준비](#p2-복구-후-재개-확인--내부-준비)·[FR-SAF-01–03](../../../docs/requirements.md#fr-saf-01) 참조 | [내부 정책](ready2go_voice/core/recovery_confirmation.py)·[운영 노드](ready2go_voice/nodes/voice_node.py) |

E Voice를 거치는 음성/텍스트 입력에는 [설정과 동작 경계](#설정과-동작-경계)와 [시운전 두 용도](#사용자-pc-시운전-명령-실제-녹음api는-사용자가-실행)가 적용됩니다. `evaluation_mode:=true`이면 cancel/status/unknown/clarify 포함 모든 `/voice/intent` 발행이 차단됩니다. 실제 음성 입력은 같은 로컬 설정의 `audio_enabled: true`와 준비된 모델/장치가 필요합니다. 요청 해석·발행 허용과 Runner/backend 연결·실물 실행 성공을 구분합니다. Runner 직접 구조화 입력은 E 평가/오디오 설정과 별개이며, E 평가 모드가 다른 입력으로 시작한 Runner 태스크를 중단하지 않습니다. 정책/Phase/수용 기준은 [FR-INT-01–03](../../../docs/requirements.md#fr-int-01)·[음성 정책](../../../docs/requirements.md#voice-policy)·[AC-INT-01–03](../../../docs/requirements.md#ac-int-01)에만 둡니다.

### 지원 명령 목록 갱신 절차

[문서: 사용자 승인] 명령·표현·대상 제한·파서/발행 게이트·Runner 라우팅·관련 계약/설정·운영 연결이 바뀌는 기능 PR은 이 표와 관련 설명을 함께 갱신합니다. E 작업 지시 작성 및 완료 검증 때 실제 생산자·수신자·설정·태스크·계약 원본과 목록/제약·미연결 상태를 대조하여 누락을 확인합니다. 타 담당 원본 변경은 E 작업 지시 세션으로 인계받아 문서에 반영하며 담당 수락·병합·실물 결과는 확인한 범위만 표시합니다. 확인 기준 버전/시점을 함께 갱신합니다. 이 절차는 수동 작업·검증 절차이며 자동 생성·자동 갱신·자동 검사·CI 차단을 구현한 것이 아닙니다.

## 설정과 동작 경계

[문서] `params/voice.yaml`은 시운전 제안값이며 `[팀 확정 필요]` 값은 장치·지연·E/D 정답표 확인 후 확정해야 합니다. 사용자 확정 기본은 **`evaluation_mode: false`, `audio_enabled: false`**입니다. 시작 시 ROS bool 파라미터 `-p evaluation_mode:=true/false`로 모드를 지정하며, 생략하면 false입니다. 이 시작 값이 YAML보다 우선하므로 기존 로컬 YAML이 true여도 미지정/CLI false는 실행 모드입니다. 유효 설정은 parser/Session/TTS 생성 전에 공유하며, 실행 중 `ros2 param set`으로 전환하는 기능은 구현하지 않습니다. 평가 모드에서는 find_item뿐 아니라 **cancel/status/unknown/clarify 모두 `/voice/intent`를 발행하지 않습니다**. ROS 진단 로그와 TTS만 제공하므로 평가 결과를 로봇 요청으로 전달하지 않습니다. C가 다른 입력으로 기동한 태스크까지 이 설정이 중단시키는 것은 아닙니다.

- 실제 웨이크/STT 평가는 장치/모델을 준비한 설정 복사본의 `audio_enabled: true`와 시작 인자 `-p evaluation_mode:=true`로 수행합니다. YAML의 evaluation_mode만 true로 바꾸는 것은 노드의 시작 기본값을 바꾸지 않습니다.
- 실행 모드는 기본값 또는 `-p evaluation_mode:=false`로 시작합니다. 기존 확인 TTS·취소·무발화·실패·중복 게이트를 유지하며, 실제 C 수신·모션·안전·태스크 연결은 별도 확인 대상입니다.
- 텍스트 override는 같은 파서의 디버깅 입력이며 실제 웨이크/STT 평가를 대신하지 않습니다.
- 요청 수용·보류·평가의 의미는 [음성 정책](../../../docs/requirements.md#voice-policy)을 참조합니다. 현재 `core/intent.py`·`adapters/api.py`는 선제 보류·LLM 후보 검증·좁은 규칙 폴백을 제공하며 `bare_item_policy` 검사와 미사용 `request_patterns` 호환 설정을 유지합니다. 정상 LLM과 오류 후 폴백은 서로 다른 경로입니다. 자유 한국어 전체의 판별을 보장하지 않으며 알려진 결함은 아래와 같습니다.
- [실측: 모의] 비요청 발화의 실행 후보 통과 결함은 미해결입니다. “지우개 가져다주면 안 돼”, “지우개 빼고 다른 것 가져줘”에 잘못된 LLM find_item(eraser)을 주입하면 `execution_allowed=true`가 됩니다. 위 보류 정책이 모든 부정·제외 문맥에서 구현됐다는 뜻은 아닙니다. 실제 발행·로봇 실행을 확인한 결과는 아니며, 판별 코드·회귀 검사의 별도 수정이 필요합니다. D의 모션 없는 평가에는 `evaluation_mode:=true`를 명시합니다.
- 기본 `confirmation_enabled: true`는 음성 확인 재생 성공 뒤 find_item 발행을 허용합니다. 실패하면 clarify로 보류합니다. C의 태스크 시작/기존 speak와 중복 안내 책임은 C/E가 맞춰야 합니다.
- cancel/status는 발화·설정 문구의 끝 `. ! ? 。 ！ ？`만 정규화하여 정확 비교합니다. `멈춰.`, `취소!`, `지금 뭐 해?`는 API/처리 큐를 거치지 않는 텍스트 제어 경로에서도 처리하며, 부정·문장 중간 문맥은 제거하지 않습니다.
- 실행 모드의 동일 find_item은 중복 시간창 안에서 TTS 전에 보류합니다. 중복 조회는 기록을 바꾸지 않으며 `/voice/intent` 발행 호출이 정상 반환한 뒤에만 기록합니다(C 수신·실행 성공 확인을 뜻하지 않습니다). TTS 실패·취소·시간 초과·발행 예외는 find_item을 소비하지 않아 재시도할 수 있습니다. 평가 모드는 동일 입력도 TTS/진단을 반복하고 모든 intent 발행을 금지합니다. unknown/clarify의 안내 및 기존 발행 중복 정책은 유지합니다. 무발화/VAD 검사 보류는 실행 모드에서도 intent를 발행하지 않습니다.
- cancel/status는 기존 intent로 C에 전달합니다. voice는 로봇 제어·ESTOP·현재 실행 상태 조회를 대신하지 않습니다. cancel은 진행 중인 E 해석 결과의 추가 발행도 취소합니다. 음성 취소는 보조 수단이며 API 처리 중 새 웨이크 청취는 일시 중지됩니다.
- STT/LLM 각각 단일 작업 슬롯과 SDK timeout/max_retries=0을 적용합니다. 늦은 결과는 폐기하며 후속 요청에 추가 발행하지 않습니다. 이미 끝나지 않은 작업이 있으면 새 API 작업을 쌓지 않고 보류/폴백합니다.
- `recording_mode: fixed`, `record_duration_sec: 5.0`, `timing_mode: commissioning`은 원본 기반 기능 시운전 기본입니다. 16kHz/int16/mono 80,000프레임을 녹음하며 웨이크 스트림을 닫은 뒤 같은 입력으로 새 sd.rec 스트림을 엽니다. `VOICE_MIC_DEVICE`→명시 input_device→16kHz 입력 자동 선택→기본 장치 순으로 한 번 정한 입력을 공유합니다. 시운전 API 상한은 STT/LLM 각각30초 제안값이고 늦은 결과 폐기·취소·평가 발행 금지는 유지합니다. commissioning의 API/녹음 설정은 실행·평가 모드 모두에서 사용할 수 있고, 평가 true는 계속 모든 발행을 차단합니다.
- 고정 녹음의 발화 종료·확인 지연은 null, latency_measurement=not_measured입니다. 녹음 완료 시각은 별도 recording_ended_*로 남기며 AC-INT-03 통과로 사용하지 않습니다. AC 준비는 recording_mode=silence/timing_mode=ac_budget로 설정하고 STT/LLM 상한·장치를 실측해 정합니다. 과거 설정에 신규 키가 없으면 기존 silence/ac_budget를 유지합니다.
- 무음 종료는 마지막 유성 프레임 시각을 기록합니다. `silence_sec` 대기·STT·LLM·TTS 준비를 [AC-INT-03](../../../docs/requirements.md#ac-int-03)의 예산에 포함합니다. `max_record_sec`는 보호 한도이며 고정 녹음 시간이 아닙니다. 한도 초과로 잘린 명령은 실행하지 않습니다.
- LLM 없는 경우 등록 별칭 규칙은 동작하지만 LLM 주 경로 및 자유 표현 완료를 의미하지 않습니다. faster-whisper 오프라인 STT는 현재 구현하지 않았습니다.

## 실행 준비와 의존성

| 구분 | 필요한 항목·확인 방법 |
|---|---|
| Python 기본 | 실제 core imports: jsonschema, PyYAML, numpy. `setup.py`에 선언 |
| Python API | `openai>=1,<3`, `langchain-openai>=0.2,<2`, `langchain-core>=0.3,<2` (`api` extra). 실제 SDK timeout/JSON 호출을 모의 검증 |
| Python 오디오 | sounddevice, openwakeword 0.6.0 (`audio` extra), 모델에 맞는 tflite_runtime 및 openwakeword 전처리 모델 자산. Python/CPU 호환 runtime은 배포 PC에서 확인 |
| ROS | rclpy, ament_index_python, std_msgs, ready2go_interfaces, ready2go_knowledge (`package.xml`). 기존 Skill 메시지 생성 필요 |
| 시스템 | PortAudio, 오디오 서버/권한·실제 마이크/스피커. Melo는 별도 CPU 환경 사용; espeak 선택 시만 espeak-ng 설치·한국어 음성 확인 필요 |
| 벤더/자산 | `OPENAI_API_KEY`는 기존 환경에서만 읽음. whisper-1/gpt-4o 계정 접근·네트워크·지연은 별도 확인. 외부 강의 `hello_rokey_8332_32.tflite` 경로를 설정하며 모델 원본/키를 커밋하지 않음 |
| 선택/미구현 | faster-whisper·Piper는 현재 imports/실행 경로에 없음. 기본 설치에 포함하지 않음 |

[문서] [공식 STT 문서](https://developers.openai.com/api/docs/guides/speech-to-text)의 whisper-1·어휘 prompt와 [구조화 출력 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)를 대조했습니다. 모델 계정 접근·유료 API 호출 성공은 문서 확인으로 대신하지 않습니다. 로컬 검사에서는 실제 키/API 호출을 하지 않았습니다.

저장소 루트에서 [전체 프로젝트 설치 안내](../../../README.md#프로젝트-의존성-설치)와 [requirements.txt](../../../requirements.txt)를 먼저 적용합니다. ROS Python은 `.venvs/project`(`--system-site-packages`), Melo CPU는 `.venvs/melotts`, Vision CUDA는 별도 환경을 사용합니다. `pip install voice[api,audio]`만으로 새 Ubuntu 24.04 PC의 설치가 끝나지 않습니다.

[실측: 로컬 파일·배포 메타데이터] 설치된 openwakeword 0.6.0의 Linux 의존성은 `tflite-runtime>=2.8,<3`이며 Python 3.12용 wheel 부재가 설치 장애입니다. 본체는 `--no-deps`로 설치하고 onnxruntime·tqdm·SciPy·scikit-learn·requests는 루트 requirements로 별도 설치합니다. 이 PC에는 시스템 Python의 `tflite_runtime/interpreter.py`가 `from ai_edge_litert.interpreter import Interpreter`를 제공하며 ai-edge-litert 2.2.0이 설치되어 있습니다. 이 호환 파일은 저장소 밖 파일이며 tflite-runtime 배포 메타데이터도 없습니다. `ai-edge-litert`만 설치해도 `tflite_runtime` 이름이 제공되는 것은 아닙니다. 새 PC를 위한 호환 runtime 배포/검증은 **미해결 인계**이며, 임의 shim이나 자동 ONNX 전환을 구현하지 않았습니다. runtime이 확인되기 전 실음성 웨이크 준비 완료로 보고하지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
cd ros2_ws
python3 /usr/bin/colcon build --symlink-install --packages-up-to ready2go_voice
cd ..
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
import importlib
for name in ('yaml', 'jsonschema', 'numpy', 'openai', 'langchain_openai',
             'sounddevice', 'onnxruntime', 'tflite_runtime.interpreter',
             'openwakeword', 'rclpy', 'ready2go_interfaces.msg'):
    try:
        module = importlib.import_module(name)
        print(name, getattr(module, '__file__', None))
    except Exception as exc:
        print(name, '미준비:', type(exc).__name__)
PYTHON
```

출력된 실제 import 경로와 실패 항목을 확인합니다. 이는 모델 로딩·마이크·API 성공 검사가 아닙니다. `python3 -m pip check`는 기존 PC의 별도 shim을 배포로 인식하지 않아 tflite-runtime 누락을 보고할 수 있습니다. 해당 오류를 설치 성공으로 숨기지 않습니다.

설정은 `logs/voice_eval/voice.local.yaml`, 키는 `secrets/voice.env`, 웨이크 자산은 `models/wakeword/`에 둡니다. 모든 명령은 저장소 루트에서 실행하며 config loader는 YAML 상대 경로를 실행 작업 경로에서 열고 Melo adapter도 작업 경로 기준으로 자산 경로를 해석합니다. YAML 파일의 디렉터리가 기준이 아닙니다. 로컬 설정의 `ontology_file: knowledge/robot_ontology.jsonld`, `intent_schema_file: contracts/intent.schema.json`, `wake_model: models/wakeword/hello_rokey_8332_32.tflite`, `tts_melotts_python: .venvs/melotts/bin/python`, `tts_melotts_assets: models/tts/melotts`를 실제 자산에 맞춰 확인합니다. 모델 이름은 예시이며 원본·키는 커밋하지 않습니다.

처음 설정할 때만 아래 복사를 수행합니다. 기존 로컬 YAML이 있으면 복사하지 않고 비교·필요 키만 수동 병합합니다. 다른 PC의 기존 `~/voice_assets/voice.pc2.yaml`은 git pull로 바뀌지 않는 진단 사례입니다. 그 파일을 표준 실행 위치로 가정하지 않으며, 로컬 표준 위치로 이식할 때 기존 장치/상한/모델/정책 값을 보존합니다. 원본 params YAML의 컨테이너/개인 경로는 호스트 실행 전에 위 상대 경로로 조정해야 합니다.

```bash
mkdir -p logs/voice_eval
if [ ! -e logs/voice_eval/voice.local.yaml ]; then
  cp -n ros2_ws/src/ready2go_voice/params/voice.yaml logs/voice_eval/voice.local.yaml
fi
```

`audio_enabled`·장치·웨이크 자산·`clarify_prompts` 전체 및 VAD 신규 키를 확인합니다. Melo 선택 시 `tts_engine: melotts`와 관련 키를 유지/설정해야 합니다. 엔진 키가 없으면 load_config는 **espeak**를 선택하며 git pull만으로 Melo가 선택되지 않습니다. 아래 검사는 키를 출력하지 않고 설정/선택만 확인합니다. 성공하더라도 실제 어댑터/재생 준비를 확인한 것은 아닙니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
from ready2go_voice.core.config import load_config
cfg = load_config('logs/voice_eval/voice.local.yaml')
print('tts_engine:', cfg['tts_engine'])
print('audio_enabled:', cfg['audio_enabled'])
PYTHON
```

Docker/compose 패키지·모델/runtime 배포는 별도 인계 대상입니다. 기존 sleep 명령만으로 voice_node가 실행되지는 않습니다.

## C/D 연결·진단·평가

[문서] `diagnostic_detail=true`에서는 민감정보를 제거한 상세 JSONL을 **YAML `diagnostic_file`의 E 로컬 파일**에 저장합니다. ROS 로그/콘솔과 tee는 최종 안내·대상·발행/수락 미확인·보류/오류 요약입니다. 새 진단 토픽이나 DB를 만들지 않습니다. 실행 모드에서는 기존 intent의 `source`에도 정보를 전달하지만 C 로그/run_id·D 화면 수신이 자동 연결되는 것은 아닙니다. 아래 부가 정보의 수신·의미는 C/D 협의 대상입니다.

- STT 원문, 실제 intent/targets, LLM 호출 여부·원문·검증 passed/failed/not_returned/not_called, 폴백 여부, 실행 허용/보류. 상세 JSONL에서 발행 여부는 최상위 `published`, intent는 `intent`입니다. 발행 여부는 진단 이벤트의 최상위 `published`이며 `/voice/intent`의 `source`에는 없습니다. `published=true`는 발행 호출 반환을 뜻하며 C 수신·실행 성공을 뜻하지 않습니다.
- 음성의 발화 종료 Unix/monotonic 시각, TTS 재생 시각, 확인 지연. TTS는 합성 시작/완료나 요청 접수가 아니라 **첫 PCM의 PortAudio DAC 재생 시각**을 장치 callback 정보로 기록합니다(`tts_start_basis=portaudio_first_dac`). 물리 스피커 청취 지연은 별도 확인해야 합니다.
- 실제 어댑터의 `tts_mock=false`와 테스트의 `tts_mock=true`를 구분합니다. 모의 시각·텍스트 입력으로 AC-INT-03 통과를 선언하지 않습니다. TTS 실패/장치 없음은 성공이나 실제 시작으로 기록하지 않습니다.

C #17 인계: 단일 find_item→태스크 수신, cancel/status, 모호/미지원 보류, 중복 요청, 확인 TTS/태스크 시작 책임, source→실행 로그/run_id 연결. voice는 nudge/pick을 직접 실행하지 않습니다. 현재 공통 pick은 탑뷰 관측→B 공간 판단/필요 시 끌기→탑뷰 재관측→새 target 집기를 수행하며, nudge.target_after 예상값을 집기에 사용하지 않습니다. 정식 find_item·점검용 p1_demo_eraser는 공통 robot_ontology.jsonld를 사용합니다. 실제 재관측·NO_PUSH_ACCESS·안전 종료 정합성 확인은 A/B/C/E 인계 사항입니다.

D #20 인계: [AC-INT-01–03](../../../docs/requirements.md#ac-int-01)·[음성 정책](../../../docs/requirements.md#voice-policy)에 연결해 평가자료 승인·문장별 정답을 먼저 고정하고 위 평가 모드에서 측정합니다. D 초안(JSON SHA256 `5995fc225c0a2cc78aa1c9264eee6a07518ad674ed4923763acf5017377aec84`)의 TC-008은 “지우개 찾아서 건네줘.”입니다. 당시 텍스트40개 회귀는 실제 음성 평가·자료 승인 완료를 대신하지 않습니다. 전체·종류별 정확도, LLM 호출 분모/검증 실패/폴백, STT·확인 지연·실행 시도를 분리해 기록하며 실제 측정은 남아 있습니다.

## P1 중단·오류 음성 안내 (#138)

[문서] 기존 `/runner/status`의 String JSON을 reliable/transient-local·depth10으로 읽기 전용 구독합니다. 상태 구독은 전용 `MutuallyExclusiveCallbackGroup`으로 동시 콜백 실행을 막고 text/action은 기존 Reentrant 그룹을 유지합니다. 수신 버퍼 확대와 콜백 상호 배제는 모든 입력 순서·누락 방지를 보장하지 않습니다. ROS 상태 콜백은 파싱·순수 정책·대기 슬롯 처리만 수행하며, 별도 안내 worker가 기존 TTS lock/취소/전체 timeout으로 재생합니다. 정지/복구 서비스나 로봇 상태/DB를 호출·변경하지 않으며 정지·취소 처리가 안내 재생을 기다리지 않습니다. 기존 취소/발행 보류·첫 DAC·Skill goal/result 계약을 유지합니다.

| 관측한 현재 코드/결과 | 고정 안내·시점 |
|---|---|
| 현재 `ESTOP` | “비상정지가 감지됐어요. 상태를 확인해 주세요.” |
| 현재 `HALTED`/취소 | “작업 중단이 요청됐어요. 상태를 확인해 주세요.” ESTOP으로 바꾸어 해석하지 않음 |
| `STOP_UNCONFIRMED`·`STATE_UNKNOWN`·`MOVE_UNCONFIRMED`·`LOCKED`·불명확 halt | “로봇 상태를 확인할 수 없어요. 직접 확인해 주세요.” |
| 새 최종 `FAILED`의 `TIMEOUT`/`LATE_RESULT` | 제한 시간·상태 확인 안내 |
| 새 최종 `FAILED`의 `DEPTH_INVALID`·`RESULT_INVALID`·`UNKNOWN_REGION`·`STUB_NOT_READY` | 물품 확인 실패·카메라/작업 공간 확인 안내 |
| 새 최종 `FAILED`의 `GRASP_FAILED` | 파지 실패·물품/그리퍼 확인 안내 |
| 그 외 새 실패·중단 결과 | 쉬운 일반 실패 또는 불명확 상태 확인 안내. 원본 오류 전문을 읽지 않음 |

문구·코드 매핑은 E의 `core/runner_notice.py` 고정 정책입니다. 7개 문구를 기존 Melo1.2 준비 캐시에 추가합니다. 안전 경고는 ESTOP→확인 불가→중단 요청 순으로 우선하며, 대기 안내는 하나만 유지합니다. 높은 경고가 오면 낮은 경고 재생을 취소하고, 새 회차/중단 해제는 낡은 대기 안내를 무효화합니다. 동일 사건 반복과 이미 확인한 완료 run_id는 재생하지 않고, 새 회차의 같은 오류는 다시 안내합니다. 첫 latched snapshot은 기준 상태로만 저장하며 동일 과거 halt/결과 반복도 무음입니다.

상태 경고는 이전 정상 안내/확인 결과의 epoch·generation을 무효화합니다. 실제 현재 halt가 유지되는 동안 정상 `/voice/speak` goal을 거절하고 이전 goal을 취소하지만, 일반 `FAILED` 자체로 지속 잠금을 만들지 않습니다. 일반 실패 뒤 새 음성 확인→intent→새 회차는 기존 게이트로 진행할 수 있습니다. 이미 재생된 음성은 되돌릴 수 없으며 취소는 기존 PCM/worker의 관측 주기에 적용됩니다. TTS 자체 오류는 실패 유형 로그만 남기고 재귀 안내·무한 재시도하지 않습니다. 상세 진단의 `notice_kind`는 고정 분류이며 새 토픽이나 계약 필드가 아닙니다.

[문서] running의 `last`는 이전 실행 결과일 수 있으므로 일반 실패로 안내하지 않습니다. 관측한 running 회차와 task_id가 맞는 새 최종 FAILED/ABORTED를 안내하며, 일반 실패는 현재 Runner가 finally 뒤 결과를 발행하는 **관측 시점**의 안내입니다. 중간 즉시 오류 안내가 아닙니다. 현재 상태에는 활성 run_id·이벤트 시각/순번이 없어 관측 전환 누락·미관측 같은 태스크의 지연/재정렬 snapshot·회차 간 완전한 결과 연결은 보장할 수 없습니다. 기존 계약을 임의로 확대하지 않고 [#138](https://github.com/Jik-Kim/ready2go/issues/138)의 C 상태 필드/발행 시점 인계로 남깁니다. 실제 E-stop/실물 상태·정지 확인·스피커·경고 지연은 미검증이며 “멈췄어요”라고 안내하지 않습니다.

## 검증과 남은 조건

```bash
PYTHONPATH=ros2_ws/src/ready2go_voice:ros2_ws/src/ready2go_knowledge:ros2_ws/src/ready2go_runner python3 -m pytest ros2_ws/src/ready2go_voice/test -q -rs
```

ROS 노드 검사는 생성된 ready2go_interfaces와 ROS 환경을 source한 뒤 실행합니다. API/오디오 SDK가 없는 환경은 해당 어댑터 검사를 명시적으로 skip하며 core 검사는 수행합니다. 테스트의 fake API·장치는 실제 음성 수용 기준의 근거가 아닙니다. 실제 장치/한국어 음성·API·C/D·Docker 연결은 CURRENT의 실측/미검증 기록을 확인하십시오.

## 사용자 PC 시운전 명령 (실제 녹음/API는 사용자가 실행)

| 용도 | 시작 인자 | `/voice/intent` 발행 | 로그 파일 |
|---|---|---|---|
| 음성 평가용 | `evaluation_mode:=true` | 모든 intent 발행 차단 | `voice.eval.*.log` 요약 + YAML 상세 JSONL |
| Runner 연동용 | `evaluation_mode:=false` | 기존 확인 TTS·취소·무발화·실패·중복 게이트 적용 | `voice.run.*.log` 요약 + YAML 상세 JSONL |

두 명령은 **같은 로컬 YAML의 `audio_enabled: true`와 준비된 마이크·웨이크 모델·입력 장치**가 있어야 실제 음성 입력을 받습니다. 명령 자체는 마이크를 켜거나 로컬 YAML을 변경하지 않습니다. `audio_enabled: false`이면 자동 마이크/웨이크 청취 없이 `/voice/text_override` 디버깅 입력을 사용할 수 있으며 실제 음성 평가가 아닙니다.

- `evaluation_mode`는 모든 `/voice/intent` 발행 차단 여부를 정합니다. ROS 시작 인자가 YAML보다 우선하며 생략하면 false입니다. 평가 모드는 다른 입력으로 시작한 Runner 태스크까지 중단시키지 않습니다.
- `audio_enabled`는 YAML에서 마이크·웨이크 사용 여부를 정합니다. 평가/Runner 연동 모드와 별개입니다.
- 두 명령의 `diagnostic_detail:=true`는 YAML `diagnostic_file`에 민감정보를 제거한 상세 JSONL을 저장합니다. 콘솔과 `tee` 파일은 요약이며 전체 LLM 증빙을 대신하지 않습니다. 기존 로컬 YAML의 새 진단/문맥/캐시 설정을 원본과 수동 병합하고, 회차별 상세 경로가 필요하면 시작 전 로컬 설정에서 바꿉니다. 기존 자산/키/YAML을 덮어쓰지 않습니다.

아래 수동 명령은 PC에 설치된 선택 도구 python-dotenv를 사용합니다(voice 런타임은 이미 로드된 환경을 읽습니다). **저장소 루트**와 현재 프로젝트 build/install 및 `.venvs/project`를 사용합니다. 로그/모델/키는 로컬 자산이며 키 값을 출력하지 않습니다. 기존 PC의 정상 로컬 설정은 사용자 선택 MeloTTS였으며, 다른 PC의 엔진 선택은 위 설정 검사로 확인합니다. 한국어 단문 합성·첫 DAC 재생은 확인했으며, 마이크/STT·LLM·전체 음성 평가는 재시험해야 합니다.

[실행 준비와 의존성](#실행-준비와-의존성)의 설정 확인, 아래 MeloTTS 절의 단독 WAV 합성, [사전 캐시 준비](#melotts-prefill)의 경로 확인·캐시 생성·완료 확인·대표 문구 청취는 **노드 실행 전 준비·점검 절차**입니다. 이 두 시운전 명령의 대안이나 실제 음성/Runner 연결 검증이 아닙니다. 설치·합성·캐시·청취의 상세 절차는 해당 절을 따르십시오.

각 실행은 `mktemp`로 새 로그를 만들어 기존 기록을 덮어쓰지 않습니다. `python3 -u`는 Python 출력 버퍼링을 줄이고 `pipefail`은 노드 오류 종료를 파이프라인 결과에 반영합니다. 로컬 YAML/키/모델은 덮어쓰지 않습니다. 진단 원본/source의 C/D 수신·필드 대응 협의는 유지하며 기본 짧은 콘솔을 상세 평가 기록으로 대신하지 않습니다.

**음성 평가용 — 모든 intent 발행 차단**

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
mkdir -p logs/voice_eval
voice_eval_log=$(mktemp logs/voice_eval/voice.eval.XXXXXXXX.log)
set -o pipefail
python3 -u - <<'PYTHON' 2>&1 | tee "$voice_eval_log"
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main
load_dotenv('secrets/voice.env')
main(args=['--ros-args', '-p', 'config_file:=logs/voice_eval/voice.local.yaml', '-p', 'evaluation_mode:=true', '-p', 'diagnostic_detail:=true'])
PYTHON
```

**Runner 연동용 — 기존 발행 게이트 적용**

요청 전달 허용은 Runner 수신·태스크 시작·실물 실행의 증명이 아닙니다. C 수신·태스크·안전 연결과 선택한 backend를 별도로 확인하십시오. 실물 연동은 DB·TF·DSR·그리퍼 상태·Runner·스킬 서버·카메라·비전의 준비 및 대상·배치를 확인한 환경에서 수행합니다. voice가 로봇을 직접 제어하지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
mkdir -p logs/voice_eval
voice_run_log=$(mktemp logs/voice_eval/voice.run.XXXXXXXX.log)
set -o pipefail
python3 -u - <<'PYTHON' 2>&1 | tee "$voice_run_log"
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main
load_dotenv('secrets/voice.env')
main(args=['--ros-args', '-p', 'config_file:=logs/voice_eval/voice.local.yaml', '-p', 'evaluation_mode:=false', '-p', 'diagnostic_detail:=true'])
PYTHON
```

기존 fixed5초/commissioning·API/TTS 상한·MeloTTS·wake0.7은 그대로 사용하며 두 모드 모두 실제 발화 종료/3초 지연은 null/not_measured입니다. 위 명령으로 실음성 정확도·지연·청취 품질·C/D 연결 완료를 선언하지 않습니다.

실제 음성 입력이 준비된 경우의 기본 콘솔 흐름은 웨이크 대기→감지 점수→5초 녹음 시작/완료→Whisper 요청/STT 결과→LLM 또는 폴백 결과→TTS 시작/종료→모드와 게이트에 따른 발행/보류→다시 대기입니다. 프레임마다 점수를 출력하지 않습니다.

## MeloTTS 설치·재생 (P1 E, 사용자 선택)

[문서] ROS Python에 Melo 의존성을 설치하지 않습니다. 기존 PC에서 확인한 프로젝트 내부 `.venvs/melotts`는 Python 3.12.3 CPU 전용이며, 새 PC 설치 검증은 별도입니다. `models/tts/melotts`는 공식 소스·한국어 모델/BERT·NLTK·Numba·WAV 캐시와 worker.log입니다. 두 경로는 Git 제외입니다. 공개 다운로드만 사용하며 TTS 실행은 오프라인이고 외부 음성 전송/API 키 사용은 없습니다.

- 공식 소스 revision: `209145371cff8fc3bd60d7be902ea69cbdb7965a` ([upstream](https://github.com/myshell-ai/MeloTTS/tree/209145371cff8fc3bd60d7be902ea69cbdb7965a)). 공식 설치 문서는 Python 3.9/Ubuntu 20.04 기준입니다.
- 한국어 Melo 모델: `myshell-ai/MeloTTS-Korean` revision `0207e5adfc90129a51b6b03d89be6d84360ed323` ([모델](https://huggingface.co/myshell-ai/MeloTTS-Korean)); 필요한 한국어 BERT: `kykim/bert-kor-base` revision `1779cc0982ada0216dd6de0dd4e86fb78201926d`.
- 이 PC에서 확인한 별도 의존성은 [melotts_requirements.txt](params/melotts_requirements.txt)에 고정합니다. torch/torchaudio 2.5.1+cpu는 공식 PyTorch CPU index, 나머지는 PyPI입니다. transformers 4.41.2/tokenizers 0.19.1·librosa 0.10.2.post1은 Python 3.12 호환 시험용으로 upstream 고정값과 다릅니다. 일반 upstream 호환 보장이 아닙니다. 한국어 MeCab wheel/사전·g2pkk·cmudict는 발음 처리에 필요합니다.
- [melotts_kr.patch](params/melotts_kr.patch)는 내려받은 전용 소스에만 적용합니다. 한국어 cleaner/BERT만 로딩하고 BERT는 pinned 로컬 경로를 사용하며 외부 URL 모델 폴백을 막습니다. 다국어 모델/일본어 사전·CUDA·학습/UI를 설치하지 않습니다. 공식 원격 저장소는 수정하지 않습니다.

저장소 소스의 설치기를 명시 실행합니다. 기존 다른 revision 소스는 덮어쓰지 않습니다. 인터넷이 필요한 것은 설치 단계뿐입니다.

```bash
python3 ros2_ws/src/ready2go_voice/ready2go_voice/adapters/melotts_install.py --project-root .
```

[문서] `tts_engine: melotts` 실패는 준비/합성 실패로 표시되고 espeak로 자동 전환하지 않습니다. 기존 설정에 엔진 키가 없으면 espeak 호환 경로입니다. MeloTTS·음성 속도1.2는 사용자 확정입니다. CPU4스레드/준비상한60초/재생전체상한20초는 기존 실측 기반 **제안값 [팀 확정 필요]**이며, AC 모드의 `start_deadline` 3초는 완화하지 않습니다. 준비 때 등록 물품별 요청 확인·구체 질문과 P1 태스크의 “{{name|을}} 찾아 올게요”, “{{name|을}} 앞쪽 트레이에 놓았어요”, “{{name|을}} 찾지 못했어요”, 고정 “서랍을 닫았어요”, `clarify_prompts` 전체와 사용자 `tts_melotts_prefill_texts`를 중복 제거해 캐시에 넣고 완료 후에만 voice ready/웨이크 입력을 시작합니다. 목록 밖 문장은 최초 합성이 필요합니다. 캐시 키는 문장·모델 파일/리비전·소스/worker·의존성·speaker·속도·스레드를 반영합니다.

단독 합성은 설치된 Melo 소스/API를 직접 사용해 새 WAV를 만듭니다. ROS·마이크·API·스피커 재생을 사용하지 않으며 voice worker의 캐시/시간 예산 검사와도 구분합니다. 저장소 루트에서 실행합니다.

```bash
mkdir -p logs/voice_eval
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NLTK_DATA=models/tts/melotts/nltk \
  .venvs/melotts/bin/python - <<'PYTHON'
import json
import os
import sys
import tempfile
from pathlib import Path
assets = Path('models/tts/melotts').resolve()
manifest = json.loads((assets / 'model_manifest.json').read_text())
os.environ['MELOTTS_BERT_PATH'] = manifest['kykim/bert-kor-base']['path']
sys.path.insert(0, str(assets / 'source'))
import torch
torch.set_num_threads(4)  # 기존 CPU 시운전 제안값; 팀 확정/해당 PC 실측 필요
from melo.api import TTS
kr = Path(manifest['myshell-ai/MeloTTS-Korean']['path'])
tts = TTS(language='KR', device='cpu', config_path=str(kr / 'config.json'),
          ckpt_path=str(kr / 'checkpoint.pth'))
with tempfile.NamedTemporaryFile(dir='logs/voice_eval', prefix='melotts.', suffix='.wav', delete=False) as f:
    output = f.name
tts.tts_to_file('지우개 가져다드리겠습니다.', tts.hps.data.spk2id['KR'], output, speed=1.2)
print(output)
PYTHON
```

[문서] 사전캐시 문장의 조사·띄어쓰기·마침표는 실제 `tasks/find_item.json` 렌더와 대조했습니다. “서랍을 닫았어요”의 E 책임은 합성 준비이며, C 태스크의 같은 실행 닫기 성공 후 안내는 [#140](https://github.com/Jik-Kim/ready2go/pull/140)(merge `0c0a971`)으로 main에 반영됐습니다. C mock 통합 리뷰와 PC2 실물 실행 순서·시간 검증은 구분합니다. 속도 변경은 캐시 키를 바꾸며 동일 환경·문장의 재시작 캐시는 기존 디스크에서 조회합니다. worker 코드 변경도 키에 반영되어 이전 캐시와 구분됩니다. PC2 준비 완료·새 속도 청취 품질·3초 달성은 미검증입니다. Google Cloud TTS 도입은 철회되었으며 SDK/자격증명은 추가하지 않습니다.

<a id="melotts-prefill"></a>

### 노드 실행 전 사전 캐시 준비

[문서] 아래 순서는 **저장소 루트**, 실제 노드와 같은 로컬 YAML·프로젝트 환경에서 실행합니다. Voice 노드를 먼저 종료하고, 현재 저장소 코드와 일치하는 설치 overlay를 사용하십시오. 확인 시점 main `bbad373`에는 [PR #144](https://github.com/Jik-Kim/ready2go/pull/144)가 병합됐습니다. 코드 병합과 해당 PC의 빌드·설치·source 반영은 구분하여 확인합니다. 필요한 설치는 [실행 준비와 의존성](#실행-준비와-의존성)을 따릅니다. 모델 다운로드/설치는 위 설치 절차이며 캐시 준비와 구분합니다.

**1. 설정·경로 확인(합성·재생 없음)**

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
import os
from pathlib import Path
from ready2go_voice.core.config import load_config
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_knowledge.core.ontology import load
cfg = load_config('logs/voice_eval/voice.local.yaml')
assert cfg['tts_engine'] == 'melotts' and cfg['tts_melotts_speed'] == 1.2, '실제 로컬 YAML의 엔진/속도를 확인하십시오'
runtime = Path(cfg['tts_melotts_python']).expanduser().absolute()
assets = Path(cfg['tts_melotts_assets']).expanduser().resolve()
assert runtime.is_file() and os.access(runtime, os.X_OK), 'Melo 전용 Python 설치/경로를 확인하십시오'
assert (assets / 'model_manifest.json').is_file(), 'Melo 모델 설치/경로를 확인하십시오'
ontology = load(cfg['ontology_file'])
texts = prefill_texts(cfg, ontology['world']['items'].values())
print('Melo Python:', runtime)
print('Melo assets:', assets)
print('현재 prefill 문장 수:', len(texts), '(warmup은 별도)')
print('캐시:', assets / 'wav_cache')
print('worker 로그:', assets / 'worker.log')
PYTHON
```

로컬 `voice.local.yaml`이 공유 설정보다 우선합니다. 경로는 저장소 루트 기준이며 로컬 YAML의 절대 경로는 그대로 사용합니다. 위 확인 실패 시 준비/노드 실행을 보류하고 해당 PC의 runtime·모델·ontology 경로를 먼저 바로잡으십시오. 이 확인은 파일 존재·설정·목록 검사이며 실제 모델 로딩 성공 검사가 아닙니다.

**2. 전체 고정 문구 캐시 생성(물리 재생 없음)**

최초 설치·속도/worker 변경 뒤 cold-cache 준비는 일반 노드의 재시작 반복으로 수행하지 않습니다. [과거 문장 목록] 이전 등록11종 안내와 상태7종은 prefill63개+warmup1개, 총64개였습니다. 이번 목록은 요청 확인·구체 질문·미지원과 bounded 빈번 문장을 포함하므로 아래 사전 준비 명령의 출력 목록/개수를 기준으로 확인합니다. [추정] 과거 속도1.0 단문 약2.43초를 단순 적용하면 약156초로, 기존 전체 준비 상한60초를 넘을 수 있습니다. 새 속도1.2·긴 안내·운용 PC의 실제 준비 시간으로 확인해야 하며 이 추정을 새 상한이나 팀 확정값으로 사용하지 않습니다.

노드를 종료한 뒤 아래 **캐시 준비만** 먼저 수행합니다(마이크/API/출력 장치 사용 없음). [사용자 결정] 사전 준비 상한은 **120초**로 선택하며 이 명시 실행의 메모리 설정에만 적용합니다. 120초 이내 완료 여부는 미실측이며 충분한 시간이라고 보장하지 않습니다. 기존 YAML·일반 노드 준비상한·재생전체20초·AC3초 예산은 변경하지 않습니다. 실패하면 상한/worker.log/환경을 점검하고 일반 노드를 시작하지 않습니다. 완료 뒤 같은 worker·속도·모델·설정으로 일반 노드를 시작합니다. 동일 환경이라도 60초 안에 준비 가능한지 PC2에서 별도 확인해야 합니다. 일반 노드의 `tts_melotts_startup_timeout_sec: 60.0`은 유지합니다. 노드는 시작마다 `prepare()`로 모델 로딩과 캐시 확인을 수행하지만, 같은 캐시 키의 디스크 WAV는 재사용하고 없거나 키가 변경된 문장만 합성합니다. 모델 로딩·캐시 확인 비용이 없어지는 것은 아닙니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
export MELOTTS_PREFILL_TIMEOUT_SEC=120
python3 - <<'PYTHON'
import math
import os
import time
from ready2go_knowledge.core.ontology import load
from ready2go_voice.core.config import load_config
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_voice.adapters.melotts import MeloTTS
cfg = load_config('logs/voice_eval/voice.local.yaml')
if cfg['tts_engine'] != 'melotts':
    raise ValueError('MeloTTS 설정을 확인하십시오')
limit = float(os.environ['MELOTTS_PREFILL_TIMEOUT_SEC'])
if not math.isfinite(limit) or limit <= 0:
    raise ValueError('준비 상한은 유한 양수 초 단위입니다')
cfg['tts_melotts_startup_timeout_sec'] = limit
ontology = load(cfg['ontology_file'])
cfg['_tts_prefill_texts'] = prefill_texts(cfg, ontology['world']['items'].values())
started = time.monotonic()
tts = MeloTTS(cfg)
try:
    tts.prepare()  # 모델·전체 문장 합성/조회만 수행하며 speak를 호출하지 않습니다.
    print('전체 캐시 준비 완료(초):', round(time.monotonic() - started, 3))
finally:
    tts.close()
PYTHON
MELOTTS_PREFILL_EXIT_CODE=$?
unset MELOTTS_PREFILL_TIMEOUT_SEC
printf '캐시 준비 종료 코드: %s\n' "$MELOTTS_PREFILL_EXIT_CODE"
test "$MELOTTS_PREFILL_EXIT_CODE" -eq 0
```

**3. 완료 로그·실패 원인 확인**

`MeloTTS 준비 완료 (고정 안내 캐시 완료)`와 `전체 캐시 준비 완료(초): ...`를 확인하고, 위에서 보존한 **종료 코드가 0**일 때만 다음 단계로 진행합니다. 완료는 현재 설정의 모델과 전체 고정 문장 합성/캐시 조회를 뜻하며, 물리 재생이나 AC-INT-03 3초 달성은 뜻하지 않습니다. 준비 시간과 사용 설정을 #138 운용 기록에 남기십시오.

캐시는 `tts_melotts_assets/wav_cache`, 로그는 같은 assets의 `worker.log`입니다(기본 `models/tts/melotts/wav_cache`, `models/tts/melotts/worker.log`). 오래된 키의 WAV도 남을 수 있으므로 파일 개수만으로 현재 준비 성공을 판정하지 않습니다. 기본 경로의 최근 로그는 다음처럼 읽습니다. assets를 변경했다면 1단계에 출력된 경로를 사용하십시오.

```bash
tail -n 80 models/tts/melotts/worker.log
```

- `MELOTTS_PREPARE_TIMEOUT`/`MELOTTS_PREPARE_FAILED`: worker 로그의 실제 원인과 해당 PC 준비 시간을 확인합니다. 120초 상한 내 준비에 실패하면 worker 로그의 실제 원인과 준비 시간을 확인합니다. 사전 준비를 다시 실행할 때는 노드를 먼저 종료합니다. 일반 노드를 반복 재시작하며 캐시를 쌓거나 일반 YAML/AC3초 예산을 임의로 늘리지 않습니다.
- `MELOTTS_RUNTIME_MISSING`/모델·의존성 오류: 설정된 전용 Python, manifest의 모델 경로, 고정 의존성과 설치 절차를 대조합니다. 종료 코드가 비0이거나 완료 문구가 없으면 노드를 시작하지 않습니다.
- 속도·모델·worker/소스·의존성·speaker·스레드·문구가 바뀌면 관련 캐시 키가 바뀌거나 새 문장이 필요하므로 사전 준비를 다시 합니다. 같은 설정·환경의 재시작은 디스크 캐시를 재사용합니다. 캐시 준비 후에도 일반 노드 준비 상한 내 완료 여부는 따로 확인합니다.

**4. 대표 문구 청취 시험(스피커 사용)**

마이크·API·로봇 없이 기존 출력 장치에서 재생하는 명령입니다. 음성 노드는 먼저 종료하십시오. 2~3단계 성공 후 실제 YAML의 출력 장치로 정상 확인·닫기·예외 안내를 들어보십시오. 실패하면 출력 장치/재생 환경을 확인하고 노드 기동을 보류합니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
from ready2go_voice.adapters.tts import create_tts
from ready2go_voice.core.config import load_config
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_knowledge.core.ontology import load
cfg = load_config('logs/voice_eval/voice.local.yaml')
if cfg['tts_engine'] != 'melotts':
    raise ValueError('로컬 설정의 tts_engine을 확인하십시오: Melo 재생 시험입니다')
cfg['_tts_prefill_texts'] = prefill_texts(cfg, load(cfg['ontology_file'])['world']['items'].values())
tts = create_tts(cfg)
try:
    tts.prepare()
    for text in ('지우개 가져다드리겠습니다.', '서랍을 닫았어요',
                 '비상정지가 감지됐어요. 상태를 확인해 주세요.'):
        print('청취 문구:', text)
        print(tts.speak(text, on_start=print, on_timing=lambda value: print('timing:', value)))
finally:
    tts.close()
PYTHON
```

**5. 같은 설정으로 노드 실행**

청취 시험을 종료한 뒤 [사용자 PC 시운전 명령](#사용자-pc-시운전-명령-실제-녹음api는-사용자가-실행)의 동일 `voice.local.yaml`을 사용합니다. 노드의 `MeloTTS 준비 완료 (고정 안내 캐시 완료)`와 음성 ready를 확인한 뒤 입력을 시작합니다. 준비 실패·timeout이면 입력/로봇 실행을 시작하지 않습니다.

청취 시험 콘솔의 `TTS 준비 완료: 캐시 사용/새 합성` 및 `timing`의 `cache_hit`·`worker_synth_sec`·`synthesis_wait_sec`·`playback_sec`를 확인합니다. prepare-only 완료 로그는 문장별 cache_hit를 출력하지 않습니다. 노드 운용에서는 아래 진단 경로를 사용합니다.

[문서] `diagnostic_detail=true`의 상세 JSONL `timing`에 `synthesis_wait_sec`(worker 준비/응답·캐시 조회/합성을 포함한 대기), `cache_hit`, `worker_synth_sec`(worker 조회/합성 처리 시간), 성공 완료 시 `playback_sec`·`playback_ended_monotonic`·`playback_end_basis=portaudio_finished_callback`을 기록합니다. 시작은 기존 첫 PortAudio DAC 기준입니다. 기본 콘솔은 기존 종료 한 줄에 합성 대기/재생 시간을 붙이며 새 전문/키는 출력하지 않습니다. 이 필드는 로그 진단이며 `/voice/speak` 결과/intent source 계약에 추가하지 않습니다. 취소/기한/장치 실패는 성공 재생 구간으로 기록하지 않습니다. Runner 요청→종료 시간은 이 두 구간 외 통신/스케줄링 등이 포함될 수 있어 전부 합성 시간으로 단정하지 않습니다.

[과거 실측: 속도1.0 CPU 합성] 같은 확인 문장 1스레드 9.79/7.59초, 2스레드 3.99/4.23초, 4스레드 2.49/2.43초. 첫 측정은 BERT 첫 로딩 비용 포함입니다. 모델 로딩 약1.8초와 합성 지연은 구분합니다. [실측: 로컬 재생] 한국어 mono/int16 44.1kHz WAV 합성 및 PortAudio 첫 DAC 재생 성공. 캐시는 약3ms 조회, 준비된 문장의 요청→첫DAC은 약0.165초였으며 **발화 종료→STT/LLM→첫 DAC 3초 달성 근거가 아닙니다**. 실제 청취 품질·40음성·C/D 연결은 미확인입니다.

## 웨이크·무발화·clarify 후속 보완

[문서] 사용자 확정 웨이크 기준은 `wake_threshold: 0.7`이며 기존 **점수 > 기준** 비교를 유지합니다(정확히0.7은 감지하지 않음). 녹음은 기존 `sd.rec`→`sd.wait` 고정5초/16kHz/int16/mono이며 추가 대기·자르기는 없습니다. 고정 녹음 완료 뒤 설치된 openwakeword의 Silero VAD를 로컬로 실행합니다. `speech_vad_model: null`은 패키지의 `resources/models/silero_vad.onnx` 자산을 뜻하며 다운로드하지 않습니다. 명시 경로도 설정할 수 있습니다.

[제안] 30ms 프레임의 VAD 점수≥`speech_vad_threshold: 0.5`와 RMS≥`speech_rms`를 함께 만족하는 연속 구간≥`speech_min_voiced_sec: 0.15`를 찾습니다. 두 VAD 튜닝값은 **[팀 확정 필요]**입니다. 전체5초 평균으로 짧은 요청을 버리지 않습니다. 무발화·모델 없음/오류·취소는 STT/LLM 호출 및 발행을 보류하며, 무발화는 `record_error=NO_SPEECH`, LLM `not_called`로 남습니다. 발화로 판정되면 5초 전체 WAV를 STT에 보냅니다. fixed의 실제 발화 종료/확인 지연은 계속 null/not_measured입니다.

[문서] `clarify_prompts`는 기본/실패 안내입니다. #194 구현은 의미 검증된 내부 LLM 문장을 유지하고 대상·판정에 맞지 않는 후보만 대체하며 최종 콘솔/TTS 입력을 일치시킵니다. 현재 대상의 구체 질문과 실제 TTS 완료 뒤의 유효한 답/대상 정정은 `Conversation`에서 한 번 처리합니다. 정책 정본은 [음성 정책](../../../docs/requirements.md#voice-policy)이며 D 정답표 반영·실음성 평가는 별도 인계입니다. 시작 캐시는 합성만 하며 과거 질문 권한을 복원하지 않습니다.

기본 콘솔은 최종 안내·intent/target·발행/수락 미확인·보류/오류와 간결한 준비/재생 정보를 표시합니다. 상세 단계 시각/LLM 원문은 `diagnostic_detail=true`의 로컬 JSONL에서 확인합니다.

[실측: 로컬 합성 입력] 실제 Silero는 무음·미세/큰 임의 잡음·200Hz 정현파를 무발화로, 기존 MeloTTS 생성 시험 WAV를 발화로 판정했습니다. 새 질문 사전캐시 준비36.26초, 일반 고정 clarify의 캐시 응답5~7ms(캐시 히트)였습니다. 마이크/STT/LLM/실제 첫DAC 지연 측정이 아닙니다. 90ms 순간 구간 거절·180ms 구간 허용은 모의 검사입니다. **180ms 이상의 웨이크 잔음도 통과할 수 있으며**, 실제 마이크에서 무발화/짧은 정상 명령·오탐을 재시험해야 합니다.

재실행은 위 “사용자 PC 시운전 명령”을 사용합니다. 웨이크 후 아무 말도 하지 않는 시험에서는 Whisper 요청 없이 무발화 안내·발행 보류가 나오는지, 짧은 정상 요청은 통과하는지 확인하십시오. LLM 질문은 검증 후 최종 문장·실제 TTS 입력과 상세 JSONL의 원본/대체 사유·캐시 시간을 대조하십시오. 실제40음성·3초·청취 품질·C/D 연결은 미완료입니다.

## P2 복구 후 재개 확인 — 내부 준비

[문서] `core/recovery_confirmation.py`와 해당 모의 시험은 E 내부 제안이며 ROS·TTS·listener·Runner 실행에 연결하지 않았습니다. 정지/복구/재개 명시 표현과 현재 사건/작업의 질문 1회·유효한 일회성 응답을 준비합니다. 현재 busy/TTS 중 실제 청취 제한은 유지합니다. [요구사항 정본](../../../docs/requirements.md#fr-saf-01)·[처리 경계](../../../docs/voice_llm.md#p2-safety-voice)·[계약안](../../../docs/interfaces.md#p2-safety-proposal)을 확인하십시오. 운영 연결의 책임·검증 기준은 [FR-SAF-03](../../../docs/requirements.md#fr-saf-03)을 참조합니다. #165 병합과 실제 마이크/API·장치 복구/재개 검증은 구분합니다.

## #43·#152 내부 확인 정책 — 운영 미연결

[문서] [사후 검증 정본](../../../docs/requirements.md#verification-policy)·[재개 접수 정본](../../../docs/requirements.md#resume-admission-policy)을 기준으로 core/skill_confirmation.py와 recovery_confirmation.py를 준비합니다. pick/place 판정은 E 내부 후보와 비전/사용자 근거 분류만 반환하고 C effect/로그·성공 안내·모션을 실행하지 않습니다. place 질문에는 이번 run/step의 기대물품별 개수·총개수·목적지를 포함하며 모호 응답은 설정된 재확인 한도 안에서 새 질문 객체로 분리합니다. 미정 대기/횟수는 안전측 보류합니다.

[문서] recovery 정책은 boot 변경·동일 run/halt의 seq·질문/TTS 완료·녹음 시작/끝·SDK 직전 접수·별도 결과 만료·일회성·재정지·포기를 분리합니다. 일반 cancel은 대상 보존이며 포기와 다릅니다. WhisperSTT의 optional before_request와 Recording의 시작/끝 monotonic은 실제 E 프로세스 경계 자료형이지만 운영 Session/노드의 P1 입력/발행에는 연결하지 않았습니다. 기존 progress whisper_requested는 실제 SDK 접수 증빙으로 쓰지 않습니다. 실제 TTS 종료는 PortAudio 완료 증빙이 필요합니다. B unknown이나 처리 예산 미정일 때 운영 재개 요청을 만들지 않습니다.

설정 원본 params/voice.yaml의 내부 값과 null/[팀 확정 필요]를 확인하십시오. P1 STT/API/AC 예산을 새 정책의 처리 예산으로 복사하지 않습니다. C v2의 answer enum/질문 등록/프로세스별 clock·hold와 B 확인 모드·관측은 [회신안·인계](../../../docs/voice_llm.md)에서 협의하며 미승인 wire/운영 adapter는 추가하지 않습니다. 이 준비는 기존 지원 명령 표의 P2 미연결 상태를 바꾸지 않습니다.


## #194 현재 질문·응답·진단과 #138 캐시 / #195 녹음 비교

[문서] 의미·정책은 [voice-policy](../../../docs/requirements.md#voice-policy), 실제 내부 필드/경계·로그/캐시·C/D 인계·녹음 비교는 [voice_llm.md](../../../docs/voice_llm.md#194-요청질문진단-연결과-138-bounded-캐시)를 참조합니다. `core/conversation.py`는 P1 질문의 로컬 권한, `core/response.py`는 최종 문장 검사, `core/diagnostics.py`는 비동기 상세 JSONL입니다. 내부 response_text/_voice는 공개 wire 신규 필드가 아니고 `/voice/intent`에서 제외합니다. 기존 source 소비 필드는 유지하며 미등록 원인은 상세 검증 사유에 보존합니다.

[문서] 예: “망치 가져오라고 말했잖아”/“엄마가 망치 가져오라고 했어”는 정상 LLM 요청 의미와 등록키 검증 경로입니다. “망치”의 구체 질문 TTS 완료 후 “응/맞아/그걸로” 또는 “렌치/아니 렌치야”는 유효 현재 문맥에서 한 번 결합합니다. 번역/부정/제외·문맥 없는 응답·만료·재시작·취소·관측된 running/잠금은 새 실행을 만들지 않습니다. “립밤 되나?”는 등록과 실행가능 미확인 안내만 하며 자동 실행하지 않습니다. 문장 검증과 실제 C 수락/동작 성공은 다릅니다.

[문서] YAML의 `dialogue_timeout_sec`·진단 경로/회전/큐·선준비 문장수/길이/UTF-8 용량·빈번 문장 기록/횟수는 제안/미확정 설정입니다. 일반 질문 시간은 P2 #152 정책과 독립이고 null이면 후속 결합을 보류합니다. 실패 후 질문 답을 자동 재시도하지 않고 새 독립 요청을 요구합니다. 상세파일은 비밀값을 필터한 원본 LLM/검증 사유/최종 문장/TTS/캐시/시각·로컬 요청/질문 ID를 남기며 파일/회전/큐/필터 오류는 경고합니다. 큐 포화·종료 정체 시 증빙 저장 미확인을 보고하며 음성/취소를 막지 않습니다. 파일은 설정 크기와 백업 수로 회전하며 큰 단일 원본은 보존 후 다음 기록에서 회전합니다. tee 요약 파일·C 실행 DB·worker.log는 별도 자료입니다.

[문서] 초기 필수 문장과 두 번 이상 성공 재생된 검증 문장의 선택 이력을 구분합니다. `models/tts/melotts/validated_phrases.json`(실제 assets 설정 기준)은 bounded 선택 기록이며 기존 WAV 저장 기능을 중복 구현하지 않았습니다. 설정 한도를 넘는 필수 목록은 준비 실패, 이력 파일 오류는 경고 후 필수만 준비합니다. worker 시간 진단 코드 변경도 기존 identity 무효화에 포함되므로 첫 재합성이 필요할 수 있습니다. 모델 로딩·선준비·전체 준비, 첫 합성/캐시 조회·첫 DAC/재생 시간은 별도 기록이고 실제 이번 합성은 미측정입니다. 기존 Melo1.2·노드 startup60·위 prepare120·AC3초는 유지합니다.

[미연결/인계] C 수락/거절의 요청 상관 식별·순서·실패/timeout/취소 책임, D #20 변경 사례/정답표 검토는 [#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 협의합니다. C/D 파일과 새 wire는 변경하지 않았고 E 포함2명 승인·스키마/예시/ICD 반영 전 연결하지 않습니다. #23의 과거 결과/미달은 보존하며 이 추적 위치 전환이 P1 완료/AC 면제를 뜻하지 않습니다. 녹음 비교 [#195](https://github.com/Jik-Kim/ready2go/issues/195)는 실제 시험 계획/기존 코드·모의 검토로 기본 fixed5/commissioning·무음/VAD 임계값을 바꾸지 않았습니다. 실제 웨이크·녹음/API·합성/청취·C 수락·로봇 AC는 이번 범위에서 미시험입니다.
