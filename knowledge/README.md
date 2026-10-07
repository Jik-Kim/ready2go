# knowledge — 로봇 온톨로지 (담당 E 고희태)

> 문서: [`docs/ontology.md`](../docs/ontology.md) · 그림: `docs/images/knowledge_graph_*.jpg`

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
| `skills/handover_with_unpack.jsonld` | 가림 탐색 복합 스킬 등록. 참조 `tasks/find_with_unpack.json`은 이전 외부 트레이 예시; 현재 P2 내부 이동 계약 반영 전 실행 기준 아님 |
| `snapshots/initial_state.json` | 초기 상태 프리셋. 실제 상태 확인 후 명시적 초기화 시 사용 |
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

- P1 스킬 정의는 열기·닫기·집기·놓기 4종. 파일 분리 자체는 실행 순서를 바꾸지 않았으며, 공통 pick의 현재 실행 순서는 아래 P1 연결을 따른다.
- `hold`·문자열 `verify`와 기존 복합 스킬 등록은 보존 데이터다. P1 로더가 이를 평가·실행하지 않는다.
- TODO(C 이영훈): 태스크의 스킬 호출·실패 상태 계약을 별도로 확정한다. 로그에 진입점만의 해시를 기록하면 분리 파일·YAML 변경을 식별할 수 없으므로 전체 구성의 버전/해시 기록도 연계한다.
- TODO(B 서동권): 접근 동작 책임·미측정 설정 사용 차단을 실행 계약으로 확정한다.

## 물품 목록 갱신 (#8)

- `world.items`는 제공된 실측/외접박스 표의 11종·12개를 반영한다. 최초 11종 번호는 공식 생성기로 만든 `config/yolo_classes.txt`에 고정했으며 여기의 순서를 다시 바꿔 기존 라벨을 해석하지 않는다.
- P1은 등록 물품의 단일 요청이며 `commute_set`은 P3 예시 참조 데이터다. `roles`의 request_target은 파지 검증 완료를 의미하지 않는다.
- `sources.item_grasp`의 `config/item_grasp.yaml`을 읽어 `grip_force`와 `grasp_verified`를 물품에 제공한다. 미확정 값은 null/false로 유지한다. 미확정 상태를 거절하는 E 함수와 실제 실행 경로 연결은 구분한다.
- 치수·분류·역할·초기 상태·인계의 현재 기준은 공용 `docs/ontology.md`, `docs/interfaces.md`, `docs/hardware.md`다. 이전의 '물품 size_m 예시값 유지' 설명은 이번 실측 반영으로 대체된다.

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

[문서] C 인계: 정식 태스크의 관측은 기존 2회에서 3회(태스크 1회+pick 2회)로 늘어 `test_tasks.py`의 호출열/횟수 기대값을 갱신해야 합니다. 탑뷰/nudge는 현재 NON_MOTION_ACTIONS에 없으므로 기존 `YAW_INVALID` retry 1도 선행 이동 뒤에는 억제됩니다. 이를 임의 우회하지 않으며, `timeout_sec=60`은 전체 pick 전개를 포함하므로 실측 예산을 재검토해야 합니다. finally는 기존 그리퍼·중단/잠금 조건을 따르며 ESTOP/서버 잠금에서 자동 닫기·홈을 보장하지 않습니다. B 배포 SHA·no-op/실패·탑뷰·wall guard와 A의 실제 새 프레임/좌표 확인 전 전체 실물 통합 완료로 보지 않습니다.

[문서] 기준은 P1 [FR-ONT-01](../docs/requirements.md#fr-ont-01)·[FR-PLN-01](../docs/requirements.md#fr-pln-01)·[FR-ACT-05/AC-ACT-05](../docs/requirements.md#fr-act-05)입니다. FR-ACT-05의 “닫은 그리퍼로 밀기”와 B의 누르고 끄는 구현 표현은 정본 담당 확인·별도 인계 사항입니다. 이 문서에서 요구사항·AC를 변경하지 않습니다. E 모의 통합 테스트의 이동 후 좌표 변화는 스텁 데이터이며 실제 재인식 성공·벽 근처 10회 실측 근거가 아닙니다. B의 [domain.md 8.5](../docs/domain.md#85-벽-인접-물체-밀어오기-담당-b)의 태스크 조합 설명은 공통 pick 변경에 맞춘 담당자 문서 정리가 필요합니다.

## 10/06 지우개 시연 전용 연결

[문서] 아래는 10/06 과거 시연용 구성으로 유지하는 파일입니다. 현재 P1 공통 실행 기준은 위 공통 pick 연결입니다. `robot_ontology_demo.jsonld`는 별도 시연 진입점이며 `open_drawer`·`close_drawer`·`pick_demo`·`place` 4종만 등록합니다. 이 과거 시연 파일은 공통 `robot_ontology.jsonld`의 등록을 바꾸지 않습니다. 시연 manifest에는 공통 pick 대신 [`skills/pick_demo.jsonld`](skills/pick_demo.jsonld)를 등록하며, 기본 온톨로지에는 pick_demo를 추가하지 않습니다.

[문서] C 태스크는 위 서랍을 연 뒤 최초 `inspect_region`의 전체 target을 `pick_demo(item=eraser, from=drawer_top, target=...)`에 전달합니다. `target`의 선언 `object`는 JSON 객체 payload를 뜻하며 온톨로지 클래스 키가 아닙니다. 스킬 내부는 `nudge_object(target=$target, drawer_id=$from, output=nudge)` → `pick_object(target=$nudge.target_after, approach_offset=[0,0,0.1])`입니다. 추가 인식이나 y 좌표 하드코딩은 하지 않습니다. 공통 pick의 pre/hold/effect/오류·verify 선언을 보존하며, 현재 P1 Runner는 pre와 성공 응답 기반 effect를 처리합니다. hold/verify 선언 보존은 P2 관측 검증 구현을 뜻하지 않습니다.

[문서] C가 제안한 실행 조합은 `ontology_file=/knowledge/robot_ontology_demo.jsonld`, `task_file=/tasks/p1_demo_eraser.json`입니다. 현재 main에 해당 C 태스크는 존재하지만 공통 pick의 재관측 경로를 사용하는 태스크는 아닙니다. 이 조합의 파일 배포·최초 인식·pick_demo 호출·place·finally close/home 연결을 C가 확인해야 합니다. 호출 태스크의 retry는 생략 또는 0으로 제한합니다. 스킬 파일만으로 태스크의 재시도 설정을 강제하지 않습니다. nudge/pick은 각각 하위 단계 로그로 남으며 전체 성공 후에만 집기 효과가 적용됩니다. nudge 실패 또는 target_after 누락은 후속 pick을 차단하며 스킬 효과를 적용하지 않습니다. place 실패 후 쥔 상태의 안전 종료·복구는 C/B 합의 사항입니다.

[문서] 10/06 시연용 pick_demo의 내부 조합은 **과거 시연 한정 구성**입니다. 공통 pick은 위 재관측 연결로 별도 변경했으며 이 과거 시연 파일은 교체·삭제하지 않습니다. target_after는 재관측 좌표가 아닌 이동량 기반 예상값입니다. 이번 경로의 성공은 [`FR-ACT-05·AC-ACT-05`](../docs/requirements.md#fr-act-05)의 재인식 완료를 뜻하지 않습니다. 연결 검증 범위는 P1 FR-ONT-01·FR-PLN-01입니다. domain 상세 정리는 시연 후로 두되 이번 출력 계약 승인을 대신하지 않습니다.

[문서] 실물 사용 전 B의 nudge/lift 오류 보존·배포 SHA·배열 approach_offset 지원, A stub와 보정 TF의 일치, 전달 위치 TF, 실물 초기 상태를 확인해야 합니다. #83의 check_only PUSH_LIMIT 보완, target_after 출력 예시 및 E 포함 2명 계약 승인은 별도 인계입니다. 이 파일 작성은 계약 승인이나 실물 배포 완료가 아닙니다.

[문서] P2 가림 물체는 같은 서랍 내부 빈 공간으로 옮기고 재관측한 뒤 목표물을 handover_zone에 전달하며, 옮긴 물체를 역순 복구합니다. located_in은 서랍 그대로 유지하고 pose/재식별·복구 기록 계약은 C·E 인계입니다. staging_tray의 world/초기상태 정의는 config·계약·소비자 잔존참조와 함께 정리할 때까지 유지하며 P2 배출 장소로 사용하지 않습니다. [domain.md 인계표](../docs/domain.md)를 참조하십시오.
