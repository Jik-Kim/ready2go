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
| `skills/handover_with_unpack.jsonld` | 기존 가림 탐색 복합 스킬 등록. `tasks/find_with_unpack.json` 참조, P2 이후 사용 |
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

- P1 스킬 정의는 열기·닫기·집기·놓기 4종. 이번 분리는 실행 순서나 로봇 동작을 추가하지 않는다.
- `hold`·문자열 `verify`와 기존 복합 스킬 등록은 보존 데이터다. P1 로더가 이를 평가·실행하지 않는다.
- TODO(C 이영훈): 태스크의 스킬 호출·실패 상태 계약을 별도로 확정한다. 로그에 진입점만의 해시를 기록하면 분리 파일·YAML 변경을 식별할 수 없으므로 전체 구성의 버전/해시 기록도 연계한다.
- TODO(B 서동권): 접근 동작 책임·미측정 설정 사용 차단을 실행 계약으로 확정한다.

## 물품 목록 갱신 (#8)

- `world.items`는 제공된 실측/외접박스 표의 11종·12개를 반영한다. 최초 11종 번호는 공식 생성기로 만든 `config/yolo_classes.txt`에 고정했으며 여기의 순서를 다시 바꿔 기존 라벨을 해석하지 않는다.
- P1은 등록 물품의 단일 요청이며 `commute_set`은 P3 예시 참조 데이터다. `roles`의 request_target은 파지 검증 완료를 의미하지 않는다.
- `sources.item_grasp`의 `config/item_grasp.yaml`을 읽어 `grip_force`와 `grasp_verified`를 물품에 제공한다. 미확정 값은 null/false로 유지한다. 미확정 상태를 거절하는 E 함수와 실제 실행 경로 연결은 구분한다.
- 치수·분류·역할·초기 상태·인계의 현재 기준은 공용 `docs/ontology.md`, `docs/interfaces.md`, `docs/hardware.md`다. 이전의 '물품 size_m 예시값 유지' 설명은 이번 실측 반영으로 대체된다.

## 10/06 지우개 시연 전용 연결

[문서] `robot_ontology_demo.jsonld`는 별도 시연 진입점이며 `open_drawer`·`close_drawer`·`pick_demo`·`place` 4종만 등록합니다. 공통 `robot_ontology.jsonld`와 `skills/pick.jsonld`는 유지합니다. 시연 manifest에는 공통 pick 대신 [`skills/pick_demo.jsonld`](skills/pick_demo.jsonld)를 등록하며, 기본 온톨로지에는 pick_demo를 추가하지 않습니다.

[문서] C 태스크는 위 서랍을 연 뒤 최초 `inspect_region`의 전체 target을 `pick_demo(item=eraser, from=drawer_top, target=...)`에 전달합니다. `target`의 선언 `object`는 JSON 객체 payload를 뜻하며 온톨로지 클래스 키가 아닙니다. 스킬 내부는 `nudge_object(target=$target, drawer_id=$from, output=nudge)` → `pick_object(target=$nudge.target_after, approach_offset=[0,0,0.1])`입니다. 추가 인식이나 y 좌표 하드코딩은 하지 않습니다. 공통 pick의 pre/hold/effect/오류·verify 선언을 보존하며, 현재 P1 Runner는 pre와 성공 응답 기반 effect를 처리합니다. hold/verify 선언 보존은 P2 관측 검증 구현을 뜻하지 않습니다.

[문서] C가 제안한 실행 조합은 `ontology_file=/knowledge/robot_ontology_demo.jsonld`, `task_file=/tasks/p1_demo_eraser.json`입니다. 이 기준 main에는 해당 C 태스크가 없어 **태스크 반영·인계 대기**입니다. 이 조합의 파일 배포·최초 인식·pick_demo 호출·place·finally close/home 연결을 C가 확인해야 합니다. 호출 태스크의 retry는 생략 또는 0으로 제한합니다. 스킬 파일만으로 태스크의 재시도 설정을 강제하지 않습니다. nudge/pick은 각각 하위 단계 로그로 남으며 전체 성공 후에만 집기 효과가 적용됩니다. nudge 실패 또는 target_after 누락은 후속 pick을 차단하며 스킬 효과를 적용하지 않습니다. place 실패 후 쥔 상태의 안전 종료·복구는 C/B 합의 사항입니다.

[문서] 현재 [`domain.md 8.5`](../docs/domain.md#85-벽-인접-물체-밀어오기-담당-b)는 태스크에서 nudge와 재인식을 조합하는 기준입니다. 이번 스킬 내부 조합은 **시연 한정 구성**이며 그 공통 기준을 변경하지 않습니다. target_after는 재관측 좌표가 아닌 이동량 기반 예상값입니다. 이번 경로의 성공은 [`FR-ACT-05·AC-ACT-05`](../docs/requirements.md#fr-act-05)의 재인식 완료를 뜻하지 않습니다. 연결 검증 범위는 P1 FR-ONT-01·FR-PLN-01입니다. domain 상세 정리는 시연 후로 두되 이번 출력 계약 승인을 대신하지 않습니다.

[문서] 실물 사용 전 B의 nudge/lift 오류 보존·배포 SHA·배열 approach_offset 지원, A stub와 보정 TF의 일치, 전달 위치 TF, 실물 초기 상태를 확인해야 합니다. #83의 check_only PUSH_LIMIT 보완, target_after 출력 예시 및 E 포함 2명 계약 승인은 별도 인계입니다. 이 파일 작성은 계약 승인이나 실물 배포 완료가 아닙니다.
