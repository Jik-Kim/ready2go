# ready2go_knowledge

- **담당**: E 고희태
- **역할**: OntologyManager: 로봇 온톨로지 로딩 · 정합성 검사 · 상태 읽기/쓰기

## 작업 전에 읽을 문서
- `docs/ontology.md`
- `docs/planner.md`

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
- `state`는 초기화용 프리셋 복사다. 실제 상태 확인과 현재 상태 적용·저장은 Runner 책임이다.
- Python 실행 의존성: `PyYAML` (`setup.py`), ROS/시스템 의존성: `python3-yaml` (`package.xml`). CI에서도 `PyYAML`을 설치한다.
- 단위 테스트: 저장소 루트에서 `PYTHONPATH=ros2_ws/src/ready2go_knowledge python3 -m pytest ros2_ws/src/ready2go_knowledge/test -q`.
- 전체 파일 역할·담당별 인계: [`knowledge/README.md`](../../../knowledge/README.md).

- 물품 파지 설정 정본 `config/item_grasp.yaml`도 로딩하여 기존 물품 조회에 grip_force(null 허용)·grasp_verified를 제공한다. `require_grasp_settings(onto, item)`은 미확정 설정을 거절하지만 실제 실행 경로 연결은 B·C 담당이다.
