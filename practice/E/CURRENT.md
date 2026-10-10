# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장)
- **현재 Phase**: P2 준비(P1 통합 종료 유지). 목표·정책·책임·완료 기준은 [requirements.md](../../docs/requirements.md#phase-scope)를 참조합니다.
- **최종 갱신**: 2026-10-10

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
