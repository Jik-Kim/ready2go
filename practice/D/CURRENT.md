# CURRENT — D 김민준

- **담당**: 기록 · 문서 · 평가 자료 · **현재 Phase**: P2 (P1 기록 병행)
- **최종 갱신**: 2026-10-13

## 지금 상태
- [코드·문서·실측] PR #288 추가 검토를 반영해 graph 조회 사이에 publisher 수가 계속 1이어도 endpoint GID 집합이 바뀌면 이전 세대 payload를 초기화하도록 보강함. 메시지 revision을 함께 비교해 새 publisher 콜백이 graph 확인보다 먼저 도착한 경우 그 새 값은 보존함. 휴대폰·다른 PC 접속용 `WEB_HOST=0.0.0.0` 실행 명령도 별도로 명시했으며 로컬 CycloneDDS 웹 시험 `63 passed`를 확인함. 실제 Runner의 빠른 재기동과 휴대폰 접속은 미검증임.
- [문서] 이슈 #267 C 회신을 반영해 `/runner/status`·`/robot_state`가 내용 변경 때만 발행되고 `RELIABLE`·`TRANSIENT_LOCAL`·`KEEP_LAST(1)`을 사용한다는 현재 동작을 기록함. `/robot_state`의 실제 필드(`robot_pose`·`gripper`·`open`·`located_in`)는 effect 뒤 Runner 기억 상태이며 좌표·관측 시각이 없음을 구분하고, Runner 기동 때 한 번 읽는 온톨로지·태스크·인텐트 원본 경로를 정리함. 최상위 실행 `run_id`·`current_skill`과 PR #286 필드는 승인 전 제안으로 남겼으며 실제 4·5단계 구현 완료를 뜻하지 않음.
- [코드·문서·실측] 이슈 #267 3단계 읽기 전용 REST를 `web/ready2go_web/server.py`에 구현하고 브라우저가 `web/status-api.js`를 통해 `GET /api/status`를 약 1초마다 조회하도록 연결함. 응답에는 형식 버전·서버 시각·권장 조회 간격과 잠금 캐시 스냅샷을 담고, 캐시 미연결 503·스냅샷 실패 500을 구분함. 기본 화면은 Runner 연결 진단만 실제 값으로 갱신하며 고정 목업 시나리오는 조회하지 않음. 실제 시험 publisher로 REST `receiving`·원본 JSON 수신, 서버 중단 오류 표시·재시작 자동 복구, publisher 종료 뒤 연결 끊김 전환을 확인함. 실제 Runner·다중 PC·실물 장비는 미검증임.
- [코드·문서·실측] 이슈 #267 2단계 `/runner/status` 연결을 `web/ready2go_web`에 구현함. Flask 프로세스가 전용 ROS context와 별도 `SingleThreadedExecutor`에서 단일 `DashboardBridge`를 실행하고, `std_msgs/msg/String` JSON 객체를 잠금 `StateCache`에 저장함. 2단계 당시에는 runner source만 활성화하고 REST·화면 반영을 보류했음. 당시 로컬 CycloneDDS 전체 시험 `57 passed`, 실제 진입점의 HTTP 200·ROS graph 단일 구독·종료 후 노드 제거를 확인했으며 실제 Runner·다중 PC·실물 연결은 미검증이었음.
- [문서·코드] PR #237 재검토의 빈 관측·근거 자동 통과 P1을 로컬에서 보완함. 전용 검증기는 machine check evidence를 비어 있지 않은 문자열 목록으로 강제하고 문자열 단독·빈 문자열 항목을 거절하며, `automatic_result=pass`의 observed·expected가 `None`·공백 문자열·빈 목록·빈 객체이면 통과시키지 않음. trial evidence도 목록 타입과 비어 있지 않은 문자열 항목을 검사함. S10의 빈 observed·expected, `evidence=[""]`, 문자열 evidence와 pass trial의 빈 근거 항목 반례를 추가함. 평가 JSON·결과 JSONL·Voice 정답표는 변경하지 않았고 실제 trial은 0건임.
- [문서·코드] PR #237 최신 재검토의 Voice 자동 판정 P2를 반영함. 전용 검증기는 모든 suite의 `automatic_result=pass`에 비어 있지 않은 trial 근거와 machine check를 요구하고, 각 check가 `status=pass`이며 observed·expected·evidence를 갖는지 공통 검사함. `voice`·`voice_issue194_regression`은 기존 Voice 정답표에 JSONL용 필수 check ID 매핑이나 별도 판정기 계약이 없으므로 이를 임의 생성하지 않고 자동 pass를 보류하며 fail·inconclusive·not_evaluated 기록만 허용함. 실패 check를 포함한 pass, 빈 check·빈 trial evidence의 pass, #194 회귀 pass 우회를 거절하는 회귀 시험을 추가함. `0.5-draft` 평가 JSON·결과 JSONL·고정 SHA-256은 변경하지 않았고 실제 trial은 0건임.
- [문서·코드] PR #237 재검토의 basis 참조 무결성 P1을 반영함. 전용 검증기가 basis 레코드를 먼저 수집해 비어 있지 않은 고유 `basis_id`, `mock`/`sim`/`real` 환경, 40자리 git `code_sha`, sources·human_approvals 목록 형식을 검사하고, 모든 trial이 정확히 하나의 basis를 참조하며 trial·basis 환경이 일치하도록 강제함. 누락·중복·미참조 basis와 잘못된 환경·SHA·환경 불일치를 거절하는 회귀 시험을 추가함. 평가 정의·결과 JSONL과 0.5-draft SHA-256은 변경하지 않았고 실제 trial은 0건임.
- [문서·코드] PR #237 재검토의 S10 필수 안전 증거 P1을 반영함. 전용 검증기가 part/recovery trial의 suite·case_id를 실제 평가 정의에서 조회하고 필수 machine/human check 집합을 정확히 대조하도록 보강함. `automatic_result=pass`는 모든 필수 machine check가 `status=pass`이고 observed·expected·비어 있지 않은 evidence를 가질 때만 허용하며, 누락·실패·unverifiable·사람 확인 ID 누락·존재하지 않는 case_id를 거절하는 회귀 시험을 추가함. 평가 정의와 결과 파일의 0.5-draft 내용·SHA-256은 변경하지 않았고 실제 trial은 0건임.
- [문서·코드] PR #237 재검토의 평가 버전 추적 P1을 반영함. `0.5-draft` 정의·결과를 `issue196_evaluation.v0.5-draft.json`·`issue196_results.v0.5-draft.jsonl`의 불변 파일 쌍으로 회전하고, 버전 변경 시 기존 파일을 덮어쓰지 않고 새 쌍을 생성하도록 고정함. `result_set`과 각 trial은 `result_set_id`·평가 버전·평가 원본 SHA-256·suite 버전으로 연결하며, Voice 참조 정답표도 원본 SHA-256으로 고정함. 전용 검사와 회귀 시험은 정의 해시 변경, 평가/suite 버전 혼합, 복수 result_set 및 허용하지 않은 레코드를 거절함. 실제 trial 레코드는 여전히 0건임.
- [문서·코드] PR #237 리뷰의 결과 집계·자동 판정·안전 게이트 지적을 반영함. append-only JSONL의 첫 메타데이터에서 가변 `status`·`trial_count`를 제거하고 trial 레코드 수로 파생하도록 했으며, 파트 25건 전체에 사례별 필수 machine check 매핑과 같은 trial의 근거·상태 판정 규칙을 추가함. S10은 명시적 복구 요청·실제 정지·안전한 힘·최신 센서/통신·컨트롤러 준비·B 복구·C 잠금 해제·자동 재개 0회와 `H-STOP-01`·`H-AREA-01`·`H-HW-01`을 모두 필수화함. 전체 평가 `0.5-draft`, 파트 `0.4-draft`, 복구 `0.2-draft`이며 실제 trial 레코드는 0건임.
- [문서·코드] 이슈 #196 체크리스트를 보조하는 신규 파일로 버전 고정 `issue196_evaluation.v0.5-draft.json`과 `issue196_results.v0.5-draft.jsonl`을 구성함. 요구사항 정본·런타임 계약을 대체하지 않는 D 평가 초안임을 `artifact_roles`에 명시하고, E/CE 5건의 시트 변경을 평가 JSON에 동기화함. 결과 JSONL은 같은 평가 버전을 참조하며 실제 시험 전에는 불변 메타데이터 한 줄만 두고 trial 수·상태는 trial 레코드에서 파생함. 로컬 분리 초안 6개는 추가하지 않음.
- [문서] 이슈 #196 개편안 사본의 E/CE 파트 검토를 반영함. E-02는 E의 목표·대상 해석 및 발행 보류와 C의 계획·실행, B의 실물 검증을 분리하고 `FR-INT-02`를 연결했으며, CE-02는 안전 계약 문서·스키마·예시 정합성 대조로 목적을 명확히 하고 `FR-SAF-01~03`·`AC-SAF-02~04`·`FR-LOG-02`를 연결함. CE-01은 성공 때만 effect 반영 및 실패 경로 상태 미갱신, E-01은 발화 종료→첫 PortAudio DAC 3초·실제/mock 구분, E-03은 문서 준비와 운영 연결·실물 검증 분리를 기대 결과에 보강함. `06_사람확인`에는 E-01 `H-VOICE-01`을 추가하고 관련 CE/E 확인 문구를 맞췄으며, 담당 열의 잘못된 검증 규칙과 결과 초기값을 각각 일반 텍스트·`대기`로 정정함. 실제 trial·검증 완료를 뜻하지 않음.
- [문서] 이슈 #196 개편안 사본의 `06_사람확인`에 `02_파트별시험`의 `H-EVIDENCE-01` 필수 사례 15건을 사전 등록함. 사례별 근거 일치 확인 문장·담당·필수 여부를 명시하고 결과는 유효한 초기값 `대기`로 두었으며, 실제 시험 전에는 `trial_id`·확인 시각·근거를 임의 생성하지 않음. 실제 시험 후 해당 값을 연결하고 사람 확인이 통과되어야 최종 통과하도록 운영 안내를 보강함.
- [문서·코드] C 10/12 Runner 점검을 반영해 S23 이전 boot 응답의 기대 코드를 `BOOT_MISMATCH`로 명시하고, 차단 판정은 직접 필드가 아니라 `halts[]` 이후 동작 없음·잠금·후속 `ABORTED`/`LOCKED`를 결합한 평가자 파생값으로 정의함. main `80270cd`, C 점검 `e0faa0f`, 승인 대기 계약 `954ed61`을 서로 다른 basis 후보로 구분하고, 계약 브랜치 전용 질문·요청·상태 필드는 해당 source가 없는 회차에서 임의 생성하지 않도록 당시 평가 세트를 `0.3-draft`로 갱신함. S31~S33은 계약 승인 전 제안이므로 추가하지 않음.
- [문서·코드] 이슈 #196 체크리스트 보조 평가 자료로 `issue196_evaluation.v0.5-draft.json`에 파트별 25건·정지/복구 30건·사람 확인 7종과 기존 음성 정답표 참조를 구성하고, `issue196_results.v0.5-draft.jsonl`을 실행결과 저장소로 생성함. 결과 파일에는 불변 데이터셋 메타데이터만 있으며 실제 trial 레코드는 0건임. 사람의 현장 확인·최종 승인·미달 후속은 Google Sheet에 기록하며, 이 초안은 런타임 계약 승인이나 모의/실물 검증 완료를 뜻하지 않음.
- [문서·코드][정리 완료] 먼저 작성했던 `issue196_evaluation_manifest.json`과 분리된 파트·복구·사람 확인·basis/trial Schema 6개는 통합 정본과 중복되므로 제거함. 필요한 ID·결과 기록 규칙은 통합 평가 JSON에 보존하며, 모든 시험에 일반 `request_id`를 강제하지 않고 `case_id`·`trial_id`·`basis_id`만 공통으로 두고 정지·복구 상관관계 ID는 해당 경로에서만 기록함.
- [문서] PR #207 리뷰의 문서 정합성 인계를 반영해 선행 연구 보고서의 2cm를 작성 당시 기준으로 구분하고, 현행 원위치 복구 기준은 요구사항 정본 [AC-ACT-03](../../docs/requirements.md#ac-act-03)으로 연결함. FR-ACT-04·AC-ACT-03·Phase P2 범위의 문서 정리이며 E 기준 확인·PR 병합·실물 검증 완료를 뜻하지 않음.
- 요구사항 기준 문서 `docs/requirements.md`를 작성하고 문서 인덱스·Phase 요약·기술 문서 링크를 정리함.
- [문서] 이슈 #20 음성 평가용 40문장·실제 결과·미달 기록 틀을 `practice/D/issue20_voice_evaluation.json`에 작성함.
- [문서] 모호 요청은 사용자 확정 정책인 `clarify`·빈 targets·실행 보류로 기록함. 미지원 문장의 `unknown`/`clarify` 선택과 전체 정답표의 D 수락은 아직 대기 상태임.
- [문서] TTS 시간 항목은 AC-INT-03 때문에 유지하되 현재 값은 `not_measured`와 `null`로 둠.
- [문서] 검토 의견을 반영해 평가 JSON을 0.2-draft로 갱신함. TC-008을 “지우개 찾아서 건네줘.”로 정정하고 LLM 호출·응답·검증, 실행 후보·발행·실행 시도, 실제 TTS 재생 지연을 분리함.
- [문서] 사용자 확정 모호 요청 정책(`clarify`, 빈 targets, 실행 보류)을 기록했으며 D 수락·정답표 동결·실제 평가는 별도 상태로 유지함.
- [문서] PR #94 리뷰를 반영해 TTS 기준값을 실제 구현 출력인 `portaudio_first_dac`와 테스트 더블의 `mock`에 맞추고, 실제 음성 3초 통과 조건도 `portaudio_first_dac` 기준으로 정정함.
- [문서] 추가 검토를 반영해 검증 가능 응답 분모가 0이면 실패율을 미측정으로 처리하고, E 원본 `llm_error`와 수동·파생 실패 분류를 분리함. 실제 audio 정확도와 text 디버그 집계, 반복 발화와 고유 문장 수도 구분함.
- [실측] 이슈 #112 최신 PM 검토의 녹화 범위에 맞춰 기존 `web/` 정적 목업을 정리함. 모든 화면에 목업 데이터·실제 장치 미연결 안내를 유지하고, STT 원문과 작업 중단 버튼·로컬 중단 완료 동작을 제거함. 음성·로봇·카메라는 확인 전, Runner는 상태 수신 대기로 표시하며 PC 가로·모바일 세로 작업 단계와 확인 이유·관측 결과는 유지함. 읽기 전용 검토 화면의 현재 상태·온톨로지는 우선 연결 대상으로, 계획 근거·실행 기록은 샘플 결과 없이 후속 연결 안내로 구분함. 실제 Flask·rclpy·ROS 2·온톨로지·MongoDB 연결 또는 기능 완료를 뜻하지 않음.
- [문서] `web/README.md`에 이슈 #112의 변화 과정과 최신 PM 검토, 파일 역할, 녹화 우선 연결 범위, STT·중단·연결 상태 변경 이유, 향후 데이터 어댑터 교체 지점, PC·휴대폰·다른 PC 접속 및 URL 시나리오를 기록함. 공통 Git·PR 정책은 루트 `AGENTS.md`를 참조함.
- [문서] 이슈 #134의 D 담당 문서 정합성을 반영해 P1 안전 검사와 P2 관측 검증 계획, 현재 ROS 제공·소비 관계, `runs`·`steps`와 P2 `states`, 재관측 `scan.target` 집기, PR #129·#130 완료 상태를 구분함. 최신 main의 P2 BFS·`achieve_goal` 실행 및 계획 로그 구현과 `/planner/plan`·시연 화면 미연결, Voice의 `/runner/status` 소비를 추가 반영하고, PR #164의 공통 pick 제한 시간 70초를 knowledge 안내와 맞춤. 공통 작업 영역 자동 검사·`WORKSPACE_VIOLATION`은 미구현이며 사람 점검과 향후 계획으로 분리함. 협동 모드·힘 제한은 적용 완료로 단정하지 않고 Skills 명령 속도 설정, B의 컨트롤러 96 N 보호정지 기록, 미확인 펜던트 설정으로 분리함. 문서 정정은 새 PC·장치·실물·AC 검증 완료를 뜻하지 않음.
- [문서] 이슈 #153 지원 범위 중 #20 음성 평가 JSON 형식을 보완함. 40문장에 문장별 기대 intent/targets/응답/실행 정책 칸을 추가하고, 미지원 10문장의 `unknown`·`clarify` 선택은 `pending_sentence_level_decision`으로 남김. 실제 입력 경로·녹음 계획과 intent/targets/응답/실행/TTS 항목별 판정 필드도 추가했으며 정답 승인·실제 평가 완료를 뜻하지 않음.
- [문서] #153 스프레드시트의 C-01을 PR #164 병합 결과(`find_item` s5.1·`p1_demo_eraser` s3·플래너 기본 `pick=70`, SHA `908718a`)에 맞추고, `04_정지복구`의 중복 머리글 `J5:K5`·`AI35:AQ35`를 제거함.
- [문서] #152 C v1 보충안의 `boot_id`·`seq`·`stamp`, 재기동 세대 무효화·오래된 상태 폐기·재개 응답 재검사·`RESUME_EXPIRED`와 E의 TTS 실패·지연·재생 중 요청·자기 음성 사례를 `04_정지복구`에 반영함. 사례표는 28건이며 C·E 확인·계약 승인·모의/실물 시험 완료를 뜻하지 않음.
- [문서] #153 추가 보완 범위만 반영해 파트별 준비를 14건으로 확장하고, 음성 완료 기준 요약·cancel/status 보조 시험, 정지·복구 TTS 실패·지연·재생·자기음성 전용 기록 열, 담당 수락·선행 조건 현황을 추가함. 기존 시험 결과와 완료 판정은 변경하지 않음.
- [문서] 사용자 지시, 음성 정책 정본과 이슈 #194 결정 `E-VOICE-UX-20261009-01`을 기준으로 기존 40문장 AC-INT-01 평가 분모는 유지한 채 `issue20_voice_evaluation.json`을 schema 1.8 / `0.6-draft`로 확장함. 인용형 전체 요청, 부정·번역·설명 예문, 현재 질문의 일회성 소비, 대상 정정, 취소·새 요청·만료·재시작, 가능 여부 질문, 미등록·미지원·Runner 태스크 미지원 원인, 최종 문장·화면·TTS 일치, TTS·발행 실패/취소 경합, 내부 LLM 응답·공개 확인 안내 분리의 12개 #194 회귀 시나리오를 별도 필수 세트로 추가함. 무효 문맥은 `clarify`·빈 targets·과거 대상 미복원으로 고정하고, controlled context와 실제 audio motionless 결과를 분리함. 진단 파일·Runner 수락·별칭 원본은 담당 경계를 넘는 D 시나리오로 만들지 않고 외부 검증 상태·증빙으로만 연결했으며 D·E 수락·버전 동결·실행 결과는 아직 아님.
- [문서] PR #200 1차 검토를 반영해 모든 expected 판정 필드와 화면·TTS 응답 일치가 시나리오·suite 합격을 좌우하도록 채점 규칙을 연결했으며, 첫 DAC 전 TTS 실패는 시작 시각·지연을 `null`/`not_measured`로 기록해 AC-INT-03 성공으로 집계하지 않도록 분리함. 이는 Runner 지원 추가나 실제 평가 완료를 뜻하지 않음.
- [문서] PR #200 재검수에서 Voice 발행과 Runner 보류를 하나의 게이트로 채점한 P1을 정정함. controlled 트랙은 `voice_execution_allowed`·Voice 발행 시도·C IntentRouter 입력/결정/원본 사유·평가용 사유 정규화·실제 로봇 동작 시도를 분리하고, 등록 비지우개도 Voice 발행 1회 뒤 C가 `UNSUPPORTED_ITEM`으로 보류하도록 기록함. actual audio motionless 트랙은 실제 발행·Runner 입력·로봇 동작 0회를 유지함. #194 승인 예문은 `find_item`·`toy_hammer`로 해석하며 실제 시험 미완료 상태는 그대로 구분함.
- [문서] 같은 재검수의 P2·정합성 지적을 반영해 현재 질문 결합 문구를 구현이 정확히 인식하는 `그걸로`, 취소 문구를 설정 원본의 `취소`로 맞추고, 미등록 물품·미지원 요청의 공개 최종 문장을 런타임 상수와 마침표까지 일치시킴. 기준 snapshot은 병합된 PR #198 최종 head `2296b5d`와 merge commit `667f0b8`로 갱신했으며 ontology·task 원본 해시는 재계산 결과 변동 없음.
- [문서·실측] PR #200의 C 회신을 반영해 `external_verification.runner_acceptance`를 C 문서·모의 확인 완료/E 확인 대기로 갱신함. C는 head `238ae08`의 Runner 입력 기대 31건을 main `d52c1bb` IntentRouter와 대조해 불일치 0건 및 보류 시 실행 미시도를 확인했으며, 실제 Voice payload 형태·hold/reject DB 기록·실물 로봇·실제 웨이크/STT는 미검증으로 유지함.
- [문서·코드] PR #200 최신 E 재리뷰의 P2 3건을 반영함. 대상 정정은 현재 질문의 답으로 즉시 `find_item` 확정되도록 고치고, 소비·취소·대체·만료·재시작 뒤 문맥 없는 응답은 과거 질문 종결 상태와 TTS 성공 후 새 `target=null` 질문을 분리해 기록함. Voice가 출력하지 않는 `question_already_consumed`·`no_active_question` 기대 사유를 제거하고, `UX194-012`는 guard에서 끝나지 않고 실제 LLM 경로에 진입하는 입력과 명시적 테스트 더블 후보로 교체함. 이는 D 평가 자료 정정이며 Voice/Runner 기능 변경이나 실제 평가 완료를 뜻하지 않음.
- [문서·코드] PR #200 추가 P2를 반영해 `UX194-012`의 LLM 테스트 더블에 실제 `LangChainIntent.schema` 필수 필드인 `response_text`·`rejection_reason`을 명시적 `null`로 추가함. `IntentParser` 주입 전에 실제 어댑터 스키마 검증을 통과해야 하며 그 결과가 `pass`여야 단계가 합격하도록 schema 1.8 / 평가 세트 `0.6-draft` / #194 suite `0.4-draft`로 갱신하고, 정답표 동결 대상도 평가 세트와 같은 `0.6-draft`로 맞춤. 시나리오의 intent·targets·공개 안내·실행 기대 의미는 변경하지 않음.
- [문서] 이슈 #134의 Voice 진단 정합성 지적에 따라 `issue20_voice_evaluation.json`에 원래 `diagnostic_file` 설정값·실행 cwd·실제 상세 JSONL 경로와 `request_id` 결합, 최상위 `published`와 `interpretation`·`tts_finished` 필드 매핑, 회전 파일·누락 증빙 처리 절차를 추가함. 콘솔·tee는 진행 요약으로만 사용하며 실제 JSONL 샘플 대조·음성 평가와 E 문서 정정·운영 연결 완료는 별도 상태로 유지함.
- [문서] 이슈 #168의 노드 카드 8건·상황별 시나리오 18건을 `practice/D/issue168/checklist.yaml`에 정리하고, 담당 확인·구현·결정 상태와 근거를 분리함. B의 교시·실측·파라미터 값과 mock·실물 시험 결과는 복제하지 않고 원본 경로 및 Google Sheet 기록으로 분리함.
- [실측] `tools/sync_issue168_checklist.py`의 YAML 검증과 Google 서비스 계정 인증 dry-run에서 `PASS: 8 node cards, 18 scenarios`와 관리 대상 셀 `NO CHANGES`를 확인함. 실제 `--apply` 쓰기와 담당자 PC 별도 키 검증, 담당 승인 및 mock·실물 시험 완료를 뜻하지 않음.
- [문서] PR #205 검토를 반영해 오류 코드 허용값을 `knowledge/skills/*.jsonld`와 Runner·Skills·Vision 실행 원본에서 읽도록 변경하고, YAML 항목 타입·시트 표시 코드 정합성·`00_진행현황!A9:D9` 관리 표식을 쓰기 전에 검사하도록 보강함. 사용자 메모가 있는 A9:D9는 덮어쓰지 않음.
- [실측] 정상 체크리스트 `PASS: 8 node cards, 18 scenarios`, 실행 원본 오류 코드 5종(`DRAWER_STUCK`·`CLOSE_NOT_CONFIRMED`·`TRAY_FULL`·`NOT_VISIBLE`·`CAMERA_TIMEOUT`) 수용, 잘못된 YAML 4종의 오류 목록 반환, 메타데이터 표식 3종의 허용·거부를 로컬에서 확인함. 실제 Google Sheet 쓰기 검증을 뜻하지 않음.
- [실측] PR #205 리뷰를 반영해 복수 저장소 파일 근거와 담당자별 확인 상태의 시트 변환 가능 여부를 검증하고, 실제 `--apply`는 현재 `HEAD`에 같은 내용으로 커밋된 체크리스트만 허용하도록 보완함. 로컬 오류 주입으로 누락된 복수 경로·변환 불가 상태·외부 및 미커밋 YAML 차단을 확인했으며 실제 Google Sheet 쓰기 검증 상태는 계속 대기임.
- [실측] PR #205 재검토의 P2 지적을 반영해 `source_catalog.type`을 다섯 가지 지원 타입으로 제한하고 GitHub URL·단일 경로·복수 경로의 타입별 필수 필드를 검증함. 오타 타입과 필수 필드 누락 오류 주입을 차단했으며 체크리스트 내용과 실제 Google Sheet 쓰기 검증 상태는 변경하지 않음.
- [문서·실측] PR #205 추가 검토를 반영해 GitHub 근거 URL을 `Jik-Kim/ready2go`의 이슈·PR·`#issuecomment` 형식과 타입별로 대조하고, `sheet`의 ID·URL·관리 탭·단방향 설정을 인증 전에 검증함. 잘못된 URL 5종과 시트 설정 4종을 차단하고 유효한 URL 4종 및 기존 체크리스트 통과를 확인했으며, 링크의 실제 존재 확인이나 Google Sheet 쓰기 검증을 뜻하지 않음.

## 확정 값 (근거 태그 필수)
- [문서] #153 P2 준비 범위에 맞춘 [Google 스프레드시트](https://docs.google.com/spreadsheets/d/14-W4kRl2PwarUf2W_R0VB2BggL5sMCX2om0YI2odnTo/edit)를 생성함. 준비현황·실행기준·파트별시험·음성평가·정지복구·미달후속 6개 탭에 파트별 준비 14건, 음성 40문장, 정지·복구 사례 28건을 구성함. 결과는 미실행이며 안전 요구사항 정본은 미확인·반영 보류, 미지원 음성의 unknown/clarify 정답은 미확정임. JSON 자동 동기화나 평가·안전 승인을 뜻하지 않음.
- [문서] #152 본문과 B·C 제안 댓글, C v1 보충안을 대조해 같은 스프레드시트의 `04_정지복구`를 사례표 28건·실제 시험 기록표·C/E 기록 항목 대조표로 재구성함. 정지 사건 ID, 복구·재개 결정/거절 코드, 잠금·명령 차단, 기동 세대·상태 순서·최신성, 재진입·effect 기록을 추가하고 근거를 본문/제안/팀 확인 필요/양식 설계로 구분함. `00_준비현황`, `01_실행기준`, `05_미달후속` 연결 항목도 보완했으며 담당자 확인·계약 승인·모의/실물 시험은 완료로 표시하지 않음.

| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 요구사항 기준 원본 | `docs/requirements.md` | [문서] |
| Phase 1 필수 로그 | MongoDB 기본 실행 이력, JSONL은 장애 시 폴백 | [문서] `docs/requirements.md` |

## 막힌 점 · 필요한 도움
- 이슈 #20 TC-031~TC-040의 문장별 `unknown`/`clarify` 및 허용 응답 정책을 E·D가 확정해야 함.
- 화자 2명의 화자 ID별 녹음·현장 발화 배정을 확정해야 함. 실제 이름은 필수 항목이 아님.
- [문서] 웹 연결 구현은 이슈 #267의 순서를 따름. `/runner/status` 수신·캐시와 REST 응답·화면 반영은 구현됐고 `/robot_state` 현재 source 계약도 C 회신으로 확인됨. 다만 실행 상태와 요청 결과를 항상 연결할 최상위 `run_id`, 선택 `current_skill`, PC2 포트·방화벽·Wi-Fi 단말 간 통신은 별도 확정 또는 현장 확인이 필요함.

## 다음 할 일
- [ ] 이슈 #267 4단계 `/robot_state`를 확인된 필드와 기억 상태 의미 그대로 같은 캐시·REST 경계에 연결
- [문서] 2026-10-07: P3 PC·모바일 웹 대시보드 제안 [#112](https://github.com/Jik-Kim/ready2go/issues/112)을 목업과 함께 등록하고, 최신 작업 상세 목업까지 기존 `web/` 시제품에 반영함. 이벤트 기록은 제외했으며 기존 P1 표시 이슈 #59와 구분함. 연동 담당·계약·일정은 협의 전이고 구현 완료를 의미하지 않음.
- [ ] E와 이슈 #20 기본 정답표 및 #194 회귀 시나리오를 승인하고 `evaluation_set_version`·`suite_version`을 고정
- [ ] 화자 ID별 발화 배정·녹음 형식·보관 경로를 반영
- [ ] 모션 없는 40문장 평가 결과와 미달 기록 입력

## 철회한 결론
-
