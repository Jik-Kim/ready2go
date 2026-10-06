# ready2go_voice

- **담당**: E 고희태. 웨이크워드·STT·P1 단일 물품 LLM 해석/검증·규칙 폴백·TTS.
- **정본**: [requirements.md](../../../docs/requirements.md)의 FR-INT-01~03(P1), AC-INT-01~03. [voice_llm.md](../../../docs/voice_llm.md)·[interfaces.md](../../../docs/interfaces.md)·[ontology.md](../../../docs/ontology.md)는 연결 참조입니다.
- [문서] 이 패키지 구현과 실제 장치/API·C 수신·D 평가 완료는 구분합니다. P2 목표 계획/BFS, P3 목록, 새 OntologyManager, 실행 상태 저장소/DB 로거는 구현 범위 밖입니다.

## 현재 구현과 파일 역할

| 경로 | 역할 |
|---|---|
| `core/config.py`, `params/voice.yaml` | YAML 설정과 범위 검사. 장치/모델/정답 정책·시간예산의 미확정 값 표시 |
| `core/intent.py` | 기존 온톨로지 전체 물품·별칭, P1 JSON·대상·확신도 검증, 규칙 폴백, 모호/미지원 보류 |
| `core/deadline.py`, `core/session.py` | API 단일 호출 슬롯·시간 초과 결과 폐기, 임시 WAV 정리, 평가/중복 발행 게이트 |
| `adapters/audio.py` | 강의 tflite 웨이크 모델 읽기, int16 mono 16kHz 녹음, RMS 무음 종료/최대 한도 |
| `adapters/api.py` | LangChain 프롬프트→gpt-4o 후보의 strict JSON, whisper-1 녹음 전사. SDK 재시도 없음 |
| `adapters/tts.py` | espeak-ng 한국어 후보 WAV 합성→합성 WAV의 샘플레이트·mono/int16 확인→출력 장치 재생 |
| `nodes/voice_node.py` | 기존 `/voice/text_override` 입력·`/voice/intent` 발행·`/voice/speak` Skill 액션·ROS 진단 로그 |
| `test/` | 해석/실패/지연·기록 종료·재생/취소·노드 평가 게이트의 모의 검사 |

[문서] 참고 코드 `keyword_extraction.py`·`STT.py`의 프롬프트/호출·녹음→Whisper 구조를 사용했습니다. 고정 도구 목록, `/` 문자열 분해, 고정 5초 녹음, import 시 dotenv, 임시파일 누수는 옮기지 않았습니다. SciPy 대신 표준 `wave`를 사용합니다. 웨이크 모델 원본을 복제/수정하거나 모델을 자동 다운로드하지 않습니다.

## 설정과 동작 경계

[문서] `params/voice.yaml`은 시운전 제안값이며 `[팀 확정 필요]` 값은 장치·지연·E/D 정답표 확인 후 확정해야 합니다. 기본 **`evaluation_mode: true`, `audio_enabled: false`**입니다. 평가 모드에서는 find_item뿐 아니라 **cancel/status/unknown/clarify 모두 `/voice/intent`를 발행하지 않습니다**. ROS 진단 로그와 TTS만 제공하므로 평가 결과를 로봇 요청으로 전달하지 않습니다. C가 다른 입력으로 기동한 태스크까지 이 설정이 중단시키는 것은 아닙니다.

- 실제 웨이크/STT 평가는 장치/모델을 준비한 설정 복사본에서 `audio_enabled: true`, `evaluation_mode: true`로 수행합니다.
- C 수신·모션·안전·태스크 연결 확인 뒤에만 `evaluation_mode: false`로 실행 모드를 선택하고 노드를 재시작합니다. C와 별도 평가 환경을 확인하십시오.
- 텍스트 override는 같은 파서의 디버깅 입력이며 실제 웨이크/STT 평가를 대신하지 않습니다.
- `bare_item_policy: clarify`는 대상 단독 발화에 대한 안전한 제안입니다. `unknown`으로 보류하도록 설정할 수도 있습니다. E/D 합의 완료로 간주하지 않습니다.
- 이름·별칭이 직접 확인되지 않은 LLM 대상은 `clarify`, 빈 targets, 실행 보류로 처리합니다. 명시된 물품도 긍정 요청 문장 전체가 보수적 문형과 맞을 때만 실행합니다. 부정·정보 질문·인용·애매한 문장은 일부 요청 문자열만으로 집기 요청으로 바꾸지 않습니다. 이는 일반 한국어 의미 이해 완료를 뜻하지 않습니다.
- LLM 결과는 등록된 단일 대상·P1 intent·확신도·명시된 물품과의 일치를 다시 검사합니다. 미등록·다중 대상·미지원 행동·부정 요청은 임의 물품 실행으로 바꾸지 않습니다. 자유 표현의 의미 정확도는 실제 평가가 필요합니다.
- 기본 `confirmation_enabled: true`는 음성 확인 재생 성공 뒤 find_item 발행을 허용합니다. 실패하면 clarify로 보류합니다. C의 태스크 시작/기존 speak와 중복 안내 책임은 C/E가 맞춰야 합니다.
- cancel/status는 기존 intent로 C에 전달합니다. voice는 로봇 제어·ESTOP·현재 실행 상태 조회를 대신하지 않습니다. cancel은 진행 중인 E 해석 결과의 추가 발행도 취소합니다. 음성 취소는 보조 수단이며 API 처리 중 새 웨이크 청취는 일시 중지됩니다.
- STT/LLM 각각 단일 작업 슬롯과 SDK timeout/max_retries=0을 적용합니다. 늦은 결과는 폐기하며 후속 요청에 추가 발행하지 않습니다. 이미 끝나지 않은 작업이 있으면 새 API 작업을 쌓지 않고 보류/폴백합니다.
- 무음 종료는 마지막 유성 프레임 시각을 기록합니다. `silence_sec` 대기·STT·LLM·TTS 준비를 **발화 종료부터 3초** 예산에 포함합니다. `max_record_sec`는 보호 한도이며 고정 녹음 시간이 아닙니다. 한도 초과로 잘린 명령은 실행하지 않습니다.
- LLM 없는 경우 등록 별칭 규칙은 동작하지만 LLM 주 경로 및 자유 표현 완료를 의미하지 않습니다. faster-whisper 오프라인 STT는 현재 구현하지 않았습니다.

## 실행 준비와 의존성

| 구분 | 필요한 항목·확인 방법 |
|---|---|
| Python 기본 | 실제 core imports: jsonschema, PyYAML, numpy. `setup.py`에 선언 |
| Python API | `openai>=1,<3`, `langchain-openai>=0.2,<2`, `langchain-core>=0.3,<2` (`api` extra). 실제 SDK timeout/JSON 호출을 모의 검증 |
| Python 오디오 | sounddevice, openwakeword 0.6.0 (`audio` extra), 모델에 맞는 tflite_runtime 및 openwakeword 전처리 모델 자산. Python/CPU 호환 runtime은 배포 PC에서 확인 |
| ROS | rclpy, ament_index_python, std_msgs, ready2go_interfaces, ready2go_knowledge (`package.xml`). 기존 Skill 메시지 생성 필요 |
| 시스템 | PortAudio, 한국어 음성이 설치된 espeak-ng, 오디오 서버/권한·실제 마이크/스피커. `espeak-ng --voices=ko`와 입력/출력 장치 확인 필요 |
| 벤더/자산 | `OPENAI_API_KEY`는 기존 환경에서만 읽음. whisper-1/gpt-4o 계정 접근·네트워크·지연은 별도 확인. 외부 강의 `hello_rokey_8332_32.tflite` 경로를 설정하며 모델 원본/키를 커밋하지 않음 |
| 선택/미구현 | faster-whisper·Piper는 현재 imports/실행 경로에 없음. 기본 설치에 포함하지 않음 |

[문서] [공식 STT 문서](https://developers.openai.com/api/docs/guides/speech-to-text)의 whisper-1·어휘 prompt와 [구조화 출력 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)를 대조했습니다. 모델 계정 접근·유료 API 호출 성공은 문서 확인으로 대신하지 않습니다. 로컬 검사에서는 실제 키/API 호출을 하지 않았습니다.

저장소 루트에서 API/오디오 의존성을 준비한 환경을 사용합니다. ROS와 함께 설치할 때 가상환경은 system-site-packages 사용 등 ROS Python 경로와 맞춰야 합니다. tflite_runtime은 Python/아키텍처 호환 배포를 확인하고 별도 설치합니다.

```bash
python3 -m pip install -e './ros2_ws/src/ready2go_voice[api,audio]'
source /opt/ros/jazzy/setup.bash
cd ros2_ws
colcon build --packages-up-to ready2go_voice
source install/setup.bash
ros2 run ready2go_voice voice_node --ros-args -p config_file:=/절대경로/voice.yaml
```

설정의 `ontology_file`·`intent_schema_file`·`wake_model`은 실행 환경의 실제 경로로 맞춥니다. `OPENAI_API_KEY`는 기존 보안 환경/voice.env를 명시적으로 로드하며 로그에 출력하지 않습니다. Docker/compose의 패키지·메시지·계약/모델 배포 및 자동기동은 이번 패키지 구현 밖의 C/E 인계입니다. 기존 Docker의 sleep 명령만으로 voice_node가 실행되지는 않습니다.

## C/D 연결·진단·평가

[문서] 진단은 `voice_diagnostic` JSON을 **기존 ROS 로그(`/rosout`) 또는 콘솔**에 출력합니다. 새 진단 토픽이나 DB를 만들지 않습니다. 실행 모드에서는 기존 intent의 `source`에도 정보를 전달하지만 C 로그/run_id·D 화면 수신이 자동 연결되는 것은 아닙니다. 아래 부가 정보의 수신·의미는 C/D 협의 대상입니다.

- STT 원문, 실제 intent/targets, LLM 호출 여부·원문·검증 passed/failed/not_returned/not_called, 폴백 여부, 실행 허용/보류, 발행 여부.
- 음성의 발화 종료 Unix/monotonic 시각, TTS 재생 시각, 확인 지연. TTS는 합성 시작/완료나 요청 접수가 아니라 **첫 PCM의 PortAudio DAC 재생 시각**을 장치 callback 정보로 기록합니다(`tts_start_basis=portaudio_first_dac`). 물리 스피커 청취 지연은 별도 확인해야 합니다.
- 실제 어댑터의 `tts_mock=false`와 테스트의 `tts_mock=true`를 구분합니다. 모의 시각·텍스트 입력으로 AC-INT-03 통과를 선언하지 않습니다. TTS 실패/장치 없음은 성공이나 실제 시작으로 기록하지 않습니다.

C #17 인계: 단일 find_item→태스크 수신, cancel/status, 모호/미지원 보류, 중복 요청, 확인 TTS/태스크 시작 책임, source→실행 로그/run_id 연결. voice는 nudge/pick을 직접 실행하지 않습니다. 벽면 배치·기존 pick_demo 예상 target_after/재조회 없음 합의는 유지하며 실제 재인식→pick 및 NO_PUSH_ACCESS 정합성은 별도 A/B/C/E 인계입니다.

D #20 인계: **20 지우개 요청/10 모호/10 미등록·미지원**, 자유 표현10은 40개 안에 포함, 화자2명 이상, cancel/status 별도 보조 시험. 문장별 정답·실행보류 정책을 E/D가 먼저 고정하고 모션 없는 평가 모드에서 측정합니다. 이름 없는 자유 표현과 문형이 불명확한 요청의 현재 구현은 확인 안내·실행 보류입니다. 문장별 정답 및 후속 사용자 확인 정책은 E/D 미확정이며, 회귀 검사에 사용한 긍정 지우개 20표현은 D의 실제 40문장 정답표를 대신하지 않습니다. 정상 unknown/clarify는 LLM 검증 실패가 아닙니다. LLM 검증 passed는 형식·등록 대상 검사 통과를 뜻하며 사용자 확인 완료나 실행 허용을 뜻하지 않습니다. 전체·종류별 정확도, LLM 호출 분모/검증 실패/폴백, STT·확인 지연·실행 시도를 구분합니다. 실제 음성 40문장 ≥36 정답, 검증 실패율≤5%·잘못된 실행0, 확인TTS≤3초는 실제 측정 대상으로 남습니다.

## 검증과 남은 조건

```bash
PYTHONPATH=ros2_ws/src/ready2go_voice:ros2_ws/src/ready2go_knowledge python3 -m pytest ros2_ws/src/ready2go_voice/test -q -rs
```

ROS 노드 검사는 생성된 ready2go_interfaces와 ROS 환경을 source한 뒤 실행합니다. API/오디오 SDK가 없는 환경은 해당 어댑터 검사를 명시적으로 skip하며 core 검사는 수행합니다. 테스트의 fake API·장치는 실제 음성 수용 기준의 근거가 아닙니다. 실제 장치/한국어 음성·API·C/D·Docker 연결은 CURRENT의 실측/미검증 기록을 확인하십시오.
