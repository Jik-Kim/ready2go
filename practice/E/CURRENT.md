# CURRENT — E 고희태


- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장)
- **현재 Phase**: P2 준비(P1 통합 종료 유지). 목표·정책·책임·완료 기준은 [requirements.md](../../docs/requirements.md#phase-scope)를 참조합니다.
- **최종 갱신**: 2026-10-12

## #227 리뷰 수정 준비 — 독립 worktree, push 보류

- [문서·코드] 계약07 상태의 `Decision.summary`에는 목표 본문 `goals`가 없으므로 `achieve_goal` 상관은 승인된 `request_id`·`run_id`와 intent/decision을 사용하도록 맞췄습니다. `find_item`은 기존 targets 대조를 유지합니다. C 계약·운영 mapper는 변경하지 않았습니다.
- [실측: 관련 회귀·CI] 목표 상태에 `goals` echo가 없는 수락·동일 run 완료와 request ID/intent/run ID 반례, AUDIO_OVERFLOW 뒤 새 capture에서 정지 발신하는 경로를 포함해 관련 시험 41건이 통과했습니다. head `73ba549` 전체 로컬 CI는 시도했으나 core는 격리 pip 설치에서 DNS 실패, colcon build는 Docker socket 권한 거부로 미완료이며 compose real/sim/dev 설정 검사는 통과했습니다(`ci_local.sh@aa5aa0f`).
- [문서] E 경로를 정적 확인만 된 상태로 표현하던 문구를 기존 모의·격리 ROS 이력 및 이번 직접 회귀 결과와 맞췄습니다. 실제 C 운영 연결·마이크/장치·DAC 완료 callback·실물 AC는 미검증으로 유지합니다.
- [인계] 별도 `codex/issue-227-review-fix` worktree(`/tmp/ready2go-issue227-review`)에서 최신 main을 PR 기준선에 병합해 준비 중입니다. 동시 E 세션의 같은 branch/files 작업은 손대지 않았습니다. 사용자가 push 보류를 지정했으므로 원격 PR 갱신은 하지 않습니다.

## E 문서 정합성 정정 — 계약07/운영 연결·오디오 경계

- [문서·코드] #221은 main에 병합됐고 C 소유 상태 예시·Runner 설명·ICD 구간과 원본 검토를 확인했습니다. E의 payload 후보·RequestRun 상관 로직은 #225에 포함됐지만 실제 C 런타임 수신·producer/source mapper·수락 후 첫 동작 연결은 미완료입니다. 실제 VoiceNode는 mapper 미설치 시 발행·speak 수락을 보류하며 설정 기본값은 `false`입니다.
- [문서·코드] #227의 기본 VoiceNode 입력은 SharedInput의 RawInputStream을 WakeAudio·Recorder가 공유하고 fixed 녹음은 공유 프레임에서 기존 길이만 수집합니다. shared_input 없는 Recorder의 sd.rec→sd.wait 호환 경로도 구분합니다. fixed 5초·commissioning·임계값은 유지합니다.
- [문서] 이 정합성 수정은 승인된 계약07 스키마/예시나 C 담당 구간을 수정하지 않습니다. 기준은 [FR-INT-02/03](../../docs/requirements.md#fr-int-02)·[FR-LOG-02](../../docs/requirements.md#fr-log-02)·[수락 TTS 정책](../../docs/requirements.md#acceptance-tts-policy)이며 policy/Phase/AC는 정본을 참조합니다.
- [문서: 미검증] 실제 C producer/source mapper·운영 수락·첫 동작 연결은 미검증입니다. 최종 head 전체 로컬 CI 결과는 이 PR 본문에 기록합니다.

## E 문서 정합성 정정 — 계약07/공유 입력 경계

- [문서·코드] #221의 C 소유 상태 예시·Runner 설명·ICD 구간 합류 및 C 원본 검토를 E 계약 검토/PR 병합·실제 C 런타임 수신/생산자 연결 미완료와 구분합니다. #225/#227의 E payload 후보와 RequestRun 상관 로직도 실제 C source mapper 미설치·request_run_enabled 기본 false 상태를 넘지 않습니다.
- [문서·코드] 기본 VoiceNode는 SharedInput RawInputStream을 WakeAudio와 Recorder가 공유하며 fixed 녹음은 기존 5초 프레임만 수집합니다. shared_input 없는 Recorder의 sd.rec→sd.wait 경로는 호환용으로 유지됩니다. fixed5초·commissioning·임계값은 변경하지 않습니다.
- [문서] 기준은 [FR-INT-01–03](../../docs/requirements.md#fr-int-01)·[FR-LOG-02](../../docs/requirements.md#fr-log-02)·[수락 TTS 정책](../../docs/requirements.md#acceptance-tts-policy) 및 [FR-SAF-01/AC-SAF-02](../../docs/requirements.md#fr-saf-01)입니다. 이번 수정은 정책·Phase·계약·C 담당 파일을 바꾸지 않습니다.
- [문서: 미검증] 실제 C 수신/운영 연결·마이크/장치·Whisper·실음성·실물 AC는 확인하지 않았습니다. 최종 head 전체 로컬 CI 결과는 이 PR 본문에 기록합니다.

## P2 모의·회귀 검증 — E-P2-VERIFY-20261011-01

- [문서: 기준·범위] 기존 `codex/e-tray-confirm-integration-20261011`/`2808d2460d3102915bd72d00d3716d5f685e2e47` 작성분을 검증했습니다. 지시 세션의 개발→모의/단위/격리 ROS→실C 통합 순서를 적용했으며 새 branch/worktree/서비스/의존성·임계값·공통 계약·타 담당 파일은 추가하지 않았습니다. 신규 test_stop_audio.py·test_safety_exchange.py는 기존 노드 AST fixture와 typed 입력을 재사용하는 시험이고 실제 C/B 증빙이 아닙니다.
- [실측: 재현 결함 1건] Session.safety_audio의 질문 stop 결과에 source가 없어 실제 `_safety_result_locked → _stop_locked → should_publish`에서 KeyError로 cancel 발신이 실패했습니다. 실제 audio/STT 문장·LLM 미사용·실행 허가 false인 기존 source를 붙여 최소 수정하고 실제 Session/노드 호출 회귀로 발신을 확인했습니다. 재개/정지 wire나 증빙 필드는 추가하지 않았습니다.
- [문서: 시험 정합성] 선정5종/goal 응답의 과거 ‘내부 평가’ 기대6건은 승인된 ‘목표 요청’ 안내에 맞췄으며 실행결함 수로 합산하지 않습니다. 낮은/같은 seq의 권한 보존과 동일 사건의 최신 의미 충돌/하한 차단을 구분해 가정을 바로잡았습니다. 공유 입력의 새로운 물리 프레임만 overflow 반례에 사용하고, stop_event를 해제한 뒤 old cancel/generation이 추가 발신되지 않는지 검사했습니다. 기존 listener/준비 순서/ESTOP 안내 fixture도 현재 원본과 대조했습니다.
- [실측: 직접 검사] Python3.12 CI venv에서 test_safety_exchange·test_stop_audio·test_voice_ux_node·test_audio_tts·test_request_run·test_place_exchange·test_intent·test_voice_ux **510 passed, 9 skipped**, 종료0입니다. skip9는 venv의 sounddevice 미설치로 기존 오디오 fixture가 수집하지 못한 검사이며 설치하지 않았습니다. 부모 지적 후 종료 조건에 의존하지 않도록 보완한 stop 시험은 **15 passed**입니다. 일반 STT/TTS 점유 중 실제 stop listener 진입, 소비자 cutoff/ADC/형식/overflow/취소/닫기, source/eval·중복, goal payload/current source/run/일회 재생·no-op 차단, place 등록/TTS 완료/새 SDK 답/모호 재질문/동일 실행 검증 결과, safety ACK/현재 work/독립 발화/거절/종료/옛 callback을 확인했습니다.
- [실측: 격리 ROS] Jazzy+기존 install overlay에서 PYTHONPATH를 현재 편집 소스로 지정했고 VoiceNode.__file__의 실제 source 경로를 확인했습니다. 기존 test_node.py **48 passed**, 종료0입니다. 기존 domain166/167·tmp 로그·audio_enabled=false·FakeTTS/API 없음으로 topic/action·상태 구독/constructor/callback을 확인했습니다. 첫 수집은 ROS pytest plugin의 lark 미설치였고 설치 없이 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1로 분리했습니다. sandbox DDS 인터페이스 오류2건은 허용된 네트워크 환경의 재실행으로 해소했으며 코드결함으로 합산하지 않습니다. 명령과 pytest 프로세스는 종료됐고 노드/executor/context 정리는 기존 finally 경로로 수행했습니다. 실제 C 생산자나 음성 장치 검증이 아닙니다.
- [문서: 재사용·남은 항목] 기존 RecoveryConfirmation의 변경 없는 core105 결과는 해당 원본에만 재사용했고 새 wrapper/노드 검증으로 대체하지 않았습니다. #43 실제 C 질문/등록/시계/confirm/동일 실행 결과, #150·07 현재 C 생산자·목표수락/first gate, #152 현재 사건/유효기간/B증빙·공개 매핑은 미연결입니다. 클라우드 지연/실패·작은 발화·자기 TTS 변형/잔음/같은 문구 보류·실제 마이크 경합 및 C/B 물리 정지·복구·재개 AC는 미검증입니다. 관련 E 경로에서 추가 미작성 기능은 이번 모의 검사로 발견하지 않았으며 실제 통합 완료로 판정하지 않습니다. 최종 전체 CI/push/PR은 후속 게시 단계입니다.

## 승인 P2 연속 기능 개발 — E-P2-CONTINUOUS-DEVELOPMENT-20261011

- [문서: 최신 지시] 지시 세션이 조율의 인간 원문 turn `01a129c0-cb0a-7473-be91-1b06bc9f21ed`/user `01a129c0-cb3f-7b93-b39c-4502d932b9b8`을 확인해 전달했습니다. 승인된 E 기능 개발을 먼저 이어가고, 더미/회귀/실ROS·최종 CI·PR을 뒤로 두는 순서입니다. 기존 `codex/e-tray-confirm-integration-20261011`/`a2d51b9f3e6e770d0fa67a1d4d5bafb32c3bd5ef`와 작성 중 코드를 보존했습니다. 아래 이전 단일작업 대기 기록은 당시 이력입니다.
- [문서: 작성 범위] #43 질문 작업·등록 관측·실TTS 완료 검사·새 녹음·confirm/STT·재질문·같은 실행 결과 안내, #150 선정 목표·07 현재 payload/목표 내용 상관·수락 run speak 일회성, #187 stop의 LLM 없는 기존 cancel 경로, #152 기존 RecoveryConfirmation의 typed 상태/질문/독립 발화·복구/재개·작업 종료 후보를 작성했습니다. actual 노드 호출과 내부 typed sender가 있으며 실제 C 원본 매핑은 미완료입니다. 기본 P1·평가·명시 opt-in을 유지합니다. 정책은 [사후 검증](../../docs/requirements.md#verification-policy)·[목표 추출](../../docs/requirements.md#fr-int-02)·[수락 TTS](../../docs/requirements.md#acceptance-tts-policy)·[재개 접수](../../docs/requirements.md#resume-admission-policy)를 참조합니다.
- [문서: 정적 보완] goal payload의 should_publish 우회 제거, 낮은/중복 seq의 현재 녹음 권한 보존·의미 충돌 시 폐기, 열린 질문/미결정 독립 요청의 새 begin 차단과 기존 기한 내 등록 대기, pending cancel의 busy 권한 정리, 질문 작업 간 직렬화/마이크 공유, 현재 수락 문장·run의 중복 재생 차단을 보완했습니다. 실행 결과로 보고하지 않습니다.
- [실측: 정적 검사] Voice Python AST 및 git diff --check 통과입니다. 새 실행 시험·더미·ROS probe·전체 CI·push·PR은 수행하지 않았습니다. 이전 a2d51b9의 36개 직접 시험 및 기존 105개 core 시험은 각 이전 대상의 결과이며 이번 노드 경로 검증이 아닙니다.
- [문서: 정확 통합 선행] #43 실제 질문 출력/confirm 수신/등록·시계/같은 실행 단계 결과, #150·07 현재 C 생산자·재기동/수락/first gate·계획 결과, #152 현재 boot/run/halt/등록 seq/상대 시각·유효기간 및 B 증빙/typed 후보의 공개 규약 매핑이 남아 있습니다. source callable이나 valid_state=True 주입은 실C 통합 증거가 아닙니다. common schema/ICD·C/B/A·DB/모션·ontology 오류목록은 수정하지 않았습니다. B 실파지·정지·외력/재진입·실음성/Whisper/Melo/로봇 AC도 미검증입니다.
- [문서: 로컬 체크포인트] 기존14E파일은 `8b5de5a691af81568f61a577097c69683207361d`로 로컬 커밋했습니다. 새 브랜치/worktree·push·PR은 생성하지 않았습니다.
- [문서: #187 추가 작성] 지시 세션의 웨이크 없는 정지 입력 범위를 반영해 audio.py의 단일 SharedInput/소비자·기존 Recorder, Session.stop_audio의 별도 STT 슬롯, VoiceNode 독립 stop listener와 실제 재생 문구 대조·현재 세대 cancel 발신/질문 중복 차단·close를 작성했습니다. 일반 P1 wake/fixed·임계값·설정·기존 cancel wire는 유지하며 새 모델/의존성/타이머를 추가하지 않았습니다. 처리/TTS/질문·Runner 실행/잠김 중 새 “멈춰”/“정지해”는 기존 RMS/무음 종료 녹음으로 접수하도록 작성했으며 LLM/P1 STT/TTS 종료를 기다리지 않습니다. 실제 장치/Whisper/echo·C/B 정지 AC는 미검증입니다. 자기 재생 문구 대조는 음향 echo 제거가 아니며 같은 문구의 사용자 발화도 보수적으로 보류할 수 있습니다. 클라우드 지연/실패·작은 발화·TTS 잔음/변형·마이크 소비 경합/overflow/close를 후속 시험 대상으로 남깁니다. 기본 일반 wake 제한을 상시 음성 수신 보장으로 바꾸지 않습니다.
- [문서: 단계 완료 조건] 기능별 실제 diff·생산자/수신자와 미구현/미연결 목록을 지시 세션에 보고하고 검토 후 해당 파일만 로컬 커밋합니다. 이후 승인된 후속 개발·시험 단계로 이어가며 PR 대기로 개발을 막지 않습니다. 모델 해시와 기존 PR225/218/217/07 refs는 보존하고 커밋에서 제외합니다.

## #43 E 교환·음성 처리 독립 준비 — E43-TRAY-CONFIRM-INTEGRATION-20261011

- [문서: 승인·기준선] 사용자 “구현 시작” 원문(turn `01a129a2-1346-7311-ba2f-be5b37f529ab`/user `01a129a2-1386-7802-8f61-ca296472a2ab`)과 #43 승인08·09, [FR-ONT-02](../../docs/requirements.md#fr-ont-02)·[FR-LOG-02](../../docs/requirements.md#fr-log-02)·[사후 검증 정본](../../docs/requirements.md#verification-policy)을 대조했습니다. 지시된 기존 checkout의 branch `codex/e-tray-confirm-integration-20261011`을 PR225 `0f1f16c2991f54f05bf5577d7cd21ec888e4df7f`에서 시작했습니다. 앞 작업 편집·실행 종료와 tracked clean을 확인했고 별도 작업 폴더를 만들지 않았습니다.
- [문서: 현재 변경] 새 place_exchange, Session.confirm_audio, 직접 시험 및 E 문서만 편집했습니다. 기존 PlaceConfirmation과 Recording·Whisper.before_request·DeadlineCall을 재사용하며 LLM 호출은 없습니다. 반환은 E 메시지 후보이고 C 등록·발행·효과가 아닙니다. 기존 설정·접수/STT 경계·전체 포함 기한을 유지하며 중복/재질문이 구간을 연장하지 않습니다. P1 노드·계약07 운영 보류·#152 경로는 변경하지 않았습니다.
- [실측: 직접 검증] Python3.12 새 test_place_exchange.py **36 passed**, 종료0입니다. yes/no·모호 재질문·차수/식별·과거 boot/work/질문·정상 관측과 오류·TTS 실패·새 녹음/SDK 접수·기한 경계·늦은 STT·중복 작업자·중단 우선·무음/누락을 모의로 검사했습니다. 기존 불변65 검사는 재실행하지 않았습니다. 실제 SDK/장치/ROS/C/로봇 및 실물 AC 검증이 아닙니다.
- [문서: 미완료·인계] 현재 checkout과 읽기 대조한 C `feat/c-status-contract`/`954ed61de614be216ab62c539fbd028ee30f4b22`에는 #43 질문 발신·confirm 수신·E용 단계 post_check 출력이 확인되지 않았습니다. 최신 C 실제 ref·타입·출력/수신 위치·등록 관측/시계 대응·검증된 전달/복구 결과를 지시 세션에 요청했습니다. C 원본 확인 뒤 정확 node/공통 schema·예시·ICD 파일 계획을 추가 대조하고 승인09의 같은 실행 결과 안내를 연결해야 합니다. 독립 준비를 전체 운영 완료와 구분합니다. REGION_NOT_VISIBLE의 ontology 오류목록 후속은 별도 담당 인계입니다.
- [문서: 로컬 커밋·연결/게시 대기] 지시 세션이 실제6파일과 Whisper 호출 경계를 검토해 추가 결함 없이 독립 준비의 로컬 커밋을 지시했습니다. 이 기록을 포함한6E파일만 커밋 대상으로 확정했으며, 커밋 결과는 Git에서 확인합니다. C 원본 연결과 최종 전체 CI·push·PR은 대기입니다. 미추적 모델 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467` 및 기존 PR225/218/217/07 refs를 보존합니다. #150/152 후속은 자동 착수하지 않습니다.

## 계약07 E 요청 상관 로직·운영 보류 — E07-REQUEST-ACCEPT-COMPLETE-IMPLEMENT-20261011

- [문서: 승인·Git] 조장 인간 turn `01a12983-fe9c-7ef0-8d57-efea3b4c3ecc`의 “진행하고 #43 구현사항 설명. 앞으로 하나 구현 -> PR 완료되면 다음 할 거 설명해”와 [계약07 승인](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6105355594)을 직접 대조했습니다. 지정 branch `codex/e-request-accept-complete-20261011`은 PR218 `2545058`에서 시작했고 공동 계약221 `e9edaf8`을 merge `7ee59b0`으로 합류했습니다. 충돌3문서의 양쪽 이력과218준비를 보존했고 C 전체 운영 branch는 합류하지 않았습니다.
- [구현: E 범위] Session/current payload 재검사, 소형 RequestRun, Voice node, cfg/YAML 기본false opt-in, 관련3시험, E 문서만 편집했습니다. 검증된 C 연결을 주입한 모의에서 큐 ID/문장을 발행하고 실제 run 결정·같은 run COMPLETED만 안내합니다. 수락 대기/진행 run을 후속 고유ID로 덮지 않으며 거절/종료/cancel 뒤 새 요청을 허용합니다. 실제 노드의 `_request_run_connected()`는 False인 TODO(E/C)로 실행 발행·수락/완료 상관·speak 수락을 보류하고 기존 P1/평가/목표 차단·halt/cancel 경고를 보존합니다. opt-in speak 로직은 실제 DAC/finished callback·non-mock·취소 검사 뒤에만 성공합니다.
- [실측: 검증] 첫 관련3파일은 149 passed/3 skipped와 AST 시험 namespace 누락1실패, 보완 후154 passed/3 skipped였습니다. 이어 실제 Jazzy probe에서 info 객체 가정 AttributeError·dict publisher_gid KeyError를 확인했고 최종 probe는 실제4키 metadata/graph endpoint만 대조했습니다. 없는 GID 경로는 철회하고 graph를 표본 근거로 대체하지 않았습니다. 후속 요청 덮어쓰기 지적 수정·dict 모의8개 회귀를 좁게 확인했고, 최종 보류 경계/실metadata형태로 시험을 재정리한 관련3파일은149 passed/3 skipped입니다. 그 뒤 추가한 진행 중 명시 cancel 검사는 별도1 passed/79 deselected로 확인했습니다. 실물 결과로 합산하지 않습니다. 공동 계약 e9 전체 CI2262/39는 별도 head 결과이며 최종 운영 준비 stable HEAD CI를 한 번 실행해 PR 본문에 기록합니다.
- [미완료·보존] C 실제 수락/중복/run 고정·speak first gate/안전 재검사·s2 중복 제거와 재기동/과거 결과 근거는 C 운영 선행입니다. 설정만 true로 바꿔 활성화하지 못하며 모의 수락과 실물 완료를 구분합니다. 새 timer/enum/boot/epoch·영구 잠금/강제 재시작·43/152/09/150 구현은 없습니다. 미추적 모델 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`과 기존refs를 보존합니다. PR 완료 후 다음 착수는 부모 설명/지시를 기다립니다.

## PR218 최종217 기준선 상속 — E-PR218-BASE-SYNC-20261011

- [문서: 범위] 기존 PR218 `6cdeceb80d8f3f033e7690fdcea14e20bc54afe5`에서 최종 PR217 `0bfda007345ebd77e6878de903b91bf5e1e465f1`을 정상 merge합니다. PR217의 main `41b456d` 이력·의미 충돌 seq 하한 차단·D/녹음 설명을 상속하며 기존218의 asked 전체 기한·trusted 요청 후보 준비와 시험을 보존합니다. 충돌은 CURRENT 한 구간이며 양쪽 기록을 모두 유지합니다. 이번 직접 편집은 이 동기화 기록뿐이고 새 정책·필드·운영 연결·#150 착수·타 담당 대리 수정은 없습니다.
- [문서: 대조·검증] Session/node/skill_confirmation 및 대응 시험3개는 기존218과 동일하고 recovery core/직접 시험은 최종217과 동일함을 대조했습니다. 불변105 및 기존65/2291 검사를 반복하지 않으며 문서 파일 링크·공백·충돌 표식을 확인한 뒤 최종 HEAD 필수 전체 CI를 한 번 실행해 PR 본문에 기록합니다. 이전6c CI를 새 head 결과로 대신하지 않습니다. 보호 모델 해시와 기존217/07/207~209 refs는 유지합니다.
- [미연결] 실제 C 수락/첫 동작·confirm/재개 수신/ACK/clock 대응·단계별 post_check E 전달, 실음성/ROS/로봇/실물 AC는 미완료입니다. 공동07 문장 정정과 #150 후속 큐는 별도로 보존합니다. 이 기록은 CI/push/게시 완료를 미리 주장하지 않습니다.

## E trusted 요청 후보 연결 — E-P2-EXECUTION-20261011 후속

- [구현: 범위] PR218 `a8e3c74faa4ebc7d4ee7fbc0b0c2065d08b36efa` 위 별도 후속 커밋으로 Session/node와 직접 시험2개·E 문서3개만 수정합니다. 실제 큐 ID와 검증 final_text·confidence·generation/epoch·원본 요청 객체를 대조해 분리된 후보를 만들고, LLM의 공개 ID/문장은 제거합니다. 실제 `_work`에서 취소/Runner 차단·평가/목표/중복 제한을 검사하고 `_voice.prepared_request`에만 둡니다. 준비는 문장을 소비하거나 C 수락/실행을 허가하지 않습니다.
- [실측: 핵심 검증] Python3.12 변경 관련 두 파일 검사에서 273 passed 및 새 시험 구성 오류1건을 확인했고, 구성 오류 수정 후 해당 시험1 passed를 별도 확인했습니다(동일 실행 결과처럼 합산하지 않음). 실제 `_work`·`_publish` 메서드 모의로 기존 P1 wire에 후보 공개 필드가 섞이지 않음을 확인합니다. 사본 변조/원본 보존·다른 큐/요청/세대/epoch/confidence·소비 후 재사용·정지/평가/녹음 오류/목표 차단을 검사했습니다. 최종 HEAD 필수 CI가 전체 변경 시험을 포함합니다.
- [미연결·보존] C 원본954의 confirm/재개 수신·ACK/clock 대응 및 단계별 post_check 결과 E 전달, 공동07의 실제 수락run/첫동작 게이트가 미연결입니다. s2/운영pub·C/B 코드·새wire/타이머/enum을 변경하지 않습니다. 기존 65 및 전체2273 결과는 재실행하지 않았으며 실음성/ROS/C수락/로봇·실물 AC는 미검증입니다. 보호 모델과 기존 refs는 보존합니다. 게시/CI 완료를 이 기록으로 미리 주장하지 않습니다.

## E P2 실행 연결 준비 — E-P2-EXECUTION-20261011

- [문서: 작업 위치] 인간의 작업 지시 세션 위임에 따라 지정된 `codex/e-p2-voice-integration-20261011`을 #217 `8a83b12`에서 생성하고 최종 #209 `f000c28`을 정상 merge했습니다(기준 `9bbe744f0d893ed7e29741ae8820ba1ec54dedbb`). CURRENT 양쪽 이력·#217 코드·D 한 문장/녹음 진단 정정을 보존하고 기존 07·207~209·217 ref는 변경하지 않습니다. 모델 이력은 기존 해시를 유지·커밋 제외합니다.
- [구현: 독립 범위] PlaceConfirmation의 최초 asked 전체 구간을 호출자 입력으로 보존하고 재질문·재전송에 연장하지 않습니다. 최종 판정의 포함 경계·만료/중단·과거 질문 무변경을 검사합니다. 새 wire/enum·E 기본 전체 시간값·타이머·B/C 설정을 만들지 않습니다. 승인08·09는 정본 관련 구간에 반영하며 승인10 적용은 B/C 담당·운영 미확인으로 유지합니다.
- [실측: 첫 핵심 검증] Python3.12 직접 test_e_verification_policy **65 passed**, 종료0입니다. 정확 100초/초과·재질문/중복·오래된 STT·정지·새 run·불변 비전 경로를 확인했습니다. 모의 시각/입력이며 실제 등록·음성·C effect/로그·실물 AC가 아닙니다.
- [실제 blocker·소유] C 고정 원본 `954ed61`의 ROS 수신에는 confirm/재개 경로가 없고 `/runner/status.last`에 단계별 post_check 결과가 없습니다. E는 같은 run의 전달 성공을 전체 FAILED/오류만으로 추정하지 않습니다. C의 질문·응답 수신/ACK 및 검증 결과 발신 원본 확인을 작업 지시 세션에 요청했고 그 수신 위치가 확정되면 기존 notice/node 경로에 연결합니다. 07 문장 정정은 별도이며 이번 독립 준비 전체를 막지 않습니다. 최종 게시 HEAD CI·커밋/push/PR은 아직 실행하지 않았습니다.

## PR217 순서 역행 리뷰 수정 — E-PR217-REVIEW-FIX-20261011

- [문서: 기준선·소유] 기존218 `6cdeceb` 편집/게시 종료·추적 clean을 확인한 뒤 기존 `codex/e-p2-safety-trim-20261011`의 `8a83b12`로 전환했습니다. 원격 최신 main `41b456d118e1eec4d7e8b17955c04d58d02bc22f`를 정상 merge합니다. 전달 main `9b1b407` 이후 B216/219 이력은 이미 main에 포함된 변경이며 대신 편집하지 않습니다. CURRENT 충돌은 양쪽 이력을 보존하고 D 과거 기준 한 문장·녹음 진단 source/_voice 정정을 상속합니다. #218의 asked/core·trusted Session/node 변경과 공동07은 역합류하지 않습니다.
- [구현: 리뷰] [리뷰 지적](https://github.com/Jik-Kim/ready2go/pull/217#discussion_r4240350283)에 따라 동일 boot/run/halt의 최신 신뢰 의미 충돌도 revision/sequences 하한에 기록한 뒤 기존 입력·현재 확인을 무효화합니다. 충돌 work는 채택하지 않고 seq 이하 상태/ACK의 재확인을 차단합니다. 정상 의미 고seq의 입력 보존, 잘못된 입력/미확인 ACK의 하한 불변·boot/종료 처리를 유지합니다. 직접 수정은 recovery core·직접 시험·voice_llm/VoiceREADME/CURRENT 5파일뿐이며 정본 정책·설정·wire·타 담당은 변경하지 않습니다.
- [실측: 회귀] Python3.12 test_recovery_confirmation **105 passed**, 종료0. seq2→충돌4→과거3/4 거절·독립 요청 생성 불가·oldACK 거절, 고seq 유효 재확인·일회 소비, 정상seq 입력 보존·잘못된값의 하한 불변·boot/종료 회귀를 확인했습니다. 최종 안정 HEAD 전체 로컬 CI를 한 번 실행하고 본문·리뷰 답변에 결과를 기록합니다. 이전198/2257 결과로 이 head 검증을 대신하지 않습니다.
- [미검증·보존] 실제 E-C ACK/clock/TTS timeout·마이크/API/ROS/로봇·실물 AC는 미검증입니다. 사용자 models SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`과 기존218/07/207~209 refs를 보존합니다. CI/push/리뷰답변 완료를 이 기록으로 미리 주장하지 않습니다.

## 공동 계약07 E 원본 초안 — E-C-REQUEST-RUN-WIRE-20261011-07 (초안 작성 당시 기록)

- [문서: 승인·Git] 상위 인간 turn `01a1292c-e625-7c40-a46b-abab4f8fac37`의 “승인”과 직전 C 구체안, [승인 기록](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6105355594)·[C 제안](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6105074716)을 직접 대조했습니다. 기존 root의 추적 clean·PR217 `8a83b124f6dae4f09b8f14f8ef7a94852d57d8be`에서 지시 세션의 통상 Git 선택에 따라 `codex/e-c-request-run-contract-20261011`을 생성했습니다. PR217과 기존 E PR ref는 변경하지 않았습니다. 미추적 모델 이력의 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`을 보존·커밋 제외합니다.
- [문서: E 범위] 승인 의미를 [정본](../../docs/requirements.md#acceptance-tts-policy)에 반영하고 intent 스키마에 두 선택 필드만 추가했습니다. 기존 required·enum·confidence·targets/goals는 유지하며 E 예시 두 파일에 필드만 추가했습니다. [공동 ICD](../../docs/interfaces.md#request-run-contract)의 E 발신 원본 구간과 Voice 문서의 승인/원본 준비/운영 미연결 구분을 정리했습니다. 기존 goal 예시는 공개 형식 예시로 보존했으며 선정 catalog나 목표 발행 지원을 주장하지 않습니다.
- [미완료: C 합류] C 소유 `contracts/examples/runner_status.json`·`docs/runner.md`와 ICD 5.3의 C 수신·상태·결과 구간은 C 최소 커밋으로 합류해야 합니다. C `feat/c-status-contract` 전체는 병합/cherry-pick하지 않았고 C/B 코드·태스크·운영 adapter를 편집하지 않았습니다. E 초안 commit/push 뒤 E 편집을 중지하고 같은 브랜치를 인계합니다. C 합류 전에는 PR 생성·동일 계약 PR 완료·공동 검증 완료로 처리하지 않습니다. E 기존 승인과 C 원본 검토·계약 합류·운영 구현·실물 검증은 별개입니다.
- [실측: E 초안 정적] `python3 tools/validate_contracts.py` OK. intent 예시2개·추가 전 P1 예시2개·유효 입력6개·빈 ID/타입 오류7개를 jsonschema로 대조했습니다. 두 새 속성을 제외한 전체 스키마와 두 예시의 기존 내용이 PR217 기준과 동일함을 확인했습니다. 변경5문서 로컬 링크/앵커375개·공백 검사 통과입니다. 기존 예시를 읽는 `tools/validate_contracts.py`는 수정하지 않았고 별도 생성기는 검색에서 발견되지 않았습니다.
- [문서: 검증 계획] 계약 검증기·기존 intent 예시·P1 필드 누락 호환·두 선택 필드 타입/빈 ID·문서 원본 참조를 좁게 대조합니다. 코드 변경 없는 E 초안 단계의 전체 pytest/build/CI는 실행하지 않습니다. 최종 전체 CI는 C 소유 최소 커밋과 ICD가 합류한 계약 PR 최종 head에서 한 번 실행합니다. 중복/빠른 완료/TTS 성공의 운영 모의·실음성·실물 결과는 이번에 검증하지 않습니다.

## E 타이머·반복 검사 축소 — E-P2-SAFETY-TRIM-20261011-06

- [문서: 승인·Git] 상위 인간 turn `01a1290f-14f1-73b3-a7d7-9ed08ac75208`의 E 한정 대체안과 후속 turn `01a12928-54e1-7981-9180-23c0dadbd7a5`의 “반복 검사 줄이는 안까지 같이 진행해” 원문을 직접 확인했습니다. 기존 root의 추적 clean·PR209 `929565a8c1c5ab58569eea877b6ecf7a2c4c8f53`에서 지시 세션이 통상 Git 선택으로 지정한 `codex/e-p2-safety-trim-20261011`을 생성했습니다. 인간이 브랜치 이름을 지정했다고 기록하지 않습니다. 완료 PR207~209는 수정하지 않습니다. 미추적 모델 파일 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`을 보존·커밋 제외합니다.
- [문서: 변경] [재개 접수 정본](../../docs/requirements.md#resume-admission-policy)을 먼저 반영하고 E 등록 ACK 대기·등록 확인→TTS 완료 추가 타이머의 설정/로더/생성자/검사를 제거했습니다. C 등록/ACK 흐름 삭제안은 철회 상태입니다. 기존 등록 함수·질문 유효성·음성 TTS timeout을 유지하며 접수/STT/독립 전체 설정은 변경하지 않습니다. 같은 작업의 정상 seq에서는 기존 녹음/분류/ACK를 보존하고, 실제 무효화 상태 변경에는 재사용하지 않습니다. 이전 구간 설명은 아래 과거 작업 이력이며 현재 구현은 [기술 문서](../../docs/voice_llm.md#p2-safety-voice)를 참조합니다.
- [문서: 확인·제외] C 고정 원본 `954ed61de614be216ab62c539fbd028ee30f4b22`의 등록/ACK/증빙 2차 검사와 C 자체 만료 처리를 읽기 대조했으며 편집하지 않았습니다. 일반 최소 계약04·C/B 검사·HALT·작업 보존/종료 퇴역·일회 소비·과거 콜백 격리를 유지합니다. place/P1/Melo/goal/nudge·공개 계약·새 wire/adapter·새 timeout/TTL/범용 캐시는 변경하지 않습니다.
- [실측: 직접 검증] Python 3.12·ROS 미source의 직접 영향 3시험 파일은 **198 passed**, 종료0입니다. 두 전용 타이머 없는 유효 ACK/실제 TTS 완료, 등록 미확인·질문 만료·TTS 실패 차단/작업 보존, 정상 seq의 녹음·분류·ACK 보존과 실제 상태 변경 무효화, 과거 콜백·종료 퇴역·중복 소비 회귀를 확인했습니다. AST 4파일·YAML의 제거 키 없음/보존 구간값·문서 링크/앵커350개·변경 공백 검사 통과입니다. 공통 계약과 운영 노드/adapter는 변경하지 않았습니다.
- [미검증·검증 계획] C 기한/현재 등록에 대응하는 E 로컬 입력과 기존 TTS timeout 실패를 연결할 운영 소비자는 없습니다. 이 내부 준비로 실제 C ACK나 실음성/API/Melo/ROS/로봇·실물 AC를 통과했다고 보고하지 않습니다. 직접 영향 시험·정적/문서 대조 후 관련 파일만 커밋하고 최종 SHA 전체 CI 1회·push·새 stacked PR 게시를 진행합니다. 최종 CI 결과는 PR 본문/외부 로그에 기록해 추가 기록 커밋으로 SHA를 바꾸지 않습니다. C/B 공동 계약 합의·운영 연결은 별도 선행입니다.

## PR209 최종208 합류 — E-PR207-209-D-DOC-REVIEW-FIX-20261011

- [문서: 범위] 기존 PR209 `929565a8c1c5ab58569eea877b6ecf7a2c4c8f53`에 최종 PR208 `d19d692d4f9e19a2eb8d1a73132e88acf59159b4`를 일반 merge합니다. PR207 `a682bf7`의 승인된 D 연구 보고서 한 문장 정정과 최신 main 이력, PR208의 녹음 진단 공개 source/내부 `_voice` 경로 정정을 상속합니다. CURRENT 충돌은 양쪽 이력을 보존해 해결하며 D 문장과 정본을 추가 편집하지 않습니다. 이전 기록의 D 미확인은 이번 head에서 정정 완료로 갱신되며 main 병합·운영 연결·실물 완료와 구분합니다.
- [문서: 보존·검증] PR209 내부 수락 코드·시험과 기존 P1 동작을 보존하고 #217·07·08 코드/계약은 합류하지 않습니다. 미추적 모델 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`은 보존·커밋 제외합니다. 최종 안정 HEAD의 전체 로컬 CI를 한 번 실행하고 결과·로그를 PR 본문에 기록합니다. 이전 직접 검증은 불변 코드에 재사용하며 실음성/API/Melo/ROS/로봇·실물 AC와 E/C 운영 연결은 미검증입니다. 이 기록은 CI·push 완료를 미리 주장하지 않습니다.

## PR209 리뷰·선행 문서 통합 — E-PR207-209-REVIEW-FIX

- [문서: 범위] 기존 `codex/e-accept-tts-20261011`의 `393536f156d23384b07b5b12073c74334c444a00`에 최종 PR208 `6bb7a4c9bbd3db2396b164b449e07c372a7433e6`을 정상 merge했습니다. PR207 `e93ac41`의 main 기준선·질문/작업 수명·ACK/독립 요청과 PR208의 JSONL/SDK 진단 설명 및 PR209 내부 수락 문장 이력을 함께 보존했습니다. 합류 충돌은 없었고 이번 추가 편집은 E 문서 세 파일뿐입니다. PR209 base를 PR208 브랜치로 갱신하며 선행 PR 미병합 의존성은 유지합니다.
- [문서·코드 대조] PR209 `393536f` 대비 Voice 구현·시험은 동일합니다. 운영 소비 호출자는 없고 Session text/audio 진입의 보관 폐기·질문 만료 재검사는 유지합니다. [C 리뷰 세 항목](https://github.com/Jik-Kim/ready2go/pull/209#pullrequestreview-5481624730)의 C 보관/문장 수명·공개 ID 한 위치/내부 파싱 호환·질문 권한과 수락 문장 권한을 [기술 문서](../../docs/voice_llm.md#acceptance-tts-preparation)의 계약 후속으로 정리했습니다. [최소 범위 결정](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6104884879)은 후속 초안 기준이며 이번에 계약·코드·설정·timeout·TTL·enum을 추가하지 않습니다.
- [미완료·검증 계획] C 등록 만료 보완·B 실제 안전 검사는 별도 선행이고 D 연구 문서 반영은 미확인입니다. 실음성/API/Melo/ROS/로봇·실물 AC와 E/C 실제 연결은 미검증입니다. 문서 링크·앵커·공백·선행 설명 보존과 코드 불변을 대조한 뒤 최종 커밋 SHA의 전체 로컬 CI를 한 번 실행하고 결과를 PR 본문에 기록합니다. 이전 CI로 이번 기준선 합류 검증을 대신하지 않고 별도 중복 영향 시험/전체 빌드는 실행하지 않습니다. 미추적 모델 이력은 기존 해시로 보존·커밋 제외합니다. 이 기록은 CI 실행·push·리뷰 답변 완료를 미리 주장하지 않습니다.

## PR207 추가 리뷰·D 과거 기준 정정 — E-PR207-209-D-DOC-REVIEW-FIX-20261011

- [문서: 승인·소유 예외] E 지시 세션의 인간 turn `01a1293f-85e4-74e0-9880-fe3bfa24303d`에서 “#207 ~ #209 리뷰 확인하고, D 쪽 문서 수정까지 한꺼번에 해 담당자 승인받았어” 원문을 직접 확인했습니다. 예외는 D 연구 보고서의 과거 복구 목표 문장과 현행 정본 참조만이며 다른 D 연구·수치·권고·출처 및 practice/D를 수정하지 않습니다.
- [문서: Git·범위] root의 추적 clean·공동 계약07 로컬 `9bbcd776dc4e56cf40267e07c4c04c714d4cc981`에서 기존 PR207 `e93ac41294c2981d9e506d7b747f2c88a2111959`로 안전 전환했습니다. 공동 원격은 C 합류로 `bc7e0aa8a5162c95921176b259e1b198480635e7`이지만 그 ref·파일은 합류하거나 편집하지 않습니다. 확인 main `e7167fa2adbce7b64631f9481694c04c23545bda`를 충돌 없이 정상 merge했습니다. 최신 main의 A/웹 합류는 기존 이력이며 타 담당 코드를 대신 편집하지 않았습니다. D 문장의 2cm는 과거 작성 당시 기준으로 보존하고 현행 숫자를 복제하지 않은 채 [AC-ACT-03](../../docs/requirements.md#ac-act-03)으로 연결했습니다. 정본의 기존 위치/방향 기준은 변경하지 않습니다.
- [문서: 검증·후속] 기존 PR207 대비 Voice 구현·시험은 동일합니다. D 수정 한 문장 외 내용 불변·정본 앵커·문맥·링크·공백과 모델 이력 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467` 보존을 대조합니다. 기존 직접 시험을 재사용하며 최종 SHA 전체 CI를 한 번 실행해 PR 본문에 기록합니다. PR208 녹음 진단 정정의 재작성/직접 검사를 반복하지 않고 후속 담당의 최종 HEAD를 기다립니다. PR209·217·07 공동 브랜치는 이번 단계에서 수정하지 않습니다. 실음성/API/ROS/Melo/로봇·실물/운영 연결은 미검증이며 문서 정정과 PR 게시를 실물 완료로 판단하지 않습니다.

## PR207 최신 main 기준선 동기화

- [문서: 통합] 기존 `codex/e-halt-policy-20261009`의 PR head `ac96d66a21f5676c08556720d4b7e45da27185b9`에 원격 main `ced8e123eddf7c23d1f06223b087412cc1d8a9f6`를 정상 merge했습니다. 최종 검토 전 head는 `d39605d28c9e1c804b663657d92af8c33eb50f26`입니다. PR diff를 최신 main 기준으로 대조했고 E 담당 변경 21개 파일만 남아 있습니다. main에 이미 반영된 A/B 변경은 PR 신규 변경으로 포함되지 않습니다.
- [문서: 검증 상태] 기준선 병합으로 이전 전체 테스트 결과는 새 head 검증을 대체하지 않습니다. 최종 기록 커밋 뒤 전체 `ci_local.sh`를 한 번 실행해 결과를 PR 본문에 기록합니다. 실행 후 CURRENT를 추가 수정하지 않습니다. 미추적 모델 사용 이력 파일은 원본 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467` 그대로 보존·제외합니다. D 소유 prior-art와 현행 AC 대조는 미해결 인계입니다.


## 수락 TTS E 내부 준비 — E-C-ACCEPT-TTS-20261011-01

- [문서: 승인] 상위 조율 사용자 turn `01a12696-4540-77b0-a575-2e90938fc5be`의 “수락 TTS 권고안 채택, 작업 시작”과 [#196 결정](https://github.com/Jik-Kim/ready2go/issues/196#issuecomment-6099557989)을 확인했습니다. 작업 후 커밋·push·PR까지 진행하는 이 작업자 세션의 사용자 지속 승인도 적용합니다. 공개 계약/운영 활성화/타 담당 편집/병합의 승인은 아닙니다.
- [문서: Git·중단 확인] 인계 경로 `/home/jonny/rokey_proj/VLA/ready2go`를 유지합니다. 이전 편집·시험 중단 인계와 현재 관련 실행 프로세스 없음, 추적 파일 깨끗함을 확인했습니다. 최신 HEAD `ac96d66a21f5676c08556720d4b7e45da27185b9`는 최초 인계 `d0544ee` 이후 #203·#207 작업이 반영된 상태입니다. 상위 조율이 지정한 `codex/e-accept-tts-20261011`을 ac96d66에서 생성·전환했으며 인간이 이름을 직접 지정했다고 기록하지 않습니다. 기존 PR207 브랜치 ref와 미추적 모델 이력 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467`을 보존했습니다. 새 worktree/thread·기존 PR207 추가 push는 없습니다. 로컬 CI의 임시 검사 worktree는 저장소의 필수 검사 절차입니다.
- [문서: 범위] [수락 TTS 정본](../../docs/requirements.md#acceptance-tts-policy)에 승인 방향을 반영하고 [기술 문서의 영향표·계약 초안](../../docs/voice_llm.md#acceptance-tts-preparation)·Voice README를 참조로 연결했습니다. Session의 기존 검증 문장 보관·현재 요청/세대/epoch·원본/내용 대조·일회성 소비와 실제 `_work` 큐 ID 연결을 준비했습니다. 새 파일·설정·wire/enum/timeout·공통 계약/예시/ICD·C/B/A/D·tasks/knowledge/씬은 변경하지 않습니다. 기존 P1 재생/발행과 목표 운영 발행/TTS 차단은 유지합니다.
- [실측: 직접 검증] 관련 3시험 파일 268 passed 뒤 실제 `_work` 연결/음성 요청 소비 시험을 보강해 변경된 2시험 파일 256 passed를 확인했습니다(중복 합산 안 함). Python3.12·ROS 미source·source 패키지 PYTHONPATH 전체 core는 2225 passed, 24 skipped, 종료0(109.74초)이며 ROS 의존14·MongoDB 연결 불가10건은 통과가 아닙니다. 마지막 시험 보강은 별도 256건에서 확인했고 최종 커밋 CI에서도 전체 검사합니다. AST·문서 링크/앵커281개·공백 검사 통과, 기존 PR207 ref/모델 해시 보존입니다. 문서 담당의 별도 수락/병합·실제 C 연결 완료를 주장하지 않습니다.
- [미완료·게시] 내부 소비 호출자는 시험뿐이며 C 수락/재생 완료/첫 동작 허가를 증명하지 않습니다. C 요청→결정→run 및 boot/순서·문장 소비/중복·timeout/취소/단절 계약은 C 합의와 E 포함2인 승인 대기입니다. 현재 find_item s2·E 수락 전 재생은 실제 공동 연결 전 유지합니다. 목표형 수락 문장/게이트, 실제 E/C 발신·수신 핸들러 통합, 실음성/API/Melo/ROS/로봇/실물 AC는 미검증입니다. 미병합 PR207 ac96d66 의존 후속 diff이며 main 독립 완료가 아닙니다. 관련8파일만 자동 커밋하고 최종 SHA 전체 로컬 CI 결과를 외부 로그·PR 본문에 기록한 뒤 Luna 게시 담당으로 stacked PR 생성·첨부합니다. 이 커밋 전 기록으로 최종 SHA CI/PR 생성 완료를 주장하지 않습니다.

## PR207 리뷰 수정 — E-PR207-REVIEW-FIX

- [문서: 승인·상태] E 작업 지시 세션의 인간 요청 turn `01a12658-ec33-73e0-ae04-5c41fe4d4901` “#207 리뷰 확인 및 수정”을 직접 확인했습니다. [리뷰](https://github.com/Jik-Kim/ready2go/pull/207#pullrequestreview-5479444136)·[인라인](https://github.com/Jik-Kim/ready2go/pull/207#discussion_r4238027146)·[문서 검토](https://github.com/Jik-Kim/ready2go/pull/207#issuecomment-6098810882)의 E 세 지적만 기존 1단계 승인 안에서 수정합니다. root·브랜치 `codex/e-halt-policy-20261009`·기준 HEAD `f261ef97ff33dcc3828461e62240f20f9a2a78bb`를 확인했으며 추적 변경은 없었습니다. 미추적 모델 사용 이력 JSON은 보존·제외하며 작업용 새 worktree/브랜치를 만들지 않습니다.
- [문서: 수정] `core/recovery_confirmation.py`의 두 명시 종료와 기존 완료 경로가 같은 E 로컬 사건 퇴역 처리를 사용합니다. 종료 뒤 동일 사건을 높은 seq로 보내도 재개 대상을 복원하지 않으며 다른 새 사건은 기존 규칙으로 수용합니다. 이는 C 종료 확정/새 wire/모션 구현이 아닙니다. 이전 요청의 STT/후보 콜백은 현재 요청과 객체가 다르면 무변경 거절하고, 현재 요청 자체의 실패/만료 처리만 유지합니다. 요청 ID가 같은 복제 객체도 현행 객체를 대신하지 않습니다.
- [문서: 안내 범위] `achieve_goal`은 실제 `_deliver`에서 TTS를 호출하지 않습니다. Voice README·voice_llm·이전 CURRENT 표현 및 `test_voice_ux_node.py`를 콘솔·final_response/intent 진단 안내, 발행 없음·TTS 호출 없음으로 정합화했습니다. 새로운 음성 연결은 추가하지 않습니다. 정본의 [재개 수명](../../docs/requirements.md#resume-admission-policy)·P2 [FR-SAF-03/AC-SAF-04](../../docs/requirements.md#fr-saf-03)·[FR-INT-02](../../docs/requirements.md#fr-int-02)·[FR-PLN-02](../../docs/requirements.md#fr-pln-02)는 유지합니다.
- [실측: 직접 검사] ROS 미source·source PYTHONPATH의 recovery_confirmation/e_verification_policy/voice_ux_node 검사 **193 passed**, 종료0입니다. 두 종료→높은 seq 동일 사건 거절→독립 재개 거절·다른 새 사건 수용, 늦은 A STT/후보가 B 음성/결과/ACK/기한을 보존하고 B만 한 번 소비, 현재 요청 만료/실패 보류를 검사했습니다. 저장된 실제 deliver 메서드로 목표 TTS 호출 없음·발행 없음·진단 문장 일치를 확인했습니다.
- [실측: 최종 검사] 허용 6파일·AST·문서 링크/앵커201개·공백 검사 OK, 미추적 모델 이력 SHA256 원본 유지입니다. Python3.12·ROS 미source 환경에서 source 패키지 PYTHONPATH로 `python3 -m pytest ros2_ws/src -q -rs -p no:cacheprovider`를 실행해 **2210 passed, 24 skipped**, 종료0(107.40초)을 확인했습니다. ROS 의존14건·MongoDB 연결 불가10건 skip은 통과가 아닙니다. 코드/시험은 이 검사 뒤 변경하지 않습니다. 관련6파일만 자동 로컬 커밋한 뒤 최종 SHA 전체 CI를 1회 실행하고 결과를 `/tmp/e-pr207-review-final-ci.log`와 PR 본문에 전달합니다. 이 커밋 전 기록 자체로 최종 SHA CI 통과를 주장하지 않습니다.
- [미해결·제외] D 소유 `docs/research/prior_art_report.md`의 과거 기준/현행 AC-ACT-03 참조 수정은 상위 인계이며 직접 수정·수락/완료 보고하지 않습니다. 공통 계약·설정·node·C/B/A/D·knowledge/tasks/씬·P1/Melo/seq 정책·정본은 변경하지 않습니다. 실제 API/ROS 음성/Melo/로봇/실물 AC·C 종료 확정·운영 연결은 미검증입니다. 관련 파일만 로컬 커밋하고 최종 SHA 전체 CI 뒤 기존 PR207을 갱신하며 새 PR/병합은 하지 않습니다.


## P2 통합 내부 구현 — E-P2-INTEGRATED-EDIT-20261010-01

- [문서: 승인] 상위 조율 세션 `01a11a9f-bcee-7c73-ad82-8887531b7526`의 인간 승인 turn `01a12507-6149-75c0-a1d1-59967fc7408e` “승인. 저장소 규칙에 맞게 계약 원본 requirements.md, 값 원본은 yaml 및 json으로 나머지는 참조만 하도록 하는 거 알지? 정합성 안 깨지게 잘해”를 확인하고 1단계 편집만 수행했습니다. 지시 세션은 기존 E 작업자에게 해당 범위를 전달·수락했습니다. 향후 작업 후 PR 절차 진행의 기존 사용자 승인도 유지합니다.
- [문서: 작업 상태] 기존 root `/home/jonny/rokey_proj/VLA/ready2go`·`codex/e-halt-policy-20261009`·기준 HEAD `1b36ca61b589e58155b6d0b55649687ca9b8ed5a`에서 이어갑니다. 앞선 편집/검사 중단 뒤 상태를 확인하고 실행했습니다. 작업용 새 branch/worktree·reset/rebase/forcepush는 없습니다. 최신 원격 main `d52c1bb661fb9a635ac305e7b06735f68d862c1b`의 승인 대상 파일은 기준 HEAD와 동일하며 추가 C 변경은 병합하지 않습니다. 미추적 모델 사용 이력 JSON은 원본 SHA256 `afa5e005ff158f55be6206adef2637021188f65940ad8d00e2ec9c8697f39467` 그대로 보존·제외합니다.
- [문서: 정본·범위] [재개 접수](../../docs/requirements.md#resume-admission-policy)·[사후 검증](../../docs/requirements.md#verification-policy)·[AC-ACT-03](../../docs/requirements.md#ac-act-03)·P2 [FR-INT-02](../../docs/requirements.md#fr-int-02)의 승인 변경을 정본에 반영했습니다. 런타임 구간값·재질문·선정 목표는 [voice.yaml](../../ros2_ws/src/ready2go_voice/params/voice.yaml), place 선언은 [place.jsonld](../../knowledge/skills/place.jsonld)이 원본입니다. 다른 Phase/AC 숫자·C 시간값·공개 계약/예시/ICD·B/C/D 코드·태스크·씬·P1 녹음/STT/Melo 설정은 바꾸지 않았습니다. 별도 문서 작업과 겹치는 #134 구간은 유지하며 이번 정본 → E 기술/실행 설명 → CURRENT 순으로 확인합니다. 문서 담당의 수락/병합을 완료로 주장하지 않습니다.
- [문서: 내부 구현] recovery는 현재 등록 ACK→TTS→새 녹음/SDK→STT의 구간 검사, 질문과 작업 수명 분리, 종료 부정 제외·독립 요청의 별도 전체/STT 구간·일회성 소비·E 재시작 후 C 상태 확인·현재 완료 폐기를 제공합니다. #78 놓침 후 기존 run 재개 금지는 유지합니다. place는 같은 run/step 절차의 횟수·종료 상태를 보존하고 접수/STT 기한을 분리합니다. P2 LLM 스키마/검증/안내는 선정 목표와 현재 world·발화를 대조하며 기본 비활성·옵트인도 운영 발행 차단입니다. 서랍 관측 evaluator나 복합 동작을 구현한 것이 아닙니다.
- [실측: 직접 검사] Python 3.12·ROS 미source·source 패키지 PYTHONPATH 환경의 변경 관련 6시험 파일은 **546 passed**, 종료0입니다. 등록 순서/기한·중복·질문/작업 수명·종료 부정·과거 녹음·독립 구간·재기동·놓침 재개 금지·트레이 절차/음성 기한·선정 목표/범위 밖/충돌/실패·기본 P1·실제 LangChain 스키마/프롬프트 및 저장된 VoiceNode 메서드의 목표 발행 차단을 모의 확인했습니다. 당시 목표 시험의 TTS 성공/실패 매개변수는 실제 TTS 호출을 검증하지 않았으므로 해당 표현을 정정합니다. 실제 API/ROS 연결·음성·로봇 검증이 아닙니다.
- [실측: 필수 core 검사] 동일 Python 3.12·ROS 미source 환경에서 `python3 -m pytest ros2_ws/src -q -rs -p no:cacheprovider`를 패키지 source PYTHONPATH로 실행해 **2202 passed, 24 skipped**, 종료0(107.50초)을 확인했습니다. ROS 의존14건·MongoDB 연결 불가10건 skip은 통과로 대체하지 않습니다. 코드/시험은 검사 뒤 변경하지 않고 승인 관련 파일만 로컬 커밋합니다. 이후 최종 커밋 SHA의 전체 CI를 `ONLY` 없이 실행하며 결과/로그를 `/tmp/e-p2-integrated-final-ci.log`로 전달합니다.
- [실측: 정합성] AST·JSON/YAML 파싱·계약 검사 OK, 수정 문서 링크/앵커와 실행 원본의 대조를 수행했습니다. place는 verify 문자열 외 필드 불변, YAML의 기존 P1 값과 재개 접수값 보존, 공개 계약/node/타 담당 파일 미편집, 삭제한 단일 place 키는 오류 처리/이행 안내/반례에만 남음을 확인했습니다. 관련 제목/앵커는 보존합니다.
- [미완료: 2단계] 실제 wire/ACK/종료·현재 요청 수락/결과 연결은 실행 원본·예시·ICD와 E 포함 계약 승인 뒤 진행합니다. C 안전 판정에서 실제 빈손 증거 미확인은 보류해야 하며 파지 조건 미충족을 빈손으로 복제하지 않았습니다. C verify/effect·복합 성공/관측 기반 복구·A/B 관측·실물 파지·마이크/API/Melo/장치/AC는 후속입니다. 계약 숫자의 정확 포함 여부가 미확정인 시간 경계는 보수적으로 거절하고 확정 경계만 포함합니다. 최종 SHA 전체 CI 결과는 커밋 후 외부 로그로 전달하며 이 기록 자체로 통과를 주장하지 않습니다.


## 정기 문서 정합성 후속 — E-ISSUE134-DIAGNOSTICS-20261010

- [문서] #134의 main `d52c1bb` 기준 정기 검토에서 확인된 E 범위 상세 진단 P2와 SDK 시각 연결 P3를 반영합니다. 근거는 [FR-INT-01–03](../../docs/requirements.md#fr-int-01)·[음성 정책](../../docs/requirements.md#voice-policy)·[AC-INT-01–03](../../docs/requirements.md#ac-int-01)입니다. 변경 대상은 `docs/voice_llm.md`, Voice README, 이 CURRENT뿐이며 요구사항·Phase·계약·코드·설정 및 B/D 담당 문서는 수정하지 않습니다.
- [문서] JSONL 상세 진단의 위치·최상위 이벤트 필드와 콘솔 요약의 한계를 현재 writer에 맞췄습니다. P1 Session의 SDK 직전 시각 callback은 진단에 연결된 상태로, 기존 `whisper_requested`와 구분합니다. P2 접수/재개 정책과 실제 운영 연결은 미연결로 유지합니다.
- [문서: 게시 상태] PR #198·#202·#203은 main에 병합됐습니다. #203 병합 커밋은 `e0df13a6d4e7bf2ab2a82d94b3f36dc89dc6561d`입니다. 아래 #203 작성 당시 Open/미병합 및 게시 계획은 당시 이력이며 현재 상태가 아닙니다. 병합은 P2 운영 연결·실물 AC 완료를 뜻하지 않습니다.
- [실측: 문서 정적] 새 요구사항·문서 링크 5개와 명시 앵커를 확인했고, 변경 문서의 diff 공백 검사를 통과했습니다. JSONL 필드·콘솔 생략 이벤트·SDK callback 설명은 `voice_node.py`, `diagnostics.py`, `session.py`, `adapters/api.py`와 대조했습니다.
- [문서: 검증 범위] 요청에 따라 PR 최종 head에서 로컬 CI를 실행하고 결과를 PR 본문에 기록합니다. 실제 사용자 진단 파일, 새 PC, API/ROS 운영 연결, 마이크/STT/TTS 및 실물 AC는 이번 정적 대조로 검증하지 않았습니다.

## Voice README 시운전 안내 정리 — E-VOICE-README-20261008

- [문서] 사용자 “README 정리해” 계획 승인 범위로 Voice README와 이 CURRENT만 정리합니다. 브랜치는 `codex/voice-readme-20261008`, 기준 원격 main은 `b1b92b540ce0696a413bf38ad2894288038ba113`입니다. 기존 aa39의 `791dcf1` 브랜치와 미추적 `:memory:.ses`는 보존합니다.
- [문서] P1 [FR-INT-01–03](../../docs/requirements.md#fr-int-01)·[AC-INT-01–03](../../docs/requirements.md#ac-int-01)·[음성 정책](../../docs/requirements.md#voice-policy)을 유지하며 중복 실행 블록을 평가용/Runner 연동용으로 통합합니다. 마이크 사용·발행 게이트·상세 진단·파일 보존과 준비/점검 절차를 구분합니다. 코드·YAML·계약·요구사항·당일 기록은 변경하지 않습니다.
- [문서] 필요한 문서 검증 후 이번2파일만 로컬 커밋하는 범위입니다. push·PR 생성/갱신·외부 게시·병합은 미승인/미실행이며 PR #180 작업과 구분합니다. 새 타 파트 변경 인계는 없습니다. 실제 Runner/backend·실음성·실물 연결은 완료 조건 밖의 미검증입니다. 전체 pytest/colcon/build·설치·모델 다운로드·마이크/API/TTS 재생·실물 AC·서브에이전트 검토는 실행하지 않습니다.

- [실측: 문서 정적] voice_node/session/YAML/실행 진입점과 설명을 대조했고 수정2문서 로컬 링크/앵커46개·Voice 인바운드 앵커9개·기존 제목 보존·bash -n/Python AST 각2블록·git diff --check를 통과했습니다. 두 시운전 명령은 기존 상세 명령 그대로이며 시운전 절 밖 설치/합성/캐시/청취·Melo1.2·PR144 병합 안내·제안값·알려진 결함·P2 운영 미연결 내용은 원문을 보존했습니다. 문서 정리·검증 완료이며 이 절을 포함한 변경만 로컬 커밋합니다.

## 지원 명령 목록 — E-VOICE-COMMANDS-20261008

- [문서] 사용자 요청·계획 승인으로 Voice README의 현재 지원 명령 표와 수동 갱신 절차, 이 CURRENT만 추가합니다. 시작 `ontology/main`·`f2678c32ff671c918b44dd66e06da914f685efa4`의 깨끗한 checkout에서 기존 커밋을 유지한 `codex/voice-commands-20261008`을 준비했습니다. 비교 원격 main은 `92b0e0d9cb32b7027fb9a1035f63dd12f70f4056`이며 관련 Voice/계약/태스크/Runner 라우팅 원본은 동일합니다. 시작 checkout에 존재한 Runner 구현 변경과 기존 커밋은 그대로 보존했고 비교 main의 차이를 이번 작업에 병합하지 않았습니다. 이번 커밋에는 문서2파일의 추가분만 포함하며 기존 PR184 시운전 안내를 보존합니다.
- [문서] 음성 단일 물품 해석과 eraser 태스크 제한, cancel/status, 실행 보류, Runner 구조화 목표형, 계약 enum/레지스트리 파일의 미지원 경계, P2 내부 후보/운영 미연결을 구분했습니다. 기능 변경 PR·E 지시/완료 검증 시 생산자/수신자/원본과 표를 수동 대조하도록 안내하며 자동 검사/CI 구현은 아닙니다. 정본의 의미·Phase·완료 기준은 변경하지 않습니다.
- [문서] 필요한 문서 검증 후 이번2파일만 로컬 커밋합니다. push/PR/병합/이슈/Slack·서브에이전트는 미승인/미실행입니다. 새 타 파트 변경 인계는 없습니다. 전체 pytest/colcon/build·설치/다운로드·API/마이크/TTS/로봇 실물 AC는 실행하지 않으며 기존 불변 명령의 문법 검증을 반복하지 않습니다.

- [실측: 문서 정적] 명령별 파서/발행 게이트·설정·계약enum·태스크trigger/targets·Runner 로딩/라우팅을읽기 전용으로 대조했습니다. 수정2문서 로컬 링크/앵커85개·Voice 인바운드 앵커5개·기존 제목/본문 전체/명령 블록·알려진 제약 보존과 git diff --check를 통과했습니다. 이는 실음성/실물 검증이 아니며 문서 정리·검증 완료 후 이번 추가분만 로컬 커밋합니다.

## MeloTTS 사전 준비 상한 — E-MELOTTS-PREFILL-120-20261008

- [문서: 사용자 결정] 사전 캐시 준비 명령의 상한만120초로 명시합니다. 이 실행의 메모리 cfg만 덮어쓰며 YAML·일반 노드 준비60초·재생전체20초·AC3초·Melo1.2는 유지합니다. 노드 시작마다 모델 로딩/캐시 확인은 수행하고 일치하는 디스크 WAV는 재사용하며 누락/키 변경 문장만 합성합니다. 120초 충분 여부·캐시 완료·60초 노드 재시작은 미실측입니다.
- [문서] 시작 `codex/voice-commands-20261008`·`6eb2d7ef262b0e46503a06bc816fa06f7fe71b65`, 작업 트리는 깨끗했습니다. README와 이 CURRENT만 수정하며 이전 지원명령 커밋·기존 main 대비11파일 차이는 보존합니다. 이번 변경은 이전 커밋을 amend하지 않고 별도 로컬 커밋합니다. push/PR/병합/외부 게시·이슈·서브에이전트는 미승인/미실행이고 새 타 파트 인계는 없습니다. 실제 환경 준비/설치·캐시 생성·API/마이크/TTS/실물·전체 테스트/빌드는 수행하지 않습니다.

- [실측: 문서 정적] adapters/melotts.py·melotts_worker.py·voice_node.py·기존 YAML 상한과 설명을 대조했습니다. 변경 prepare 명령1블록의 bash -n/Python AST, 수정2문서 링크/앵커85개·기존 제목·다른 명령 블록/무관 본문 보존·git diff --check를 확인했습니다. 일반 노드60초·재생20초·AC3초 설정 원본은 변경하지 않았으며 실캐시/환경 준비 성공이나120초 완료를 측정한 결과가 아닙니다.

## #43·#152 승인 정책 구현 준비 — 2026-10-08

- [문서] 조율 사용자 “#43, #152 수정 진행해” 직접 승인을 지시 세션에서 전달받아 깨끗한 `codex/voice-commands-20261008`·`50ceec95adfbb8f8ac00929e9da621108f740ad0`에서 진행합니다. 기존 main 병합/타 세션 커밋·과거 checkout/로컬 자산은 보존합니다. [사후 검증](../../docs/requirements.md#verification-policy)·[재개 접수](../../docs/requirements.md#resume-admission-policy)는 P2 정책이며 현재 P1 실행/발행 흐름은 유지합니다.
- [문서] 스킬 verify 문자열3개와 E 내부 pick/place/재개 정책·Whisper SDK 직전 optional guard·녹음 시작/끝 자료형·미정 설정을 정리합니다. open_drawer는 원문 유지, 공유 wire/타 담당 코드/소비자 자료형은 변경하지 않습니다. 운영 Session/노드 연결·C 최종 effect/log·B 실제 관측/확인 모드·A handover 재촬영은 후속입니다. 새 효과/성공 TTS/로봇 동작을 E 내부 정책이 실행하지 않습니다.
- [문서] C v2의 asked enum 충돌·질문 등록·프로세스 간 monotonic 비교 불가·STT/C hold 미정을 [E 회신안](../../docs/voice_llm.md)에 분리했습니다. 관련 스키마/예시/ICD와 E 포함2명 승인 전 운영 adapter는 보류합니다. B expected_width·측정부위 확인·신선 관측도 후속입니다. #23 당근/학습·#187 독립 정지·자동 놓기·while/fallback 재개 확대는 제외합니다.
- [문서] API/실제 TTS/마이크/실물 AC·학습/모델 시험은 수행하지 않습니다. 필수 검사·diff를 지시 세션에서 검토할 수 있게 보고한 뒤 이번 파일만 로컬 커밋하며 push/PR는 미승인입니다. 사용자 요청으로 커밋 후 전체 로컬 CI를 별도로 실행하며, push/PR는 수행하지 않습니다.

- [실측: 정적·core 모의] 계약 검사 OK, 승인 파일17개·로컬 링크/앵커304개·FR/AC 및 Phase 표·기존 명령·스킬 verify 문자열 자료형 보존·Python AST/JSON/YAML·git diff --check를 확인했습니다. 최종 변경 후 `env -u PYTHONPATH python3 -m pytest ros2_ws/src -q -rs -p no:cacheprovider`는1742 passed,24 skipped(ROS/MongoDB),68.49초입니다. 기존 ROS 경로를 상속한 최초 pytest는 ready2go_interfaces 미설치로 수집 중단(exit5)이었으며 통과 결과로 계산하지 않습니다. 운영 노드·ROS 인터페이스 변경은 없고 별도 colcon/실물/API/TTS 시험은 실행하지 않았습니다. 전체 로컬 CI 결과는 이 커밋 이후 검사 SHA와 함께 별도 보고합니다.

- [문서: 조율 대기] #43의 world 최소−2mm 자동계산13.4/18mm는 사용자10mm 결정을 대체하지 않습니다. B 공용 빈손2mm·서랍손잡이3mm는 변경하지 않았습니다. hardware손잡이29mm와 사용자12.5mm는 측정부위 확인 대기이고 직접 실측하지 않았습니다. world 외접박스 expected_width 불일치 개선은 B 후속이며 코드 삭제 승인으로 해석하지 않습니다.

## #78 모션 차단·놓침 후 새 실행 — E-78-HALT-MOTION-20261009-01

[문서: 이력] 최초 구현·검증·승인 상태는 2026-10-09 `dd7ee06` 작성 당시 기록입니다. 10/10 PR 게시·통합 및 현재 C 구현 상태는 아래 #203 리뷰 보완 절과 갱신된 인계표를 참조하십시오.

- [문서: 승인] 조율 세션 사용자 승인 turn `01a11fca-f317-7102-974c-e382b3465f87` 원문과 [#78 결정 댓글](https://github.com/Jik-Kim/ready2go/issues/78#issuecomment-6077437823)을 확인했습니다. 기존 root `codex/voice-ux-20261009`·`d0544ee92cd15913628adaf935d1f49b8f6b5277`와 미추적 `models/tts/melotts/validated_phrases.json`을 보존하고 지시된 `codex/e-halt-policy-20261009`를 그 HEAD에서 생성했습니다. 새 worktree는 만들지 않았습니다. [PR #193](https://github.com/Jik-Kim/ready2go/pull/193)·[PR #198](https://github.com/Jik-Kim/ready2go/pull/198)은 선행 게시/미병합이며 이번 후속 push/PR/병합은 미승인·미실행입니다.
- [문서] 의미·책임·P1/P2 경계·새 실행 예외는 [정본](../../docs/requirements.md#halt-motion-policy)에 먼저 반영하고 FR-SAF-03·NFR-SAF-02·AC-SAF-04의 기존 일반 재개 문구를 연결했습니다. Phase·수용 숫자는 유지했습니다. E place errors·원인별 미확인 안내·내부 사건/증빙별 후보와 대응 시험, E 기술/실행 문서만 변경합니다. 스킬의 기존 조건/효과·manifest·pick 오류·ROS node·공통 wire·YAML·Melo worker/자산은 유지합니다.
- [문서: 문서 병합] 별도 문서 worktree `46cc`는 읽기 전용 확인 시 깨끗하며 최신 `19bb4e2`는 CURRENT의 #134 상태 갱신입니다. 이번 E 구간은 새 #78 절과 정본 안전 정책·그 참조로 제한해 #134를 편집하지 않습니다. 문서 작업자의 해당 구간 수락·PR 병합은 미확인입니다. 정본 → E 기술/실행 문서 → CURRENT 순으로 대조하고, 향후 같은 구간 수정은 담당·병합 순서 협의를 선행합니다.
- [문서·인계: 2026-10-10] PR #202의 C `HALT_MOTION_CODES`/`HALT_CODES` 차단·잠금·새 요청 거절·두 오류의 재개 보존 제외는 main 병합 코드에서 확인했습니다. 남은 B handover 센서/낙하 코드 구분·보유 확실성·실제 정지/신선 관측, C 관측 기반 상태 동기화·안전한 잠금 해제·명시적 새 run 및 사건 상관 연결은 후속입니다. 새로운 wire/상태 표현은 실행 원본/예시/ICD 동시 반영과 E 포함 2인 승인 뒤 연결합니다. E 내부 자료형/모의 시험은 실제 정지·복구 완료의 증거가 아니며 운영 로봇/DB/상태를 쓰지 않습니다.
- [실측: 변경 검증 완료] Python 3.12.3·ROS 미source 환경에서 package 경로를 PYTHONPATH로 지정한 직접 검사(`test_runner_notice.py`, `test_recovery_confirmation.py`, `test_e_verification_policy.py`, `test_voice_ux.py`) 178 passed를 확인했습니다. 대상은 이번 core/시험 변경이며 원인·증거 부족·과거 사건·재정지·TTS 실패·센서 정상화와 일반 cancel/#152 v1 SDK 10초 경계 회귀를 포함합니다. `python3 tools/validate_contracts.py` OK, AST/JSON·place errors 외 모든 필드 보존·변경11파일/Phase/관련 AC 숫자 보존·기존 제목/수정6문서 링크·앵커338개·diff 정적 검사를 확인했습니다. 최초 직접 pytest의 패키지 경로 미설정 수집 오류는 PYTHONPATH 지정 후 재실행으로 해소했습니다.
- [실측: 최종 core] 같은 Python·ROS 미source 환경에서 source 패키지 경로를 PYTHONPATH로 지정한 `python3 -m pytest ros2_ws/src -q -rs -p no:cacheprovider`가 **1842 passed, 24 skipped**, 종료0(74.22초)입니다. skip은 ROS 의존 모듈/사례14건과 MongoDB 연결 불가10건이며 MongoDB/ROS 검증 완료로 표현하지 않습니다. core/시험 검증 뒤 코드·데이터는 변경하지 않고 이 결과·인계 기록만 보완해 승인11파일을 묶어 자동 로컬 커밋합니다. 기존 d0544ee 전체CI는 선행의 근거일 뿐 이번 후속 PR head의 CI가 아닙니다. 전체CI/colcon·API/마이크/STT/TTS 합성·재생/로봇·추가 subagent는 실행하지 않았습니다.
- [문서: 담당 범위 완료·통합 대기] E 정본/오류 선언/안내·내부 후보와 관련 문서/모의 검증은 완료했습니다. 현재 운영에서 추가된 것은 기존 상태 코드의 안전한 미확인 고정 안내 분류이며, 대상별 회수/복구 안내·새 시작 후보는 실제 운영에 미연결입니다. #78 전체 종료·공통 모션 차단·실물 수용 완료로 보고하지 않습니다. 새 PR 승인 후 최종 게시 SHA 전체CI와 PR193/198 병합 의존성을 확인해야 합니다.

| 인계 대상 원본 | 확인한 필드·근거와 영향 | 필요한 조치·선행 조건 |
|---|---|---|
| B [skill_server.py](../../ros2_ws/src/ready2go_skills/ready2go_skills/nodes/skill_server.py) `_do_place_object`; [grasp_check.py](../../ros2_ws/src/ready2go_skills/ready2go_skills/core/grasp_check.py) `check_hold` | 비정상 폭은 hold.reason=`SENSOR_INVALID`이지만 place에서 held=false를 모두 `self.held=None`/운반 `OBJECT_DROPPED`로 반환합니다. 보유 확실성과 실제 낙하를 코드만으로 구분할 수 없습니다. | 센서 이상/정상 관측 낙하 반환 구분, 불명확 보유 상태 보존, 실제 정지·관측·사람 복구/안전 확인 근거 제공. 새로운 값/표현은 B/C/E 협의 후 확정합니다. |
| C [interpreter.py](../../ros2_ws/src/ready2go_runner/ready2go_runner/core/interpreter.py) `HALT_CODES`·실행/finally/재개 경로 | PR #202 병합 원본은 두 오류를 기존 HALT_CODES에 포함해 ABORTED·잠금, 비모션 finally만 허용, 새 요청 거절과 재개 보존 제외를 구현합니다. E errors 선언과 별개의 C 구현이며 실물 정지·복구 완료 증거는 아닙니다. | 관측 기반 논리 상태 동기화·안전한 잠금 해제·명시적 새 시작의 새 run 운영 연결과 로그가 남아 있습니다. reset_state는 시작 스냅샷 복원이며 잠금을 풀거나 실제 상태 일치를 검증하지 않습니다. |
| B/C [runner_status.py](../../ros2_ws/src/ready2go_runner/ready2go_runner/core/runner_status.py)·[runner_node.py](../../ros2_ws/src/ready2go_runner/ready2go_runner/nodes/runner_node.py) 상태/관측 연결 | 기존 phase/task_id/halt_code/last만으로 물리 정지·현재 대상·정상 센서·현재 boot/run/halt의 신선 관측을 증명하지 못합니다. E 신규 입력은 내부 모의 자료형이며 wire가 아닙니다. | 관측/사건 상관·질문/응답·정지/안내 순서와 timeout/재정지 책임 협의, 실행 원본/예시/ICD 동시 반영·E 포함2인 승인 후 adapter 연결. 확인에 이동이 필요한 안전 복구 절차는 미확정입니다. |

[미완료: #78 전체] B/C 수락·계약 승인·운영 연결 후 실패 주입으로 후속 이동/그리퍼·retry/fallback/skip/safe_home/finally·새 task/기존 run 재개 우회와 성공 effect 미반영, 오류 원인/확실성·로그를 검증해야 합니다. 별도 승인된 저속·2인 실물 시험에서 실제 정지·사람 복원·센서/대상/서랍/작업영역 확인·상태 동기화·명시적 새 run 처음부터 실행과 TTS 실패 중 차단 유지를 확인해야 합니다. 현재 수락·계약·실물 근거는 미확인입니다.

## #198 리뷰 보완 — E-198-REVIEW-FIX-20261010-01

[문서: 이력] 아래는 `2296b5d` 작성 당시 범위·검증 기록입니다. 이후 #198은 main base로 게시됐고 이번 #203 브랜치에 통합합니다.

- [문서: 승인·작업 상태] 조율 세션 `01a11a9f-bcee-7c73-ad82-8887531b7526`의 인간 승인 turn `01a123f7-ada0-77d2-8a97-e9ee1e14973d` 원문 “#198 수정 후 push.”를 직접 확인했습니다. P1 [FR-INT-02–03](../../docs/requirements.md#fr-int-02)·[기존 음성 정책](../../docs/requirements.md#voice-policy)의 [리뷰2건](https://github.com/Jik-Kim/ready2go/pull/198#issuecomment-6077783022)만 보완합니다. 기존 root의 #78 브랜치 `codex/e-halt-policy-20261009`·`dd7ee06dc7202ec836d1661d950a55fff0436436`와 미추적 모델 사용 이력을 보존한 뒤 기존 `codex/voice-ux-20261009`·`d0544ee92cd15913628adaf935d1f49b8f6b5277`로 전환했습니다. 새 브랜치/worktree/reset/rebase/forcepush는 하지 않습니다. 전체CI가 쓰는 일시 검사 checkout은 저장소 CI 절차로 생성·회수하며 작업용 worktree를 추가하는 것이 아닙니다.
- [구현] adapter 내부 strict 스키마의 required 사유를 등록 targets enum과 분리하고 parser가 타입/enum·unknown/빈targets·등록 대상과의 일치를 검사해 `_voice.reason`으로 전달합니다. 기존 response 최종 안내가 사유에 따라 물품/요청 미지원을 구분합니다. 원문 문구/특정 미등록 키로 의미를 분류하지 않습니다. 공개 intent 계약/기존 source 필드는 유지하고 원본은 기존 llm_raw 진단에 보존합니다. Conversation/guard의 응답 판별을 공유해 유효 질문 없는 동의/대명사는 clarify/빈targets/대상 재확인으로 보류하며 과거 권한을 복원하지 않습니다.
- [범위] 변경은 E api.py·intent.py·conversation.py, 직접 관련 시험3파일과 Voice README·voice_llm·이 CURRENT입니다. response/node·SOT/Phase/AC 숫자·공통 계약·B/C/D 코드·#78 SOT/오류/안내/복구 코드·Melo/녹음 설정은 변경하지 않습니다. 기존 #78 커밋은 이 PR에 혼합하지 않으며 향후 새 #198 head와의 별도 통합이 필요합니다. GitHub에서 #193 병합을 확인했습니다. #198의 현 base는 `codex/e-policy-pr-20261009`이며 게시 전담이 main retarget과 최종 diff/head 대조를 수행할 예정입니다. 작업자는 merge/rebase/retarget/병합을 하지 않습니다. 새 타 파트 인계는 없고 기존 C 수락/상관관계·D 정답표·실음성/실물 후속은 유지합니다.
- [실측: 직접 검사] Python 3.12.3·ROS 미source·source 패키지 PYTHONPATH 환경에서 `test_voice_ux.py/test_voice_ux_node.py/test_intent.py/test_config_api.py` 직접 검사353 passed, 종료0입니다. 실제 LangChain 스키마의 enum/required/additionalProperties 및 schema 적합 unknown 미등록/미지원 사유·문구 교차, 현재/무문맥/만료/취소/세대/재시작/경고/잠금 질문과 정상/실패/없음 LLM, 기존 일회성·평가/실행·TTS/발행 실패·취소 게이트를 모의 확인했습니다. AST·수정3문서 링크/앵커158개·기존 제목·승인9파일/공개 계약·정본/설정/node/#78 코드 불변·git diff --check를 확인했습니다. 계약 검사 `python3 tools/validate_contracts.py` OK입니다. 같은 Python/ROS 미source/PYTHONPATH 환경의 최종 `python3 -m pytest ros2_ws/src -q -rs -p no:cacheprovider`는 **1981 passed, 24 skipped**, 종료0(75.71초)이며 ROS 의존14건·MongoDB 연결 불가10건 skip을 통과로 보고하지 않습니다. 코드·시험은 이 검사 뒤 변경하지 않고 승인9파일을 묶어 자동 로컬 커밋합니다. 그 최종SHA의 전체CI는 이후 실행하고 결과/로그를 외부 `/tmp/e198-review-fix-final-ci.log`로 전달합니다. 이 기록만으로 최종SHA CI 통과를 주장하지 않으며 기존 d054 결과로 대체하지 않습니다.
- [게시·미검증] 기존 PR198 normal push·근거/리뷰 반영 댓글 갱신은 승인됐으며 PR 전담 세션이 담당합니다. 작업자는 직접 push/새PR/병합하지 않습니다. 최종 head의 전체CI 근거는 외부 로그로 전달하며 CI 뒤 CURRENT만 재커밋하지 않습니다. 실제 API/마이크/STT/Melo 합성/재생/로봇·C 수락/실물AC는 시험하지 않습니다. 모의 검증/CI와 게시/수락/병합을 구분합니다.

## #203 병합 상태 현행화 — E-203-MERGED-STATUS-20261010-02

- [문서: 승인·목적] 지시 세션 `01a11aa1-3875-7b00-9647-cfc4abcecad3`의 인간 turn `01a1244b-6bdf-71d2-8b9f-9bb1fda17363` 원문 “#203 코멘트 확인 후 수정”과 기존 작업 후 commit/push/PR 지속 승인을 확인했습니다. [최신 리뷰](https://github.com/Jik-Kim/ready2go/pull/203#pullrequestreview-5477791033)의 선행 병합·현재 base 설명만 현행화합니다. 직접 수정은 voice_llm과 이 CURRENT 2파일이며 새 정책/계약/코드·설정·타 파트 상태 변경은 없습니다.
- [문서: 당시 게시 상태] #193·#198·#202·#203은 main에 병합됐습니다. #198 병합 SHA는 `667f0b8a0e59a459ac0e1fb1bcf5b100413edaab`, #203 병합 SHA는 `e0df13a6d4e7bf2ab2a82d94b3f36dc89dc6561d`입니다. 아래 `e0a57e5` 작성 당시의 #198 Open·stacked 42파일·retarget 예정 및 #203 Open/게시 예정 기록은 이력이며 현재 상태가 아닙니다. 선행 변경이 main에 포함되어 중복 diff에서 제외됐으며, 병합은 운영 연결이나 실물 검증 완료를 뜻하지 않습니다.
- [실측: 통합·보존] 기존 `codex/e-halt-policy-20261009`·`e0a57e5d5d7cc6e64b86831f1311876370b2765c`에서 origin/main을 fetch해 지정된 `667f0b8`과 동일함을 확인했습니다. 같은 브랜치에서 normal merge 후 충돌·추가 파일 차이 없이 기존 HEAD와 동일 tree였음을 확인했고, 이어 문서2파일만 보완합니다. 새 worktree/브랜치/reset/rebase/forcepush/subagent를 사용하지 않으며 미추적 모델 사용 JSON은 보존·제외합니다. 정본 Phase/숫자/정책·실행 원본/설정/계약·Melo/녹음·B/C/D 파일과 E 기능/시험은 그대로입니다.
- [문서·검증 재사용] 코드와 시험이 `e0a57e5`와 동일하므로 이전 직접 회귀485건 및 리뷰385건 결과를 각각의 검사 범위 근거로 재사용하며 합산하거나 재실행하지 않습니다. 문서 링크/앵커·현행/이력 구분·main 조상·E11파일 diff를 확인해 관련 문서를 묶어 로컬 커밋합니다. 새 최종 SHA의 필수 전체 CI는 1회 실행하고 `/tmp/e203-merged-status-final-ci.log`로 전달합니다. 이전 e0 CI로 대체하지 않으며 CI 뒤 CURRENT만 재커밋하지 않습니다.
- [문서: 범위·미완료] P1 원인별 안내/오류 선언과 P2 내부 복구·새 시작 준비의 FR/NFR/AC 구분은 아래 #203 최초 보완 기록과 [정본](../../docs/requirements.md#halt-motion-policy)을 유지합니다. B 센서/놓침 구분·실제 정지/관측, C 상태 동기화·안전한 잠금 해제·새 run 운영 연결, E 포함2인 계약 승인·운영 adapter·실물 AC는 후속입니다. 실제 API/마이크/STT/Melo 합성·재생/로봇/실물 시험은 하지 않으며 #78 전체 완료를 주장하지 않습니다.
- [실측: 문서 정합] 수정2문서 로컬 링크/앵커109개·기존 제목/과거 기록 보존·충돌 마커 없음·diff 공백 검사를 통과했습니다. main 병합 index는 e0a57e5 tree와 동일하고 작업 tree 차이는 문서2개뿐입니다. main↔head E11파일 범위도 확인했으며 코드/시험/정본/설정/계약/타 파트 파일 보존을 근거로 기존 회귀 결과를 재사용합니다.
- [문서: 게시 절차] 로컬 수정·검증·커밋·최종CI 결과는 부모가 실제 diff/SHA와 대조한 뒤 기존 PR 전담에 normal push·main 기준 E11파일/선행 병합·최종CI 본문 갱신과 코멘트 반영을 인계합니다. 작업자는 별도 게시 agent·직접 push·새 PR/이슈/Slack·PR 병합을 하지 않습니다. 게시 완료와 #203 병합은 별도 상태입니다.

## #203 리뷰 보완 — E-203-REVIEW-FIX-20261010-01

[문서: 이력] 아래는 2026-10-10 `e0a57e5` 작성 당시의 통합·검증·게시 조건입니다. 현재 선행 병합/base/diff 상태는 위의 병합 상태 현행화 절을 참조하십시오.

- [문서: 승인·범위] 지시 세션 `01a11aa1-3875-7b00-9647-cfc4abcecad3`의 인간 turn `01a1241d-1e39-7312-9044-f0f79cd211ba` 원문 “#203 리뷰 확인 및 수정”과 이 작업자 세션의 “#78 커밋도 PR 작성해 앞으로 작업 후 PR까지 알아서 진행해” 승인을 확인했습니다. [리뷰](https://github.com/Jik-Kim/ready2go/pull/203#pullrequestreview-5477543507)·[현행 C 반영 요청](https://github.com/Jik-Kim/ready2go/pull/203#issuecomment-6093743387)의 통합·Phase 표기·E 문서 상태만 보완하며 새 정책/계약/타 파트 직접 수정·PR 병합은 제외합니다.
- [문서·통합] 기존 `codex/e-halt-policy-20261009`·`dd7ee06dc7202ec836d1661d950a55fff0436436`에서 최신 #198 `2296b5d22b64bd9ed46dd15502bc6106f0282b3c`를 정상 병합했습니다. CURRENT 단일 충돌은 #78/#198 두 기록을 모두 유지해 해소했습니다. 이어 최신 main `77cb64c22773d6135dffedc1ce9a4e87f874c3e8`을 정상 병합하며 #202 C 차단/시험·fixture와 이미 병합된 B 변경을 그대로 가져옵니다. 새 worktree/브랜치/reset/rebase/forcepush를 사용하지 않고 미추적 모델 사용 JSON을 보존·제외합니다. main 유입은 E가 B/C/계약 파일을 직접 편집한 변경이 아닙니다.
- [문서: Phase·정본] P1 원인별 안내·오류 선언/안전 정합화는 [FR-ACT-03](../../docs/requirements.md#fr-act-03)·[FR-ONT-01](../../docs/requirements.md#fr-ont-01)·[FR-COM-01](../../docs/requirements.md#fr-com-01)·[NFR-SAF-02](../../docs/requirements.md#nfr-saf-02)·[AC-SAF-01](../../docs/requirements.md#ac-saf-01), P2 내부 복구·새 시작 준비는 [FR-SAF-03](../../docs/requirements.md#fr-saf-03)·[FR-ONT-02](../../docs/requirements.md#fr-ont-02)·[FR-LOG-02](../../docs/requirements.md#fr-log-02)·[AC-SAF-04](../../docs/requirements.md#ac-saf-04)를 참조합니다. #78/#152/#196은 요구사항 ID가 아닌 추적 이슈이며 정본의 Phase·정책·수용 숫자를 바꾸지 않습니다.
- [문서·코드 대조] #202에서 놓침·센서 이상의 공통 차단·잠금·새 요청 거절·재개 보존 제외를 확인해 ontology/Knowledge/Voice 문서의 누락·후속 문구를 갱신했습니다. B handover place 센서/놓침 코드 혼용과 보유 확실성·실제 정지/신선 관측, C 관측 기반 상태 동기화·잠금 해제·새 run 운영 연결, E 포함 2인 계약 승인·관측/질문/응답 adapter·실물 AC는 여전히 후속입니다. C test_runner_node의 intent_schema_file/tasks_dir override도 병합 원본에서 확인했으며 아래 #194의 호스트 오류 5건은 당시 이력입니다. 이번 비ROS 모의/CI로 ROS fixture 실행 통과를 주장하지 않습니다.
- [실측: 통합 직접 검사] Python 3.12.3·ROS 미source·source 패키지 PYTHONPATH로 recovery_confirmation/runner_notice/e_verification_policy 및 #198 voice_ux/voice_ux_node/intent/config_api, C #202의 놓침·센서 이상 후속 모션/새 요청 거절·재개 보존 제외·원자 finally 반례를 함께 검사해 **485 passed**, 종료0(6.71초)을 확인했습니다. 계약 검사 OK, 수정5문서 링크/앵커243개·기존 제목·충돌 마커 없음·정본 dd7ee06 원문 및 #198/#78 코드 보존·main 유입 파일 원문 일치를 확인했습니다. C/B 코드·테스트는 직접 편집하지 않았고 이 결과는 모의 회귀이며 실제 정지·ROS fixture/실물 AC 검증이 아닙니다. 관련 문서·통합 변경을 묶어 로컬 커밋한 뒤 최종 SHA의 전체 CI 결과를 외부 로그로 전달합니다.
- [게시·검증 경계] #198은 현재 Open·main base, #203은 기존 `codex/voice-ux-20261009` base를 유지합니다. 최신 main 유입으로 stacked diff에 이미 병합된 B/C 변경이 보일 수 있으므로 E 직접 변경과 구분합니다. #198 병합 확인 후 main retarget·최종 diff 정리가 선행이며 여기서 #198/#203을 병합하지 않습니다. 직접 회귀·계약·문서/실행 원본 정합 검사 뒤 관련 변경을 묶어 커밋하고 최종 SHA의 전체 CI를 실행합니다. 과거 dd7ee06·2296b5d CI는 이력으로 재사용하며 통합 CI를 대체하지 않습니다. 결과는 `/tmp/e203-review-fix-final-ci.log`에 전달하고 CI 뒤 CURRENT만 재커밋하지 않습니다. normal push·PR 본문 P1/P2/실제 ID·현행/CI·반영 댓글 갱신은 부모의 기존 PR 전담 인계로 수행하며 별도 게시 에이전트를 만들지 않습니다. 실제 API/마이크/STT/Melo 합성·재생/로봇·실물 AC와 추가 subagent는 실행하지 않습니다.

## #194 Voice UX·#138 캐시·#195 비교 — E-VOICE-UX-20261009-01

- [실측: 후속 검증] 승인25파일을 체크포인트 커밋으로 보존한 뒤 Voice 테스트 기대값/대역6건과 시험 캐시 경로를 보완했습니다. 비ROS Voice679 passed/9 skipped, Python AST·JSON/YAML·계약 검사·요구사항/기존 설정/물품 구조 보존·로컬 링크/앵커280개·diff 검사는 통과했습니다. colcon build7패키지 성공, 실제 ROS Voice colcon test735건(오류/실패/skip0) 통과입니다. ROS 환경 전체 pytest는 초기6실패/1907통과/10skip/5오류였고, Voice6실패는 보완·재검증했습니다. 남은5오류는 C test_runner_node.py의 기존 /contracts/intent.schema.json 기본 경로 부재로 인계 대상이며 C 코드는 수정하지 않습니다. core MongoDB10건은 호스트에서 연결 불가로 건너뛰었으므로 전체 core 통과로 표현하지 않습니다. 전체 로컬 CI는 검사 SHA `aad75f3329696048acbfd4ba0c50935333fc60ea`에서 `ci_local.sh@aa5aa0f`로 2026-10-09 17:03에 종료0을 확인했습니다: validate_contracts OK / pytest1778 passed,38 skipped(py3.12, REQUIRE_MONGO=1·임시 MongoDB7.0) / compose real·sim·dev OK / colcon build OK. 이 결과는 ROS를 source하지 않은 CI 환경의 전체 검사이며 앞선 호스트 ROS fixture 오류5건과 구분합니다. 이번 CURRENT 결과 기록의 후속 커밋은 해당 검사 SHA와 다르며 그 문서 커밋까지 CI를 실행했다고 주장하지 않습니다. 실제 API/마이크/TTS 합성·재생/로봇·AC는 미실행이고 C 수락 연결·D 검토는 대기입니다. 모의 시험이 만든 models/tts/melotts/validated_phrases.json은 텍스트 사용 이력만 포함하며 커밋 제외·보존했고 시험 assets 경로를 tmp_path로 분리했습니다.

- [문서: 승인] 상위 조율의 사용자 “확인했어 진행해”를 원문 확인한 지시 범위입니다. 깨끗한 `codex/e-policy-pr-20261009`·`7f967713b32eaa9ae70a41720c1f6d0e94cadf8f`를 보존하고 공유 root에서 `codex/voice-ux-20261009`로 분리했습니다. PR #193의 기존17파일 변경·aa39 로컬 자산은 보존합니다. 이번 새 변경만 로컬 커밋하며 push/PR·중복 이슈/외부 게시·추가 subagent는 수행하지 않습니다.
- [문서] P1 [FR-INT-01–03](../../docs/requirements.md#fr-int-01)·[voice-policy](../../docs/requirements.md#voice-policy)·[AC-INT-01–03](../../docs/requirements.md#ac-int-01)의 승인 예외를 정본부터 반영했습니다. 기존 Phase/AC 숫자는 유지합니다. 물품 일상 별칭만 보강하며 키/클래스/치수/목록은 유지합니다. 내부 질문/응답/비동기 상세 로그 모듈과 노드 연결, bounded 캐시 선준비·시간 진단·핵심 모의 검사를 정리합니다. 실제 캐시 합성·API/장치·로봇/AC 시험은 하지 않습니다.
- [문서] 정책/현재 구현과 필드·검증 경계는 [voice_llm.md](../../docs/voice_llm.md#194-요청질문진단-연결과-138-bounded-캐시)·[Voice README](../../ros2_ws/src/ready2go_voice/README.md)와 실행 원본을 참조합니다. 공개 intent/계약·C/D 코드·기존 recovery/skill 정책 및 P2 params/테스트는 변경하지 않습니다. 일반 대화는 P2 사건/10초 정책과 독립입니다. 구현 모의·ROS검사·최종로컬CI는 명령/SHA와 실제 결과로 구분해 후속 기록합니다.
- [인계: 대기] [#194](https://github.com/Jik-Kim/ready2go/issues/194)·[#138](https://github.com/Jik-Kim/ready2go/issues/138)·[#195](https://github.com/Jik-Kim/ready2go/issues/195)는 P1 기반 개선/비교로 유지하며 후속 C 수락 연결·D #20 정책 사례 검토는 [#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 추적합니다. #23 관리종료는 과거 이력/P1 미달을 완료/AC 면제로 바꾸지 않습니다. 과거 latched/같은 문장 결과의 요청 상관 식별·TTS/수락 순서·timeout/단절/취소 책임은 C 합의 전 미연결입니다. 새 계약은 E 포함2명 승인+스키마/예시/ICD 선행이며 조율의 협의 전달은 수락/승인이 아닙니다. #43/#152/#187/#150 새 구현은 제외합니다. 녹음 기본/임계값·기존 승인 상한을 유지했고 실음성 비교/채택 근거는 미측정입니다.

## 지금 상태

- [문서] 2026-10-09 대조 기준 원격 main은 `fd4c8aa788c25f794a2aae8fe56ef1a941add65c`이며 작업 시작 HEAD와 같습니다. #180의 과거 Open 표시는 당시 이력이며 현재 상태가 아닙니다. 후속 인계 34건의 관리 위치는 [#134](https://github.com/Jik-Kim/ready2go/issues/134)이고 목록을 이 CURRENT에 복제하지 않습니다. B/C/D의 수락·담당별 변경 및 최종 통합 완료는 각 항목의 근거를 대조해 구분합니다.
- [문서] #134의 10/09 검토 기준으로 C의 제외 후 박스 모델 재분류 수정은 main에 반영되지 않았고, B의 서랍 안 놓기 [PR #191](https://github.com/Jik-Kim/ready2go/pull/191) 및 트윈 [PR #192](https://github.com/Jik-Kim/ready2go/pull/192)는 열려 있습니다. main의 현재 서랍 안 place 지원은 미구현이며 #191 병합만으로 지지면 목표·실물 수용 완료를 뜻하지 않습니다. 실행 응답 후 사후 관측 검증을 관리하는 [#43](https://github.com/Jik-Kim/ready2go/issues/43)도 열려 있고, [`close_drawer.verify`](../../knowledge/skills/close_drawer.jsonld)의 선언은 런타임 검증 완료를 뜻하지 않습니다. E 복구 확인 내부 정책도 운영 ROS/TTS/청취 경로에 미연결입니다. 이 상태는 [FR-ONT-02](../../docs/requirements.md#fr-ont-02)·[AC-ONT-01](../../docs/requirements.md#ac-ont-01)의 Phase·완료 기준과 구분하며, 요구사항 축소나 시험 제외로 합의하지 않았습니다.
- [문서] 기준 main에는 PR #165(`b4cc2fe`), #166(`f4646b4`), #167(`dea9016`), #169(`6f274e0`), #176(`65148d4`), #180·#181·#182·#185·#186·#188·#189가 병합됐습니다. 반복(`while`)·`fallback` 내부 정지의 재개 문맥 보존 제약은 [#152](https://github.com/Jik-Kim/ready2go/issues/152), 지지면 협의는 [#134](https://github.com/Jik-Kim/ready2go/issues/134)에서 관리합니다. 코드 병합은 실제 운영 연결·승인된 wire·실물 검증과 구분합니다. 진행·인계는 [#152](https://github.com/Jik-Kim/ready2go/issues/152)·[#153](https://github.com/Jik-Kim/ready2go/issues/153)을 확인하십시오.
- [문서] PR #144 MeloTTS·캐시·중단 안내와 #160/#161/#162 실행 안내는 기준 main에 반영됐습니다. #134의 D #158 최신 상태와 전체 설치/실물 완료는 이번 작업에서 재검증하지 않았습니다.
- [문서] 공통 [manifest](../../knowledge/robot_ontology.jsonld)·[pick](../../knowledge/skills/pick.jsonld)과 [정식 태스크](../../tasks/find_item.json)가 현재 실행 원본입니다. E 음성의 실제 구현·진단·시운전은 [Voice README](../../ros2_ws/src/ready2go_voice/README.md), 로더는 [Knowledge README](../../knowledge/README.md)를 참조합니다. 과거 시연 전용 정의를 현재 실행 원본으로 복원하지 않습니다.
- [문서] 작업 시작 당시 사용자 변경16개를 승인된 stash에 보존했던 이력은 당일 기록에 남깁니다. 이후 사용자 “stash 폐기” 요청으로 해당 stash가 제거됐으며 현재 stash 목록은 비어 있음을 확인했습니다. 이번 PR 보완에서는 stash를 복원·변경하지 않았고 다른 브랜치·worktree·로컬 키/모델/로그도 변경하지 않았습니다.

## 막힌 점 · 필요한 도움

- [문서] #134 후속은 담당별 문서·구현·통합 상태를 분리해 관리합니다. 과거 26건 정책·156건 회귀·595건 ROS/모의 결과는 [당시 기록](2026-10-08_practice.md)의 결과이며 이번 재실행이 아닙니다. 이번 상태 갱신은 GitHub 병합 상태와 현재 문서·원본의 정적 대조이며 전체 pytest/build·설치·마이크/API·실물 시험은 수행하지 않았습니다.
- [문서] A/B/C/D와 공통 문서 소유자의 중복 기준 정리, 가림 관계·재식별 adapter, 지지면 복구 범위 협의, 안전 wire 계약 승인(E 포함 2명)·스키마/예시/문서 동시 반영이 남습니다. 링크 정리는 자동 검사·운영 연결 구현이 아닙니다.
- [문서] 기존 비요청 판별 결함, 웨이크/runtime 배포, 운용 PC 캐시·청취 품질·실음성 평가·C/D 수신, A/B 재관측/파지 및 안전 정지·복구·재개·실물 AC는 완료로 판정하지 않습니다. 수용 기준은 [AC 목록](../../docs/requirements.md#ac-index)을 참조합니다. E는 nudge 시험 담당에서 제외합니다.
- [문서] 10/09 #134 후속으로 E의 현재 상태를 `practice/E/CURRENT.md`와 [#134 관리 요약](https://github.com/Jik-Kim/ready2go/issues/134)에 반영했습니다. 타 담당 문서·코드·계약은 수정하지 않았으며, #43의 운영 연결·실물 수용 완료와 #191/#192 병합, 전체 빌드·테스트는 미완료/미검증 상태로 남습니다. push·PR은 요청 범위에 포함하지 않습니다.

## 확정 값 (근거 태그 필수)

[문서] 의미·정책·수용 기준은 [정본](../../docs/requirements.md), 런타임 값과 승인 상태는 [실행 원본](../../docs/requirements.md#runtime-sources)을 확인합니다. 이 CURRENT에 기준값을 재복제하지 않습니다.

## 다음 할 일

- [ ] 결정권자가 인계 목록의 담당자를 확인하고 담당 문서 반영·지지면/계약 협의를 진행합니다.
- [ ] 별도 승인된 운영/실물 검증 결과를 현재 구현·병합 이력과 구분해 기록합니다.

## 철회한 결론

[문서] 과거 TF null·치수 순서·manifest 직접 로딩·시연 정의 관련 정정 이력은 [날짜별 기록](2026-10-07_작업기록.md)에 보존합니다. 현재 의미와 실행 원본은 위 정본 링크를 확인합니다.

## 날짜별 상세 기록

- [2026-10-08 작업 기록](2026-10-08_practice.md): 요구사항 정본화 및 #144/#160/#165 당시 검증·게시 상태 이력.
- [2026-10-07 작업 기록](2026-10-07_작업기록.md)
- [2026-10-06 작업 기록](2026-10-06_작업기록.md)
- [2026-10-05 작업 기록](2026-10-05_작업기록.md)
- [2026-10-04 작업 기록](2026-10-04_작업기록.md)
