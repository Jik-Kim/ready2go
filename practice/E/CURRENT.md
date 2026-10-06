# CURRENT — E 고희태

- **담당**: 통합 지휘 · 하드웨어 · 음성 · LLM · 온톨로지 (조장) · **현재 Phase**: P1
- **최종 갱신**: 2026-10-05

## 지금 상태
- #1·#8 최신 결정에 따라 hardware·metrics_risks의 서랍 재질/레일·높이 기준 문구를 정정함. 작업 브랜치 `codex/hardware-doc-alignment`, 기준 main `f6c2aa4`. 사용자께서 문서 수정·로컬 커밋·push·새 PR 생성을 승인함. [문서]
- 일반 후보 높이 1.5 cm 유지, 지우개만 예외. 새 서랍 가운데 파지 3/3은 해당 조건의 결과이며 전체 배치·모든 물품 검증 완료가 아님. [#8 결정](https://github.com/Jik-Kim/ready2go/issues/8#issuecomment-5980582810) [문서]
- PR #46은 병합됨. #70~#73은 이번 확인 시점에 미병합이며 승인·병합·추가 변경은 본 문서 작업 범위 밖임. `DRAWER_NOT_AT_TRAVEL`의 실제 노드 연결·실물 검증은 후속 확인 사항임. [문서]
- `f123f50` head의 [원격 CI 실행 127](https://github.com/Jik-Kim/ready2go/actions/runs/37179524578)은 contracts-and-core·ros-build·compose 모두 성공했습니다. 아래 로컬 검증 기록과 구분하며, 후속 커밋의 CI 결과를 대신하지 않습니다. [문서]
- PR #46 재검토 수정과 main `5350bd9`(#58 TF 정정·#61 pose 규칙 포함) 통합을 완료했습니다. 작업 브랜치: `codex/ontology-review-fixes`. 사용자 승인 후 지정 PR 세션을 통해 커밋 `f123f50`의 push·기존 [PR #46](https://github.com/Jik-Kim/ready2go/pull/46) 갱신·Draft 해제를 완료했습니다. 당시 PR은 Open·Ready for review였으며 이후 병합됐습니다. [문서]
- 시연 최소 표시·터미널 대체와 D 담당·C 검토·E 데이터 인계를 복원하고 이슈 #59 참조를 17.4·17.5·17.6으로 갱신했습니다. 실제 담당별 데이터 연결·수락·완료는 별도 확인 사항입니다. [문서]
- #8의 실측/외접박스 표 11종·12개를 world 원본에 반영했습니다. 등록 물품 전체가 P1 단일 요청 대상이며 최종 파지 승인은 별도입니다. [문서]
- 파지 힘은 item_grasp.yaml의 null, 승인 상태는 false로 두었습니다. 미확정 설정 거절 함수 제공과 B/C 실물 경로 연결은 구분합니다. [문서]
- 공용 ontology/interfaces/hardware/README와 연관 예시·프리셋을 갱신했습니다. 높이 1.0 cm 일괄 변경이나 실물 위치·시험 성공을 임의 확정하지 않았습니다. [문서]
- 온톨로지 작성 원본을 classes·world·스킬 파일로 분리하고, `robot_ontology.jsonld`는 공통 context와 참조 목록으로 구성했습니다. [문서]
- E 로더가 분리 파일·초기 상태 프리셋·장소 YAML을 연결하고 기존 `classes/world/state/skills` 조회 구조를 반환합니다. [문서]
- 장소 설정의 정본은 `config/places.yaml`이며 공통 식별자로 결합합니다. 미측정 null은 유지합니다. [문서]
- 기존 복합 스킬 이름을 `handover_with_unpack`으로 변경했습니다. 태스크 경로와 동작 정의는 유지했습니다. [문서]
- 초기 상태 프리셋은 `knowledge/snapshots/initial_state.json` 하나로 유지합니다. 실제 상태 확인·적용·저장은 Runner 책임입니다. [문서]

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 장소 설정 정본 | `config/places.yaml` | [문서] 사용자 합의 |
| 연결 식별자 | `world.places`와 YAML의 동일 장소 키 | [문서] 사용자 합의 |
| 복합 스킬 이름 | `handover_with_unpack` | [문서] 사용자 지정 |
| 물품 치수 순서 | `size_m = [긴 변, 짧은 변, 높이]`, m | [문서] #6·PR #46 PM 코멘트·병합된 #61 대조 |

## 막힌 점 · 필요한 도움
- 구매 기록에서 실제 제품명은 확인하지 못함. PR 구매 기록은 “제품명 미확인 / 철제 고정대 + 원목 2단 서랍장(금속 레일)”로 보고하며 제품명 확인이 필요함. [문서]
- E 포함 2명 계약 승인은 미확인입니다. 사용자 수정·push 승인을 팀 계약 승인으로 대신하지 않습니다. [문서]
- TODO(A): lip_balm 외접박스 높이 20.0 mm/이전 20.2 mm 보고의 차이를 확인해야 합니다. size_m 로컬 축/yaw 기준은 #6·#61에 맞춰 정렬했습니다. [문서]
- TODO(B·E): 물품별 힘·파지점·반복성·실물 실행 검증(일반 높이 기준 유지·지우개 예외는 #8에서 확정); TODO(C): require_grasp_settings와 실제 실행·TTS·인스턴스 상태 연결. [문서]
- TODO(C 이영훈): 태스크 스킬 호출·실패 상태 계약 및 로그의 전체 구성 해시 기록 연결이 필요합니다. [문서]
- TODO(B 서동권): 접근 동작 책임과 미측정 설정의 실행 전 검사 계약 확인이 필요합니다. [문서]

## 다음 할 일
- [x] 사용자 승인 후 지정 PR 세션 인계, `f123f50` push·PR #46 갱신·Draft 해제 및 해당 head의 원격 CI 성공 확인
- [ ] E 포함 2명 계약 승인과 #59 D/C/E 데이터 연결 확인
- [ ] A가 고정된 클래스 번호를 사용해 촬영·라벨링 시작
- [ ] C·B와 실행 계약 보완 사항 확정

## 철회한 결론
- ~~drawer_top TF는 항상 null~~: #56·#58 실측/정정에 따라 원본 YAML 값과 비교하고 null은 독립 fixture로 검증합니다. [문서]
- ~~size_m = [폭, 길이, 높이]~~: #6·#61의 긴 변 방향 yaw에 맞춰 앞 두 치수를 정렬했습니다. [문서]
- 진입점 JSON을 직접 읽으면 전체 정의가 나온다는 기존 가정은 파일 분리 후 사용할 수 없습니다. [문서]

## PR #46 문서 정합성 보완
- requirements.md를 기준으로 ontology·시연·인덱스·일정의 참조와 구현/계획 구분을 정리했습니다. [문서]
- 최신 main 통합: PR #45의 manifest 호환 데이터셋 로더·학습 README와 PR #48의 새 서랍 YAML 설정을 유지했습니다. [문서]
- 최초 번호 파일은 10/04 아래 조치로 생성했습니다. 촬영·라벨링은 A, 파지 실행 연결·실패 상태 계약은 B/C 인계 사항입니다. [문서]
- 검증 기준은 문서 정합성·참조·충돌 해결이며 전체 코드 테스트를 완료 근거로 사용하지 않습니다. [문서]
- 이번 확인: 변경 문서의 파일 링크·요구사항 앵커·미구현 설명, 충돌 표식 제거, JSON 파싱 통과. PR #45의 sources.world 조회로 새 물품 11종 확인(클래스 번호 생성 없음). 전체 테스트·빌드는 수행하지 않았습니다. [문서]

## 2026-10-04 FR-ML-01 클래스 번호 정본 준비
- PR head의 world.items 순서로 공식 `build_dataset.py --init-classes`를 실행하여 config/yolo_classes.txt 11종(0–10)을 생성했습니다. 순서 변경 금지·신규 클래스 끝에 추가 규칙을 유지합니다. [문서]
- load_classes(): 11종·경고 없음. 임시 두 세션의 각 11개 라벨 fixture로 일반 CLI 데이터셋 생성(allow-ontology-order 없이) 성공, nc=11·classes.txt·train/val 각11개 확인. 실제 영상·학습·성능을 검증한 것은 아닙니다. [실측]
- 번호 파일 준비 당시 changelog.md는 사용자 해결 내용을 유지하기 위해 수정하지 않았습니다. 이번 재검토에서는 최신 main 기록과 기존 E 기록을 모두 보존해 충돌을 해결했습니다. [문서]

## 2026-10-04 PR #46 재검토 수정 검증
- 치수 정렬과 hardware·ontology·interfaces 설명을 정정했습니다. A의 pose 규칙 함수·B 밀기 계산과 대조했으며 타 담당 코드는 main 내용을 보존했습니다. [문서]
- 계약 검증 OK, core 테스트 229 passed. 원본 YAML과 로더 TF 대조 및 독립 null fixture를 포함합니다. [실측]
- 11종 치수와 문서 표 일치, 클래스 번호·파지 설정·main 장소 설정 및 main 전용 변경 30개 파일 보존을 확인했습니다. 변경 문서 파일 링크·앵커와 diff 공백 검사도 통과했습니다. [실측]
- 위 로컬 검증에는 ROS/Docker 빌드, 실물 실행, 실제 영상 라벨링·YOLO 학습, MongoDB/JSONL 표시 연결을 포함하지 않았습니다. ROS 빌드·compose 검사는 별도로 위 원격 CI에서 성공했으며 실물·학습·표시 연결 완료를 뜻하지 않습니다. [문서]

## 2026-10-05 하드웨어 문서 정합성 작업
- 관련 범위: P1 FR-ACT-01·02·03, NFR-SAF-01·02. 요구사항·완료 기준은 변경하지 않음. [문서]
- 근거: [#1 최신 요청](https://github.com/Jik-Kim/ready2go/issues/1#issuecomment-5980612526), [#8 최신 결정](https://github.com/Jik-Kim/ready2go/issues/8#issuecomment-5980582810), [#15 인출 거리 요청](https://github.com/Jik-Kim/ready2go/issues/15#issuecomment-5976855710). 실측 설정은 config/places.yaml 한 곳을 참조함. [문서]
- 설정·코드·계약·트레이 역할은 변경하지 않음. OBJECT_DROPPED는 #78 별도 협의 범위이며, PR #70~#73의 승인·병합이나 실제 노드 연결 완료를 뜻하지 않음. [문서]
- PR 생성·push 결과는 지정 PR 세션의 실제 PR 링크·원격 head로 확인함. 제품명·실물 인계 미확인 사항은 별도 유지함. [문서]
- 검증: #1·#8·#15 결정/요청 및 관련 P1 요구사항과 문구 대조, 기존 일반 재질 기준 보존, 실측·미확정 연결 구분, 로컬 파일 링크/앵커 및 승인된 3개 파일 범위·diff 공백 검사 통과. 코드 변경이 없어 전체 테스트·빌드·실물 시험은 수행하지 않음. [문서]

## 2026-10-06 #22 시연용 pick_demo 연결
- 사용자 승인 범위: E 파일 4개 작성·관련 최소 검증·로컬 커밋. 기준 main `e05a2f5cde29874600d789b8f12d00dd448d01bc`, 작업 브랜치 `codex/ontology-demo-pick`. push·PR·병합은 미승인. [문서]
- `knowledge/robot_ontology_demo.jsonld`는 open_drawer/close_drawer/pick_demo/place 4종으로 구성. 공통 manifest/pick/초기 상태는 유지함. `pick_demo`는 기존 pre/hold/effect/오류·verify 선언을 보존하고 nudge → 반환 전체 target_after로 pick을 연결함. approach_offset=[0,0,0.1]. [문서]
- 실제 E 로더의 참조 결합·4종/중복 없음, 기본 ontology/pick 보존, 모의 태스크의 task schema 확인 통과. 실제 C Runner + MemoryLogStore로 11사례 통과: 정상, target_after 누락(VAR_UNDEFINED), pick GRASP_FAILED, nudge GRASP_FAILED, 안전 오류 5종, pre 불충족, target 입력 누락(TASK_INVALID). 마지막 입력 누락은 최신 C 사전 검증이 실행 전 거절함을 확인하고 검사 기대값을 바로잡음. [실측: 로컬 모의]
- nudge 입력 전체 target 및 pick 입력 전체 target_after 전달, inspect_region 1회, nudge 1회(retry=0), 성공 시에만 gripper/located_in 효과, 실패/출력 누락 시 pick 미호출·집기 효과 없음, nudge/pick 각각의 params/result/status·실패 단계 로그를 확인함. 정상 pick 후 place/close 실물 연결 검증은 포함하지 않음. [실측: 로컬 모의]
- 임시 검증 스크립트 `/tmp/verify_e_pick_demo.py`는 저장소 커밋에 포함하지 않음. ROS·Docker 전체 빌드, 실제 로봇·MongoDB/JSONL 저장·배포 검증은 수행하지 않음. [문서]
- C 제안 실행 조합: ontology_file=/knowledge/robot_ontology_demo.jsonld, task_file=/tasks/p1_demo_eraser.json. 기준 main에는 해당 태스크 없음: C 반영·실행 조합 확인 대기. 호출 태스크 retry 생략/0, place 실패 시 쥔 상태의 종료·복구 정책은 C/B 인계임. [문서]
- B #83 head25e97ef 배열 지원·lift 오류 보존의 13사례 통과는 검토 세션 전달 결과이며 E의 재검증이 아님. check_only PUSH_LIMIT 보완, target_after 계약 출력 예시·E 포함2명 승인은 별도 인계. A stub·B 보정 TF/실물 준비·C 패키지는 수정하지 않음. [문서]
- target_after는 이동량 기반 예상값이며 FR-ACT-05/AC-ACT-05 재인식 완료가 아님. P1 FR-ONT-01/FR-PLN-01 연결의 시연 한정 구성. domain 상세는 시연 후 계획으로 유지하며 출력 계약 승인이나 실물 배포 완료를 대신하지 않음. [문서]
