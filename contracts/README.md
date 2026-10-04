# contracts — JSON 계약

> 문서 설명: [`docs/runner.md`](../docs/runner.md), [`docs/voice_llm.md`](../docs/voice_llm.md), [`docs/interfaces.md`](../docs/interfaces.md)

| 파일 | 내용 | Phase |
| :--- | :--- | :--- |
| `task.schema.json` | 태스크(복합 스킬) JSON 스키마 | P1~ |
| `intent.schema.json` | 음성·LLM 인텐트 출력 (`/voice/intent`) | P1~ (`goals`·`query`는 P2) |
| `examples/execution_log.json` | 실행 로그 예시 (`pre_check`·`post_check`·`state_diff`는 P2) | P1~ |
| `examples/inspect_region_result.json` | `inspect_region` 결과 예시 (runner.md 7.1). `pose` = `{frame, position, yaw}`의 축·원점·yaw(긴 변 방향)는 확정(정의: `config/places.yaml` 첫 부분, runner.md 7.1). `position`의 마스크·박스 중심, yaw 범위·대칭 처리, `position.z`는 B의 `pick_object`와 합의 전 **[팀 확정 필요]** | P1 |
| `examples/task_nudge_then_pick.json` | `nudge_object`를 쓰는 P1 태스크 예시(밀기 → 다시 인식 → 재판단 → 집기). `validate_contracts.py`가 스키마와 P1 범위를 검사 | P1 |
| `examples/intent_find_item.json` | P1 인텐트 예시 | P1 |
| `examples/intent_goal.json` | 목표형 명령 인텐트 예시 | P2 |

## 규칙
- 계약을 바꾸면 스키마·예시·문서를 **같은 PR**에서 고치고 `python3 tools/validate_contracts.py`를 통과시킨다.
- 물품 키·장소 이름 enum은 런타임에 온톨로지(`knowledge/robot_ontology.jsonld`)에서 생성하므로 스키마에는 문자열로만 둔다.
- TODO(C 이영훈): 실행 로그·온톨로지 스키마(`log.schema.json`, `ontology.schema.json`) — Phase 2.
