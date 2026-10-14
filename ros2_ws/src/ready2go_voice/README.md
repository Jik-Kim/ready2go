# ready2go_voice

- **담당**: E 고희태. 웨이크워드·STT·P1 단일 물품 LLM 해석/검증·규칙 폴백·TTS.

## 현재 캐시 준비 예산 — PR #356

[문서: 실행 원본 대조] [voice.yaml](params/voice.yaml)의 일반 `tts_melotts_startup_timeout_sec`는 **600초**입니다. 일반 노드는 사용한 YAML의 명시값을 그대로 사용하므로 기존 local의 60초가 자동으로 600초가 되지는 않습니다. 패키지 기본값을 적용하려면 사용 설정과 설치 반영 여부를 확인하고 노드를 재시작하십시오. local 원본을 임의로 덮어쓰지 않습니다.

[문서: prepare/live 구분] [voice_trial.py](tools/voice_trial.py)의 trial 복사본은 prepare/live 모두 `tts_prefill_max_texts`를 패키지 YAML의 **512개**로 덮습니다. 일반 startup은 원본 local의 명시값을 보존하고, 명시 `prepare` 실행만 메모리 복사에서 **3600초**로 덮습니다. 이 prepare 값은 원본 local·시험 YAML·일반 live 예산을 변경하지 않습니다. warmup 1개가 개수 상한에 포함되므로 필수 문장은 최대511개이며, 문장별160자와 warmup을 포함한 UTF-8 전체65536바이트는 별도 제한입니다. 아래의 60/120초·256개 실측/승인 기록은 당시 이력입니다.

[미검증] 준비 예산은 [AC-INT-03 발화 응답 기준](../../../docs/requirements.md#ac-int-03)과 별개입니다. #356의 코드·설정과 실제 준비 시간/성공·음성·장치 연결은 이번 문서 보완에서 검사하지 않았습니다. 600초·3600초 안에 완료된다고 보장하지 않습니다.


## #351 최신 코멘트 보완 — 2026-10-14

[구현] 첫 C 수락에서 확인한 request/run/boot/source·세대·태스크의 연속성을 유지하므로, 다른 요청의 BUSY/status 결정이 현재 실행의 후속 안내를 폐기하지 않습니다. 실제 새 RUN·idle/종료·중단/잠금·재기동·연결 유실은 해당 재생 권한을 폐기합니다. 첫 수락의 실제 재생 성공 조건과 실패 시 첫 모션 차단은 유지합니다.

[원본 연결] `core/runner_speech.py`가 C `ready2go_runner.core.failure_speech`와 현재 `tasks/find_item.json`·`find_with_unpack.json`을 읽습니다. no_room 템플릿은 C의 보간/조사 함수로 물품별 생성하며, 원인·TIMEOUT·동작 실패·generic 문구는 C factory를 사용합니다. `package.xml`에 Runner 실행 의존성을 선언하고 `setup.py`가 두 태스크 원본을 E share/tasks에 설치합니다. 소스 실행은 현재 태스크를 우선하고 설치 실행은 패키지 산출물을 사용하므로 태스크 변경 뒤 E 재빌드/설치가 필요합니다. 타 담당 원본은 직접 편집하지 않았습니다.

[구현·한계] 현재 검증된 실행의 후속 안내가 C factory 원인 문장 화이트리스트에 포함되고 DAC 시작/재생 완료 검증을 통과한 경우만 근거를 보존합니다. 최종 결과가 동일 run·태스크의 FAILED이고 낮은 경고이면 중복 안내를 생략합니다. status.current_step이나 전개된 failed_step의 정적 태스크 조회로 원인을 다시 계산하지 않으므로 동적 achieve_goal 태스크에도 적용됩니다. 재생 실패/거절·다른 실행·미확인/일반 완료·닫기 안내는 생략 근거가 아니며 중단·상태 불명 등 높은 안전 경고는 유지합니다. 이는 동일 실행에서 원인 문장 재생 성공을 근거로 한 중복 억제이며, text-only 호출의 원래 실행 출처나 개별 오류의 추가 식별을 보장하지 않습니다. 새 계약은 추가하지 않았습니다.

[당시 실측: 선택·모의, #356 변경 전] 직접 회귀 17개 통과. node/prepare 공통 목록은 source·기존 local 각각 필수246+warmup1, frequent0, 15519bytes이며 cap256·중복·누락·용량 검사 통과입니다. startup60/prepare120·속도1.2·history/models/cache는 유지합니다. 실제 새 WAV 캐시 준비·PC2/API/마이크/스피커·ROS/DDS·실로봇은 미검증이며 기존 prepare 절차와 통합 시험이 남습니다. 근거/요구사항은 [CURRENT](../../../practice/E/CURRENT.md#voice-351-latest-comments-20261014)와 [FR-INT-03](../../../docs/requirements.md#fr-int-03)·[P2 수락 TTS 책임](../../../docs/requirements.md#acceptance-tts-policy)을 참조하십시오.

## #351 수신 경로 보완 — 2026-10-14

[구현·중단 음성 조회] `_listen`의 safety_audio → `_safety_recording`/질문 worker → Session의 실제 STT 결과 → 읽기 전용 결과 수신 → 기존 notice 경로를 연결했습니다. 등록된 고정 상태·위치 질의에만 받은 전사를 재사용하고 STT/LLM 재호출·intent 발행·재개 권한을 만들지 않습니다. 해당 녹음 receipt만 정리하고 중단 work·기존 질문 객체/등록/기한은 보존합니다. 읽기 안내는 질문/녹음·dialog 소유권 종료 뒤에 전달하며 기존 질문의 다음 새 녹음도 기존 접수·결과 기한으로 검사합니다.

[구현·C 후속 speak] 첫 accept_text는 기존 한 번만 허용하고 실제 재생 증빙이 성공해야 후속 안내를 허용합니다. 현재 검증된 C source·동일 E request/run·running/unlocked 상태에서 완료·닫기·오류 문장을 받고, 접수 때의 run/boot/generation을 재생 직전·도중에도 확인합니다. 첫 수락 실패·중복, 종료된 run·잠금/취소·평가·재기동·연결 유실·접수 뒤 run 변경은 거절합니다. 일반 TTS의 차단이나 첫 동작 게이트를 통째로 풀지 않았습니다. **기존 Skill params_json의 text-only 호출에는 원래 run 식별이 없으므로, 새 run 중 뒤늦게 도착한 과거 호출 자체의 출처는 식별하지 못합니다.** 이를 차단 완료로 보고하지 않으며 C 송신 상관은 타 담당 선행입니다. 공용 계약/C 코드는 변경하지 않았습니다.

[원인·선준비] 현재 `tasks/find_item.json`·`find_with_unpack.json`의 실제 failed_step이 speak인 BACKEND_ERROR만 “음성 안내를 재생하지 못했습니다. 작업 상태를 확인해 주세요.”로 안내합니다. 물리 전달 완료나 집기 실패를 새로 단정하지 않습니다. 다른 단계·미등록 태스크/단계는 일반 실패로 유지하며 C task의 FAILED/skip 정책은 바꾸지 않았습니다. 같은 source/YAML 문구가 필수 prefill에 포함되어 source·기존 local은 **필수209+warmup1**, 당시 cap256·일반60초/prepare120초·모델/속도/history를 보존했습니다. 현행 예산은 위 #356 설명을 참조하십시오. 새 캐시 생성·실음성 청취는 수행하지 않았습니다. 직접 회귀 고유9건은 현재 수신 경로/첫 동작 모의/거절 경계/원인 분류를 확인하며, 실제 PC2·API·ROS·장치·물리 완료는 미검증입니다. [보완 기록](../../../practice/E/CURRENT.md#voice-351-receive-supplement-20261014)을 참조하십시오.

## 음성 피드백 5항목 — 2026-10-14 로컬 보완

[구현·입력 경계] 정지 후 새로 요청한 위치·개폐·고정 상태 질의와 제어 보류 안내만 기존 비권한 notice worker로 전달합니다. 일반 TTS의 잠금·취소 차단은 유지하며, 취소된 일반 요청을 다시 실행하거나 정지·복구·재개 권한을 만들지 않습니다. 대기/재생 중 높은 안전 경고와 질문 캡처를 우선하고, 정지·run/사건·질문·boot/연결 변경은 이전 안내를 무효화합니다. 정상 heartbeat의 seq 증가만으로 같은 의미의 새 읽기 안내를 취소하지 않습니다.

[현재 기록·표현] 기본 위치·개폐 답변은 “지우개는 아래 서랍에 있습니다.”·“위 서랍은 현재 닫혀있습니다.”처럼 짧게 말합니다. 정보 원본은 계속 Runner 기록이며 물리 관측 검증이 아닙니다. 출처/currentness와 물리 관측 미검증은 진단에 남깁니다. 미수신·형식 오류·재기동·유실은 확인 불가로 답하고 초기 배치로 대신하지 않습니다. 명시적인 legacy/dummy 초기 참조는 기존 설명을 유지합니다. “지금 뭐하고 있어?”·“현재 상태”는 현재 Runner phase/재개 질문과 실제 E 요청/run 상관을 읽기만 합니다. 물품명이 확인될 때만 “지우개를 찾고 있습니다.”라고 말하고 불명확하면 일반 작업 안내를 사용하며 LLM/intent 발행·모션을 만들지 않습니다. E 보존 정보가 없다는 이유만으로 C에 작업이 없다고 단정하지 않습니다.

[알림음·설정] 패키지 `voice_flow.wake_cue_enabled` 기본을 true로 바꿨고, 명시 local false는 유지합니다. 시작 진단은 실효 enabled/생성 여부/출력장치/gain과 비활성·실패 사유를 표시합니다. 기존 출력 lock·cue 완료·guard 뒤 새 캡처 순서·기한/gain은 유지하며 생성/재생 실패는 녹음을 시작하지 않습니다. 이 변경에서 실제 beep를 재생하지 않았습니다. 기존 local 설정이 recorded_* 문구를 명시 override하면 그대로 사용하며, 옛 “열림/닫힘 상태” 템플릿은 문법이 깨지지 않게 같은 noun 값을 사용합니다.

[원인 안내·선행] 실제 CAMERA_TIMEOUT·TF_UNAVAILABLE/DEPTH_INVALID·REGION_NOT_VISIBLE·파지·벽/이웃 간섭·NO_FREE_SPACE·원위치 복구 불완전과 안전 복구 실패를 구분합니다. 일반 TIMEOUT은 현재의 두 기본 태스크 정의에서 task_id/failed_step이 정확한 inspect_region 단계일 때만 비전 단계 지연으로 분류하고, 근거가 없으면 일반 timeout을 유지합니다. NOT_REACHED나 pushed=false를 비전 단절/넛지 불필요로 해석하지 않습니다. 물품 원위치 복구 실패에는 기존 fn.1 안내를 재사용하며 잠금 유지/안전 해제로 설명하지 않습니다. 결과/높은 경고의 기존 중복·우선순위를 유지합니다. 현재 last 결과는 finally 뒤에 도착하므로 E 결과 안내가 서랍 정리 전 원인 전달을 구현한 것은 아닙니다. 정리 전에는 C의 실제 기존 speak 호출/원인·현재 실행 상관이 선행이며, 첫 수락 게이트와 현재 run의 후속 speak 구분은 위 수신 경로 보완에 반영했으며, text-only 원천 run 식별 한계는 남아 있습니다. C 파일/계약은 이 보완에서 변경하지 않습니다.

[준비·미검증] 새 문장은 node/prepare 공통 필수 목록에 포함하고 e28의 실패·중단 12문장을 유지합니다. 수신 경로 보완 당시 source와 기존 local YAML의 선택은 각각 필수209+warmup1로 cap256 이내이며 startup60/prepare120·속도1.2·history는 유지합니다. 코드/목록 변경 뒤 기존 prepare와 적용 확인이 필요하지만 cache/receipt를 생성·삭제하지 않습니다. 선택·모의 검사와 실제 API/마이크/스피커·beep/음성·ROS·PC2/로봇/물리 AC는 구분하며 후자는 미검증입니다. [이번 CURRENT](../../../practice/E/CURRENT.md#voice-five-log-fixes-20261014)에서 버전·검사·담당 후속을 확인하십시오.

## 위 서랍 열기·닫기 명시 실행 옵션 — 2026-10-14

[구현·범위] [FR-INT-02](../../../docs/requirements.md#fr-int-02)·[FR-PLN-02/P2](../../../docs/requirements.md#fr-pln-02)의 기존 목표 경로를 사용합니다. VoiceNode 시작 시 `-p upper_drawer_enabled:=true -p p2_goal_enabled:=true -p request_run_enabled:=true`를 함께 지정하면 원본 선정 목록에서 `drawer_top`의 `open=true/false` 두 단일 목표만 선택합니다. 기본 P1·기존 opt-in 기본값은 유지합니다. 명시된 기존 두 opt-in은 기존 제어 런타임도 활성화하며 현재 source·halt·B/C 검사와 복구·재개·종료 조건은 유지합니다. C RUNNER_RESUMABLE을 자동 변경하지 않습니다. “지금 위 서랍 열어줘”, “위쪽 서랍 닫아줘”를 현재 온톨로지·선정 목록과 LLM 결과로 검증하며, 부정·인용·가능 여부 질문·아래 서랍·범위 밖 복합/물품 목표는 실행 후보로 확정하지 않습니다. 평가 모드·잠금/작업 중·현재 C 연결 미확인은 기존 발신 차단을 유지합니다.

[연결·C 인계] E 목표 후보 → 기존 Session 발행 조건 → 현재 C source/요청 상관 → C achieve_goal 플래너 → 기존 수락 speak/첫 동작 게이트를 사용합니다. `tools/dev/pc2_voice.sh --control`은 현재 `request_run_enabled`만 설정하므로 이 기능을 활성화하지 않습니다. C 담당은 위 세 ROS 인자를 실제 VoiceNode argv로 전달하는 실행 옵션을 추가해야 합니다. 해당 스크립트·사용자 local YAML은 여기서 수정하지 않았습니다. 기존 C 계획·speak 삽입 경로는 코드로 대조했고, 선택 검사는 ROS 비의존 모의이며 실물 열기·닫기나 PC2 실행 완료가 아닙니다.

[검증] 경고 dequeue→active 인계 보호, 질문/독립 녹음 생산자의 낮은 안내 취소와 실제 재생 직전 활동 재검사·dialog lock 보존을 보완했습니다. 변경 경합·개폐/잠금/발신 차단·기존 수락 speak/물품 찾기 선택 **24 passed, 157 deselected (3.11s)**입니다. 수정 전 선택 235개는 이전 버전 근거로 구분하여 재사용하고 전체 재실행하지 않았습니다. [CURRENT](../../../practice/E/CURRENT.md#voice-five-log-fixes-20261014)를 참조하십시오.

## 운영 입력·Runner 메모리·종료 보류 — #322 (2026-10-14)

[구현] 일반 요청·음성 정지는 `bash tools/dev/pc2_voice.sh`의 기본 설정으로 사용합니다. 기존 위치·서랍 개폐 질의는 기본 `request_run_enabled=false`에서도 `VoiceNode`의 `/robot_state` 구독 → 읽기 전용 메모리 → `IntentParser.state_provider` → 기존 질의 → TTS로 연결됩니다. C가 발행하는 String JSON과 TRANSIENT_LOCAL/RELIABLE(depth 1)을 사용하며 상태를 쓰거나 새 질의 wire를 발신하지 않습니다. 답변은 **Runner 기록 기준**이고 실제 관측·실물 위치 일치의 증거가 아닙니다.

[구현·경계] 선택 Runner 이름/namespace·단일 endpoint와 기존 `/runner/status` boot/seq 연결을 확인합니다. 상태 JSON에 boot/stamp를 가정하지 않습니다. 미수신·형식 오류·연결 유실·재기동에는 초기 snapshot이나 과거 기록 대신 확인 불가를 안내합니다. 첫 접속·재기동·유실 뒤 state-first/status-first 모두 후보를 보관하고 현재 status·endpoint·표본 순서를 대조한 뒤 연결합니다. 후보는 status 확인 전 질의에 사용하지 않습니다. 같은 boot/status endpoint와 state endpoint가 확인된 유실 복구는 구독을 교체해 현재 발행자의 latched 기록을 새로 수신합니다. 유실 전 로컬 캐시는 복원하지 않으며 이전 구독의 대기 콜백은 배제합니다. 현재 status 재수신 또는 새 state 수신이 없으면 확인 불가를 유지합니다. 정지 상태의 기존 일반 TTS 취소·안전 안내 우선순위는 유지합니다. pick effect의 located_in=gripper는 Runner 기록 기준 쥔 상태로 답하며 다른 물품/서랍 질의도 유지합니다. world에 장소를 추가하지 않습니다. 기존 Jazzy metadata의 source timestamp는 표본 순서 확인에만 사용하며 새 freshness timeout·handshake·공개 필드를 추가하지 않습니다.

[구현] 독립 정지 STT 전에 기존 SpeechPresence의 RMS/VAD 발화 검사를 적용합니다. 일반 입력의 VAD lock을 기다리지 않도록 별도 검사 인스턴스를 사용하고, 발화 없음·검사 실패·취소에서는 SDK를 호출하지 않습니다. 제어 STT에는 단어 나열 prompt를 보내지 않으며, 기존 local YAML에 옛 stt_control_prompt가 남아 있어도 제어 SDK prompt는 비웁니다. 일반 물품/현재 질문 힌트·원본 PCM·정확 긍정/부정/인용/자기 TTS 검사·한 SDK worker/최신 대기 캡처를 유지합니다. 오전사의 음향 원인이 확정되거나 실음성 정지 성공이 검증된 것은 아닙니다.

[구현] 콘솔에는 실제 수용 제어·오류·상태 변경을 남깁니다. 수용 전/자기 TTS/무관한 제어 전사는 기본 콘솔에서 제외하며 bounded 상세 JSONL에는 기록합니다. 동일 phase/work_retained/termination_pending과 같은 세대의 반복 보류는 중복 출력하지 않으며 첫 보류 원인은 표시합니다. 실제 C 결과에는 `runtime_*` 안내를 사용하고 `control_*` 더미 안내는 명시 시험 경로에만 남깁니다. 복구 뒤 등록된 재개 질문을 앞두고 복구 안내를 중복 재생하지 않습니다.

[구현·안전 경계] 현재 run/boot의 종료 요청 뒤 `halt.stop=unconfirmed`, 같은 run의 `SUSPENDED`, `halt.locked=true`이면 성공 대기 대신 **종료 보류**로 표시합니다. 대상은 보존하고 C 잠금·일반 요청 차단을 유지하며 시간 경과로 idle/폐기/허가를 만들지 않습니다. 같은 사건의 C 확인·ABORTED·보존 폐기만 종료 확인으로 처리합니다. 현행 C는 unconfirmed의 늦은 백엔드 응답을 같은 사건에 반영하지 않고 end_task 재요청을 `STOP_NOT_CONFIRMED`로 거절합니다. 사람 확인 후 기존 C reset_state의 해당 run 폐기를 관측하면 보존 대상만 정리하며, 이를 실제 정지·잠금 해제나 종료 요청의 물리 성공으로 안내하지 않습니다. 현재 C cancel 결정으로 보고된 재정지와 재기동은 이전 종료 의도를 폐기합니다. C에서 상태/결정 변화로 발행하지 않은 내부 재정지는 E가 독자적으로 관측했다고 주장하지 않습니다.

[운용·미검증] 복구·재개·실행 중 종료 wire는 `bash tools/dev/pc2_voice.sh --control`과 Runner의 `RUNNER_RESUMABLE=1`을 함께 사용합니다. C의 현재 W2→새 W1·마지막 안전/재진입 검사가 담당 경계입니다. 외력 연결 [PR #335](https://github.com/Jik-Kim/ready2go/pull/335)은 main에 병합됐습니다(병합 커밋 `f30513ac`). 현재 B W1은 정지 상태에서 힘 판정 결과를 응답에 연결하며, 값 미확인·이동 중에는 null을 유지합니다. C는 외력 false와 나머지 조건을 확인하고 true/null은 거절합니다. 코드 연결과 별도로 PC2 적용·실제 자세/쥔 물품에 따른 외력 판정·응답 시간·정상 실물 복구/재개는 현장 검증이 남아 있습니다. E는 거절을 우회하지 않습니다. 기준은 [FR-INT-03](../../../docs/requirements.md#fr-int-03)·[FR-SAF-01/03](../../../docs/requirements.md#fr-saf-01)·[AC-SAF-02/04](../../../docs/requirements.md#ac-saf-02)이며, 모의/CI/실물 상태는 [이번 CURRENT](../../../practice/E/CURRENT.md#322-current-completeness-20261014)를 구분해 확인하십시오.

[선준비] runtime 안내와 등록 물품/장소의 기록 질의·그리퍼 보유·서랍 열림/닫힘 답을 node/prepare 공통 prefill에 포함합니다. 이 연결을 보완할 당시 cap256·startup60·prepare120·모델/속도는 유지했습니다. 현행 예산은 위 #356 설명을 참조하십시오. 문장/소스 identity 변경으로 기존 receipt만으로 새 준비를 증명할 수 없으므로 사용자는 기존 `bash ros2_ws/src/ready2go_voice/tools/voice_trial.sh prepare` 절차로 준비한 뒤 사용자 승인된 live/운영 시험을 진행합니다. 에이전트가 cache/receipt를 생성·삭제하거나 모델/의존성을 설치하지 않습니다. 아래 10/12 더미 prepare/live 절차를 실제 Runner 제어·잠금 해제로 해석하지 마십시오.

## 활성 물품·P2 시작 상태 — 2026-10-13

[문서] 음성 별칭·LLM targets enum은 로딩한 `world.items`를 사용합니다. 현재 당근 펜을 제외한 활성 10종이며 은퇴 물품 요청은 실행 대상으로 허용하지 않습니다. 기존 학습 11종·과거 prefill 실측/개수와 현재 활성 목록을 구분합니다. 캐시·모델·키·실음성은 이번 변경으로 갱신/검증하지 않았습니다. 단일 초기 위치는 [Knowledge 안내](../../../knowledge/README.md#p2-시작-배치-선택--e-구현c-연결-대기)을 참조합니다. Voice·Runner의 기본 로딩은 manifest의 단일 초기 상태입니다. S3도 JSON에는 지우개의 아래 서랍 위치를 유지하고 실물에서만 제외하는 시험이며, 관측 불일치·LLM 결과 전달의 실제 연결/검증은 별도입니다. 공개 intent·실행 게이트·opt-in·제어 정책은 유지합니다.

## C 제어 wire 매핑 준비 — 2026-10-13

[구현: 실제 호출 경로] `main()` → `VoiceNode.__init__()` → `_init_runner_control_source()` → 기존 `/runner/status` 수신 → `bind_control_source/bind_request_source`로 연결합니다. 기존 `request_run_enabled` opt-in을 사용하고 기본 false·평가 모드·명시 더미 binding은 보존합니다. [RunnerSource](ready2go_voice/adapters/runner_control.py)는 선택한 Runner의 이름/namespace·String 타입·단일 실제 graph endpoint의 현재성을 확인합니다. 선택 ROS 파라미터는 `control_runner_name`(기본 runner)·`control_runner_namespace`(기본 /)입니다. missing/multiple/교체·boot 변경은 세대/현재 요청을 무효화하고, 같은 boot의 낮은/중복 seq와 이전 boot는 폐기합니다. 소스 복귀만으로 과거 SDK/요청을 복원하지 않습니다. 일반 요청도 같은 실제 연결 확인 뒤 기존 request_id/run_id 수락·첫 안내 경로를 사용합니다.

[구현: 계약/증명 한계] [현재 설치 intent 원본](../../../contracts/intent.schema.json)을 검증해 recover·end_task·resume_register·resume_answer·resume를 기존 publisher로 발신합니다. 8b 이력 뒤 C 원본이 포함된 main5c를 정상 merge한 a440이 작업 기준입니다. Jazzy의 실제 dict 메타데이터 4개 시각/sequence 키를 받으며 없는 `info.publisher_gid`를 요구하지 않습니다. graph endpoint_gid는 연결 identity이고 개별 표본 GID·암호학적 발신 인증·B 센서 신선도 증거가 아닙니다. 별도 source handshake·새 공개 필드·자동 제어 발신은 없습니다.

[구현: 질문/최종 결정] `RunnerOffer`는 현재 source/boot/event/run·C 제안/등록의 내부 표현입니다. `offered`에서 질문 등록 후보를 만들고 현재 question.state=registered를 확인한 뒤에만 실제 TTS를 시작합니다. 등록 전에는 새 E ACK 타이머를 만들지 않으며 C 거절/만료/상태 변경으로 질문을 닫습니다. 등록 echo의 잔여시간은 해당 기존 E 등록 송신 시각+remaining으로 보수적으로 대응하고 수신 now+remaining·UTC·C/E 절대 monotonic 비교로 기한을 늘리지 않습니다. 동일 ID/정상 seq는 기한을 연장하지 않습니다. 선택 legacy `SafetyProof/provider`는 제품 C의 추가 필수 인터페이스가 아닙니다. C 제안은 실행 허가가 아니며 B 정상/empty 플래그를 E에서 만들어 넣지 않습니다. 실제 B 상태·pre/재진입·부분 effect 검사는 C가 소비 직전에 수행합니다.

[구현: 답/종료] 현재 등록·실제 TTS 완료·새 SDK receipt에 묶인 “응/네/예”와 명시 재개를 처리하고, 질문답·거절·만료에도 기존 선택 request_id를 보내 C 최종 decision/reason을 상관합니다. `decision=resume`은 현재 대상 상관을 지우기 전에 1회 소비하고 E 보존 대상을 종료하며, reject/hold/closed는 질문/요청만 닫고 작업을 보존합니다. 없어지는 terminal echo만 기다리지 않습니다. 진행 중 명시 종료는 현재 수락 run/boot로 event_id 없이 end_task를 직접 발신하며, C requested/unconfirmed에서는 완료로 처리하지 않습니다. 동일 대상의 실제 정지 confirmed·ABORTED·보존 폐기 확인 뒤에만 종료를 확정합니다. 정지 후 END도 현재 실제 C 결과를 대조하며 C의 from_step과 최종 failed_step 하위 ID를 다른 사건으로 오인하지 않습니다. C 잠금/phase는 E가 변경하지 않습니다.

[실측: 모의/미검증] 실제 C core/라우터/노드 상태 생성 본문과 E Node/Session을 연결한 직접 13사례, 관련 mapper 포함 39사례가 통과했습니다. PCM·SDK·ROS 전송은 모의이며 실ROS/실물 수용이 아닙니다. 해당 검사는 당시 SHA의 결과입니다. 현재 main의 C #319 시간 끝값·#316 복구 중 재정지는 반영됐으며, 실제 B 응답/외력 연결과 실물 검증은 별도로 남습니다. 값/책임/완료 기준은 P2 [FR-SAF-01/03](../../../docs/requirements.md#fr-saf-01)·[AC-SAF-02/04](../../../docs/requirements.md#ac-saf-02)·[접수 정책](../../../docs/requirements.md#resume-admission-policy), 정확 source/검사/최종 상태는 [E CURRENT](../../../practice/E/CURRENT.md#e-c-w3-wire-runtime-20261013)를 참조하십시오. 아래 10/12 typed/dummy 준비는 당시 이력이며 현재 runtime 연결과 구분합니다.

## 종료·중지 최소 연결 — 2026-10-12

[구현: E 내부/더미] 일반 음성·독립 stop SDK에서 정확한 종료 의도를 받고, running의 현재 요청 run과 검증된 생산자 boot에 고정합니다. 기존 공개 cancel로 정지를 요청한 뒤 같은 현재 typed 정지 확인에서 기존 TaskEndCandidate·제어 TTS/현재 세대·실제 재생 proof·명시 수락을 거쳐 더미 idle로 연결합니다. 종료 발화는 의도 근거이며 새 SDK 결과/독립 재개 등록 증빙으로 재사용하지 않습니다. 중복 전사는 새 cancel/후보를 만들지 않고 동일 halted heartbeat/같은 사건의 seq 진행은 유효 안내를 불필요하게 폐기하지 않습니다. 실제 재정지·다른 run/boot·생산자 변경·정지 미확인·TTS 실패에는 작업 보존/새 요청 차단을 유지합니다. idle도 아직 수락된 미완료 run이 있으면 “작업 없음”으로 단정하지 않습니다.

[구현: 안내/입력] 정확 “중지”를 config/parser/stop/safety 분류에 포함하고 부정·인용·전언·자기 TTS는 기존 규칙으로 차단합니다. running 종료의 대상/adapter 확인 실패는 기존 비권한 notice worker로 확인 불가 안내를 전달하며 높은 안전 경고를 덮지 않습니다. 고정 control_recover/resume/end/failed 4문장을 node/prepare 공통 prefill에 포함했습니다. 당시 cap256·warmup·startup60·prepare120은 유지했습니다. 현행 예산은 위 #356 설명을 참조하십시오. 문장 목록 identity가 달라져 기존 준비 receipt는 현재 준비를 대신하지 못하므로 기존 prepare/live 두 명령으로 사용자 재시험하십시오. 에이전트는 실제 캐시 생성·장치/API 실행을 하지 않았습니다.

[구현: STT 힌트] `stt_control_prompt`는 stop/safety의 실제 Whisper SDK prompt에서만 사용하고 일반 물품/현재 질문 힌트는 유지합니다. “요소희/이어서헥스”를 재개로 강제 치환하지 않습니다. 모델/PCM/장치/임계값·TTS 상한은 바꾸지 않았습니다.

[10/12 당시 인계: 실제 C 미연결] `bind_request_source(check, boot=...)`의 boot는 검증된 현재 생산자 identity를 전달하는 E 내부 adapter 입력이며 새 공개 wire가 아닙니다. 실제 C의 현재 run/boot 및 재기동 바인딩, typed 정지 증빙·종료 후보/명시 수락·보존 폐기 adapter는 C 확인/계약 협의 선행입니다. 현재 공개 cancel 전송과 실제 작업 종료·잠금 해제는 구분합니다. 더미 idle은 COMPLETED/effect/빈손/실로봇 완료가 아닙니다. 이 문단은 10/12 인계 이력입니다. 현재 C wire 및 기존 위치/개폐 읽기 질의 연결은 위 #322 절을 참조하십시오. 새 P3 상태 질의 범위·실제 C/B·실음성·실물 수용은 이 이력으로 완료 판정하지 않습니다. 기준은 [FR-SAF-01/03](../../../docs/requirements.md#fr-saf-01)·[FR-INT-03](../../../docs/requirements.md#fr-int-03)·[재개/종료 접수 정책](../../../docs/requirements.md#resume-admission-policy), 직접 검사/게시 경계는 [E CURRENT](../../../practice/E/CURRENT.md#end-stop-minimal-20261012-01)를 참조하십시오.

## P2 실음성 더미 준비

[문서: 준비 단계] [p2_voice_dummy.py](tools/p2_voice_dummy.py)는 기본 명령에서 구성만 확인합니다. `--serve-local`은 기존 격리 시험 도메인 166·localhost에서 실제 VoiceNode를 유지하지만, 임시 설정의 audio=false·평가 모드·기존 opt-in=false와 STT/LLM 차단·무재생 TTS를 사용합니다. 제품 설정/게이트를 수정하지 않고 `/voice/intent`, `/voice/text_override`, `/runner/status`, `/voice/speak`를 `/e_p2_dummy/` 아래로 remap합니다. C/B/모션·DB는 시작하지 않습니다. Ctrl+C로 종료하며 `--smoke-local`은 같은 노드의 생성·종료만 확인합니다.

저장소 루트에서 준비 명령은 다음과 같습니다. 이 명령은 secrets를 source하지 않으며 실제 녹음·외부 호출·재생을 하지 않습니다.

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export PYTHONPATH="$PWD/ros2_ws/src/ready2go_voice:$PWD/ros2_ws/src/ready2go_knowledge:$PWD/ros2_ws/src/ready2go_runner:$PYTHONPATH"
.venvs/project/bin/python ros2_ws/src/ready2go_voice/tools/p2_voice_dummy.py
.venvs/project/bin/python ros2_ws/src/ready2go_voice/tools/p2_voice_dummy.py --serve-local
```

[문서: 명시 live 단계] `create_live_voice`는 승인 bool 기본false·승인 hostname 미지정이면 거절합니다. `--serve-live`에서만 이 factory와 `LiveDummyBridge`를 격리 executor에 추가합니다. `logs/voice_eval/voice.local.yaml`과 `load_dotenv('secrets/voice.env', override=False)`를 재사용하고, STT/LLM의 실제 SDK hostname이 모두 `api.openai.com`인지 확인한 뒤 기존 실제 SharedInput·Whisper·LLM·Melo를 주입 대체 없이 사용합니다. HF/Transformers는 offline으로 기존 모델만 사용합니다. bridge의 명시 모의 current source callable과 계약07 수락/run·speak action을 연결하며, VoiceNode의 DAC 시작/재생 완료 검사를 통과한 action 성공 및 현재 세대/run이 유지될 때만 **더미** 첫 동작을 기록합니다. `complete` 입력 시 현재 첫 동작을 재검사한 뒤 더미 완료를 기록하며 실제 로봇 결과가 아닙니다. 트레이 질문·등록/결과 fixture, typed 정지 work·복구 질문/등록/독립 등록도 `dummy_assumption=true` 로그로 구분합니다. 현재 작업을 보존한 복구/재개/종료의 더미 수락과 TTS는 아래 [제어 안내 후속](#중단-작업-제어-안내--2026-10-12)을 따르며 실제 잠금 해제·모션은 하지 않습니다. 기한·revision·증빙은 시나리오 호출자가 지정하며 새 wire/시간 한계를 만들지 않습니다.

[실측: 읽기 전용 준비 확인, 2026-10-11] 실제 local YAML은 audio=true, fixed, 16kHz, Melo 속도1.2, whisper-1/gpt-4o이며 입출력 장치 `None`은 시스템 기본 선택입니다. 지정 wake/Melo Python/ontology/schema 파일이 있고 지정 assets에 WAV109개가 있습니다. 파일 수는 현재 캐시 준비/재생 성공의 증거가 아닙니다. secrets 파일에는 키가 있으나 키 내용은 조회 결과에 출력하지 않았습니다. 현재 프로세스 환경 우선·dotenv override=false를 고려해 외부 요청 없이 만든 STT/LLM SDK의 hostname은 모두 `api.openai.com`입니다. 환경 override가 바뀌면 실행 직전 hostname을 다시 확인해야 합니다. 샌드박스 장치 metadata 조회는 빈 목록이며 호스트 장치 부재로 단정하지 않습니다.

[문서: 실행 승인] 지시 세션이 조율 사용자 원문 “승인하고 실음성 시험 진행”을 확인했습니다. 승인 내용은 짧은 시험 WAV/물품 prompt를 Whisper(`api.openai.com/v1/audio/transcriptions`)로, 전사문/물품 목록/질문 문맥/정책을 같은 hostname의 LLM으로 전송하는 것입니다. 시험 발화는 “망치 가져다줘”·미지원 물품·질문 답변·“멈춰”·복구/재개/종료로 한정합니다. 사람의 발화가 없으면 통과로 기록하지 않습니다. 아래 명령은 마이크·유료 API·Melo 준비/재생을 실행하는 별도 단계입니다. `live_factory_started`는 스트림/녹음 성공 증거가 아니며 실제 ready·진단을 확인합니다.

```bash
# 위와 동일한 ROS/source PYTHONPATH 준비 후, 승인된 시험 발화만 입력
.venvs/project/bin/python -u ros2_ws/src/ready2go_voice/tools/p2_voice_dummy.py --serve-live --config-file logs/voice_eval/voice.local.yaml
```

### 대화 핫픽스 — 오후 통합 전 사용자 확인

[구현: E-VOICE-DIALOGUE-HOTFIX-20261012-02] 현재 질문은 쉼표·복합 답을 판정하는 동안 유지하고, 같은 세대/기한에서 긍정 또는 대상 정정을 판정한 뒤 한 번 소비합니다. “어, 맞아.”·“맞아, 그거 갖다줘.”·“맞아, 그걸로 갖다줘.”와 그걸로는 원문을 보존해 처리합니다. 질문 없음·만료·부정·미지원·새 다른 대상은 이전 대상을 자동 수락하지 않습니다. 정상 빈 전사 보존과 기존 기한은 그대로입니다.

가능 여부 질문(“립밤 가져올 수 있어?” 포함)은 실행하지 않고 등록 지원·실재고/파지 미확인을 안내한 뒤 대상 확인 질문을 합니다. 명시 긍정 후에도 기존 대상/요청 검증을 통과해야 합니다. 실제 시험의 “지금 망치 어딨어?”·“위쪽 서랍 열려있어?”와 끝마침표 형태도 위치/열림 질의로 처리합니다. 장소는 기존 위 서랍 이름의 방향 수식만 정규화하며 원본 장소/별칭을 추가하지 않습니다. 위치/열림 질의는 실행 분류 전에 기존 ontology.load/get의 초기 state를 읽기만 하며 “초기 배치 기준”이라고 안내합니다. IntentParser.state_provider에 바인딩된 읽기 전용 callable이 있으면 reference_query가 기존 state mapping을 실제 호출해 Runner 기록 기준으로 안내합니다. None일 때만 초기 배치를 사용하며 연결 실패/누락은 모름 안내입니다. 현재 VoiceNode의 C 공급자 바인딩·미수신/유실/재기동 경계는 위 #322 절에 구현했습니다. 독립 parser/dummy의 provider=None 초기 배치 경로는 유지하되 운영 노드의 현재 상태로 대체하지 않습니다.

더미 cancel은 현재 run의 명시 stopped fixture를 보존합니다. 이후 새로운 음성의 복구/재개/종료는 기존 typed safety 경로를 사용하고 일반 LLM에 보내지 않습니다. 복구 증빙·재개/종료는 모의 가정/후보이며 실제 B/C 상태·잠금 해제·모션 성공이 아닙니다. 작업 없음/완료 후에는 보존된 작업이 없음을 안내합니다. 실제 C의 정지/복구/재개/종료 상태 매핑은 담당 인계 사항입니다. 독립 정지는 멈춰/정지/그만/정지해/중단해를 기존 cancel 경로로 보내며 자기TTS·부정/인용은 보류합니다. 아래 정지·더미 후속의 DC 제외 판정을 적용하며 기존 임계값·보호한도·모델은 유지합니다.

아래 시험 복사 명령은 cue/WAV를 켜고 유효 옵션을 표시합니다. 원본 local·장치·모델·키·시간 예산은 보존합니다. 현재 요청 수락/발행 로그는 같은 request의 수락 상태를 사용합니다. 실제 마이크/스피커/API·정지/재개·초기 배치와 현재 상태 일치는 사용자 통합 시험에서 확인하십시오. 기준은 [음성 정책](../../../docs/requirements.md#voice-policy), [FR-SAF-01–03](../../../docs/requirements.md#fr-saf-01)입니다.

### 정지·더미 후속 — 2026-10-12

[구현: E-VOICE-STOP-CANCEL-HOTFIX-20261012-03] Recorder의 발화 판정은 프레임 평균을 뺀 AC RMS를 사용합니다. 원본 PCM과 350 임계값·0.4초 무음·8초 보호 상한은 유지합니다. 기존 두 로그의 저장 WAV를 재생 없이 재사용한 결과와 실제 마이크 정지 발화 검증은 구분합니다.

더미 revision은 생성자에서 0으로 시작하고 cancel/완료/안전 fixture는 같은 submit_lock으로 처리합니다. stopped fixture 거절 시 더미의 첫 동작·run·revision을 부분 변경하지 않습니다. 중단 작업은 complete로 성공 처리하지 않고 기존 종료 후보 경로를 요구하며, 종료 뒤 다음 작업은 기존 수락→실제 TTS 성공→첫 동작→complete 검사로 완료합니다. executor 예외는 `dummy_test_unavailable_executor_failed`와 오류 타입만 기록하고 시험을 중단합니다. stdin은 허용 command의 접수/거절만 남기며 발화 원문 로그를 늘리지 않습니다.

문형 폴백 밖의 “어, 그거.” 같은 관련 답도 유효 질문·대상·원문을 같은 LLM 호출에 먼저 전달한 뒤 판정/공통 검증과 현재 기한을 확인해 소비합니다. 부정·다른 대상·정보·미지원·만료는 이전 대상 권한을 받지 않습니다. 같은 질문을 보존하는 재확인은 기한을 연장하지 않습니다. 읽기 안내의 은/는은 기존 조사 helper를 쓰며, 초기 물품 위치와 초기 서랍 열림 및 그 값의 Runner 기록 기준 문장만 필수 prefill에 추가합니다. 다른 현재 상태/동적 문장은 최초 합성이 필요할 수 있습니다. [당시 구현] 128개 상한·실패 정책과 일반 startup60초를 유지했습니다. 아래 256개 후속은 당시 승인 이력이며, 현행 문장 상한은 위 #356의 512개 설명을 따릅니다.

[사용자 승인] cue_gain은 0.12에서 0.18로 조정했고 시험 복사 명령은 최신 원본 gain과 cancel 표현을 적용합니다. 장치·공유 출력 lock·원본 local·모델·키·기존 캐시는 보존합니다. [실측: 오프라인] 준비 비프 PCM clipping은 0이며 TTS 캐시 PCM과 비교했습니다. 실제 청취에서 동일 음량인지는 미검증입니다. 같은 request의 확인된 수락 기록은 늦은 발행 로그에서 미확인으로 되돌리지 않으며, 이 로그 기억은 실행 허가에 사용하지 않습니다.

재시작은 아래 복사 명령의 `E_VOICE_CUE=1 E_VOICE_SAVE_WAV=1`을 유지하고, stop 무음 종료는 일반 녹음 옵션과 독립입니다. 일반 요청도 무음 종료로 비교할 때만 `E_VOICE_SILENCE=1`을 사용합니다. 자동 완료는 기존 선택 옵션이며 중단 작업 complete 거절을 우회하지 않습니다. 실제 정지 발화·장치 DC 원인·비프 청취·C 상태 연결/모션은 미검증입니다.

### 사전 캐시 문장 상한 — 256개 후속

[10/12 당시 사용자 승인 이력: E-TTS-PREFILL-CAP-256-20261012-01] 실행 원본 `tts_prefill_max_texts`와 누락 기본값을 256으로 맞췄습니다. warmup 1개를 포함하므로 필수 문장 255개까지 허용하며 초과하면 기존 준비 실패 정책을 유지합니다. 문자 길이·UTF-8 용량 제한은 그대로입니다. 같은 cap을 사용하는 질문 중복 기록 deque도 누락 기본값만 맞췄으며 질문 소비·기한·일회 실행 권한을 바꾸지 않았습니다.

[10/12 당시 동작] 시험 복사 명령은 당시 패키지 YAML을 읽어 old local128의 복사본을 256으로 맞췄습니다. 현행 trial 복사본은 위 #356의 512개를 사용합니다. 원본 local·기존 run 로그는 보존합니다. 과거 128개 상한/실측 목록은 당시 이력이며 이번 개수 상한 변경이 prepare/노드 목록 차이나 일반 startup60초 timeout을 해결했다는 뜻은 아닙니다. 일반 startup60·prepare 전용120·AC 시간·모델·키·캐시는 유지하며, 다음 사용자 재시작에서 새 설정을 적용해야 합니다. 실제 준비·음성은 이번에 시험하지 않았습니다.

### 통합 음성 흐름 — 사용자 직접 시험

[구현: E-VOICE-FLOW-20261012-01] [정본의 음성 정책](../../../docs/requirements.md#voice-policy)에 따라 현재 P1 질문의 자연스러운 답을 처리합니다. 빠른 정확 답은 유지하고 YAML의 전체 답 문형과 부정/인용/미지원 가드를 통과한 현재 대상만 LLM 문맥/공통 검증·규칙 폴백에 연결합니다. 대상이 없으면 물품 이름을 묻고, running/잠금 상태에서는 질문 읽기·권한 생성을 하지 않고 상태를 안내합니다. 정상 SDK 빈 문자열은 현재 질문 ID·세대·기한을 그대로 보존하며 새 question_ready를 만들지 않습니다. 녹음/SDK/TTS 실패·취소·만료·새 독립 요청·running/잠금은 보존 표식으로 복원하지 않습니다. #43/#152의 질문/접수 규약은 변경하지 않았습니다.

[구현·진단] `interpretation.intent._voice.original_interpretation`·`execution_hold_reason`으로 원래 find 판정과 실행 보류를 구분합니다. 원본 LLM은 기존 interpretation에 한 번만 유지하고, `안내/제어 메시지 발행`은 실행 요청 수락이 아닙니다. 검증된 최종 문장·콘솔·TTS 입력은 일치하며 C 수락/완료 전 실행이나 성공을 단정하지 않습니다. 기존 STT 한 줄과 429 최소 정보 필터도 유지합니다.

[시험 옵션] 값·문구·문형은 [params/voice.yaml](params/voice.yaml)의 `voice_flow` 한 곳에서 관리합니다. 누락된 오래된 local 설정은 source/설치-share YAML의 mapping을 읽으며 명시 local 값과 원본 파일은 보존합니다. 아래 복사 명령의 환경 스위치는 시험 복사본만 바꿉니다.

| 스위치 | 사용자 시험 옵션 |
|---|---|
| E_VOICE_CUE=1 | 같은 출력장치/출력 lock의 미리 만든 로컬 띠딩. 입력 소비자 준비→실제 첫 DAC/PCM 유음 끝→finished/guard→capture_ready를 기록합니다. audible 띠딩 끝 직후 발화가 기준이며 guard/로그 표시를 기다린 발화만으로 첫 음절 검증을 대신하지 않습니다. |
| E_VOICE_SAVE_WAV=1 | 해당 run 폴더 captures에 P1 원음 WAV와 최소 RMS/peak/샘플수/시각 증빙을 저장합니다. 기본 저장0·원격 수집0, 파일 실패는 경고/진단으로 분리합니다. 현재 저장 대상은 일반 P1과 독립 stop·복구/재개/종료 safety 입력이며 #43 전용 원음 저장은 변경하지 않았습니다. |
| E_VOICE_TRIM=1 | 기존 RMS와 YAML padding으로 앞뒤 구간을 정리한 전송 WAV를 비교합니다. 원음은 저장 옵션에서 보존하고 start/end sample을 기록하며 원래 녹음 시각/AC 기준은 바꾸지 않습니다. |
| E_VOICE_STT_HINT=0/1 | 현재 유효 P1 질문의 STT 문맥 힌트를 비교합니다. 빈값은 local/YAML 설정 그대로이며 실제 SDK 접수 직전에 기한·세대를 다시 확인합니다. 새 모델/재시도/추가 호출은 없습니다. |
| E_VOICE_SILENCE=1 | 1은 복사본에서만 기존 silence 녹음을 비교하고 0은 원본 local 모드(현재 확인한 fixed)를 유지합니다. 기본 fixed5초·모델·임계값·commissioning 예산은 변경하지 않습니다. |
| E_VOICE_AUTO_COMPLETE=1 | 아래 명령에 --auto-complete를 붙입니다. 현재 run 수락→실제 수락 TTS 성공→더미 첫 동작 이후 기존 complete gate에서만 모의완료합니다. 이 복사 명령의 옵션0은 시험 복사본 dummy_auto_complete도 false로 맞춰 수동 complete 대기를 명시합니다. 원본 local true는 덮어쓰지 않습니다. 복사 명령을 생략한 직접 실행은 CLI 미지정 시 실제 local/YAML 값을 따릅니다. |

[구현·미검증] 일반 노드는 같은 SharedInput reader를 웨이크/새 캡처 창에 사용합니다. 알림음의 audible 종료는 첫 출력 DAC와 실제 준비 PCM의 마지막 유음 샘플에서 계산하고, 그 이전 샘플만 제외합니다. 경계를 걸친 ADC 프레임은 샘플 단위로 나누며 종료 이후 짧은 발화는 출력 버퍼 drain/guard 동안 쌓여도 보존합니다. Recorder에는 같은 prepared 경계를 넘겨 다시 전체 discard하지 않습니다. cue 중 정지 녹음은 보류하고 세대/취소/다른 출력에는 캡처를 중단합니다. 계산 경계와 mock ADC/DAC 검사는 실제 마이크의 첫 음절/room echo/입출력 시계 정합성·알림음 청취 성공을 대신하지 않습니다.

[사용자 재검증] 수동 모드는 첫 동작 뒤 complete→완료/idle을 확인한 뒤 대화 시험을 합니다. 자동 모드는 dummy_auto_complete_fixture_not_physical→모의완료/idle을 확인합니다. idle에서 대상만 망치→질문 TTS 완료/question_ready→웨이크 후 어어 맞아/어 그걸로 갖다줘/가져다줘를 시험하고 동일 대상·질문 ID의 한 번 수락을 대조합니다. 빈 전사가 나오면 기존 question ID/expires 보존 여부를 확인하며 부정/기한 만료/진행 중/SDK 오류가 자동 긍정이나 기한 연장으로 이어지지 않는지 확인합니다. cue/저장/trim/silence는 한 스위치씩 바꾼 새 run 폴더로 비교하고 띠딩 직후 짧은 응을 포함한 첫 음절, 원음의 cue 잔음, waveform·RMS/peak, 실제 STT/hint 적용·LLM 판정/보류·수락TTS/더미 완료를 구분합니다. 실음성·물리 수용 결과는 아직 없습니다.

### P1 짧은 확인 답변

[구현: E-VOICE-SHORT-REPLY-20261012-01] 기존 `core/intent.py:is_context_reply`의 정확 표현 목록에 “응 맞아”·“네 맞아요”를 추가했고, 같은 작업의 추가 사용자 승인으로 단독 긍정 “어어”도 지원합니다. “어”·“어어어”·부정/인용/제3자 문맥은 긍정 표현으로 확대하지 않습니다. 기존 공백/끝 종결기호 정규화를 재사용하며 부분 문자열로 긍정을 판단하지 않습니다. 실제 질문 TTS 성공 뒤 `Conversation.delivered`가 등록한 현재 질문의 대상·세대·기한에서 한 번만 결합합니다. 질문 없음·만료·실패·진행 중/잠금·부정 혼합에서는 실행 후보를 확정하지 않습니다. 빈 전사는 최신 정본 조정에 따라 현재 유효한 일반 P1 질문을 기존 기한으로 보존하지만 긍정 해석/권한 복원/연장은 하지 않습니다. SDK 오류는 계속 폐기합니다. 이 정확 답 목록의 앞선 작업은 node/config/녹음/모델/더미를 바꾸지 않았으며, 이후 통합 흐름 변경은 위 절을 참조하십시오.

[실측·코드 대조] `_094102/diagnostic.jsonl`의147–184행에서 망치 질문의 실제 TTS 완료 뒤 question_ready가 없고, 후속 STT 결과166/179행이 빈 문자열이었습니다. 앞선 더미 첫 동작은 있지만 완료/cancel 로그가 없었고, 더미의 running 상태 주입과 `runner_blocks → delivered(blocked=True)` 경로는 이 질문 준비 차단과 부합합니다. 당시 정책 객체 전체가 기록되지 않아 이를 단독 원인으로 확정하거나 제품 질문 준비 결함으로 단정하지 않습니다. local dialogue30을 확인했으며 누락 설정을 새로 주입하지 않습니다. 영상 음성 트랙 없음은 조율 확인을 재사용했고 원음을 재조사/새 녹음하지 않았습니다. 빈 전사의 음향 누락과 STT 미검출 원인은 미확인입니다.

[검증·후속] 실제 node 메서드 기반 모의에서 현재 질문→TTS 성공→question_ready→동일 대상/질문 ID의 복합 답→한 번 수락, 앞선 검사에서는 실패/만료/진행 중·빈 전사/SDK 실패 폐기를 확인했으며 정상 빈 전사의 현재 정책/구현은 위 통합 흐름과 정본을 참조합니다. API/마이크/스피커의 실제 짧은 답 인식 성공은 검증하지 않았습니다. 앞선 단계에서 보고한 진행 중 질문 읽기 UX는 통합 흐름에서 상태 안내로 변경했습니다. 기준은 [음성 정책](../../../docs/requirements.md#voice-policy)입니다.

### STT 전사 콘솔 확인

[구현: E-VOICE-STT-CONSOLE-20261012-01] 일반 음성의 기존 `stt_result`를 `STT 결과: …` 한 줄로 표시합니다. 기존 비밀값 redaction을 먼저 적용한 뒤 LF/CR을 공백으로 바꿉니다. 상세 JSONL의 동일 이벤트·전사는 기존 필터와 구조를 유지하며 콘솔/파일에 각각 한 번 기록합니다. 빈 STT 결과, `발화 없음: STT·LLM 생략`, 원인별 `STT 실패`는 구분합니다. 오류 안내·질문 문맥·요청 수락 정책과 설정은 변경하지 않습니다.

[실측: 기존 사용자 시험 로그] `logs/voice_eval/p2_dummy_20261012_094102/diagnostic.jsonl`의 request `c3ab1221307448da88e4c9279bc270cb`은 34행 STT “망치, 망치, 망치, 망치”, 35행 LLM passed clarify·targets=[]·question_target=toy_hammer였습니다. “가져다줘”가 없는 전사를 실행 명령으로 강제하지 않으며 앞선 NO_SPEECH와 별도 결과입니다. 실제로 명확한 문장이 입력된 경우의 규칙/모의 LLM 후보 회귀는 실API의 전사·LLM 선택 성공을 뜻하지 않습니다.

[문서: 입력 조사·미확인] SharedInput의 등록/discard 이전 프레임 배제·overflow 오류, WakeAudio→새 fixed 소비자의 고정 길이 수집, WAV의 전체 PCM 기록, Whisper의 전체 파일 전송을 대조했습니다. 기존 시험 설정 fixed5초/16kHz/1280프레임/whisper-1을 유지했습니다. 모의 fixed shared→WAV 검사는 80000샘플과 마지막 샘플 보존을 확인하며 실제 발화 누락 원인은 확정하지 않습니다. 당시 WAV/실제 음향·발화 타이밍 증빙이 없어 어느 단계에서 동작 말이 누락됐는지는 미확인입니다. 사용자 프로세스·원본 설정·모델·API/마이크/스피커는 조작하지 않았습니다. [FR-INT-01–03](../../../docs/requirements.md#fr-int-01)·[음성 정책](../../../docs/requirements.md#voice-policy)·[AC-INT-01–03](../../../docs/requirements.md#ac-int-01)의 실제 수용 검증은 별도입니다.

### STT API 오류 진단과 안내

[구현: E-VOICE-API-ERROR-20261011-01] 일반 음성 STT 실패는 `stt_failed.api_error`와 `_voice.stt_failure`에 status/code/type/category만 저장합니다. SDK의 정규화된 속성에서 HTTP status는 100–599 정수만, code/type은 `core/stt_error.py`의 닫힌 허용 목록만 받습니다. 누락·이상값·속성 읽기 오류는 안전하게 미확정 처리합니다. API 키·전체 예외 문자열/본문/헤더·WAV·예외 내 전사 및 request ID/retry-after는 수집하지 않습니다. 일반 콘솔에도 이 최소 정보만 표시하며 상세 파일은 기존 redaction을 거칩니다. 메타정보 없는 기존 실패 이벤트는 오류 종류만 표시하고 빈 `{}`를 붙이지 않습니다. 새 공개 계약/source 필드는 없습니다.

| 확인된 429 정보 | 내부 분류와 음성 안내 |
|---|---|
| code `rate_limit_exceeded`/`slow_down` 또는 type `rate_limit_error` | `rate_limit`: 요청이 많아 처리하지 못했으며 잠시 후 새 요청을 하도록 안내 |
| code `insufficient_quota`/`credit_balance_exhausted`/`project_spend_limit_exceeded`/`organization_usage_limit_exceeded`/`organization_spend_limit_exceeded` 또는 type `insufficient_quota` | `quota`: 크레딧이나 사용 한도 확인 안내 |
| 알려진 정보 없음, rate/quota 정보 충돌 또는 세부 원인 없는 RateLimitError | `unknown_429`: 요청 제한 원인 미확정·오류 기록 확인 안내 |

[문서] 분류 근거는 [OpenAI 공식 오류 안내](https://developers.openai.com/api/docs/guides/error-codes)와 [429 원인 안내](https://help.openai.com/en/articles/5955604-troubleshooting-api-rate-limits-and-429-errors)입니다. 알려지지 않은 code/type을 원문으로 저장하거나 추측해 분류하지 않습니다. 다른 일반 STT 오류와 발화/VAD 실패는 기존 안내를 유지합니다. 정상 STT·일반 clarify·시간 예산·SDK 재시도0·실행 보류를 보존합니다. 오류 안내는 내부 final_text에서 실제 노드 최종 응답/TTS 입력까지 전달되고, 과거 물품 확인 질문을 다시 실행 권한으로 쓰지 않습니다. stop/트레이/안전 STT 실패에는 같은 최소 내부 진단만 추가하며 기존 실패·취소 결과를 유지합니다.

[구현·설정] 실제 문구는 [voice.yaml](params/voice.yaml)의 `stt_error_prompts`입니다. 오래된 local YAML에서 키가 누락되면 패키지 YAML의 해당 mapping만 읽어 사용하고, 명시한 유효 사용자 문구는 보존합니다. source 실행은 패키지 params, 설치 실행은 기존 ament_index_python의 share/ready2go_voice/params/voice.yaml을 찾습니다(setup.py의 data_files 배치). 코드에 문구 원본을 중복하지 않습니다. 직접 raw cfg를 사용하는 Session/prefill도 같은 mapping 조회를 사용하며 전체 설정을 재귀 재로드하지 않습니다. 시험 설정 복사 명령도 load_config를 사용하므로 새 문구가 포함되며 원본 local은 덮어쓰지 않습니다. 사전 캐시 선택에 세 문구가 추가됩니다. 현재 실제 local로 **선택만** 확인한 문장수는80이며, 이전77문장 캐시 ready는 새3문구 준비/재생의 근거가 아닙니다. 다음 사용자가 시작하는 노드에서 전체 준비 완료와 웨이크 대기를 확인해야 합니다. 기존60초 startup·자산/장치·캐시를 보존하며 새 합성/실API/마이크/스피커 시험은 수행하지 않았습니다.

[실측·한계] `_212053`/`_213609` 시험 로그의 과거 RateLimitError는 당시 최소 code/type이 없어 원인 미확정입니다. 이번 수정으로 과거 원인이 확정되거나 API 제한이 해소됐다고 판단하지 않습니다. 모의 예외·실제 노드 메서드·진단 파일 필터·설정/default·캐시 선택을 검사하며 [FR-INT-01–03](../../../docs/requirements.md#fr-int-01)·[AC-INT-01–03](../../../docs/requirements.md#ac-int-01)의 실제 음성/지연 수용 검증은 별도입니다.

### 중단 명령·상태·정지 캡처 후속 — 2026-10-12

[구현: E-VOICE-CONTROL-STATE-20261012-02] 일반·stop·safety STT 전사를 기존 redaction으로 같은 콘솔/상세 진단에 표시합니다. 실행 도구는 Python 출력과 ROS/native stdout·stderr의 fd1/2를 한 경로로 redaction 후 `console.log`에 한 번 저장합니다. stdin은 변경하지 않습니다. Voice 상태·중단 작업 보존·종료 수락 대기, 후보/수락/거절을 구분하며 SDK JSON 응답 전체나 키를 출력하지 않습니다.

기존 정확 긍정 명령의 내부 띄어쓰기만 정규화하고 단독 “중단”·“복구”를 지원합니다. 부정·인용·전언은 계속 거절합니다. 문형 불일치와 요청/기한/상태·등록/증빙 불충족은 별도 reason으로 기록합니다. 종료 후보는 E 로컬 정책에서 작업을 퇴역시켜도 Voice의 수락 대기를 유지합니다. 신뢰된 현재 종료 수락은 후보 identity/세대를 확인해야 하며, 그 뒤에도 idle 관측이 있어야 일반 요청을 받습니다. 더미는 명시 typed 종료 후보 수락 뒤에만 필드를 정리하고 idle 시험 상태를 전달합니다. 실제 C 완료/모션 허가나 종료 ACK wire를 구현한 것이 아니며 실제 C adapter는 미연결입니다. 복구/재개·원본 #43/#152·일회 실행 조건은 그대로입니다.

정지 녹음은 SDK worker1개와 최신 대기 캡처1개로 분리합니다. 네트워크 응답을 기다리는 동안 다음 새 발화를 녹음할 수 있으며 대기 중 더 최신 캡처가 오면 이전 대기만 교체합니다. 같은 세대·취소·자기TTS·정확 정지 검사는 그대로이고, 이전 세대/취소된 결과는 발행하지 않습니다. 입력/원격 처리의 기존 한도만 사용하며 새 운용 시간값·모델·KWS·LLM·무제한 큐·원음 재사용은 추가하지 않았습니다. 실제 SDK 속도/정지 성공 개선은 미실측입니다.

기존 `capture_save_wav` opt-in은 독립 stop과 safety 입력에도 원본 WAV를 저장합니다(`captures/stop_<id>.wav`, `safety_<id>.wav`). NO_SPEECH 검사 전 원음을 보존하며 안전 입력에는 trim을 적용하지 않습니다. 모델·VAD/350 임계값·0.4초 무음·8초 보호 한도는 유지합니다. 캡처 식별자/입력 종류로 SDK/결과/보류 진단을 연결합니다. 실제 원음 없는 과거 NO_SPEECH 원인이나 녹음 미시작을 단정하지 않습니다.

정상 종료 요청/실행 중 executor 예외/정리 실패를 구분해 기록합니다. stop/closing 뒤 executor 예외는 종료 중단으로 분류하고, 실행 중 실패는 더미 시험 불능으로 표시합니다. cleanup은 한 단계가 실패해도 나머지 정리를 시도하며, 이미 닫힌 ROS context에 shutdown을 다시 호출하지 않습니다. 닫힌 context의 RCLError는 operation/context 상태를 남깁니다. 과거 두 RCLError의 정확 발생 위치는 당시 로그에 없으므로 미확정이고 실제 ROS 종료 재시험은 이번에 수행하지 않았습니다.

동일한 prepare/live 두 명령을 사용합니다. 사용자 재시험은 prepare 성공→live ready→일반 요청/정지 반복(대기 중 다음 발화 포함)→중단 후 새 웨이크 “복구”/“이어서 해”→현재 증빙·종료 수락→idle 뒤 지우개 새 요청 순서입니다. 전사/구체 reason·원음·종료 상태를 새 run 폴더에서 확인하십시오. 소프트웨어/모의 결과를 실음성·물리 정지 완료로 보고하지 않습니다.

### 중단 작업 제어 안내 — 2026-10-12

[구현: E-VOICE-CONTROL-FEEDBACK-20261012-03] 실제 수락한 더미 작업의 중단 뒤 새 웨이크 “복구해”는 명시 복구 fixture와 실제 TTS 경로의 안내를 연결합니다. 안내는 새 웨이크 후 “이어서 해”를 요청하며 자동 복구 질문·유효기간·등록을 만들지 않습니다. “응/네”, 안내 완료, 과거 전사만으로 재개하지 않습니다. 이미 유효한 등록 질문이 있으면 기존 등록·재생·새 답변 경로를 보존합니다. 기준은 [재개 정책](../../../docs/requirements.md#resume-admission-policy)을 참조합니다.

새 녹음·SDK 경계·현재 등록 ACK/작업/세대·복구 증빙을 통과한 명시 후보에 한해 더미 수락 안내를 재생합니다. DAC 시작/finished callback 증명과 현재 후보/세대를 다시 확인한 뒤 재개는 running fixture, 종료는 idle fixture로 전환합니다. 종료 후보만으로 중단 작업을 지우지 않습니다. 재개는 원래 작업 인자와 run을 보존하고 더미 내부 요청 상관만 새로 연결하므로 이후 수동 complete로 모의 완료할 수 있습니다. 안내 중 재정지는 이전 후보의 running/idle 전환을 막습니다. 실제 C 해제·모션·물리 완료가 아니며 새 공개 wire는 없습니다. 원래 수락한 작업이 없는 수동 stopped fixture는 재개 가능한 작업으로 만들지 않습니다.

인식·조건 실패는 작업을 보존하고 실패 TTS를 호출합니다. 정상 무음/빈 전사/비정지 입력의 반복 stop 보류는 일반 콘솔에서 줄이되 상세 진단은 남깁니다. 실제 오류·안전 STT·이유·상태 전환은 표시합니다. 확인된 halted에서는 중복 stop 처리를 줄이며 재생/복구·재개 전환 중에는 감시를 유지합니다. 새 제어 문장의 첫 TTS 합성은 필요할 수 있습니다. 모델·원음·VAD·시간 설정은 변경하지 않았습니다.

[실측: 선택 모의] 기준 be010813 위 변경의 선택 25사례를 실패 부분 보완 후 모두 확인했습니다. [검증 한계 정정] 이 25개 중 복구·재개·종료 흐름은 `_diagnostic`을 모의하고 피드백 재생을 직접 호출했습니다. 실제 진단의 null 처리와 `_work`·`_safety_work`·`_listen`의 비동기 인계/웨이크 재진입을 검증하지 못했고, 실제 복구 TTS·재입력 성공 근거로 사용할 수 없습니다. 검토 지적의 기존 종료 시험도 후보→work 보존→실제 _say callback/proof→종료 수락→idle→새 지우개 요청을 확인합니다. 테스트 목록·실패 이력과 명령은 [E CURRENT](../../../practice/E/CURRENT.md)에 기록했습니다. 실제 장치/SDK/음향 재시험·C 연결은 미검증입니다.

[실측: 오프라인 원음 비교] 16:50:42 실행의 stop 원음 0.96초가 같은 시간대 safety 원음 5초의 샘플 offset46325에 완전히 포함됩니다. 기존 SpeechPresence는 비교한 원본 3개 모두 false, 메모리 내 DC 제거 비교 복사본은 true였습니다. 원음/설정/PCM/모델/임계값은 수정하지 않았으며, 실제 NO_SPEECH/전사의 단일 원인이나 실음성 개선 완료를 뜻하지 않습니다. 원인은 미확정입니다.

사용자 재시험은 아래 prepare/live 두 명령을 유지합니다. 일반 작업 수락→정지→새 웨이크 복구→안내 완료→새 웨이크 명시 재개→running→complete, 또는 정지→명시 종료→안내 완료→idle→새 지우개 요청을 새 로그에서 확인하십시오. 조건 실패 안내와 수락 안내 도중 재정지의 보존 상태도 확인해야 합니다. 실제 C 작업/정지/복구 증빙·등록 ACK·재개점 연결과 실물 시험은 선행 미완료 항목입니다.

### 제어 안내 진단·작업자 회귀 보완 — 2026-10-12

[확인: E-VOICE-CONTROL-FEEDBACK-20261012-03-R1] 18:01:32 실행의 복구 STT/더미 복구 확인 뒤 `reason=null` 정상 진단이 콘솔 메시지 사전의 무관한 표현식에서도 평가되어 TypeError를 일으켰습니다. 피드백 점유를 설정한 뒤 진단이 실패했고, 일반 작업자의 무조건 busy 해제와 웨이크 외부/내부 점유 검사 차이로 재입력도 막혔습니다. 이는 모델/SDK 인식 원인으로 분류하지 않습니다. 원본 근거와 실제 `_diagnostic` 재현은 조율·지시 세션의 확인 결과를 재사용했습니다.

[구현] 원본 상세 진단의 null은 보존하고 콘솔 reason만 안전한 문자열로 표시합니다. 피드백 큐 등록 중 진단 예외는 새 점유/후보를 정리하고 호출자에게 전파하며, 작업자는 오류를 표시하고 계속 입력을 받을 수 있습니다. 오류 보고 자체가 실패하면 예외 타입/작업명만 최소 출력하며 숨기지 않습니다. 일반 요청 소유자와 안전 pending/running을 기준으로 busy/safety_activity를 정리하고 웨이크의 외부·내부 검사를 같은 함수로 맞췄습니다. TTS 실패/재정지는 후보를 재사용하지 않고 중단 작업을 보존합니다. 기존 등록·증빙·기한·세대·fresh 입력 조건, 정책/문구/시간 설정·원음·모델·캐시와 prepare/live 두 명령은 그대로입니다. running 상태의 종료 정책·라우팅은 이번 보완 범위가 아닙니다.

[실측: 연결 모의] 새 [작업자 경계 시험](test/test_control_feedback_workers.py)은 `_diagnostic`/진단 writer·logger, `_listen`→`_work`→`_safety_recording`→더미 수신→`_safety_work`→`_say`를 실제 메서드로 연결했습니다. 장치·SDK·ROS 전송만 모의 처리했고 Event/condition으로 동기화했습니다. 7개 고유 흐름에서 reason=None 복구/재개/종료 진단, TTS 후 다음 wake, running/complete 및 종료/idle/새 요청, pending/running 점유, 큐 등록·실행 중 진단 예외/TTS 실패/재정지·첫 인식실패 안내 후 점유 정리·작업 보존을 확인했습니다. 일반 콘솔/상세 저장/redaction도 연결했습니다. 최초6통과에는 모의 장치 종료 속성 누락 경고4건이 있어 해당4개를 보완·경고를 오류로 재검사했고, 실행 중 진단예외1개 및 영향 TTS 실패1개는 별도로 확인했습니다. 실제 마이크/API/스피커/C/로봇·물리 복구 성공은 여전히 미검증입니다. 정확 명령·결과는 [E CURRENT](../../../practice/E/CURRENT.md)를 참조합니다.

### 사용자 직접 시험 — 재실행과 증빙

[실측: 인계 상태, 2026-10-11] 에이전트 실행은 stdin `exit`로 정상 종료(exit0)했습니다. PID250630 및 더미/Melo worker 잔존 없음, 기존 close/finally의 공유 입력·worker·executor/context 정리를 확인했습니다. 당시 로그는 `/tmp/e-p2-live-voice-dummy-20261011-ready.log`에 보존했습니다. 사람 발화·STT/LLM 결과·실TTS 재생·더미 첫 동작/완료는 관측0이며 사용자가 직접 다음 시험을 수행합니다. 준비 성공과 실음성 통과는 다릅니다.

[구현: E-VOICE-LAUNCH-STOP-INPUT-20261012-01] [프로젝트 Python 의존성 설치](../../../README.md#프로젝트-의존성-설치), [공통 호스트 build/install·새 터미널 준비](../../../README.md#실행), [Voice 패키지 빌드/install 준비](#실행-준비와-의존성)를 마친 뒤 **저장소 루트에서** 아래 두 명령을 각각 명시 실행합니다. 스크립트는 자신의 위치에서 저장소 루트를 계산해 이동하고 ROS Jazzy·기존 `ros2_ws/install`을 source한 뒤 `.venvs/project/bin/python`으로 실행합니다. 시험 설정 복사와 로그 저장도 도구가 처리합니다. prepare는 마이크/API/재생/live를 호출하지 않으며, 성공 뒤에만 별도 live 명령을 사용합니다. live는 실제 마이크/API/스피커를 사용하는 기존 격리 더미 시험입니다. 에이전트는 이번 변경에서 두 실제 실행을 수행하지 않았습니다.

```bash
bash ros2_ws/src/ready2go_voice/tools/voice_trial.sh prepare
bash ros2_ws/src/ready2go_voice/tools/voice_trial.sh live
```

재실행마다 `logs/voice_eval/voice_prepare_<날짜>_<식별자>` 또는 `voice_live_<날짜>_<식별자>`를 새로 만들고 `voice.local.yaml`·`console.log`·`result.json`을 남깁니다. live 상세 진단과 일반 P1 원음 WAV도 해당 새 폴더에만 저장합니다. 원본 local·기존 run 로그·장치/모델/키/캐시는 덮어쓰지 않습니다. 시험 복사본의 누락 P1/P2 필수 키만 패키지 실행 원본에서 보충하고, 명시 null이면 시작을 거절합니다. 현행 패키지 원본의 cap512·cue_gain·cancel 표현은 두 단계의 시험 복사본에 같이 적용합니다. 기본 옵션은 cue/WAV 켬·trim 끔·원본 일반 녹음 모드·수동 complete·기존 STT hint이며 일반 무음 비교는 live에 `--silence`, 모의 자동 완료는 `--auto-complete`를 붙입니다. 기존 E_VOICE 환경 옵션도 지원합니다.

prepare와 live는 같은 함수로 온톨로지/상태를 반영한 prefill 목록을 선택합니다. 일반 startup은 사용 YAML의 명시값(패키지 기본600초, 기존 local60초 등)을 따르고 prepare만 메모리에서3600초를 사용합니다. AC 발화 예산은 별도입니다. 최신 prepare의 성공과 TTS 설정/목록 identity가 맞아야 live를 시작합니다. 실패한 최신 prepare가 과거 성공을 대신하지 않으며 자동 재시도/자동 live를 실행하지 않습니다. 이 성공 기록은 준비 호출 완료의 근거이며 실제 모델/worker/cache identity는 노드가 다시 검사합니다. `result.json`의 success는 명령 종료 상태이고 음성·로봇 성공이 아닙니다. 실행 중 executor 실패/정리 오류는 별도 진단으로 확인합니다. stdin은 그대로 연결되어 `complete`·`exit`를 입력할 수 있고 Ctrl+C는 기존 close/finally로 정리합니다.

[확인된 코드 조건] 중단 후 fixed 입력의 로컬 발화 검사가 False이면 `NO_SPEECH` ValueError로 SDK를 호출하지 않습니다. 실제 기존 로그의 ValueError가 이 조건인지·원음/장치 문제인지는 아직 미확정입니다. 실패는 capture_validation/speech_check/admission/sdk/classification 단계와 허용된 사유 코드로 표시하고, SDK 응답의 빈 전사·접수 확인 여부·후보 없음도 구분합니다. 후보 판정이 먼저 무효화한 뒤 남은 예약은 새 현재 질문/요청이 없는 경우에만 정리하여 다음 새 요청을 받을 수 있게 합니다. work·새 사건·기한·명시 재개·일회 실행·#43/#152 조건은 보존합니다. 실제 C의 현재 작업/증빙/등록 ACK가 없으면 복구/재개/종료를 완료했다고 보지 않습니다.

독립 stop 상세 진단은 capture 종료·SDK 요청/응답·빈 전사/정확 정지/자기TTS 보류·발행 시각을 나눕니다. `stop_request_published`는 보조 정지 메시지 발행이며 실제 물리 정지 확인이 아닙니다. SharedInput은 reader별로 전달하며 마이크 탈취/녹음 미시작으로 단정하지 않습니다. 모델·350 임계값·0.4초 무음·8초 보호한도·원음은 변경하지 않았습니다. 실제 짧은 정지 발화/속도·자기TTS 혼입·중단 후 인식은 사용자 재시험에서 확인합니다.



먼저 `MeloTTS 준비 완료 (고정 안내 캐시 완료)`와 `웨이크 대기 (입력: …)`를 모두 확인합니다. `live_factory_started_not_recording_proof`만으로 입력 ready를 판정하지 않습니다. 당시 기본 장치는 input/output7이었지만 재실행 시 실제 선택을 다시 확인합니다. hostname이 승인된 `api.openai.com`과 다르면 factory가 시작을 거절합니다. 모델 준비 실패 시 아래 기존 [캐시 사전 준비](#노드-실행-전-사전-캐시-준비) 절차를 확인하고 ready 전에는 발화하지 않습니다. 패키지의 선정 목표 catalog도 그대로 보충되지만 이번 승인 발화 범위를 선정5종 시험으로 확대하지 않습니다.

| 순서·입력 | 확인할 로그/결과 | 다음 단계·한계 |
|---|---|---|
| 1. “헬로 로키” → “망치 가져다줘” | 상세 `record_started/record_finished`, `whisper_sdk_request`, `stt_result`의 실제 시험 전사, `interpretation`의 intent/LLM·폴백 구분; 콘솔 `accepted_fixture`와 상세 `request_accepted`의 같은 run | LLM 실패/폴백을 정상 LLM 성공으로 기록하지 않습니다. 등록 물품을 수락하는 **더미**이며 실제 Runner의 지원 물품 판정이 아닙니다. |
| 2. 첫 요청의 수락 TTS 종료까지 기다림 | `tts_started.source.tts_mock=false`, `tts_start_basis=portaudio_first_dac`; `tts_finished.timing.playback_end_basis=portaudio_finished_callback`·종료 시각; `dummy_first_action_after_real_speak_success` | 실제 소리/문장도 듣고 기록합니다. first action이 없거나 TTS 실패면 `complete`를 입력하지 않습니다. |
| 3. 터미널 stdin `complete` | 같은 run의 `dummy_completed_not_robot_result`, 상세 `request_completed`와 완료 안내 | 첫 동작 전/취소 뒤 complete는 `completion_rejected_no_current_first_action`이어야 합니다. 물리 성공 증거가 아닙니다. |
| 4. 완료 안내 후 웨이크 → 미지원 물품 요청(예: “사과 가져다줘”) | unknown/미지원 안내, 새 `accepted_fixture`·더미 첫 동작0 | 과거 첫 요청의 로그를 현재 요청의 결과로 세지 않습니다. |
| 5. 웨이크 → 대상만 “망치”, 확인 질문 종료 뒤 다시 웨이크 → “응”/“응 맞아”/“네 맞아요”/“어어”/“아니요”/모호한 답 | 질문 문장·상세 JSONL question_ready·새 답 전사·확인/거절/보류; 긍정일 때만 수락과 TTS gate 이후 첫 동작 | 수동 모드는 complete, 자동 모드는 모의완료로 이전 더미 작업을 끝낸 뒤 idle과 상세 question_ready를 확인합니다. 진행 중 차단을 우회하지 않습니다. P1 답은 일반 WakeAudio를 다시 거치며 시험 복사본의 dialogue_timeout_sec=30.0(현재 제안 설정의 시험값) 문맥 안에서 진행합니다. 각 답 종류는 독립 시험으로 진행하고 active 질문/처리 중 다음 시험을 겹치지 않습니다. |
| 6. 새 망치 요청의 처리·TTS 중, 또는 첫 동작 후 complete 전에 웨이크 없이 “멈춰” | `cancel_received_not_physical_stop`, `dummy_idle_after_cancel_not_physical_stop_evidence`; old run의 추가 첫 동작/완료0 | STT 지연/실패·늦은 결과·자기 TTS 영향과 실제 소리를 기록합니다. 자기 발화 문구 대조는 음향 echo 제거가 아니며 물리 정지 시각/성공은 미검증입니다. |
| 7. idle/이전 작업 종료 뒤 stdin `tray 100` | 질문 재생·`tray_answer`의 `asked`→동일 question 등록 fixture; 상세 `confirm_sdk_request` | 100은 [전체 확인 기한 정본](../../../docs/requirements.md#verification-policy)에 연결된 명시 모의 입력입니다. 임의 새 timeout이 아닙니다. 질문 후 답에는 웨이크를 붙이지 않습니다. |
| 8. 질문 완료 뒤 “네”/“아니요”/모호 답 | yes/no/ambiguous 및 모호 답의 최대1회 재질문, 새 질문 ID/attempt·다시 새 녹음 | 각 종류는 별도 tray 시나리오입니다. yes 이후에만 stdin `tray_complete` 또는 `tray_partial`로 전달/복구 결과 fixture 안내를 확인합니다. C 관측/실물 결과가 아닙니다. |
| 9. stdin `stopped` 한 번, 이어 `question 60` | `typed_stopped_fixture_not_bc_evidence`, `typed_offer_fixture_not_bc_recovery`, `typed_safety_fixture`의 register_question; 실제 복구 확인 질문·TTS 완료 | 60초는 이번 더미 시험의 **명시 fixture 유효기간 인자**이며 운용 기본값·C 계약이 아닙니다. [재개 정책](../../../docs/requirements.md#resume-admission-policy)의 접수/STT 한계를 바꾸지 않습니다. C 유효기간 매핑 전이므로 새 운용 기본값을 정하지 않습니다. |
| 10. 질문 완료 뒤 “재개해”/거절. 독립 발화는 각 새 실행에서 `stopped` 한 번 → `independent` → 새 “복구해”/“재개해”/“작업 종료해” | `safety_sdk_request`·새 전사와 `typed_safety_fixture`의 declined/recover/register_independent/candidate; 과거·중복 응답으로 추가 후보0 | 등록·증빙은 같은 모의 work의 주입입니다. 현재 로그는 모든 typed work ID/정지 SDK 시각을 출력하지 않으므로 없는 증빙은 미확인으로 남깁니다. 후보는 로그뿐이며 실잠금 해제·재개·작업 종료를 실행하지 않습니다. |
| 11. stdin `exit` 또는 Ctrl+C | 명령 종료 코드, 현재 PID/worker 종료와 마이크 반환; console/diagnostic 로그 보존 | 다음 시험의 재현 발화·원인·해결·검증/미검증을 분리 기록합니다. |

`stopped`는 현재 harness에서 boot=`dummy`, 새 work의 revision=1을 지정합니다. 같은 프로세스에서 이를 다시 입력하면 기존 revision보다 낮아 거절될 수 있습니다. 같은 사건의 question/independent를 순차 시험하고, 새로운 정지 사건은 정상 종료 후 새 실행으로 분리합니다. `question 60`은 이번 더미 시험의 명시 입력 예시이며 실제 C 기한 검증은 시험 밖입니다. 이 값을 제품 정책이나 C의 운용 기본값으로 옮기지 않습니다. stdin에는 fixture 명령만 입력하고 실제 발화를 텍스트로 대체하지 않습니다. 시험 범위 외 대화를 녹음/전송하지 않습니다. [FR-INT-02](../../../docs/requirements.md#fr-int-02)·[AC-SAF-02](../../../docs/requirements.md#ac-saf-02)·[AC-SAF-04](../../../docs/requirements.md#ac-saf-04)의 실제 C/물리 수용 완료와 구분합니다.

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
| `nodes/voice_node.py` | 기존 `/voice/text_override` 입력·`/voice/intent` 발행·`/voice/speak` Skill 액션·ROS 진단 로그, 질문 작업·수락 상관·typed 안전 입력 경계 |
| `core/place_exchange.py`, `core/place_input.py` | 트레이 질문 상관·발신 후보·현재 개발 입력 정규화. C 실제 입력 매핑은 후속 |
| `core/safety_exchange.py`, `core/recovery_confirmation.py` | 복구 질문·독립 새 발화·현재 등록/증빙·재개/종료 내부 후보. 공개 wire/모션 없음 |
| `core/request_run.py` | 일반 요청 targets 또는 선정 목표 요청 ID와 C 수락 run·최종 결과 상관 |
| `test/` | 해석/실패/지연·기록 종료·재생/취소·노드 평가 게이트의 모의 검사 |

[문서] 참고 코드 `keyword_extraction.py`·`STT.py`의 프롬프트/호출·녹음→Whisper 구조를 사용했습니다. 원본 `sd.rec`→`sd.wait`의 고정 5초 녹음을 시운전 기본으로 적용했습니다. 고정 도구 목록, `/` 문자열 분해, import 시 dotenv, 임시파일 누수는 옮기지 않았습니다. SciPy 대신 표준 `wave`를 사용합니다. 웨이크 모델 원본을 복제/수정하거나 모델을 자동 다운로드하지 않습니다.

## 현재 지원 명령

[문서·코드 대조: 2026-10-11] 최신 E 연속 기능 개발의 실제 함수·설정·기존 계약을 대조했습니다. 새 경로는 작성 후 모의·회귀 확인 단계입니다. 변경 관련 직접 검사510 passed/9 skipped(sounddevice 미설치), 기존 격리 ROS 노드 검사48 passed이며 실제 마이크/API·C 통합·실물 실행 결과는 아닙니다. 아래 현재 호출 범위와 통합 선행을 구분합니다. 이전 P1 실험 결과를 새 P2 기능 검증으로 대신하지 않습니다.

| 명령 종류·연결 상태 | 발화/입력 예시 | 현재 처리 | 제한·운영 연결 | 근거 원본 |
|---|---|---|---|---|
| 단일 물품 가져오기 — 음성 해석 `find_item` | “지우개 찾아줘”, “지우개 가져다줘”, “지우개 좀”; 다른 등록 이름/별칭의 단일 요청 | 등록 단일 대상·발화 일치·요청 단서·확신도를 검증하고 확인 TTS 뒤 발행 게이트 적용 | 해석 대상은 등록 물품이며 현재 기본 `find_item` 태스크의 `trigger.targets`는 `eraser`만. 다른 등록 대상은 Runner에서 `UNSUPPORTED_ITEM` 보류. 실행 중/잠김/서버 미준비도 거절. 직접 태스크 실행은 trigger 제한을 거치지 않아 별도 입력 확인 필요 | [파서](ready2go_voice/core/intent.py)·[노드](ready2go_voice/nodes/voice_node.py)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py)·[태스크](../../../tasks/find_item.json) |
| 취소 — 음성/텍스트 제어 `cancel` | “멈춰”, “정지”, “취소”, “그만”; “멈춰.”, “정지해” | 설정 문구와 승인된 stop 분류를 LLM 없이 적용. 처리·TTS·질문·Runner 실행 중 새 “멈춰”/“정지해”는 웨이크 없이 무음 종료 녹음→별도 STT 슬롯→기존 cancel로 연결하도록 작성. 질문 STT와 동일 세대의 중복 발신을 차단하고 진행 중 E 작업을 취소. Runner는 실행 중이면 `halt()` | 실행 중이 아니면 `NOT_RUNNING`. 실제 정지 확인·하드웨어 E-stop 대체가 아님. 일반 요청의 웨이크 제한은 유지하며 독립 정지 수신은 audio_enabled=true·물리 입력 준비가 필요. 클라우드 STT 지연/실패·실제 echo 억제·로봇 정지는 미검증. P2 안전 AC 완료와 구분 | [문구 설정](params/voice.yaml)·[파서](ready2go_voice/core/intent.py)·[Voice 노드](ready2go_voice/nodes/voice_node.py)·[Runner 노드](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| 상태 요청 — 음성/텍스트 제어 `status` | “지금 뭐 해”, “지금 뭐해”, “상태 알려”, “진행 상황”; “지금 뭐 해?” | 설정 문구와 같은 정확 비교로 E intent 발행. Runner는 `/runner/status`를 다시 발행 | 실제 현재 상태를 조회하여 음성으로 읽어주는 기능은 연결되지 않음. 기존 오류/중단 안내는 별도. 상태 요청은 일반 웨이크 청취 제한을 유지하며 독립 정지 STT에서는 처리하지 않음 | [문구 설정](params/voice.yaml)·[파서](ready2go_voice/core/intent.py)·[Runner 노드](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| 보류 응답 — `clarify`/`unknown`, 실행 명령 아님 | “지우개”, “그거 가져줘”, 여러 대상·미등록·미지원 요청 | 단독/모호/복수 대상과 유효 질문 없는 동의/대명사 응답은 대상 재확인, 미등록 물품/미지원 요청은 검증된 내부 사유로 안내를 구분. 오류 후 폴백과 정상 unknown/clarify는 구분 | 실행 후보로 확정하지 않음. 실행 모드에서 보류 intent 자체가 발행될 수 있으나 Runner는 `NEEDS_CLARIFY`로 실행하지 않음. 부정/번역/제외·현재 질문 문맥의 핵심 모의 검사는 아래 #194 절에서 구분; 자유 실음성 일반화는 미검증 | [파서](ready2go_voice/core/intent.py)·[게이트](ready2go_voice/core/session.py)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py) |
| 목표형 achieve_goal — 선정 5종 E 경로 작성 | 지우개/립밤 트레이 전달, 위 서랍 열어 둬/닫아, 지우개 전달+서랍 열어 둬 | 선정 catalog·현재 world·명시 발화·LLM 후보를 검증하고 현재 request_id/accept_text payload와 동일 목표 내용의 수락 run을 연결. 수락 뒤 기존 speak로 한 번 재생 | 기본 p2_goal_enabled=false, request_run_enabled=false. 두 opt-in과 현재 C 생산자 확인 필요. 실제 C first gate·계획/검증·B 파지와 실물 AC는 미완료 | [목표 정본](../../../docs/requirements.md#fr-int-02)·[catalog](params/voice.yaml)·[Session](ready2go_voice/core/session.py)·[RequestRun](ready2go_voice/core/request_run.py) |
| `find_list`/`find_class`/`query_state` — 현재 음성 미지원 | 음성 미지원/계약 enum만 존재 | Voice P1 필터에서 거절. 현재 `tasks/`에는 대응 trigger 태스크가 없어 기본 Runner 라우팅은 `UNSUPPORTED_INTENT` | 계약 enum 존재만으로 지원/실행 가능이라 판정하지 않음. 확장 기준·Phase는 [FR-INT-02](../../../docs/requirements.md#fr-int-02) 참조 | [계약](../../../contracts/intent.schema.json)·[Voice 필터](ready2go_voice/core/intent.py)·[태스크 목록](../../../tasks/)·[라우터](../ready2go_runner/ready2go_runner/core/intent_router.py) |
| 레지스트리 태스크 `return_items` — 파일 존재, 현재 intent 연결 미지원 | 음성 미지원; 파일의 `examples_ko`는 지원 발화 근거 아님 | Runner loader는 `trigger.intent`를 등록하고 `intent_tasks` override를 우선하지만 `return_items`는 현재 계약 enum 밖이라 intent 입력은 `BAD_INTENT`. Voice도 미지원 | 레지스트리 로딩이 schema enum이나 음성 파서를 자동 확장하지 않음. 파일은 트레이 관측 단계만 있어 반납 완성 기능이 아님. `p1_demo_eraser`는 trigger.intent 없이 override/직접 실행용 | [예시 태스크](../../../tasks/return_items.json)·[시연 태스크](../../../tasks/p1_demo_eraser.json)·[계약](../../../contracts/intent.schema.json)·[로딩](../ready2go_runner/ready2go_runner/nodes/runner_node.py) |
| 복구 요청 — E typed 호출 작성 | “복구해”, “상태 확인 후 복구해” | 현재 확인된 보존 work의 복구 의사를 LLM 없이 typed sender에 전달 | C 공개 매핑 미연결. E가 실제 복구·잠금 해제·그리퍼 조작을 하지 않음 | [안전 정책](../../../docs/requirements.md#resume-admission-policy)·[SafetyExchange](ready2go_voice/core/safety_exchange.py)·[노드](ready2go_voice/nodes/voice_node.py) |
| 재개·새 시작 — E 질문/독립 발화 호출 작성 | 현재 질문 뒤 “재개해/이어서 해”, 승인된 새 시작 질문 뒤 “처음부터 시작해”; 질문 거절 “아니요” | 현재 등록·TTS 증빙·새 녹음·SDK·결과를 검사해 내부 후보. 질문 거절은 질문만 닫고 work 보존. 새 독립 발화는 등록 확인 뒤 한 번 소비 | 과거 질문 답을 독립 요청으로 바꾸지 않음. text_override로 재개 증빙을 만들지 않음. 실제 C/B 상태·증빙·최종 허가 매핑 미연결 | [정본](../../../docs/requirements.md#resume-admission-policy)·[core](ready2go_voice/core/recovery_confirmation.py)·[Session](ready2go_voice/core/session.py) |
| 작업 종료 — E 현재 대상 후보 작성 | “종료/작업 종료해/이 작업 종료해/계속하지 말고 종료해” | 현재 질문·독립 새 녹음에서 명확한 종료만 내부 후보로 반환. 종료 부정과 단순 질문 거절을 구분 | 실제 C 종료 매핑 미연결. 종료 후보는 모션·잠금 해제·새 작업 허가가 아님 | [정본](../../../docs/requirements.md#resume-admission-policy)·[분류](ready2go_voice/core/recovery_confirmation.py) |
| 트레이 확인 confirm — E 개발 입력 경로 작성 | 현재 정상 미검출 질문 뒤 “네/아니요”, 첫 모호 답 뒤 한 번 재질문 | 현재 질문 등록 관측→실TTS 끝→새 녹음→SDK→STT→confirm 발신. 같은 실행의 검증 결과에서 복구 실패 안내 | place_test_input_topic 기본 빈 문자열. question/registered/result는 개발 가정이며 C 공개 계약 확정 아님. 서랍/관측 오류를 yes 성공으로 처리하지 않음. 실C·장치 검증 미완료 | [정본](../../../docs/requirements.md#verification-policy)·[교환](ready2go_voice/core/place_exchange.py)·[입력 경계](ready2go_voice/core/place_input.py) |

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
- `recording_mode: fixed`, `record_duration_sec: 5.0`, `timing_mode: commissioning`은 원본 기반 기능 시운전 기본입니다. 기본 VoiceNode는 SharedInput의 RawInputStream을 WakeAudio와 Recorder가 공유하고 audible cue/새 prepared 캡처 경계 뒤 동일 reader의 fixed 모드에서 기존 16kHz/int16/mono 80,000프레임만 수집합니다. shared_input 없이 만든 Recorder는 기존 sd.rec→sd.wait 경로를 사용합니다. `VOICE_MIC_DEVICE`→명시 input_device→16kHz 입력 자동 선택→기본 장치 순으로 한 번 정한 입력을 공유합니다. 시운전 API 상한은 STT/LLM 각각30초 제안값이고 늦은 결과 폐기·취소·평가 발행 금지는 유지합니다. commissioning의 API/녹음 설정은 실행·평가 모드 모두에서 사용할 수 있고, 평가 true는 계속 모든 발행을 차단합니다.
- 고정 녹음의 발화 종료·확인 지연은 null, latency_measurement=not_measured입니다. 녹음 완료 시각은 별도 recording_ended_*로 남기며 AC-INT-03 통과로 사용하지 않습니다. AC 준비는 recording_mode=silence/timing_mode=ac_budget로 설정하고 STT/LLM 상한·장치를 실측해 정합니다. 과거 설정에 신규 키가 없으면 기존 silence/ac_budget를 유지합니다.
- 무음 종료는 마지막 유성 프레임 시각을 기록합니다. `silence_sec` 대기·STT·LLM·TTS 준비를 [AC-INT-03](../../../docs/requirements.md#ac-int-03)의 예산에 포함합니다. `max_record_sec`는 보호 한도이며 고정 녹음 시간이 아닙니다. 한도 초과로 잘린 명령은 실행하지 않습니다.
- LLM 없는 경우 등록 별칭 규칙은 동작하지만 LLM 주 경로 및 자유 표현 완료를 의미하지 않습니다. faster-whisper 오프라인 STT는 현재 구현하지 않았습니다.

## 실행 준비와 의존성

| 구분 | 필요한 항목·확인 방법 |
|---|---|
| Python 기본 | 실제 core imports: jsonschema, PyYAML, numpy. `setup.py`에 선언 |
| Python API | `openai>=1,<3`, `langchain-openai>=0.2,<2`, `langchain-core>=0.3,<2` (`api` extra). 실제 SDK timeout/JSON 호출을 모의 검증 |
| Python 오디오 | sounddevice, openwakeword 0.6.0 (`audio` extra), 모델에 맞는 tflite_runtime 및 openwakeword 전처리 모델 자산. Python/CPU 호환 runtime은 배포 PC에서 확인 |
| ROS | rclpy, ament_index_python, std_msgs, ready2go_interfaces, ready2go_knowledge, ready2go_runner (`package.xml`; C 실패 factory/조사 함수 사용). 기존 Skill 메시지 생성 필요 |
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

[문서] `diagnostic_detail=true`에서는 민감정보를 제거한 상세 JSONL을 **YAML `diagnostic_file`의 E 로컬 파일**에 저장합니다. ROS 로그/콘솔과 tee는 비밀값을 필터한 STT 전사·최종 안내·대상·발행/수락 미확인·보류/오류 요약입니다. 새 진단 토픽이나 DB를 만들지 않습니다. 실행 모드에서는 기존 intent의 `source`에도 정보를 전달하지만 C 로그/run_id·D 화면 수신이 자동 연결되는 것은 아닙니다. 아래 부가 정보의 수신·의미는 C/D 협의 대상입니다.

- STT 원문, 실제 intent/targets, LLM 호출 여부·원문·검증 passed/failed/not_returned/not_called, 폴백 여부, 실행 허용/보류. 상세 JSONL에서 발행 여부는 최상위 `published`, intent는 `intent`입니다. 발행 여부는 진단 이벤트의 최상위 `published`이며 `/voice/intent`의 `source`에는 없습니다. `published=true`는 발행 호출 반환을 뜻하며 C 수신·실행 성공을 뜻하지 않습니다.
- 음성의 발화 종료 Unix/monotonic 시각, TTS 재생 시각, 확인 지연. TTS는 합성 시작/완료나 요청 접수가 아니라 **첫 PCM의 PortAudio DAC 재생 시각**을 장치 callback 정보로 기록합니다(`tts_start_basis=portaudio_first_dac`). 물리 스피커 청취 지연은 별도 확인해야 합니다.
- 실제 어댑터의 `tts_mock=false`와 테스트의 `tts_mock=true`를 구분합니다. 모의 시각·텍스트 입력으로 AC-INT-03 통과를 선언하지 않습니다. TTS 실패/장치 없음은 성공이나 실제 시작으로 기록하지 않습니다.

C #17 인계: 단일 find_item→태스크 수신, cancel/status, 모호/미지원 보류, 중복 요청, 확인 TTS/태스크 시작 책임, source→실행 로그/run_id 연결. voice는 nudge/pick을 직접 실행하지 않습니다. 현재 공통 pick은 탑뷰에서 `inspect_region`으로 새 scan을 받은 뒤 `pick_object`를 먼저 실행합니다. 움직임 전 `WALL_TOO_CLOSE` 거부일 때만 nudge→탑뷰→새 scan 관측 1회→그 scan의 새 target으로 다시 집기하며, 두 pick 모두 해당 관측의 전체 scan을 전달합니다. 직접 집기 성공에는 추가 nudge·재관측이 없습니다. 상세 호출 경로·관측 횟수는 [공통 pick 실행 연결](../../../docs/ontology.md#p1-공통-pick-실행-연결)을 참조하며, `nudge.target_after` 예상값은 집기에 사용하지 않습니다. 정식 find_item·점검용 p1_demo_eraser는 공통 robot_ontology.jsonld를 사용합니다. 실제 재관측·NO_PUSH_ACCESS·안전 종료 정합성 확인은 A/B/C/E 인계 사항입니다.

D #20 인계: [AC-INT-01–03](../../../docs/requirements.md#ac-int-01)·[음성 정책](../../../docs/requirements.md#voice-policy)에 연결해 평가자료 승인·문장별 정답을 먼저 고정하고 위 평가 모드에서 측정합니다. D 초안(JSON SHA256 `5995fc225c0a2cc78aa1c9264eee6a07518ad674ed4923763acf5017377aec84`)의 TC-008은 “지우개 찾아서 건네줘.”입니다. 당시 텍스트40개 회귀는 실제 음성 평가·자료 승인 완료를 대신하지 않습니다. 전체·종류별 정확도, LLM 호출 분모/검증 실패/폴백, STT·확인 지연·실행 시도를 분리해 기록하며 실제 측정은 남아 있습니다.

## P1 중단·오류 음성 안내 (#138)

[문서] 기존 `/runner/status`의 String JSON을 reliable/transient-local·depth10으로 읽기 전용 구독합니다. 상태 구독은 전용 `MutuallyExclusiveCallbackGroup`으로 동시 콜백 실행을 막고 text/action은 기존 Reentrant 그룹을 유지합니다. 수신 버퍼 확대와 콜백 상호 배제는 모든 입력 순서·누락 방지를 보장하지 않습니다. ROS 상태 콜백은 파싱·순수 정책·대기 슬롯 처리만 수행하며, 별도 안내 worker가 기존 TTS lock/취소/전체 timeout으로 재생합니다. 정지/복구 서비스나 로봇 상태/DB를 호출·변경하지 않으며 정지·취소 처리가 안내 재생을 기다리지 않습니다. 기존 취소/발행 보류·첫 DAC·Skill goal/result 계약을 유지합니다.

| 관측한 현재 코드/결과 | 고정 안내·시점 |
|---|---|
| 현재 `ESTOP` | “비상정지가 보고됐어요. 로봇의 실제 정지와 상태를 확인해 주세요.” |
| 현재/새 실패의 `OBJECT_DROPPED` | 놓침 보고·실제 정지와 물품 상태 확인. 코드만으로 실제 낙하·대상·회수 가능을 확답하지 않음 |
| 현재/새 실패의 `SENSOR_INVALID` | 센서값 이상 보고·실제 정지와 센서/물품 상태 확인. 빈손·낙하로 단정하지 않음 |
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

실제 음성 입력이 준비된 경우 기본 콘솔에는 웨이크 대기·감지, 비밀값을 필터한 한 줄 STT 전사, 요약된 해석 결과, 발행/보류 상태와 오류가 표시됩니다. 녹음 시작/완료, Whisper 요청, TTS 시작 같은 단계 이벤트는 콘솔에서 생략됩니다. `diagnostic_detail:=true`는 설정된 `diagnostic_file`에 이벤트별 최상위 필드를 가진 상세 JSONL을 저장하며 `tee`로 받은 콘솔 요약에는 전체 증빙이 없습니다. 상세 진단은 [음성·LLM 문서의 현재 진단 절](../../../docs/voice_llm.md#voice-diagnostics-current)을 참조하십시오.

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

[문서] `tts_engine: melotts` 실패는 준비/합성 실패로 표시되고 espeak로 자동 전환하지 않습니다. 기존 설정에 엔진 키가 없으면 espeak 호환 경로입니다. MeloTTS·음성 속도1.2는 사용자 확정입니다. CPU4스레드/준비상한60초/재생전체상한20초는 당시 실측 기반 **제안값 [팀 확정 필요]** 이력입니다. 현행 준비 예산은 위 #356 설명을 따르며 재생전체20초와 AC 모드의 `start_deadline` 3초는 별개입니다. 준비 때 등록 물품별 요청 확인·구체 질문과 P1 태스크의 “{{name|을}} 찾아 올게요”, “{{name|을}} 앞쪽 트레이에 놓았어요”, “{{name|을}} 찾지 못했어요”, 고정 “서랍을 닫았어요”, `clarify_prompts` 전체와 사용자 `tts_melotts_prefill_texts`를 중복 제거해 캐시에 넣고 완료 후에만 voice ready/웨이크 입력을 시작합니다. 목록 밖 문장은 최초 합성이 필요합니다. 캐시 키는 문장·모델 파일/리비전·소스/worker·의존성·speaker·속도·스레드를 반영합니다.

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
texts = prefill_texts(cfg, ontology['world']['items'].values(), reference_state=ontology['state'], places=ontology['world']['places'], item_names={k:v['name_ko'] for k,v in ontology['world']['items'].items()})
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

노드를 종료한 뒤 아래 **캐시 준비만** 먼저 수행합니다(마이크/API/출력 장치 사용 없음). 명시 prepare는 메모리 복사 설정의 준비 상한을 **3600초**로 덮습니다. 기존 120초 선택은 과거 이력이며 현행 명령의 상한이 아닙니다. 일반 노드는 사용 YAML의 준비 상한을 따릅니다(패키지 기본600초, 기존 local 명시60초는 그대로). 3600초 이내 준비 성공이나 일반 노드가 자기 예산 안에 ready가 되는지는 실제 PC에서 확인해야 하며 보장하지 않습니다. 재생전체20초·AC3초 예산은 변경하지 않습니다. 실패하면 상한/worker.log/환경을 점검하고 일반 노드를 시작하지 않습니다. 완료 뒤 같은 worker·속도·모델·설정으로 일반 노드를 시작합니다. 노드는 시작마다 `prepare()`로 모델 로딩과 캐시 확인을 수행하지만, 같은 캐시 키의 디스크 WAV는 재사용하고 없거나 키가 변경된 문장만 합성합니다. 모델 로딩·캐시 확인 비용이 없어지는 것은 아닙니다.

```bash
bash ros2_ws/src/ready2go_voice/tools/voice_trial.sh prepare
```

이 준비 명령은 위 live 명령과 같은 시험 복사/선택 함수를 사용하고 최신 준비 성공 기록을 남깁니다. 실패하면 live를 시작하지 않습니다. 원본 local의 일반 startup 명시값은 유지하며, prepare의3600초는 live에 넘기지 않습니다.


**3. 완료 로그·실패 원인 확인**

`MeloTTS 준비 완료 (고정 안내 캐시 완료)`와 `전체 캐시 준비 완료(초): ...`를 확인하고, 위에서 보존한 **종료 코드가 0**일 때만 다음 단계로 진행합니다. 완료는 현재 설정의 모델과 전체 고정 문장 합성/캐시 조회를 뜻하며, 물리 재생이나 AC-INT-03 3초 달성은 뜻하지 않습니다. 준비 시간과 사용 설정을 #138 운용 기록에 남기십시오.

캐시는 `tts_melotts_assets/wav_cache`, 로그는 같은 assets의 `worker.log`입니다(기본 `models/tts/melotts/wav_cache`, `models/tts/melotts/worker.log`). 오래된 키의 WAV도 남을 수 있으므로 파일 개수만으로 현재 준비 성공을 판정하지 않습니다. 기본 경로의 최근 로그는 다음처럼 읽습니다. assets를 변경했다면 1단계에 출력된 경로를 사용하십시오.

```bash
tail -n 80 models/tts/melotts/worker.log
```

- `MELOTTS_PREPARE_TIMEOUT`/`MELOTTS_PREPARE_FAILED`: worker 로그의 실제 원인과 해당 PC 준비 시간을 확인합니다. 명시 prepare의3600초 또는 일반 노드가 사용한 YAML 상한(패키지600초/local 명시값) 중 어느 경로에서 실패했는지와 실제 경과 시간을 확인합니다. 사전 준비를 다시 실행할 때는 노드를 먼저 종료합니다. 일반 노드를 반복 재시작하며 캐시를 쌓거나 일반 YAML/AC3초 예산을 임의로 늘리지 않습니다.
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
ontology = load(cfg['ontology_file'])
cfg['_tts_prefill_texts'] = prefill_texts(cfg, ontology['world']['items'].values(), reference_state=ontology['state'], places=ontology['world']['places'], item_names={k:v['name_ko'] for k,v in ontology['world']['items'].items()})
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

[문서] 사용자 확정 웨이크 기준은 `wake_threshold: 0.7`이며 기존 **점수 > 기준** 비교를 유지합니다(정확히0.7은 감지하지 않음). 기본 녹음은 동일 SharedInput reader의 고정5초/16kHz/int16/mono입니다. 공유 입력 없는 standalone Recorder는 sd.rec→sd.wait를 유지합니다. cue/guard·전송 구간 trim은 위 voice_flow 시험 옵션이며 기본모드/임계값을 확정 변경하지 않습니다. 고정 녹음 완료 뒤 설치된 openwakeword의 Silero VAD를 로컬로 실행합니다. `speech_vad_model: null`은 패키지의 `resources/models/silero_vad.onnx` 자산을 뜻하며 다운로드하지 않습니다. 명시 경로도 설정할 수 있습니다.

[제안] 30ms 프레임의 VAD 점수≥`speech_vad_threshold: 0.5`와 RMS≥`speech_rms`를 함께 만족하는 연속 구간≥`speech_min_voiced_sec: 0.15`를 찾습니다. 두 VAD 튜닝값은 **[팀 확정 필요]**입니다. 전체5초 평균으로 짧은 요청을 버리지 않습니다. 무발화·모델 없음/오류·취소는 STT/LLM 호출 및 발행을 보류하며, 무발화는 `record_error=NO_SPEECH`, LLM `not_called`로 남습니다. 기본은 발화로 판정한5초 전체 WAV를 STT에 보냅니다. trim 옵션은 VAD 판정 입력을 유지한 채 전송 구간만 비교하고 원래 녹음 시각을 보존합니다. fixed의 실제 발화 종료/확인 지연은 계속 null/not_measured입니다.

[문서] `clarify_prompts`는 기본/실패 안내입니다. #194 구현은 의미 검증된 내부 LLM 문장을 유지하고 대상·판정에 맞지 않는 후보만 대체하며 최종 콘솔/TTS 입력을 일치시킵니다. 현재 대상의 구체 질문과 실제 TTS 완료 뒤의 유효한 답/대상 정정은 `Conversation`에서 한 번 처리합니다. 정책 정본은 [음성 정책](../../../docs/requirements.md#voice-policy)이며 D 정답표 반영·실음성 평가는 별도 인계입니다. 시작 캐시는 합성만 하며 과거 질문 권한을 복원하지 않습니다.

기본 콘솔은 비밀값을 필터한 한 줄 STT 전사·최종 안내·intent/target·발행/수락 미확인·보류/오류와 간결한 준비/재생 정보를 표시합니다. 상세 단계 시각/LLM 원문은 `diagnostic_detail=true`의 로컬 JSONL에서 확인합니다.

[실측: 로컬 합성 입력] 실제 Silero는 무음·미세/큰 임의 잡음·200Hz 정현파를 무발화로, 기존 MeloTTS 생성 시험 WAV를 발화로 판정했습니다. 새 질문 사전캐시 준비36.26초, 일반 고정 clarify의 캐시 응답5~7ms(캐시 히트)였습니다. 마이크/STT/LLM/실제 첫DAC 지연 측정이 아닙니다. 90ms 순간 구간 거절·180ms 구간 허용은 모의 검사입니다. **180ms 이상의 웨이크 잔음도 통과할 수 있으며**, 실제 마이크에서 무발화/짧은 정상 명령·오탐을 재시험해야 합니다.

재실행은 위 “사용자 PC 시운전 명령”을 사용합니다. 웨이크 후 아무 말도 하지 않는 시험에서는 Whisper 요청 없이 무발화 안내·발행 보류가 나오는지, 짧은 정상 요청은 통과하는지 확인하십시오. LLM 질문은 검증 후 최종 문장·실제 TTS 입력과 상세 JSONL의 원본/대체 사유·캐시 시간을 대조하십시오. 실제40음성·3초·청취 품질·C/D 연결은 미완료입니다.

## P2 복구 후 재개 확인 — 내부 준비

[문서] `core/recovery_confirmation.py`는 E 내부 정책 구현이며 현재 Session·SafetyExchange·VoiceNode의 질문/독립 제어 작업에 연결돼 있습니다. 등록·TTS 완료·새 녹음·SDK 접수와 작업 보존 경계는 모의로 확인했습니다. 독립 stop은 처리/TTS 중에도 별도 녹음·STT를 사용하고, 일반 웨이크 입력의 점유 제한은 유지합니다. 실제 C 생산자·B 증빙·공개 안전 매핑과 실장치 복구/재개는 미연결·미검증입니다. [요구사항 정본](../../../docs/requirements.md#fr-saf-01)·[처리 경계](../../../docs/voice_llm.md#p2-safety-voice)·[계약안](../../../docs/interfaces.md#p2-safety-proposal)을 확인하십시오. 운영 연결의 책임·검증 기준은 [FR-SAF-03](../../../docs/requirements.md#fr-saf-03)을 참조합니다. #165 병합과 실제 마이크/API·장치 복구/재개 검증은 구분합니다.

## #43·#152 내부 확인 정책 — 운영 미연결

[문서: E 통합 준비·검증 이력] VoiceNode의 질문 작업·Session.confirm_audio/safety_audio·SafetyExchange 및 선정 목표 상관 경로를 작성했습니다. [호출별 현황](../../../docs/voice_llm.md#p2-safety-voice)을 참조하십시오. 개발 typed 입력은 C 공개 규약 확정이나 실제 생산자 증거가 아닙니다. 기존 직접510/skip9·격리ROS48, 원격73ba549의 직접41·38800a8 CI2632/skip41, 로컬12e0c29의 리뷰 및940c1f83 종료34는 각 이전SHA/환경의 이력입니다. 이번 통합의 최종SHA 전체CI는 아직 미실행이며 결과를 합산하거나 전용하지 않습니다. 상세한 실패/부분 검사/현재 통합 근거는 [E CURRENT](../../../practice/E/CURRENT.md#pr227-final-integration-20261012-01)를 참조하십시오. 실제 C/B 운영·음성 장치·실물 수용은 미검증입니다.

[문서: #43 독립 준비] [core/place_exchange.py](ready2go_voice/core/place_exchange.py)는 기존 place 정책 위에 질문 식별·메시지 차수 변환·asked/응답 후보와 일회성 녹음 예약을 제공합니다. [VoiceSession.confirm_audio](ready2go_voice/core/session.py)는 Recording·Whisper의 SDK 직전 접수·DeadlineCall을 재사용하며 LLM 없이 분류합니다. [직접 회귀](test/test_place_exchange.py)는 새 교환과 STT 경계를 모의로 확인합니다. 현재 노드 호출·같은 실행의 개발 입력 결과 안내를 작성했으며 C 등록 증빙·공통 계약·실제 단계 결과 매핑은 미연결입니다. 반환된 메시지는 운영 승인이나 C 최종 판정이 아닙니다. 구현·선행 조건은 [상세 설명](../../../docs/voice_llm.md#p2-safety-voice)에 기록합니다.

[문서] [사후 검증 정본](../../../docs/requirements.md#verification-policy)·[재개 접수 정본](../../../docs/requirements.md#resume-admission-policy)을 기준으로 core/skill_confirmation.py와 recovery_confirmation.py를 준비합니다. pick/place 판정은 E 내부 후보와 비전/사용자 근거 분류만 반환하고 C effect/로그·성공 안내·모션을 실행하지 않습니다. place 질문에는 이번 run/step의 기대물품별 개수·총개수·목적지를 포함하며 모호 응답은 설정된 재확인 한도 안에서 새 질문 객체로 분리합니다. 같은 run/step의 중복 시작과 종료 후 재시작으로 횟수를 초기화하지 않으며 실패 절차는 재사용하지 않습니다. 구간값·재질문 상한은 `params/voice.yaml`에서 읽고 null이면 보류합니다. 서랍 top view 관측과 C 최종 판정은 이 core의 운영 구현에 포함되지 않습니다.

[문서] recovery 정책은 boot 변경·동일 run/halt의 seq·질문/TTS 완료·녹음 시작/끝·SDK 직전 접수·등록 ACK 뒤 TTS 시작·별도 결과 만료·일회성·재정지·질문 거절·명시 작업 종료를 분리합니다. 일반 cancel은 대상 보존이며 포기와 다르고, 질문 실패/거절도 work를 보존합니다. 독립 요청은 고유 ID·새 녹음·STT 처리 구간·전체 구간·현재 등록 확인을 검사합니다. E 재기동 후 새 C 상태를 확인하고 Runner boot 변경/현재 C 완료는 보존 대상을 폐기합니다. 현재 P1 Session은 WhisperSTT의 optional `before_request` callback을 연결해 실제 SDK 호출 직전 `whisper_sdk_request.requested_monotonic` 진단 이벤트를 기록합니다. 기존 progress `whisper_requested`는 그보다 앞선 진행 표시이므로 SDK 접수 증빙으로 쓰지 않습니다. `interpretation.intent.source.recording_ended_monotonic`과 내부 `interpretation.intent._voice.recording_started_monotonic`·`interpretation.intent._voice.recording_ended_monotonic`에 기록됩니다. 필드가 누락되거나 null이면 유효한 녹음 증빙으로 추정하지 않습니다. P1 시각 진단 자체는 P2 접수 권한이 아닙니다. 별도 Session.safety_audio·VoiceNode typed 호출에서 P2 정책을 연결하도록 작성했으며 실제 C 공개 입력/후보 매핑은 미연결입니다. 독립 stop_audio는 복구/재개 접수와 구분됩니다. 실제 TTS 종료는 PortAudio 완료 증빙이 필요합니다. B unknown이나 처리 예산 미정일 때 운영 재개 요청을 만들지 않습니다. 같은 사건의 최신 신뢰 의미 충돌은 seq 하한을 보존해 과거 상태/ACK의 재확인을 차단합니다. 충돌 상태 자체를 실행 대상으로 채택하지 않습니다.

설정 원본 [params/voice.yaml](params/voice.yaml)의 승인 내부값과 미정 null을 구분하십시오. E의 두 등록/TTS 전용 추가 타이머는 제거했으며 기존 등록 ACK·질문 유효 기한·음성 TTS timeout은 유지합니다. 동일 요청의 녹음/분류와 정상 seq에서의 재사용, 실제 상태 변경 시 무효화는 [구현 설명](../../../docs/voice_llm.md#p2-safety-voice)을 참조하십시오. C 기한과 ACK의 실제 E 입력 매핑은 미완료이며, E 질문 작업의 재생 완료 증빙 경로는 작성·모의 검증했지만 실제 DAC 완료 callback/장치 재생은 미검증입니다. 제거된 `place_answer_timeout_sec`는 설정 오류로 거절하며 접수와 STT 키를 각각 사용합니다. P1 STT/API/AC 예산을 새 정책의 처리 예산으로 복사하지 않습니다. 미승인 wire enum/등록 ACK 형식/프로세스별 clock 대응과 C hold·B 확인 모드·관측은 [회신안·인계](../../../docs/voice_llm.md)에서 협의하며 미승인 wire/운영 adapter는 추가하지 않습니다. 이 준비는 기존 지원 명령 표의 P2 미연결 상태를 바꾸지 않습니다.


## P2 선정 목표 — E 발신 경로 개발

[문서] [FR-INT-02](../../../docs/requirements.md#fr-int-02)·[FR-PLN-02](../../../docs/requirements.md#fr-pln-02)·[FR-ONT-02](../../../docs/requirements.md#fr-ont-02)를 참조하십시오. 기본 `p2_goal_enabled=false`는 기존 P1 경로를 유지합니다. 옵트인 시 `params/voice.yaml`의 선정 목록·현재 world·명시 발화를 검증하고 기존 계약의 목표 후보만 반환합니다. 부정·충돌·범위 밖·LLM 실패는 실행 폴백을 하지 않습니다. 검증된 목표 문장은 현재 요청의 accept_text로 준비하며 E가 수락 전에 중복 재생하지 않습니다. 실제 수락된 현재 요청/run의 기존 speak 경로에서 한 번만 재생하도록 작성했습니다. 계약07 수락 상관은 goals echo 없이 현재 요청 ID·intent·run 결정·run ID를 확인하며, 등록 payload를 보존합니다. 같은 요청의 run/intent/결정 충돌은 연결을 무효화합니다. 실제 C 매핑과 실행 검증은 미완료입니다. Session은 선정 목표·요청 상관의 두 명시 opt-in과 평가/중복 검사를 적용하고 노드는 현재 C 연결을 추가 확인합니다. 실제 플래너/C 전달·복합 동작·실물 lip_balm/eraser 파지 확인은 후속입니다.


## #78 모션 차단 안내·E 내부 후보 (운영 미연결)

[문서] 정책은 [모션 차단·놓침 후 새 실행 정본](../../../docs/requirements.md#halt-motion-policy)·[일반 재개 접수](../../../docs/requirements.md#resume-admission-policy)를 참조하십시오. 기존 상태 구독은 위의 원인별 고정 미확인 안내를 사용합니다. `phase=halted`를 실제 정지 증명으로 쓰거나 `task_id`로 지우개를 추론하지 않습니다.

[문서·코드 대조: 2026-10-10] C의 [PR #202](https://github.com/Jik-Kim/ready2go/pull/202)는 main에 병합돼 놓침·센서 이상에 `ABORTED`·잠금, 후속 모션/finally 제한·새 요청 거절과 재개 보존 제외를 구현했습니다. B handover place의 센서 이상/놓침 코드 혼용·보유 확실성·실제 정지/신선 관측, C 관측 기반 상태 동기화·잠금 해제·명시적 새 run 운영 연결은 후속입니다. `reset_state()`는 시작 스냅샷 복원이며 잠금 해제·실제 상태 확인이 아닙니다. 남은 B/C 협의·E 포함 2인 계약 승인·운영 adapter·실물 AC를 C 코드 병합이나 E 내부 모의 통과로 대신하지 않습니다.

[구현: ROS 비의존 준비] `core/recovery_confirmation.py`의 `notice(HaltNoticeEvidence)`·`NewStartEvidence/NewStartCandidate`는 trusted B/C 관측을 가정한 내부 후보입니다. 현재 사건과 실제 정지/신선도/낙하/대상 근거가 있을 때만 대상별 복원 안내를 만들며, 과거/미확인 입력에는 회수를 지시하지 않습니다. place 놓침에 기존 `Evidence`/“재개해”를 주면 재개 후보를 내지 않고, 같은 사건의 실행 종료·복원/실제 상태 검사·C 동기화·B/C 조건을 모두 확인한 뒤 명시적 새 시작 응답에만 다른 자료형의 후보를 냅니다. TTS 실패·재정지 뒤 기존 run의 재개 우회도 거절합니다. 일반 cancel v1은 유지하고 센서 이상 재개에는 정상화 증빙을 추가 검사합니다. 현재 E node의 typed 안전 입력·질문 작업은 이 복구 정책을 호출하도록 작성했습니다. 실제 C/B 입력과 공개 규약 매핑은 미연결이며 실행 검증은 후속입니다.

[문서] 고정 미확인 안내는 기존 `STATUS_PROMPTS`→`tts_prefill.prefill_texts`의 bounded 필수 목록에 포함됩니다. 대상별 복구 안내·새 시작 질문은 운영 prefill/재생에 연결하지 않았으며 Melo 설정·worker·기존 WAV를 변경하지 않습니다. 직접 관련 모의 검사는 `test_runner_notice.py`·`test_recovery_confirmation.py`와 기존 #152 v1 `test_e_verification_policy.py`입니다. 실제 API/마이크/STT/TTS 합성·로봇·글로벌 차단/실물 AC를 검증한 결과가 아닙니다. B/C 선행·계약 승인·인계 상태는 [기술 문서](../../../docs/voice_llm.md#78-e-안내새-실행-후보-준비)와 [#196](https://github.com/Jik-Kim/ready2go/issues/196)을 확인하십시오.

## #194 현재 질문·응답·진단과 #138 캐시 / #195 녹음 비교

[문서] 의미·정책은 [voice-policy](../../../docs/requirements.md#voice-policy), 실제 내부 필드/경계·로그/캐시·C/D 인계·녹음 비교는 [voice_llm.md](../../../docs/voice_llm.md#194-요청질문진단-연결과-138-bounded-캐시)를 참조합니다. `core/conversation.py`는 P1 질문의 로컬 권한, `core/response.py`는 최종 문장 검사, `core/diagnostics.py`는 비동기 상세 JSONL입니다. 내부 response_text/rejection_reason/_voice는 공개 wire 신규 필드가 아니고 `/voice/intent`의 새 필드로 발행하지 않습니다. parser는 사유를 검증 후 `_voice.reason`으로만 옮기며 node는 `_voice`를 제외합니다. 기존 source 소비 필드와 원본 `source.llm_raw`는 유지합니다. 실제 `LangChainIntent.schema`에 맞는 unknown/빈 targets/내부 사유로 물품 미등록과 요청 미지원을 구분하며, 미등록 target 예외 시험만으로 정상 LLM 안내 연결을 확인했다고 보고하지 않습니다.

[문서] 예: “망치 가져오라고 말했잖아”/“엄마가 망치 가져오라고 했어”는 정상 LLM 요청 의미와 등록키 검증 경로입니다. “망치”의 구체 질문 TTS 완료 후 “응/맞아/응 맞아/네 맞아요/어어/그걸로” 또는 “렌치/아니 렌치야”는 유효 현재 문맥에서 한 번 결합합니다. 번역/부정/제외·문맥 없는 응답·만료·재시작·취소·관측된 running/잠금은 새 실행을 만들지 않습니다. 유효한 질문 없는 “응/맞아/그걸로”는 LLM 호출 전 clarify/빈 targets로 대상 재확인을 안내하고, 성공 재생 뒤 새 질문에도 이전 물품을 복원하지 않습니다. “립밤 되나?”는 등록과 실행가능 미확인 안내만 하며 자동 실행하지 않습니다. 문장 검증과 실제 C 수락/동작 성공은 다릅니다.

[문서] YAML의 `dialogue_timeout_sec`·진단 경로/회전/큐·선준비 문장수/길이/UTF-8 용량·빈번 문장 기록/횟수는 제안/미확정 설정입니다. 일반 질문 시간은 P2 #152 정책과 독립이고 null이면 후속 결합을 보류합니다. 실패 후 질문 답을 자동 재시도하지 않고 새 독립 요청을 요구합니다. 상세파일은 비밀값을 필터한 원본 LLM/검증 사유/최종 문장/TTS/캐시/시각·로컬 요청/질문 ID를 남기며 파일/회전/큐/필터 오류는 경고합니다. 큐 포화·종료 정체 시 증빙 저장 미확인을 보고하며 음성/취소를 막지 않습니다. 파일은 설정 크기와 백업 수로 회전하며 큰 단일 원본은 보존 후 다음 기록에서 회전합니다. tee 요약 파일·C 실행 DB·worker.log는 별도 자료입니다.

[문서] 초기 필수 문장과 두 번 이상 성공 재생된 검증 문장의 선택 이력을 구분합니다. `models/tts/melotts/validated_phrases.json`(실제 assets 설정 기준)은 bounded 선택 기록이며 기존 WAV 저장 기능을 중복 구현하지 않았습니다. 설정 한도를 넘는 필수 목록은 준비 실패, 이력 파일 오류는 경고 후 필수만 준비합니다. worker 시간 진단 코드 변경도 기존 identity 무효화에 포함되므로 첫 재합성이 필요할 수 있습니다. 모델 로딩·선준비·전체 준비, 첫 합성/캐시 조회·첫 DAC/재생 시간은 별도 기록이고 실제 이번 합성은 미측정입니다. 이 진단을 보완할 당시 Melo1.2·노드 startup60·prepare120·AC3초는 유지했습니다. 현행 준비 예산은 위 #356 설명을 따르며 Melo1.2·AC3초는 별개입니다.

[미연결/인계] C 수락/거절의 요청 상관 식별·순서·실패/timeout/취소 책임, D #20 변경 사례/정답표 검토는 [#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 협의합니다. C/D 파일과 새 wire는 변경하지 않았고 E 포함2명 승인·스키마/예시/ICD 반영 전 연결하지 않습니다. #23의 과거 결과/미달은 보존하며 이 추적 위치 전환이 P1 완료/AC 면제를 뜻하지 않습니다. 녹음 비교 [#195](https://github.com/Jik-Kim/ready2go/issues/195)는 실제 시험 계획/기존 코드·모의 검토로 기본 fixed5/commissioning·무음/VAD 임계값을 바꾸지 않았습니다. 실제 웨이크·녹음/API·합성/청취·C 수락·로봇 AC는 이번 범위에서 미시험입니다.


## 요청 발행·수락·완료 준비 — #196

[구현] E의 검증 payload 발행 경로·수락 run 상관·같은 run 완료 안내 로직은 [기술 문서](../../../docs/voice_llm.md#acceptance-tts-preparation)를 참조하십시오. 의미·책임은 [정본](../../../docs/requirements.md#acceptance-tts-policy), 필드는 [공동 ICD](../../../docs/interfaces.md#request-run-contract)의 원본 링크를 따릅니다. `request_run_enabled: false`가 기본이며 P1 확인 TTS와 목표 발행 차단을 유지합니다.

[문서: 현재 연결 경계] bind_request_source에 실제 C 생산자·재기동 확인 함수를 연결해야 발신/수락/완료/speak를 진행합니다. 매 호출 시 현재 연결을 확인하며 실패하면 상관을 폐기합니다. 기본 미설치 상태나 설정만 변경한 상태는 보류합니다. Jazzy metadata와 graph는 생산자 증빙이 아닙니다. 실제 C 검사 구현과 first gate 통합·실물 검증은 미완료입니다.

[검증 범위] 검증된 C 연결을 모의 주입해 trusted 큐 ID/문장 발행, 사전 TTS 제거, 수락 run·최종 결과 상관, 중복·빠른 완료·수락 대기 중 후속 요청 차단과 종료 후 새 요청을 시험했습니다. no-op/mock PCM 반환은 성공하지 않습니다. 실제 Jazzy callback metadata에는 개별 표본 publisher_gid가 없음을 확인했고 graph를 대체 증거로 쓰지 않았습니다. C 실제 수신·첫 동작 게이트·재기동 증거·실음성/로봇 AC는 미완료입니다.

[실측: P2 호출 경계 모의] 변경 관련 직접8파일 검사510 passed/9 skipped와 기존 격리 ROS test_node.py48 passed를 확인했습니다. 신규 [정지/공유 입력 시험](test/test_stop_audio.py)·[복구 교환 시험](test/test_safety_exchange.py)은 기존 [실제 노드 메서드 fixture](test/test_voice_ux_node.py)를 재사용합니다. 등록/TTS 증빙/typed C 입력은 모의 가정이며 실제 음향/관측 증거가 아닙니다. safety_audio stop의 source 누락으로 발신이 실패하던 결함을 수정했고, 기존 요청/질문/goal·평가/세대/일회성·old callback 반례를 확인했습니다. 상세 대상·환경·skip·미연결은 [E CURRENT](../../../practice/E/CURRENT.md#p2-모의회귀-검증--e-p2-verify-20261011-01)에 기록했습니다. 전체 head 로컬 CI와 실C/API/마이크/로봇 AC는 별도입니다.

[문서·코드 대조: #187 독립 입력] `SharedInput`은 물리 RawInputStream 하나에서 프레임을 읽고 일반 웨이크/고정 녹음·질문·정지 소비자를 분리합니다. 새 소비자에게 과거 프레임을 재전송하지 않고, 기존 최대 녹음량을 넘긴 소비자는 오류로 폐기합니다. `Recorder.record`의 기존 RMS·무음 종료·음성 시작/최대 길이 보호를 정지 입력에 재사용하며 일반 fixed 길이/후처리 VAD·설정값은 유지합니다. 공유 입력의 fixed는 같은 프레임에서 기존 길이만 수집하고, 공유 입력을 쓰지 않는 Recorder의 sd.rec→sd.wait 경로도 유지합니다. cancel/close는 소비자의 대기와 물리 입력을 종료합니다.

[문서·코드 대조: 정지 한계] `Session.stop_audio`는 새 녹음과 현재 세대를 검사하고 일반 STT/LLM/TTS 완료를 기다리지 않는 별도 DeadlineCall에서 현재 Whisper를 호출합니다. 기존 정확 문구 분류로 부정·인용·전언·모호 표현을 보류하고, 녹음과 겹친 실제 재생 문구에 포함된 stop 텍스트도 보류합니다. 이 문구 대조는 음향 echo 제거가 아니며 같은 문구의 실제 사용자 발화도 보수적으로 보류할 수 있습니다. 처리/TTS/질문·Runner 실행/잠김 동안의 독립 청취를 작성한 상태로, 클라우드 지연/실패·자기 TTS 변형/잔음·작은 발화·동시 마이크 소비·실제 정지 AC는 후속 시험 대상입니다. 네트워크 비의존 정지나 B/C의 물리 정지 증빙으로 보고하지 않습니다. 무음은 STT를 호출하지 않고 다른 명령은 독립 stop 경로에서 LLM으로 넘기지 않습니다.

[후속 준비] `PlaceConfirmation.asked`의 최초 전체 구간·재질문은 [정본](../../../docs/requirements.md#verification-policy)을 참조합니다. E 내부 typed 호출과 질문/STT·후보 경로는 작성했으며, 실제 C ACK·confirm 질문/답 수신·단계별 post_check·복구/재개 공개 규약 매핑은 미연결입니다. 기존 녹음/SDK 진단과 문장 캐시를 보존했습니다.
