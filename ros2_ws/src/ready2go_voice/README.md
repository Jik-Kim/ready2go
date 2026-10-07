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
| `adapters/audio.py` | 강의 tflite 웨이크 모델 읽기, int16 mono 16kHz 녹음, 원본 고정5초 시운전 또는 RMS 무음 종료/최대 한도 |
| `adapters/api.py` | LangChain 프롬프트→gpt-4o 후보의 strict JSON, whisper-1 녹음 전사. SDK 재시도 없음 |
| `adapters/tts.py`, `adapters/melotts.py`, `adapters/melotts_worker.py` | 사용자 선택 MeloTTS 격리 CPU 합성/캐시→mono/int16 WAV→기존 PortAudio 재생. 명시 선택 espeak 호환 유지, 자동 폴백 없음 |
| `nodes/voice_node.py` | 기존 `/voice/text_override` 입력·`/voice/intent` 발행·`/voice/speak` Skill 액션·ROS 진단 로그 |
| `test/` | 해석/실패/지연·기록 종료·재생/취소·노드 평가 게이트의 모의 검사 |

[문서] 참고 코드 `keyword_extraction.py`·`STT.py`의 프롬프트/호출·녹음→Whisper 구조를 사용했습니다. 원본 `sd.rec`→`sd.wait`의 고정 5초 녹음을 시운전 기본으로 적용했습니다. 고정 도구 목록, `/` 문자열 분해, import 시 dotenv, 임시파일 누수는 옮기지 않았습니다. SciPy 대신 표준 `wave`를 사용합니다. 웨이크 모델 원본을 복제/수정하거나 모델을 자동 다운로드하지 않습니다.

## 설정과 동작 경계

[문서] `params/voice.yaml`은 시운전 제안값이며 `[팀 확정 필요]` 값은 장치·지연·E/D 정답표 확인 후 확정해야 합니다. 사용자 확정 기본은 **`evaluation_mode: false`, `audio_enabled: false`**입니다. 시작 시 ROS bool 파라미터 `-p evaluation_mode:=true/false`로 모드를 지정하며, 생략하면 false입니다. 이 시작 값이 YAML보다 우선하므로 기존 로컬 YAML이 true여도 미지정/CLI false는 실행 모드입니다. 유효 설정은 parser/Session/TTS 생성 전에 공유하며, 실행 중 `ros2 param set`으로 전환하는 기능은 구현하지 않습니다. 평가 모드에서는 find_item뿐 아니라 **cancel/status/unknown/clarify 모두 `/voice/intent`를 발행하지 않습니다**. ROS 진단 로그와 TTS만 제공하므로 평가 결과를 로봇 요청으로 전달하지 않습니다. C가 다른 입력으로 기동한 태스크까지 이 설정이 중단시키는 것은 아닙니다.

- 실제 웨이크/STT 평가는 장치/모델을 준비한 설정 복사본의 `audio_enabled: true`와 시작 인자 `-p evaluation_mode:=true`로 수행합니다. YAML의 evaluation_mode만 true로 바꾸는 것은 노드의 시작 기본값을 바꾸지 않습니다.
- 실행 모드는 기본값 또는 `-p evaluation_mode:=false`로 시작합니다. 기존 확인 TTS·취소·무발화·실패·중복 게이트를 유지하며, 실제 C 수신·모션·안전·태스크 연결은 별도 확인 대상입니다.
- 텍스트 override는 같은 파서의 디버깅 입력이며 실제 웨이크/STT 평가를 대신하지 않습니다.
- 사용자 확정 정책은 대상 단독·대명사·대상불명 요청을 `clarify`, 빈 targets, 실행 보류로 처리하는 것입니다. 기존 `bare_item_policy: clarify` 설정은 유지하며 충돌하는 `unknown` 설정은 거절합니다. 미사용 `request_patterns`는 설정 호환을 위해 유지하되 실행 판단에 사용하지 않습니다. D 첨부의 E/D 승인 완료를 뜻하지 않습니다.
- 이름·별칭이 직접 확인되지 않은 LLM 대상은 `clarify`, 빈 targets, 실행 보류로 처리합니다. 정상 LLM 경로는 특정 문장 전체 정규식이나 평가40개에 한정하지 않고, 등록된 단일 물품을 받기/가져오기 위한 요청 의미를 해석합니다. 사용자 승인 `지우개 좀`, `지우개 좀.`, `지우개 좀요`는 축약 부탁이며 모든 등록 이름·별칭에 같은 정책을 적용합니다. `혹시 지우개를 받을 수 있을까요?`처럼 폴백 문형 밖 표현도 정상 LLM 결과와 공통 검증을 통과하면 실행 후보입니다. 대상 단독 `지우개`와 대상불명 `그거 좀`은 계속 clarify입니다.
- 선제 보류는 빈 발화·단독 대상·다중/충돌 별칭·대상불명 및 명백한 부정·정보 질문·인용·불명확 문맥·미지원 행동에 적용합니다. 결과 검증에서는 기존 스키마·P1 허용값·등록 단일 대상·발화 대상 일치·유한 확신도/최소값을 확인합니다. find_item에는 요청/필요/받기/축약 부탁의 단서도 필요하며 이름만이나 단서만으로 실행하지 않습니다. 전체 문형 일치를 정상 LLM 결과에 다시 요구하지 않습니다. 자유 한국어 문맥 전체의 안전·정확성을 보장하는 의미 검사기는 아니며 실제 평가가 필요합니다.
- [실측: 모의] 비요청 발화의 실행 후보 통과 결함은 미해결입니다. “지우개 가져다주면 안 돼”, “지우개 빼고 다른 것 가져줘”에 잘못된 LLM find_item(eraser)을 주입하면 `execution_allowed=true`가 됩니다. 위 보류 정책이 모든 부정·제외 문맥에서 구현됐다는 뜻은 아닙니다. 실제 발행·로봇 실행을 확인한 결과는 아니며, 판별 코드·회귀 검사의 별도 수정이 필요합니다. D의 모션 없는 평가에는 `evaluation_mode:=true`를 명시합니다.
- 오류·시간 초과·검증 실패 또는 LLM 없음의 규칙 폴백은 기존 긍정 **문장 전체** 문형과 승인된 단일 대상+좀/좀요만 수용합니다. 정규식 밖의 이름 있는 표현은 clarify, 미등록은 unknown으로 보류합니다. 정상 LLM unknown/clarify를 폴백 find_item으로 덮어쓰지 않습니다. 찾기/꺼내기→가져오기·건네기·전달 트레이에 놓기의 기존 흐름은 유지하며, 부정·인용을 삭제하지 않습니다. 직접 손 전달·다른 목적지·반납·정리·던지기·다중 요청은 보류합니다.
- 기본 `confirmation_enabled: true`는 음성 확인 재생 성공 뒤 find_item 발행을 허용합니다. 실패하면 clarify로 보류합니다. C의 태스크 시작/기존 speak와 중복 안내 책임은 C/E가 맞춰야 합니다.
- cancel/status는 발화·설정 문구의 끝 `. ! ? 。 ！ ？`만 정규화하여 정확 비교합니다. `멈춰.`, `취소!`, `지금 뭐 해?`는 API/처리 큐를 거치지 않는 텍스트 제어 경로에서도 처리하며, 부정·문장 중간 문맥은 제거하지 않습니다.
- 실행 모드의 동일 find_item은 중복 시간창 안에서 TTS 전에 보류합니다. 중복 조회는 기록을 바꾸지 않으며 `/voice/intent` 발행 호출이 정상 반환한 뒤에만 기록합니다(C 수신·실행 성공 확인을 뜻하지 않습니다). TTS 실패·취소·시간 초과·발행 예외는 find_item을 소비하지 않아 재시도할 수 있습니다. 평가 모드는 동일 입력도 TTS/진단을 반복하고 모든 intent 발행을 금지합니다. unknown/clarify의 안내 및 기존 발행 중복 정책은 유지합니다. 무발화/VAD 검사 보류는 실행 모드에서도 intent를 발행하지 않습니다.
- cancel/status는 기존 intent로 C에 전달합니다. voice는 로봇 제어·ESTOP·현재 실행 상태 조회를 대신하지 않습니다. cancel은 진행 중인 E 해석 결과의 추가 발행도 취소합니다. 음성 취소는 보조 수단이며 API 처리 중 새 웨이크 청취는 일시 중지됩니다.
- STT/LLM 각각 단일 작업 슬롯과 SDK timeout/max_retries=0을 적용합니다. 늦은 결과는 폐기하며 후속 요청에 추가 발행하지 않습니다. 이미 끝나지 않은 작업이 있으면 새 API 작업을 쌓지 않고 보류/폴백합니다.
- `recording_mode: fixed`, `record_duration_sec: 5.0`, `timing_mode: commissioning`은 원본 기반 기능 시운전 기본입니다. 16kHz/int16/mono 80,000프레임을 녹음하며 웨이크 스트림을 닫은 뒤 같은 입력으로 새 sd.rec 스트림을 엽니다. `VOICE_MIC_DEVICE`→명시 input_device→16kHz 입력 자동 선택→기본 장치 순으로 한 번 정한 입력을 공유합니다. 시운전 API 상한은 STT/LLM 각각30초 제안값이고 늦은 결과 폐기·취소·평가 발행 금지는 유지합니다. commissioning의 API/녹음 설정은 실행·평가 모드 모두에서 사용할 수 있고, 평가 true는 계속 모든 발행을 차단합니다.
- 고정 녹음의 발화 종료·확인 지연은 null, latency_measurement=not_measured입니다. 녹음 완료 시각은 별도 recording_ended_*로 남기며 AC-INT-03 통과로 사용하지 않습니다. AC 준비는 recording_mode=silence/timing_mode=ac_budget로 설정하고 STT/LLM 상한·장치를 실측해 정합니다. 과거 설정에 신규 키가 없으면 기존 silence/ac_budget를 유지합니다.
- 무음 종료는 마지막 유성 프레임 시각을 기록합니다. `silence_sec` 대기·STT·LLM·TTS 준비를 **발화 종료부터 3초** 예산에 포함합니다. `max_record_sec`는 보호 한도이며 고정 녹음 시간이 아닙니다. 한도 초과로 잘린 명령은 실행하지 않습니다.
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

[문서] `diagnostic_detail=true`에서는 `voice_diagnostic` JSON을 **기존 ROS 로그(`/rosout`) 또는 콘솔**에 출력합니다. 기본은 짧은 진행·실패 유형 로그입니다. 새 진단 토픽이나 DB를 만들지 않습니다. 실행 모드에서는 기존 intent의 `source`에도 정보를 전달하지만 C 로그/run_id·D 화면 수신이 자동 연결되는 것은 아닙니다. 아래 부가 정보의 수신·의미는 C/D 협의 대상입니다.

- STT 원문, 실제 intent/targets, LLM 호출 여부·원문·검증 passed/failed/not_returned/not_called, 폴백 여부, 실행 허용/보류. 상세 콘솔 JSON에서 발행 여부는 `voice_diagnostic.published`, intent는 `voice_diagnostic.intent`입니다. 발행 여부는 진단 이벤트의 최상위 `published`이며 `/voice/intent`의 `source`에는 없습니다. `published=true`는 발행 호출 반환을 뜻하며 C 수신·실행 성공을 뜻하지 않습니다.
- 음성의 발화 종료 Unix/monotonic 시각, TTS 재생 시각, 확인 지연. TTS는 합성 시작/완료나 요청 접수가 아니라 **첫 PCM의 PortAudio DAC 재생 시각**을 장치 callback 정보로 기록합니다(`tts_start_basis=portaudio_first_dac`). 물리 스피커 청취 지연은 별도 확인해야 합니다.
- 실제 어댑터의 `tts_mock=false`와 테스트의 `tts_mock=true`를 구분합니다. 모의 시각·텍스트 입력으로 AC-INT-03 통과를 선언하지 않습니다. TTS 실패/장치 없음은 성공이나 실제 시작으로 기록하지 않습니다.

C #17 인계: 단일 find_item→태스크 수신, cancel/status, 모호/미지원 보류, 중복 요청, 확인 TTS/태스크 시작 책임, source→실행 로그/run_id 연결. voice는 nudge/pick을 직접 실행하지 않습니다. 벽면 배치·기존 pick_demo 예상 target_after/재조회 없음 합의는 유지하며 실제 재인식→pick 및 NO_PUSH_ACCESS 정합성은 별도 A/B/C/E 인계입니다.

D #20 인계: **20 지우개 요청/10 모호/10 미등록·미지원**, 자유 표현10은 40개 안에 포함, 화자2명 이상, cancel/status 별도 보조 시험. 사용자 확정 모호=clarify 정책을 반영하되 평가자료의 승인 상태·문장별 정답을 E/D가 먼저 고정하고 모션 없는 평가 모드에서 측정합니다. 40문장은 평가용 정답표이며 허용 목록·학습 자료가 아닙니다. 이름 없는 자유 표현과 요청 의미가 불명확한 경우는 확인 안내·실행 보류입니다. D 초안(JSON SHA256 `5995fc225c0a2cc78aa1c9264eee6a07518ad674ed4923763acf5017377aec84`)의 최신 TC-008은 “지우개 찾아서 건네줘.”입니다. 이 자료를 읽기 전용 정답 참고로 사용한 텍스트40개 회귀는 실제 음성 평가·D 자료 승인 완료를 대신하지 않습니다. 후속 확인 대화와 자료 승인·정답표 동결은 E/D 인계로 남습니다. 정상 unknown/clarify는 LLM 검증 실패가 아닙니다. LLM 검증 passed는 형식·등록 대상 검사 통과를 뜻하며 사용자 확인 완료나 실행 허용을 뜻하지 않습니다. 전체·종류별 정확도, LLM 호출 분모/검증 실패/폴백, STT·확인 지연·실행 시도를 구분합니다. 실제 음성 40문장 ≥36 정답, 검증 실패율≤5%·잘못된 실행0, 확인TTS≤3초는 실제 측정 대상으로 남습니다.

## 검증과 남은 조건

```bash
PYTHONPATH=ros2_ws/src/ready2go_voice:ros2_ws/src/ready2go_knowledge python3 -m pytest ros2_ws/src/ready2go_voice/test -q -rs
```

ROS 노드 검사는 생성된 ready2go_interfaces와 ROS 환경을 source한 뒤 실행합니다. API/오디오 SDK가 없는 환경은 해당 어댑터 검사를 명시적으로 skip하며 core 검사는 수행합니다. 테스트의 fake API·장치는 실제 음성 수용 기준의 근거가 아닙니다. 실제 장치/한국어 음성·API·C/D·Docker 연결은 CURRENT의 실측/미검증 기록을 확인하십시오.

## 사용자 PC 시운전 명령 (실제 녹음/API는 사용자가 실행)

아래 수동 명령은 PC에 설치된 선택 도구 python-dotenv를 사용합니다(voice 런타임은 이미 로드된 환경을 읽습니다). 저장소 루트와 현재 프로젝트 build/install 및 `.venvs/project`를 사용합니다. 로그/모델/키는 로컬 자산이며 키 값을 출력하지 않습니다. 기존 PC의 정상 로컬 설정은 사용자 선택 MeloTTS였으며, 다른 PC의 엔진 선택은 위 설정 검사로 확인합니다. 한국어 단문 합성·첫 DAC 재생은 확인했으며, 마이크/STT·LLM·전체 음성 평가는 재시험해야 합니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
from dotenv import load_dotenv
from ready2go_voice.nodes.voice_node import main
load_dotenv('secrets/voice.env')
main(args=['--ros-args', '-p', 'config_file:=logs/voice_eval/voice.local.yaml', '-p', 'evaluation_mode:=false', '-p', 'diagnostic_detail:=true'])
PYTHON
```

위 명령의 `evaluation_mode:=false`를 `true`로 바꾸면 모든 intent 발행을 차단하는 평가입니다. 인자를 생략해도 기본 false이며, 로컬 YAML/키/모델은 덮어쓰지 않습니다. 기존 fixed5초/commissioning·API/TTS 상한·MeloTTS·wake0.7은 그대로 사용하고, 실행 모드에서도 실제 발화 종료/3초 지연은 null/not_measured입니다.

기본 콘솔: 웨이크 대기→감지 점수→5초 녹음 시작/완료→Whisper 요청/STT 결과→LLM 또는 폴백 결과→TTS 시작/종료→모드와 게이트에 따른 발행/보류→다시 대기. 프레임마다 점수를 출력하지 않습니다. D 상세 원본은 아래 명령으로 보존합니다. 각 실행은 `mktemp`로 새 로그를 만들어 기존 기록을 덮어쓰지 않습니다. `pipefail`로 노드 오류 종료를 파이프라인 결과에 반영합니다. 진단 원본/source의 수신·필드 대응 협의는 유지하며 기본 짧은 콘솔을 상세 평가 기록으로 대신하지 않습니다.

평가용 상세 기록(모든 intent 발행 차단, 실제 녹음/API는 사용자가 실행):

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

실행용 상세 기록(기존 발행 게이트 적용, C 수신·모션 연결은 별도 확인 대상):

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

[문서] `tts_engine: melotts` 실패는 준비/합성 실패로 표시되고 espeak로 자동 전환하지 않습니다. 기존 설정에 엔진 키가 없으면 espeak 호환 경로입니다. Melo 기본 CPU4스레드/속도1.0/준비상한60초/재생전체상한20초는 실측 기반 **제안값 [팀 확정 필요]**이며, AC 모드의 `start_deadline` 3초는 완화하지 않습니다. 준비 때 등록 물품 이름으로 확인 문장과 `clarify_prompts` 전체, 추가 `tts_melotts_prefill_texts`를 캐시에 넣고 완료 후에만 voice ready/웨이크 입력을 시작합니다. 목록 밖 문장은 최초 합성이 필요합니다. 캐시 키는 문장·모델 파일/리비전·소스/worker·의존성·speaker·속도·스레드를 반영합니다.

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
tts.tts_to_file('지우개 가져다드리겠습니다.', tts.hps.data.spk2id['KR'], output, speed=1.0)
print(output)
PYTHON
```

마이크·API·로봇 없이 기존 출력 장치에서 재생하는 명령입니다. 음성 노드는 먼저 종료하십시오.

```bash
source /opt/ros/jazzy/setup.bash
source .venvs/project/bin/activate
source ros2_ws/install/setup.bash
python3 - <<'PYTHON'
from ready2go_voice.adapters.tts import create_tts
from ready2go_voice.core.config import load_config
cfg = load_config('logs/voice_eval/voice.local.yaml')
if cfg['tts_engine'] != 'melotts':
    raise ValueError('로컬 설정의 tts_engine을 확인하십시오: Melo 재생 시험입니다')
tts = create_tts(cfg)
try:
    tts.prepare()
    print(tts.speak('지우개 가져다드리겠습니다.', on_start=print))
finally:
    tts.close()
PYTHON
```

[실측: CPU 합성] 같은 확인 문장 1스레드 9.79/7.59초, 2스레드 3.99/4.23초, 4스레드 2.49/2.43초. 첫 측정은 BERT 첫 로딩 비용 포함입니다. 모델 로딩 약1.8초와 합성 지연은 구분합니다. [실측: 로컬 재생] 한국어 mono/int16 44.1kHz WAV 합성 및 PortAudio 첫 DAC 재생 성공. 캐시는 약3ms 조회, 준비된 문장의 요청→첫DAC은 약0.165초였으며 **발화 종료→STT/LLM→첫 DAC 3초 달성 근거가 아닙니다**. 실제 청취 품질·40음성·C/D 연결은 미확인입니다.

## 웨이크·무발화·clarify 후속 보완

[문서] 사용자 확정 웨이크 기준은 `wake_threshold: 0.7`이며 기존 **점수 > 기준** 비교를 유지합니다(정확히0.7은 감지하지 않음). 녹음은 기존 `sd.rec`→`sd.wait` 고정5초/16kHz/int16/mono이며 추가 대기·자르기는 없습니다. 고정 녹음 완료 뒤 설치된 openwakeword의 Silero VAD를 로컬로 실행합니다. `speech_vad_model: null`은 패키지의 `resources/models/silero_vad.onnx` 자산을 뜻하며 다운로드하지 않습니다. 명시 경로도 설정할 수 있습니다.

[제안] 30ms 프레임의 VAD 점수≥`speech_vad_threshold: 0.5`와 RMS≥`speech_rms`를 함께 만족하는 연속 구간≥`speech_min_voiced_sec: 0.15`를 찾습니다. 두 VAD 튜닝값은 **[팀 확정 필요]**입니다. 전체5초 평균으로 짧은 요청을 버리지 않습니다. 무발화·모델 없음/오류·취소는 STT/LLM 호출 및 발행을 보류하며, 무발화는 `record_error=NO_SPEECH`, LLM `not_called`로 남습니다. 발화로 판정되면 5초 전체 WAV를 STT에 보냅니다. fixed의 실제 발화 종료/확인 지연은 계속 null/not_measured입니다.

[문서] `clarify_prompts`가 규칙별·무발화·오류·일반 확인 안내의 단일 설정 원본입니다. 기존 규칙 질문의 의미는 유지하고 자유 LLM 질문은 `general`의 짧은 고정 안내로 바꾸며, 최종 `clarify_question`과 실제 안내가 일치합니다. 원본은 기존 `source.llm_raw`에 남습니다. 이 설정이 없는 이전 로컬 파일은 새 항목을 복사해 갱신해야 합니다. unknown/find/control 판별·D40 정답 정책은 바꾸지 않습니다. 대상 단독은 계속 clarify이며 “네”나 대상만 이어 말해 실행하는 새 확인 대화가 아닙니다. 시작 캐시에는 질문을 합성만 하고 재생하지 않습니다.

기본 콘솔은 발화 검사→무발화 시 “발화 없음: STT·LLM 생략”, TTS 준비(캐시 확인/필요 합성)→준비 완료(캐시 사용/새 합성)→실제 첫DAC 기반 TTS 시작/종료를 구분합니다. 상세 LLM 원문은 기존 `diagnostic_detail=true`로 확인합니다.

[실측: 로컬 합성 입력] 실제 Silero는 무음·미세/큰 임의 잡음·200Hz 정현파를 무발화로, 기존 MeloTTS 생성 시험 WAV를 발화로 판정했습니다. 새 질문 사전캐시 준비36.26초, 일반 고정 clarify의 캐시 응답5~7ms(캐시 히트)였습니다. 마이크/STT/LLM/실제 첫DAC 지연 측정이 아닙니다. 90ms 순간 구간 거절·180ms 구간 허용은 모의 검사입니다. **180ms 이상의 웨이크 잔음도 통과할 수 있으며**, 실제 마이크에서 무발화/짧은 정상 명령·오탐을 재시험해야 합니다.

재실행은 위 “사용자 PC 시운전 명령”을 사용합니다. 웨이크 후 아무 말도 하지 않는 시험에서는 Whisper 요청 없이 무발화 안내·발행 보류가 나오는지, 짧은 정상 요청은 통과하는지 확인하십시오. 자유 LLM clarify는 고정 일반 질문과 캐시 사용 로그·상세 llm_raw를 대조하십시오. 실제40음성·3초·청취 품질·C/D 연결은 미완료입니다.
