# 플래너: 명령 → 스킬 조합

> 아래 내용은 requirements.md의 요구사항에 따른 설계·계약 설명입니다. 문서의 존재나 현재형 표현만으로 구현 완료를 의미하지 않으며, Phase·완료 기준은 requirements.md를 따릅니다. 실제 연결 여부는 담당 코드와 작업 기록에서 확인합니다. [문서]

> 관련 요구사항: [FR-PLN-02–03](requirements.md#fr-pln-02), [FR-ONT-02–03](requirements.md#fr-ont-02). 플래너 알고리즘과 실행 상세는 이 문서에서 다룹니다.

## 7. 로봇 온톨로지 및 JSON 규격 (일부)

### 7.7 플래너: 명령 → 스킬 조합 (담당 C)

강사 챌린지의 "명령을 내리면 그 조합으로 다양한 행동"을 담당. **동작 순서는 하드코딩하지 않고 스킬의 조건·결과에서 도출**함.

```
음성 명령 → LLM(6.4)이 목표 추출: goals = [{predicate: located_in, subject: lip_balm, value: drawer_bottom}]
         → 플래너: 현재 state에서 primitive 스킬을 너비 우선 탐색(BFS)하여 목표를 만족하는 최단 조합 탐색
            (기본 목표에 "이번 계획에서 연 서랍은 닫기"를 자동 추가)
         → 계획(7.2 형식 JSON) 생성 → 스키마 검증 → 화면 표시 → Runner 실행
```

**예: "립밤 아래 서랍에 넣어줘"** (립밤은 전달 트레이, 아래 서랍은 닫힘, 그리퍼 비어 있음)

| 순서 | 스킬 | 이 순서가 나온 이유 (조건) |
| :--- | :--- | :--- |
| 1 | `open_drawer(drawer_bottom)` | `place`는 `open.drawer_bottom = true`가 필요. `open_drawer`는 `gripper = empty`가 필요하므로 **집기 전에** 열어야 함 |
| 2 | `pick(lip_balm, handover_zone)` | `place`는 `gripper = lip_balm`이 필요 |
| 3 | `place(lip_balm, drawer_bottom)` | 목표 `located_in.lip_balm = drawer_bottom` 달성 |
| 4 | `close_drawer(drawer_bottom)` | 자동 추가 목표(연 서랍 닫기), `place` 후 그리퍼가 비어 있어 가능 |

* **탐색 범위**: 스킬 수가 10개 안팎인 작은 세계이므로 BFS(깊이 제한 8)로 충분함. 외부 플래닝 라이브러리 없이 Python으로 구현.
* **계획 불가 시**: 어떤 조건을 만족할 수 없는지 설명하여 TTS로 응답(예: "임시 트레이가 가득 차서 옮길 수 없습니다").
* **이미 만족된 목표**: 계획 길이 0 → "이미 아래 서랍에 있습니다" / "이미 닫혀 있습니다"처럼 상태를 근거로 응답.
* **실행 중 실패 시 재계획**: 스텝이 실패하면 관측으로 갱신된 상태에서 1회 재계획, 그래도 실패하면 안전 정지.
* LLM은 **목표만** 출력하고 동작 순서는 만들지 않음 → LLM이 위험한 순서를 지어낼 여지를 없앰.
