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

## 음성 요청 상관 (계약07)

E 가 실행 요청(`find_item`·`achieve_goal`)에 최상위 `request_id`·`accept_text`를 실으면: 같은 ID 재전송·충돌은 첫 결정을 다시 발행만(재실행 없음, 이번 기동 동안), 수락할 때 정한 `run_id`가 `/runner/status` `last_intent.run_id`와 최종 `last.run_id`에 같게 나오고, `accept_text`는 그 run 의 첫 안내 1회(실패하면 첫 동작 없음). 둘 다 없으면 P1 그대로. 규칙은 [runner.md 7.1 "요청 상관 — 계약07"](../../../docs/runner.md).

## 실행 기록 보기

MongoDB `cobot2.runs`·`steps`는 사람이 바로 읽기 어려워서, 요약 명령을 둡니다(읽기 전용, ROS 토픽 불필요).

```bash
ros2 run ready2go_runner run_report                                  # 가장 최근 실행
ros2 run ready2go_runner run_report --uri mongodb://172.24.0.3:27017 -n 2   # PC2 DB 최근 2건
ros2 run ready2go_runner run_report --run f45c86 --markdown         # GitHub 댓글용 표
ros2 run ready2go_runner run_report --jsonl /logs                    # DB 장애 때 JSONL 예비 기록
```

## 규칙
- 다른 담당의 패키지는 수정하지 않음. 필요하면 GitHub Issue로 요청.
- 계약(`ready2go_interfaces`, `contracts/`)을 바꾸면 스키마·예시·문서를 같은 PR에서 함께 수정.
