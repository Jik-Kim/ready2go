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
- 로더는 기존 `classes`·`world`·`state`·`skills` 조회 구조를 반환한다. 호출자는 원본 JSON을 직접 읽지 않고 `ready2go_knowledge.core.ontology.load()`를 사용한다.
- 필수 참조 파일, 장소 설정, 종류·목록 참조가 누락되거나 JSON/YAML 키·스킬 식별자·장소 설정이 중복되면 로딩을 거절한다.
- 미측정 `null`은 그대로 보존한다. 해당 설정이 필요한 동작은 실행 전 준비 여부를 확인해야 하며 로더가 예시 좌표로 채우지 않는다.
- 물품 `size_m`은 #8 보고를 반영했다. 파지 힘·최종 승인 상태는 `config/item_grasp.yaml`에서 미확정으로 관리한다.
- `state[predicate][subject] = value`. 프리셋을 읽는 것은 실제 상태 확인이 아니다. Runner가 확인·초기화·실행 중 상태 관리와 저장을 담당한다. 상태 조회마다 프리셋을 다시 로딩하지 않는다.

## 단계와 인계

- P1 스킬 정의는 열기·닫기·집기·놓기 4종. 이번 분리는 실행 순서나 로봇 동작을 추가하지 않는다.
- `hold`·문자열 `verify`와 기존 복합 스킬 등록은 보존 데이터다. P1 로더가 이를 평가·실행하지 않는다.
- TODO(A 김병직): `tools/yolo/build_dataset.py:class_names()`는 기존 단일 JSON의 `world.items`를 직접 읽는다. 분리 구성에서는 공통 로더를 사용하거나 `world.jsonld`를 읽도록 변경해야 한다. 물품 키의 순서는 유지했다.
- TODO(C 이영훈): 태스크의 스킬 호출·실패 상태 계약을 별도로 확정한다. 로그에 진입점만의 해시를 기록하면 분리 파일·YAML 변경을 식별할 수 없으므로 전체 구성의 버전/해시 기록도 연계한다.
- TODO(B 서동권): 접근 동작 책임·미측정 설정 사용 차단을 실행 계약으로 확정한다.

## 물품 목록 갱신 (#8)

- `world.items`는 제공된 실측/외접박스 표의 11종·12개를 반영한다. 번호 고정은 A의 `config/yolo_classes.txt`에서 하며 여기의 순서를 다시 바꿔 기존 라벨을 해석하지 않는다.
- P1은 등록 물품의 단일 요청이며 `commute_set`은 P3 예시 참조 데이터다. `roles`의 request_target은 파지 검증 완료를 의미하지 않는다.
- `sources.item_grasp`의 `config/item_grasp.yaml`을 읽어 `grip_force`와 `grasp_verified`를 물품에 제공한다. 미확정 값은 null/false로 유지한다. 미확정 상태를 거절하는 E 함수와 실제 실행 경로 연결은 구분한다.
- 치수·분류·역할·초기 상태·인계의 현재 기준은 공용 `docs/ontology.md`, `docs/interfaces.md`, `docs/hardware.md`다. 이전의 '물품 size_m 예시값 유지' 설명은 이번 실측 반영으로 대체된다.
