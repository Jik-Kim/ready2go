# D 실행 상세 조회를 위한 기록 저장 시점 확인

확인 기준: PR #389의 Runner 소스 `b2a9481a`, 2026-10-15. C 코드·계약·저장 형식은 수정하지 않았다.
요구사항 기준은 [FR-LOG-01(P1)·FR-LOG-02(P2)](../docs/requirements.md#fr-log-01),
[AC-LOG-01](../docs/requirements.md#ac-log-01), 목록·분류 범위는 [FR-INT-02(P3)](../docs/requirements.md#fr-int-02)를 참조한다.
아래는 현행 구현과 확인 결과이며 새 계약이나 실시간 제공 합의가 아니다.

## 코드에서 확인한 기록 시점

| 정보 | 시작 | 진행 | 종료 및 D 조회 의미 |
| --- | --- | --- | --- |
| 상위 그룹 run | `_run_group`이 `run_group` 호출 전에 `start_run`. `inputs.semantic` 포함 | 상위 `items`를 단계마다 갱신하는 쓰기 없음 | `run_group` 반환 후 `end_run`에 `items`, `start_text`, `summary_text` 추가. 현재 D는 연결된 종료 기록만 조회 |
| 확정 순서·제외 목록 | `plan_group`이 메모리에서 결정하지만 시작 문서에는 저장하지 않음 | 메모리의 결과 객체만 갱신 | 상위 종료 `items`에 runnable 뒤 excluded 순서로 저장. `semantic.items`나 child ID 정렬을 실행 계획으로 대신 쓰면 안 됨 |
| 물품 child | 각 물품 차례에 `runner.run`을 호출하며 `R.n` 및 `parent_run_id=R` 전달. child 시작 문서부터 부모 참조 존재 | 현재 child 식별자를 상위 DB 문서에 실시간 갱신하지 않음 | child 종료 기록을 쓴 뒤 `run_group`이 전달·복구 결과를 판단하고, 마지막에 상위 종료 문서 저장 |
| 계획 구간 child | `run_plan`이 해당 구간을 실행할 때 생성 | `segments`는 실행 결과 객체에 누적 | `_run_plan`의 상위 `end_run`에서 `segments` 저장. 전체 구간 목록을 시작 기록으로 제공하는 경로가 아님 |
| 단계 | 시작 시 메모리에 seq와 기록 생성 | `_log_step`은 단계가 끝날 때 `write_step`. 중첩 블록은 자식보다 늦게 저장될 수 있음 | seq는 시작 순서이며 DB 쓰기 순서·성공 여부가 아님. 미완료 단계가 steps에 없다고 미실행으로 단정하지 않음 |
| `semantic.evidence` | 수신한 `decision.inputs.semantic`에 있을 때 상위 시작 입력에 함께 저장 | 근거를 새로 계산하거나 보강하는 상위 기록 갱신 없음 | 상위 종료 입력에도 유지. 물품 child 입력은 target/accept_text이며 상위 semantic 전체의 자동 복제가 아님 |
| 저장소 | Mongo: runs upsert / JSONL: runs 줄 추가 | Mongo: steps insert / JSONL: steps 줄 추가 | Mongo: 같은 run 문서 교체 / JSONL: runs 완성본 추가, 조회 시 마지막 runs 사용 |

[문서·코드 확인] 근거 위치:
- [RunnerNode `_run_group`·`_run_plan`](../ros2_ws/src/ready2go_runner/ready2go_runner/nodes/runner_node.py)
- [`item_group.plan_group`·`run_group`](../ros2_ws/src/ready2go_runner/ready2go_runner/core/item_group.py), [`plan_exec.run_plan`](../ros2_ws/src/ready2go_runner/ready2go_runner/core/plan_exec.py)
- [`Runner.run`·`_log_step`·`_finish`·`_suspend`·`continue_resumed`](../ros2_ws/src/ready2go_runner/ready2go_runner/core/interpreter.py)
- [`run_document`](../ros2_ws/src/ready2go_runner/ready2go_runner/core/log_records.py), [JSONL/Mongo/Fallback 저장소](../ros2_ws/src/ready2go_runner/ready2go_runner/core/logstore.py)

`ended_at`만으로 불변 최종 결과를 판정하면 안 된다. 일반 Runner는 SUSPENDED에도 `_finish`를 통해 종료 형식 문서를 쓰고, 같은 run의 재개 후 결과를 다시 쓴다. 그룹 실행은 내부 재개를 비활성화한다. D는 기존 요청/run 연결 및 종료 상태 검증을 유지해야 한다.

정상 동기 저장 호출 순서는 child 종료 → 물품 결과 판단 → 상위 종료 → `_finished`이다. 따라서 정상 경로에서 부모 종료가 child 종료보다 먼저 저장된다고 가정할 근거는 없다. 다만 `_log`/`_log_run`은 저장 오류를 잡고 실행을 계속하므로 상위 종료가 있다고 child 저장 성공까지 보장하지 않는다. 별도 프로세스 간 조회 지연·Mongo 장애 전환·양 저장소 누락은 이번 코드 확인으로 검증되지 않았다. 누락 child가 나중에 반드시 생긴다고 가정한 자동 재조회는 추가하지 않았다.

## 실행 기록으로 확인한 범위

[실측: 저장소에 포함된 기록 파일 조회] 기존 PC2 fixture 두 건을 읽어 확인했다. 이번에 PC2를 새로 실행한 결과가 아니다.

| 원본 | backend / 종료 상태 | 단계 수 | 한계 |
| --- | --- | --- | --- |
| [6fc193](../ros2_ws/src/ready2go_runner/test/fixtures/pc2_run_20261006_6fc193.json) | sim / FAILED | 7 | 종료 스냅샷이며 parent/items/segments/semantic 없음 |
| [f45c86](../ros2_ws/src/ready2go_runner/test/fixtures/pc2_run_20261006_f45c86.json) | sim / COMPLETED | 16 | 종료 스냅샷이며 parent/items/segments/semantic 없음 |

이 파일들은 P3 상위/child 저장 시점이나 실행 중 조회 가능성을 증명하지 않는다.

[실측: 모의 백엔드 + 실제 Runner 코어/JSONL] [저장 시점 시험](tests/test_execution_record_timing.py)은 실제 `Runner.run`과 `JsonlLogStore`를 실행하고 D reader로 동작 콜백 중 디스크를 읽는다. 성공·실패 두 경로에서 다음을 확인했다.

- 실행 전: 해당 run 없음.
- 첫 동작 실행 중: 시작 문서의 입력·parent 참조 있음, 단계와 종료 필드 없음.
- 둘째 동작 실행 중: 첫 단계 SUCCESS만 저장됨, 둘째 단계와 종료 필드 없음.
- 반환 후: 두 단계 결과와 COMPLETED 또는 FAILED·ended_at 확인.
- 계약 예시의 `semantic.evidence`가 시작 입력부터 그대로 읽힘. 이는 입력 보존 시험이며 실제 분류 추론·실물 근거 검증이 아니다. 테스트에서 child에 semantic을 명시적으로 주입했으며 운영 그룹 child가 semantic을 자동 상속한다는 뜻도 아니다.

```bash
python3 -m pytest web/tests/test_execution_record_timing.py web/tests/test_execution_detail.py -q
```

결과: **27 passed**. ROS 노드의 상위 그룹 전체 실행, 실 MongoDB 쓰기/조회 시점, 실물·PC2 신규 통합 시험은 수행하지 않았다. 전체 로컬 CI는 사용자 요청에 따라 최종 단계에 남긴다.

## D 후속 구현 경계

기존 기록으로 종료 상세를 제공하는 범위는 유지할 수 있다. 시작 시 확정 순서·제외 목록, 진행 중 현재 child와 물품별 전달 결과를 연결하려면 해당 데이터의 제공 경로 확인이 여전히 필요하다. D에서 계획·분류·작업 장소를 재계산하지 않는다. 이번 변경은 저장 시점 확인 자료와 회귀시험 추가이며 UI·API 런타임 동작 변경은 없다.
