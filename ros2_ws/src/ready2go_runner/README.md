# ready2go_runner

- **담당**: C 이영훈
- **역할**: JSON Runner · 플래너 · 상태 추적 · 실행 로그(LogStore→MongoDB)

## 작업 전에 읽을 문서
- `docs/runner.md`
- `docs/planner.md`
- `docs/ontology.md (7.8 상태 추적)`
- `docs/interfaces.md`

## 구조

| 폴더 | 내용 |
| :--- | :--- |
| `ready2go_runner/core/` | ROS에 의존하지 않는 로직. **단위 테스트 대상** (`pytest`로 ROS 없이 실행) |
| `ready2go_runner/nodes/` | rclpy 노드 (ROS 토픽·서비스·액션 연결만) |
| `ready2go_runner/adapters/` | 장치·외부 서비스 연결 (DSR, RG2, RealSense, OpenAI, MongoDB 등) |
| `test/` | `core/` 테스트 |

## 규칙
- 다른 담당의 패키지는 수정하지 않음. 필요하면 GitHub Issue로 요청.
- 계약(`ready2go_interfaces`, `contracts/`)을 바꾸면 스키마·예시·문서를 같은 PR에서 함께 수정.
