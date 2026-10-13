# knowledge — 로봇 온톨로지 (담당 E 고희태)

> 의미·정책·책임·Phase·수용 기준: [FR-ONT-01–03](../docs/requirements.md#fr-ont-01)·[물품 정책](../docs/requirements.md#item-policy)·[가림 정책](../docs/requirements.md#occlusion-policy). 설명: [`docs/ontology.md`](../docs/ontology.md). 과거 그래프는 현재 데이터의 근거로 사용하지 않습니다.

## 작성 원본과 진입점

| 파일 | 역할 |
| :--- | :--- |
| `robot_ontology.jsonld` | 공통 `@context`와 `sources` 참조 목록. 로더의 진입점 |
| `classes.jsonld` | `classes`: 종류·분류 관계 |
| `world.jsonld` | `world`: 물품·목록·장소의 식별자·종류·이름·별칭·물품 속성 |
| `skills/open_drawer.jsonld` | `skills.open_drawer`: 서랍 열기 |
| `skills/close_drawer.jsonld` | `skills.close_drawer`: 서랍 닫기 |
| `skills/pick.jsonld` | `skills.pick`: 집기 |
| `skills/place.jsonld` | `skills.place`: 놓기 |
| `skills/handover_with_unpack.jsonld` | 가림 탐색 복합 스킬 등록. `tasks/find_with_unpack.json`의 현재 내부 이동·복구 경로를 참조; 실물 통합 검증은 별도 |
| `snapshots/initial_state.json` | 기본 로딩의 단일 초기 상태 정의. 실제 상태 확인 후 명시적 초기화 시 사용 |
| `../config/places.yaml` | 장소 TF·치수·인출 거리·처짐·복구 위치·슬롯 설정의 정본 |

## 연결 규칙

- `sources`는 프로젝트 로더가 읽는 참조 목록이다. JSON-LD 자체의 자동 import 기능이 아니다.
- 참조 경로는 `robot_ontology.jsonld`가 있는 폴더 기준이다. 스킬 목록을 명시하므로 파일을 놓기만 해서는 자동 등록되지 않는다.
- `world.places`와 YAML의 공통 식별자(`drawer_top` 등)로 연결한다. 장소 설정은 YAML 한 곳에만 작성하며 로딩할 때 메모리에서 결합한다. 결과 `world.places.<id>`에는 의미 정의와 물리 설정이 함께 제공된다.
- 로더는 기존 `classes`·`world`·`state`·`skills` 조회 구조를 반환한다. 전체 구성 조회자는 `ready2go_knowledge.core.ontology.load()`를 사용한다. A의 학습 도구는 물품 목록만 필요하므로 PR #45의 `sources.world` 참조 조회를 사용한다. 클래스 번호 정본은 `config/yolo_classes.txt`이다.
- 필수 참조 파일, 장소 설정, 종류·목록 참조가 누락되거나 JSON/YAML 키·스킬 식별자·장소 설정이 중복되면 로딩을 거절한다.
- 미측정 `null`은 그대로 보존한다. 해당 설정이 필요한 동작은 실행 전 준비 여부를 확인해야 하며 로더가 예시 좌표로 채우지 않는다.
- 물품 `size_m`은 #8 보고를 반영했다. 파지 힘·최종 승인 상태는 `config/item_grasp.yaml`에서 미확정으로 관리한다.
- `state[predicate][subject] = value`. 프리셋을 읽는 것은 실제 상태 확인이 아니다. Runner가 확인·초기화·실행 중 상태 관리와 저장을 담당한다. 상태 조회마다 프리셋을 다시 로딩하지 않는다.

## 단계와 인계

- 스킬 범위는 [FR-ONT-01](../docs/requirements.md#fr-ont-01)을 참조한다. 현재 manifest는 열기·닫기·집기·놓기 원본을 등록한다. 파일 분리 자체는 실행 순서를 바꾸지 않았으며, 공통 pick의 현재 실행 순서는 아래 P1 연결을 따른다.
- `hold`·문자열 `verify`와 기존 복합 스킬 등록은 보존 데이터다. P1 로더가 이를 평가·실행하지 않는다.
- TODO(C 이영훈): 태스크의 스킬 호출·실패 상태 계약을 별도로 확정한다. 로그에 진입점만의 해시를 기록하면 분리 파일·YAML 변경을 식별할 수 없으므로 전체 구성의 버전/해시 기록도 연계한다.
- TODO(B 서동권): 접근 동작 책임·미측정 설정 사용 차단을 실행 계약으로 확정한다.

## 물품 목록 갱신 (#8)

- [문서] 현재 `world.items`는 당근 펜을 제외한 활성 10종·실물 11개(지우개 2개)다. 온톨로지 키는 종류 단위이며 지우개 instance를 새로 만들지 않았다. 학습 클래스는 기존 11종·`carrot_pen` class_id=5를 포함해 `config/yolo_classes.txt`의 번호를 유지한다. A [PR #262](https://github.com/Jik-Kim/ready2go/pull/262)의 head `87fa5e5bd4b53d795d98dca2343483fe1e436aff`를 E 작업 브랜치에 정상 합류했다. `config/yolo_retired_classes.txt`의 carrot_pen과 공통 `class_errors`로 활성 목록 제거 후에도 고정 번호를 검사한다. #262는 확인 시 open·main 미병합이며 최종 합류 SHA의 전체 CI·게시와 모델/실물 검증은 별도다. 모델·라벨은 재생성하지 않는다.
- 요청 범위·등록과 승인 구분은 [물품 정책](../docs/requirements.md#item-policy)을 참조한다. 현재 `commute_set`·`roles`는 로더가 반환하는 데이터이며 음성/파지 연결 상태는 별도 확인한다.
- `sources.item_grasp`의 `config/item_grasp.yaml`을 읽어 `grip_force`와 `grasp_verified`, 선택 항목 `grasp_width_m`·`grasp_width_long_m`(B 실측 잡은 폭, 외접 박스와 다른 물품만, 그 변 이하 양수)을 물품에 제공한다. 미확정 값은 null/false로 유지한다. 미확정 상태를 거절하는 E 함수와 실제 실행 경로 연결은 구분한다.
- 치수·분류·역할·초기 상태의 의미는 [물품 정책](../docs/requirements.md#item-policy), 값·검증 상태는 실행 원본, 구현/인계는 공용 기술 문서를 참조한다. 과거 예시값 설명은 현재 실측 원본에 적용하지 않는다.

<a id="p2-시작-배치-선택--e-구현c-연결-대기"></a>
## 단일 초기 상태와 선택 API

[문서] 기본 `load(manifest)`는 [`sources.initial_state`](robot_ontology.jsonld)의 [`initial_state.json`](snapshots/initial_state.json)만 읽습니다. 사용자 배치 원문을 반영한 단일 초기 상태이며 운영 장면별 파일 3개는 제거했습니다. 등록 world 10종과 이 파일에 위치를 기입한 6종은 구분합니다.

| 초기 위치 | 기입한 물품 |
| :--- | :--- |
| drawer_top | toy_wrench·caramel_box·car_key |
| drawer_bottom | cover_plate·eraser·lip_balm |

[문서] 위치가 없는 airpods_case·masking_tape·toy_car·toy_hammer는 등록 물품입니다. 위치 생략을 미등록이나 실물 재고 없음으로 정의하지 않습니다. home·empty·두 서랍 닫힘·handover_zone 값도 사용자 초기 파일 그대로이며 실제 빈손·닫힘·쌓임/가림/pose 증거가 아닙니다.

[문서] S3도 같은 JSON의 eraser → drawer_bottom을 유지하고 **실물에서만 지우개를 제외하는 시험**입니다. 초기 정의와 실제 관측의 차이를 확인하기 위한 배치이며, 이 파일만으로 LLM 전달·재식별·자동 상태 갱신의 운영 연결이나 검증 완료를 선언하지 않습니다. 관측의 `occluded_by`·`target=null`은 별도 관측 결과로 보존합니다.

[문서] 기존 `load(manifest, snapshot=provided_state_path)` API는 유지합니다. 사용자가 별도로 제공한 시험용 초기 상태 파일을 선택할 수 있으며 상대 경로는 manifest 폴더 기준, 절대 Path도 지원합니다. 기존 중복 키·located_in 참조 검사가 적용되고 단일 파일 legacy는 기본 호출만 지원합니다. E 양성/오류 선택 시험은 tmp_path에만 입력을 만들어 운영 폴더에 장면 파일을 생성하지 않습니다.

[미연결/인계] C `runner_node.py`는 기본 `load(ontology_file)`로 시작 상태를 읽습니다. 파일을 수정한 것만으로 이미 기동한 Runner의 상태가 자동 갱신되지 않으며 reset은 저장된 시작 상태 복사입니다. 실물 검증·B 기억 정리·잠금 해제를 뜻하지 않습니다. C `ontology_query.query()`는 등록돼 있어도 위치가 없으면 `UNKNOWN_ITEM`을 반환하므로 미기입 4종 처리와 실제 관측 결과·LLM 전달은 C 후속입니다. 조건부 pick의 현재 공통 흐름은 아래 [공통 pick](#p1-공통-pick의-벽-인접-끌기재관측-연결)을 참조합니다. 유효 scan 재사용은 미연결이며 pick/pre/effect/place는 합류한 main 원본을 유지합니다.

## P1 공통 pick의 벽 인접 끌기·재관측 연결

[문서: E-PICK-CONDITIONAL-NUDGE-20261013-01] 공통 [`robot_ontology.jsonld`](robot_ontology.jsonld)는 기존 [`skills/pick.jsonld`](skills/pick.jsonld)를 등록합니다. pick 이름·`item/from`·pre/hold/effect/verify·errors는 유지하고 **expand만** C #263/#269 지원에 맞춰 전환했습니다. 정식 [`tasks/find_item.json`](../tasks/find_item.json)의 `s5.1`과 공통 pick을 쓰는 P2 caller가 같은 카드를 사용합니다.

1. 같은 서랍 탑뷰 → `inspect_region(region=$from, search_target=$item)` → 로컬 `scan`.
2. `pick_object(target=$scan.target, scan=$scan, approach_offset=[0,0,0.1])`를 먼저 실행합니다.
3. 움직임 전 `WALL_TOO_CLOSE` 거부만 `fallback.next_on`의 다음 대안으로 넘어갑니다: `nudge_object(target=$scan.target, drawer_id=$from, scan=$scan)` → 탑뷰 → 재관측 **1회**로 로컬 `scan` → 새 target과 같은 전체 scan으로 집기.

[문서] 직접 집기 성공이면 skill 관측 1회, WALL 대안 성공이면 2회입니다. 기존 정식 P1 태스크의 최초 관측까지 합하면 각각 2회/3회이며, C의 같은 자세 이동 억제는 관측 재사용을 의미하지 않습니다. B no-op `pushed=false`라도 WALL 대안에 들어간 뒤에는 재관측 1회를 수행합니다. `target_after`·needed·plan_code를 집기 입력이나 재분기 조건으로 사용하지 않으며 독립 nudge 스킬·반복·새 공개 필드·TTL은 추가하지 않습니다. B의 그리퍼 닫기/drag_down/접근·벽 검사와 place 책임은 유지합니다.

[문서] C #263의 자동 하위 ID·부모 timeout/취소·로컬 scope와 #269의 넛지 뒤 새 관측 변수 출처/덮어쓰기 검사를 사용합니다. 기본 `scan`은 호출자 blackboard에서 전달될 수 있지만 이번 카드는 새 관측으로 덮어쓰고, 넛지 뒤에는 같은 로컬 `scan`을 inspect 응답으로 갱신합니다. 최초/재관측 null은 기존 `VAR_NULL`로 후속 pick 전송 전에 차단합니다. YAW_INVALID·NEIGHBOR_TOO_CLOSE·NOT_ON_FLOOR·BAD_PARAMS·안전 코드와 움직였을 수 있는 실패는 다음 대안으로 보내지 않습니다. nudge/탑뷰/재관측 실패·정지 때 뒤 집기는 없고 두 번째 WALL도 반복하지 않습니다. 실제 Runner의 전체 성공 뒤 effect 경로를 유지하며 hold/verify 선언은 관측 기반 성공 검증의 구현이 아닙니다.

[미연결/인계] 같은 run·현재 대상·서랍 및 stop/resume/불확실 이동에 연결된 **전체 scan의 유효성 판정·무효화**는 현재 C에 확인되지 않았습니다. `interpreter._run_skill()`의 scope 전달과 `_dispatch()`의 output 저장만으로 유효 관측 재사용을 선언하지 않습니다. 따라서 이번 카드는 항상 탑뷰/새 관측으로 시작하고 #245의 관측 재사용 전체 완료는 아닙니다. 최소 C 후속은 해당 출처·대상·서랍·실행 경계와 무효화 근거를 소비자가 확인할 수 있게 지원한 뒤 E 조건 분기를 연결하는 것입니다. 새 필드명이나 항상 유효 flag는 확정하지 않습니다.

[문서/검사] E [`test_pick_runner.py`](../ros2_ws/src/ready2go_knowledge/test/test_pick_runner.py)는 실제 수정 카드·C Runner/backend로 직접 집기/WALL·다른 거부·새 전체 scan·null·실패/정지 경계를 검사합니다. C의 `test_tasks.py` 호출열/횟수·하위 ID 기대와 P1/Unpacking 회귀 갱신은 담당 C 인계 사항입니다. PR #130의 6단계/3회 검사는 당시 선형 카드의 결과이며 이번 현재 호출열의 근거로 전용하지 않습니다. 태스크 시간 예산은 [원본](../tasks/find_item.json)을 유지하고 finally·retry는 현재 C 안전 조건을 따릅니다. B [domain.md 8.5](../docs/domain.md#85-벽-인접-물체-밀어오기-담당-b)의 6단계 현재 설명 갱신도 담당 인계입니다.

[문서] 기준은 P1 [FR-ONT-01](../docs/requirements.md#fr-ont-01)·[FR-PLN-01](../docs/requirements.md#fr-pln-01)·[FR-ACT-05/AC-ACT-05](../docs/requirements.md#fr-act-05), P2 연결은 [FR-PLN-02](../docs/requirements.md#fr-pln-02)·[FR-ACT-04](../docs/requirements.md#fr-act-04)를 참조합니다. 정본 정책·Phase·공개 계약은 바꾸지 않았습니다. 스텁 좌표 변화·모의 중단은 실제 A 재인식/새 프레임·B 공간 판단/배포/안전·실물 성공률 증거가 아니며 실음성/ROS/장치/로봇·AC-ACT-05 실측은 미검증입니다.

## 현재 실행 진입점과 과거 기록

[문서] 현재 실행 진입점은 공통 [`robot_ontology.jsonld`](robot_ontology.jsonld)이며 집기는 [`skills/pick.jsonld`](skills/pick.jsonld)의 위 조건부 넛지·재관측 경로를 사용합니다. 정식 [`tasks/find_item.json`](../tasks/find_item.json)과 점검용 [`tasks/p1_demo_eraser.json`](../tasks/p1_demo_eraser.json)은 모두 공통 `pick`을 호출합니다. 점검 태스크 이름의 demo는 별도 온톨로지 사용을 뜻하지 않습니다.

[문서] 10/06 시연 전용 온톨로지·집기 정의는 제거했습니다. 과거 실측 로그·fixture·보고서의 레이블과 변경 이력은 당시 결과 해석용으로 보존하며 현재 실행 안내로 사용하지 않습니다. 현재 경로는 끌기 예상값 대신 재관측 target으로 집습니다. 실물 AC-ACT-05 성공률·배포·안전 연결 검증 완료를 문서 정리만으로 선언하지 않습니다.

[문서] 삭제 반영 후속 완료: `ready2go_runner/test/test_intent_router.py`의 물품 목록 로딩은 공통 진입점으로 정정됐고(PR #130), B의 HANDOVER 현재 실행 명령도 공통 온톨로지 진입점을 사용하도록 정리됐습니다(PR #129). 삭제된 시연 manifest를 쓰던 과거 로그·fixture·보고서는 당시 결과 해석용으로 보존하며 현재 실행 안내로 사용하지 않습니다. 이 문서 정리와 CI 성공만으로 배포·장치·실물 검증 완료를 선언하지 않습니다.

[문서] P2 목표는 [FR-ACT-04](../docs/requirements.md#fr-act-04)·[가림 정책](../docs/requirements.md#occlusion-policy)을 참조하십시오. 현재 `tasks/find_with_unpack.json`은 서랍 내부 이동과 LIFO 복구 경로, `aside` 처리 및 `RESTORE_INCOMPLETE` 종료 경로를 포함합니다. `aside`는 원위치 복구 완료가 아니며 코드상의 완료 상태만으로 실물 복구를 보장하지 않습니다. `staging_tray`는 초기 상태의 open에서만 제외했고, world·`config/places.yaml` 정의는 config·계약·소비자 잔존참조 때문에 유지합니다. 실제 재식별/pose 기록·내부 배치/복구 검증은 [domain.md 인계표](../docs/domain.md)와 담당 구현을 대조해야 합니다.

## #43 P2 verify 준비·소비자 경계

[문서] [사후 검증 정본](../docs/requirements.md#verification-policy)에 맞춰 pick/place/close_drawer의 **문자열 선언만** 정리하고 open_drawer는 유지했습니다. pre/hold/effect/expand·스킬/물품 식별자·manifest·로더 반환 구조는 변경하지 않았습니다. P1 로더는 문자열을 보존하고 Runner는 현재 하위 실행 성공→effect 경로이므로 evaluator/관측 기반 상태 적용이 연결된 것이 아닙니다. [E 내부 정책](../ros2_ws/src/ready2go_voice/ready2go_voice/core/skill_confirmation.py)은 pick 후보·handover 확인만 제공하며 상태/로그/성공 안내를 쓰지 않습니다. C의 verify 대기/최종 effect·B 실제 파지/닫힘/신선 관측·A handover TF/ROI/재촬영과 wire 승인은 후속입니다. 구조화 verify로 자료형을 바꾸거나 타 파트 코드를 수정하지 않았습니다.

[문서: 이번 내부 구현] place의 문자열 verify는 목적지 재촬영·서랍 top view·트레이 정상 미검출 사용자 근거의 구분을 선언합니다. 기존 JSON 자료형과 pre/hold/effect/expand는 유지합니다. E 내부 확인은 같은 절차의 횟수·종료 상태와 질문별 TTS/녹음/SDK/STT 증빙을 보존합니다. 선언의 존재로 서랍 관측 evaluator·복합 성공·C effect 차단이 연결됐다고 판단하지 않습니다. 복합 검증과 복구 수용 기준은 [사후 검증 정본](../docs/requirements.md#verification-policy)·[AC-ACT-03](../docs/requirements.md#ac-act-03)을 참조하십시오.

## #78 place 오류 선언 정합성

[문서] [모션 차단·놓침 후 새 실행 정본](../docs/requirements.md#halt-motion-policy)에 연결해 `knowledge/skills/place.jsonld`의 errors에 B가 현재 반환하는 `OBJECT_DROPPED`를 추가했습니다. 당시 errors 추가는 params/pre/hold/effect/expand/verify·manifest·로더를 보존했습니다. 이번 verify 선언 갱신은 위 #43 절을 참조하십시오. errors는 선언 데이터이며 Runner 잠금·정지·복구/재개를 실행하는 허용 목록이 아닙니다. pick의 `GRASP_FAILED`나 아직 확정되지 않은 place 센서 반환 목록은 변경하지 않습니다.

[문서·코드 대조: 2026-10-10] C의 [PR #202](https://github.com/Jik-Kim/ready2go/pull/202)는 main에 병합됐습니다. `interpreter.HALT_MOTION_CODES`의 `OBJECT_DROPPED`·`SENSOR_INVALID`는 기존 `HALT_CODES` 경로로 `ABORTED`·잠금을 적용하고, finally의 후속 모션과 잠금 중 새 요청을 차단합니다. 두 오류는 재개 모드에서도 실행을 보존하지 않습니다. E errors 선언이 이 동작을 구현한 것은 아니며, C 모의 검사와 실제 정지·복구 완료는 구분합니다.

[미연결/인계] B handover place의 센서 이상/놓침 반환 구분·보유 확실성·실제 정지/신선 관측과 C의 관측 기반 상태 동기화·잠금 해제·명시적 새 run 운영 연결은 후속입니다. 현재 `reset_state()`는 시작 스냅샷을 복원하며 잠금 해제나 물리 상태 검증을 하지 않습니다. [#78](https://github.com/Jik-Kim/ready2go/issues/78)·[#196](https://github.com/Jik-Kim/ready2go/issues/196)에서 남은 B/C 협의·E 포함 2인 계약 승인·운영 adapter·실물 검증을 확인합니다.
