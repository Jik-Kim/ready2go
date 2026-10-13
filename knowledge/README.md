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
| `snapshots/initial_state.json` | 기본 P1 초기 상태 프리셋. 실제 상태 확인 후 명시적 초기화 시 사용 |
| `snapshots/p2_s1.json`·`p2_s2.json`·`p2_s3.json` | 승인된 P2 시작 배치 프리셋. C 기동/reset 자동 적용은 미연결 |
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

## P2 시작 배치 선택 — E 구현·C 연결 대기

[문서] 기본 `load(manifest)`는 기존 `sources.initial_state`를 사용합니다. E 로더의 선택 입력 예시는 다음과 같습니다. 상대 snapshot 경로는 manifest 폴더 기준이며 절대 `Path`도 지원합니다. 선택 파일에도 기존 중복 키·located_in 참조 검사가 적용됩니다. 단일 파일 호환 형식은 기본 호출만 지원하고 선택 입력은 명시적으로 거절합니다.

```python
from ready2go_knowledge.core.ontology import load
onto = load("knowledge/robot_ontology.jsonld", snapshot="snapshots/p2_s3.json")
```

| 프리셋 | 기입한 위치 |
| :--- | :--- |
| [S1](snapshots/p2_s1.json) | toy_wrench·caramel_box·car_key → drawer_top |
| [S2](snapshots/p2_s2.json) | cover_plate·eraser·lip_balm → drawer_bottom |
| [S3](snapshots/p2_s3.json) | cover_plate·lip_balm → drawer_bottom; eraser 위치 생략 |

[문서] 세 장면은 같은 활성 10종을 조회하며 비등장 물품의 위치를 채우지 않습니다. 세 장면 합집합에 없는 활성 물품은 airpods_case·masking_tape·toy_car·toy_hammer 4종입니다. 비위치 상태는 기본 프리셋의 home·empty·서랍 닫힘·handover_zone 값을 보존합니다. 시작 예시값은 실제 빈손·닫힘·물리 reset 증거가 아닙니다. 쌓임/가림/pose는 미리 확정하지 않고 관측의 `occluded_by`·`target=null`을 보존합니다.

[미연결/인계] C `runner_node.py`는 현재 기본 `load(ontology_file)`만 호출합니다. 기동/명시 reset에서의 snapshot 선택 인자와 소비 방식은 C 협의·구현 전이며 이 Python 입력을 ROS 파라미터로 확정하지 않습니다. C `ontology_query.query()`는 등록 물품도 located_in이 없으면 `UNKNOWN_ITEM`을 반환하고 `find_with_unpack`의 s1→s3/s4는 조회 drawer_id를 소비합니다. 따라서 S3 지우개의 C 탐색 경로는 후속 수정 전 미연결입니다. 위치를 거짓 기입하지 않으며 reset은 저장된 시작 상태 복사일 뿐 B 기억 정리·잠금 해제·물리 검증을 수행하지 않습니다. 조건부 pick은 C 스킬 expand 제어 블록 지원 PR과 E 포함 2인 승인 전 보류하며 이번 pick/pre/effect/place는 유지합니다.

## P1 공통 pick의 벽 인접 끌기·재관측 연결

[문서] 공통 [`robot_ontology.jsonld`](robot_ontology.jsonld)는 기존 [`skills/pick.jsonld`](skills/pick.jsonld)를 등록합니다. 정식 [`tasks/find_item.json`](../tasks/find_item.json)의 `s5.1`이 호출하는 pick은 `item/from`, pre/hold/effect/verify를 유지하고 다음 원자 동작을 선형으로 전개합니다.

1. `move_to_named_pose(pose_name=drawer_top_view, drawer_id=$from)`
2. `inspect_region(region=$from, search_target=$item)` → `scan`
3. `nudge_object(target=$scan.target, drawer_id=$from)` → `nudge`
4. 같은 서랍 탑뷰로 이동
5. 같은 대상 재관측 → 스킬 로컬 `scan` 갱신
6. `pick_object(target=$scan.target, approach_offset=[0,0,0.1])`

[문서] P1 공간 판단은 B의 기존 `plan_drag/nudge_object`가 맡습니다. 충분하면 B가 `pushed=false`로 이동 없이 성공하고, 부족하면 접촉 힘을 확인하며 끕니다. 두 경우 모두 두 번째 관측을 수행합니다. 같은 스킬 로컬 `scan`을 두 번째 응답으로 갱신하므로 집기는 `nudge.target_after` 예상값이나 최초 관측 대신 **재관측 전체 target**을 사용하며, B의 기존 pick wall guard도 유지됩니다. 최초/재관측 응답은 각각 e2/e5 기록에, 예상 출력은 e3 기록에 보존되며 e6의 params에는 두 번째 관측 target이 남습니다. 스킬 내부 if/다른 스킬 호출이나 독립 nudge 온톨로지 스킬은 추가하지 않습니다. P2 이후 주변 물체 간격 판단 주체·필드는 미확정이며 [이슈 #120](https://github.com/Jik-Kim/ready2go/issues/120)의 후속 합의 대상입니다.

[문서] 기존 Runner는 하위 동작 실패를 전파하고 전체 성공 뒤에만 effect를 적용합니다. 최초/재관측 `target=null`은 현재 main의 `VAR_NULL` 검사로 다음 nudge/pick 전송 전에 차단합니다. errors에는 기존 NOT_VISIBLE/GRASP_FAILED와 A 조회·B 탑뷰/끌기/집기 및 Runner null 차단의 기존 코드를 반영했습니다. errors는 선언 데이터이며 오류를 변환하거나 새로 생성하지 않습니다. B 공통 안전·통신 오류도 원래 코드로 전파되며 이 목록이 모든 장애의 허용 목록은 아닙니다. hold/verify는 보존 선언이며 관측 기반 상태 검증을 새로 구현하지 않습니다.

[문서] C 인계 반영 완료(PR #130): 정식 태스크의 관측이 기존 2회에서 3회(태스크 1회+pick 2회)로 늘어난 호출열·횟수와, 재관측 `scan.target`이 실제 집기 입력인지 `test_tasks.py`에서 확인합니다. 탑뷰/nudge는 현재 NON_MOTION_ACTIONS에 없으므로 기존 `YAW_INVALID` retry 1도 선행 이동 뒤에는 억제됩니다. 이를 임의 우회하지 않으며, 공통 pick의 시간 예산은 PR #164에서 정식 태스크와 점검 태스크 및 테스트에 반영됐습니다. 현재 값은 [정식 태스크 원본](../tasks/find_item.json)에서 확인하며 전체 pick 전개를 포함합니다. 실물 소요 시간에 따른 예산 재검토는 별도입니다. finally는 기존 그리퍼·중단/잠금 조건을 따르며 ESTOP/서버 잠금에서 자동 닫기·홈을 보장하지 않습니다. 코드·테스트 반영은 B 배포 SHA·no-op/실패·탑뷰·wall guard와 A의 실제 새 프레임/좌표를 확인한 전체 실물 통합 완료를 뜻하지 않습니다.

[문서] 기준은 P1 [FR-ONT-01](../docs/requirements.md#fr-ont-01)·[FR-PLN-01](../docs/requirements.md#fr-pln-01)·[FR-ACT-05/AC-ACT-05](../docs/requirements.md#fr-act-05)입니다. FR-ACT-05의 “닫은 그리퍼로 밀기”와 B의 누르고 끄는 구현 표현은 정본 담당 확인·별도 인계 사항입니다. 이 문서에서 요구사항·AC를 변경하지 않습니다. E 모의 통합 테스트의 이동 후 좌표 변화는 스텁 데이터이며 실제 재인식 성공·[AC-ACT-05](../docs/requirements.md#ac-act-05) 실측 근거가 아닙니다. B의 [domain.md 8.5](../docs/domain.md#85-벽-인접-물체-밀어오기-담당-b)는 현재 P1 공통 pick의 6단계·no-op 후 재관측·이동 후 재시도 억제를 설명하며, 과거 예시와 P2 계획을 별도로 구분합니다.

## 현재 실행 진입점과 과거 기록

[문서] 현재 실행 진입점은 공통 [`robot_ontology.jsonld`](robot_ontology.jsonld)이며 집기는 [`skills/pick.jsonld`](skills/pick.jsonld)의 위 6단계 재관측 경로를 사용합니다. 정식 [`tasks/find_item.json`](../tasks/find_item.json)과 점검용 [`tasks/p1_demo_eraser.json`](../tasks/p1_demo_eraser.json)은 모두 공통 `pick`을 호출합니다. 점검 태스크 이름의 demo는 별도 온톨로지 사용을 뜻하지 않습니다.

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
