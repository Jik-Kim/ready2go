# ready2go_knowledge

- **담당**: E 고희태
- **역할**: `core.ontology`의 함수로 온톨로지를 로딩하고 참조·파지 설정 및 조건을 검사합니다. `get()`은 전달받은 상태를 조회하고, `apply()`는 원본 상태를 바꾸지 않고 효과를 반영한 새 상태와 차이를 반환합니다. `OntologyManager` 클래스는 없습니다. 실제 현재 상태 관리·적용·저장은 Runner(C) 책임입니다.

## 작업 전에 읽을 문서
- [문서 인덱스](../../../docs/README.md)
- [FR-ONT-01–03](../../../docs/requirements.md#fr-ont-01)·[물품 정책](../../../docs/requirements.md#item-policy)·[가림 정책](../../../docs/requirements.md#occlusion-policy): 의미·정책·Phase·완료 기준의 정본
- [온톨로지 구현](../../../docs/ontology.md)·[플래너 구현](../../../docs/planner.md): 해당 모듈 설명. 요구사항을 복사해 정의하지 않음

## #302 composite 계획 필드 검사

`core.ontology.load()`는 manifest와 구 단일 파일에서 `plan_effect`가 있는 composite의 새 형식을 검사합니다. 기존 actual effect는 sensing으로 유지하고, 계획 필드를 읽어 실제 상태를 쓰는 경로는 추가하지 않았습니다. 형식/등록 참조/매개변수·pre 검사 범위와 C 소비 대기는 [knowledge 원본 설명](../../../knowledge/README.md#302-계획-전용-composite-필드--e-구현--c-연결-대기)을 참조하십시오. primitive와 계획 필드 없는 구 온톨로지의 기존 경로는 보존합니다.

후속 `test/test_plan_effect_consumer.py`는 C #373의 실제 opt-in core API에 E 원본을 로드하여 후보 선택·find_with_unpack mock 실행·실제 위치 확인/재계획과 성공 표기만 있는 미전달 차단을 검사합니다. E `a991a888` 데이터/로더 + C `810de713` 공개 head에서 직접3사례가 통과했습니다. C core API가 없는 기본 main에서는 해당 연결 사례를 skip하고, C API/테스트 mock을 함께 제공한 격리 환경에서만 이 연결 검사를 실행합니다. C 노드/음성 운영 연결은 별도입니다.

직접 회귀는 `test/test_plan_effect.py`와 기존 `test_ontology.py`·`test_pick_runner.py`로 확인합니다. 실제 C 공개 plan/run 대조는 미연결이면 명시적 skip이며 통합 성공으로 세지 않습니다. 향후 planner 후보 선택이 연결되어도 실제 구간 실행·상태 재계획·실물 확인은 별도입니다. [FR-PLN-02](../../../docs/requirements.md#fr-pln-02)·[FR-ONT-02](../../../docs/requirements.md#fr-ont-02), 형식 E 포함2명 승인과 실행 후속은 [#302](https://github.com/Jik-Kim/ready2go/issues/302)에서 확인하십시오.

## 구조

| 폴더 | 내용 |
| :--- | :--- |
| `ready2go_knowledge/core/` | ROS에 의존하지 않는 로직. **단위 테스트 대상** (`pytest`로 ROS 없이 실행) |
| `ready2go_knowledge/nodes/` | rclpy 노드 (ROS 토픽·서비스·액션 연결만) |
| `ready2go_knowledge/adapters/` | 장치·외부 서비스 연결 (DSR, RG2, RealSense, OpenAI, MongoDB 등) |
| `test/` | `core/` 테스트 |

## 규칙
- 다른 담당의 패키지는 수정하지 않음. 필요하면 GitHub Issue로 요청.
- 계약(`ready2go_interfaces`, `contracts/`)을 바꾸면 스키마·예시·문서를 같은 PR에서 함께 수정.

## 온톨로지 로딩 (P1)

- `core.ontology.load(<저장소>/knowledge/robot_ontology.jsonld)`가 `sources`의 JSON-LD·초기 상태 JSON·장소 YAML을 읽는다.
- 반환 구조는 `classes`·`world`·`state`·`skills`로 유지한다. 장소 설정은 `config/places.yaml`을 정본으로 하며 공통 식별자로 결합한다.
- `robot_ontology.jsonld`는 이제 참조 목록이므로 `json.load()`만 호출하면 전체 지식을 얻을 수 없다.
- 기본 load는 manifest의 단일 initial_state를 읽는다. 선택 입력 `load(manifest, snapshot=provided_state_path)`은 사용자가 별도로 제공한 시험 파일을 읽으며 상대 경로는 manifest 폴더 기준이다. 현재 6종 위치·S3 실물 제외·API 호환/운영 경계는 [단일 초기 상태와 선택 API](../../../knowledge/README.md#p2-시작-배치-선택--e-구현c-연결-대기)을 참조한다.
- `state`는 초기화용 프리셋 복사다. 실제 상태 확인과 현재 상태 적용·저장은 Runner 책임이다.
- Python 실행 의존성: `PyYAML` (`setup.py`), ROS/시스템 의존성: `python3-yaml` (`package.xml`). CI에서도 `PyYAML`을 설치한다.
- 단위 테스트: 저장소 루트에서 `PYTHONPATH=ros2_ws/src/ready2go_knowledge python3 -m pytest ros2_ws/src/ready2go_knowledge/test -q`.
- 전체 파일 역할·담당별 인계: [`knowledge/README.md`](../../../knowledge/README.md).

- 물품 파지 설정 정본 `config/item_grasp.yaml`도 로딩하여 기존 물품 조회에 grip_force(null 허용)·grasp_verified와 선택 항목 grasp_width_m·grasp_width_long_m(B 실측 잡은 폭, size_m 해당 변 이하 양수)을 제공한다. `require_grasp_settings(onto, item)`은 미확정 설정을 거절하지만 실제 실행 경로 연결은 B·C 담당이다.

## P3 TTL 의미 조회 — #302 첫 시험

`core.semantic_query.load_ttl()`은 명시한 로컬 TTL을 읽고 활성 물품 키·은퇴 목록과 대조한다. RDF 파싱은 RDFLib, 상속 경로 탐색·순환/참조 검사는 E 함수에서 수행한다. 현재 지원 관계는 `rdf:type`, `rdfs:subClassOf`, `rdfs:label`, 프로젝트 `alias_ko`·`hasItem`이다. OWL 전체 추론기가 아니다.

```python
from pathlib import Path
from ready2go_knowledge.core import ontology, semantic_query

root = Path.cwd()  # 저장소 루트에서 실행
onto = ontology.load(root / 'knowledge/robot_ontology.jsonld')
retired = (root / 'config/yolo_retired_classes.txt').read_text().splitlines()
catalog = semantic_query.load_ttl(
    root / 'knowledge/examples/p3_semantics.ttl',
    active_items=onto['world']['items'], retired_items=retired)
result = catalog.query_class('귀중품')  # query_list('출근 준비물')도 지원
```

분류 결과 예시:

```json
{
  "items": ["car_key"],
  "source": {"kind": "class", "id": "Valuables", "name_ko": "귀중품", "sha256": "<읽은 TTL 바이트의 SHA-256>"},
  "evidence": {"car_key": {"class_paths": [["Key", "Valuables"]]}}
}
```

- 반환 물품은 중복 없이 키 순으로 정렬한다. 실행 순서·실행 가능·파지 가능 판정이 아니다. 위치 기록이 없는 등록 물품도 반환한다.
- `source`는 선택한 분류/목록과 읽은 파일의 출처이며 현재 로봇 상태·관측 시각이 아니다. 클래스/목록 키와 이름·별칭으로 조회하며 모호하거나 없는 이름은 `ValueError`로 거절한다. 정상 빈 분류·목록은 빈 `items`를 반환한다.
- 미등록·은퇴 물품, 누락된 분류/목록 참조, 클래스/물품/목록 선언 충돌, 분류 순환과 허용하지 않은 관계를 읽을 때 거절한다. 복수 상위 분류는 지원하며 각 물품의 직접 분류별 최단 상속 경로 하나를 근거로 반환한다.
- `knowledge/examples/p3_semantics.ttl`은 **저장소의 소규모 시험 자료**다. 운영 manifest와 설치 데이터에는 등록하지 않는다. 운영 의미 원본의 TTL 전환 또는 기존 원본에서 그래프를 만드는 방식은 아직 미결이다. 기존 JSON-LD·초기 상태·스킬은 그대로 사용한다.
- C 전달 후보는 `items`·`source`·`evidence`다. C는 기존 `query_ontology {item}`으로 현재 위치를 조회하며 `list/class`는 `NOT_SUPPORTED`를 유지한다. **음성 입력·C 전달 어댑터·다중 서랍 실행·GUI는 아직 미연결**이다. 새 ROS/wire 계약은 이번에 추가하지 않는다.
- Python 의존성은 `setup.py`·공통 `requirements.txt`의 `rdflib>=6.1.1,<8`, ROS 시스템 의존성은 `package.xml`의 `python3-rdflib`이다. 기존 로더는 이 모듈을 import하지 않는다. C 동의로 core CI의 pip 목록에도 같은 범위를 추가했다. 도커 실행 이미지 추가는 Runner/음성 연결 시 검토하며 이번에는 변경하지 않는다.

최소 검사는 `PYTHONPATH=ros2_ws/src/ready2go_knowledge:ros2_ws/src/ready2go_runner python3 -m pytest ros2_ws/src/ready2go_knowledge/test/test_semantic_query.py -q`로 실행한다. 기존 로더/스킬 회귀와 실행 수신 연결은 별도 근거로 구분한다. 기준은 [FR-ONT-03](../../../docs/requirements.md#fr-ont-03), 담당별 결정은 [#302](https://github.com/Jik-Kim/ready2go/issues/302)를 따른다.
