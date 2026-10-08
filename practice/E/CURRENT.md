# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장)
- **현재 Phase**: P2 준비(P1 통합 종료 유지). 목표·정책·책임·완료 기준은 [requirements.md](../../docs/requirements.md#phase-scope)를 참조합니다.
- **최종 갱신**: 2026-10-08

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

## 지금 상태

- [문서] `codex/requirements-centralization`의 공통·E 문서 정리는 [PR #180](https://github.com/Jik-Kim/ready2go/pull/180)에 게시됐으며 확인 시점 Open·미병합입니다. 최초 게시 커밋은 `d4ca24e`, 최신 확인 base/main은 `bbad37320cb2ff1deec1dd29a5a30656c36a484d`이며 작업 시작 기준 `65148d4`와 구분합니다. 의미·정책·수용 기준은 [요구사항 정본](../../docs/requirements.md), 실행 필드·값은 [실행 원본 안내](../../docs/requirements.md#runtime-sources)에 둡니다. 다른 담당 문서는 직접 수정하지 않았습니다. 후속 인계34건의 실제 관리 위치는 [#134](https://github.com/Jik-Kim/ready2go/issues/134)입니다. 목록을 이 CURRENT에 복제하지 않습니다. [B 해당 범위 수락](https://github.com/Jik-Kim/ready2go/issues/134#issuecomment-6054747674)은 domain의 선택·복구·AC/시간 예산 안내와 Skills README의 과거 시험 안내, [C 해당 범위 수락](https://github.com/Jik-Kim/ready2go/issues/134#issuecomment-6054720331)은 Runner·planner 재계획 안내 및 ICD/안전의 C 몫에서 확인했습니다. C 주담당12–18은 [C 후속 회신](https://github.com/Jik-Kim/ready2go/pull/180#issuecomment-6055195230)에서 로컬 `056f1b7` 반영 및 #180 병합 뒤 별도 PR 예정으로 보고됐습니다. 이는 수락 이후의 로컬 반영 보고이며 E가 C 파일 수정 결과나 병합·최종 통합 완료를 검증한 것은 아닙니다. B의 수정·병합·최종 통합 완료도 미확인입니다. 기타 담당 범위의 수락·완료도 미확인으로 남깁니다.
- [문서] 현재 기준 main에는 PR #165(`b4cc2fe`), #166(`f4646b4`), #167(`dea9016`), #169(`6f274e0`), #176(`65148d4`)이 병합됐습니다. E 복구 확인 내부 정책은 운영 ROS/TTS/청취 경로에 미연결입니다. C의 잠금 해제와 단계 재개 준비, B의 첫 서랍 놓기는 바닥만 지원하며 다른 물체 윗면 복구 목표와 차이가 있습니다. 반복(`while`)·`fallback` 내부 정지의 재개 문맥 보존 제약도 [#152](https://github.com/Jik-Kim/ready2go/issues/152) 협의 항목입니다. 이 제약과 바닥만 지원하는 지지면 차이는 미달·미검증 항목이며 요구사항 축소나 시험 제외로 합의하지 않았습니다. 지지면 협의는 [#134](https://github.com/Jik-Kim/ready2go/issues/134)에서 관리합니다. 지원 범위 협의가 남으며 코드 병합은 실제 운영 연결·승인된 wire·실물 검증과 구분합니다. 진행·인계는 [#152](https://github.com/Jik-Kim/ready2go/issues/152)·[#153](https://github.com/Jik-Kim/ready2go/issues/153)을 확인하십시오.
- [문서] PR #144 MeloTTS·캐시·중단 안내와 #160/#161/#162 실행 안내는 기준 main에 반영됐습니다. 오래된 Open·미병합 및 당시 로컬 게시 대기 표시는 날짜별 이력으로만 읽습니다. #134의 D #158 최신 상태와 전체 설치/실물 완료는 이번 작업에서 다시 확인하지 않았습니다.
- [문서] 공통 [manifest](../../knowledge/robot_ontology.jsonld)·[pick](../../knowledge/skills/pick.jsonld)과 [정식 태스크](../../tasks/find_item.json)가 현재 실행 원본입니다. E 음성의 실제 구현·진단·시운전은 [Voice README](../../ros2_ws/src/ready2go_voice/README.md), 로더는 [Knowledge README](../../knowledge/README.md)를 참조합니다. 과거 시연 전용 정의를 현재 실행 원본으로 복원하지 않습니다.
- [문서] 작업 시작 당시 사용자 변경16개를 승인된 stash에 보존했던 이력은 당일 기록에 남깁니다. 이후 사용자 “stash 폐기” 요청으로 해당 stash가 제거됐으며 현재 stash 목록은 비어 있음을 확인했습니다. 이번 PR 보완에서는 stash를 복원·변경하지 않았고 다른 브랜치·worktree·로컬 키/모델/로그도 변경하지 않았습니다.

## 막힌 점 · 필요한 도움

- [문서] 이번 작업은 문서 정합성·FR/AC 정의 및 Phase 유지·기존 앵커/링크·실행 원본과 소비 코드 경계를 대조합니다. 전체 pytest/build·설치·마이크/API·실물 시험은 실행하지 않습니다. 과거 26건 정책·156건 회귀·595건 ROS/모의 결과는 [당시 기록](2026-10-08_practice.md)의 결과이며 이번 재실행이 아닙니다.
- [문서] A/B/C/D와 공통 문서 소유자의 중복 기준 정리, 가림 관계·재식별 adapter, 지지면 복구 범위 협의, 안전 wire 계약 승인(E 포함 2명)·스키마/예시/문서 동시 반영이 남습니다. 링크 정리는 자동 검사·운영 연결 구현이 아닙니다.
- [문서] 기존 비요청 판별 결함, 웨이크/runtime 배포, 운용 PC 캐시·청취 품질·실음성 평가·C/D 수신, A/B 재관측/파지 및 안전 정지·복구·재개·실물 AC는 완료로 판정하지 않습니다. 수용 기준은 [AC 목록](../../docs/requirements.md#ac-index)을 참조합니다. E는 nudge 시험 담당에서 제외합니다.
- [문서] 사용자 “#180 리뷰 확인하고 수정해” 승인 범위로 요구사항 정본과 E 기록3파일의 문서 보완·검증·커밋·기존 PR push를 진행합니다. 이번 보완은 근거 링크·평가 장면/담당 경계·높이 기준과 현재 인계 상태를 정리하며 추가 댓글은 작성하지 않습니다. 타 담당 문서 반영·계약 승인·병합·새 이슈·Slack은 이번 범위에 포함하지 않습니다.

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
