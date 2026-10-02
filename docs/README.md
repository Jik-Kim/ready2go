# ready2go 문서 인덱스

음성 명령으로 실물 Doosan M0609 + RG2가 서랍 속 물건을 찾아 꺼내고 원상 복구하는 시스템. 로봇의 동작·상태를 JSON 온톨로지로 정의하고 명령에 맞춰 조합하며, 모든 동작의 성공 여부를 기록함.

* **현재 기준**: 기획서 v4.1을 주제별로 분할한 이 `docs/` 폴더가 단일 기준(SOT). 변경 이력은 [changelog.md](changelog.md).
* **개발 단계**: [phases.md](phases.md) — Phase 1(최소) → Phase 2(발전) → Phase 3(기획서 전체). 각 문서 맨 위에 해당 Phase 범위가 표시됨.

## 읽는 규칙 (사람·AI 에이전트 공통)

1. 이 인덱스를 먼저 읽고, **작업에 필요한 문서만** 연다. 전체를 한 번에 읽지 않는다.
2. JSON은 문서가 아니라 **원본 파일**을 본다: `contracts/`(스키마·예시), `knowledge/`(온톨로지), `tasks/`(태스크).
3. 지금 작업이 어느 Phase인지 [phases.md](phases.md)에서 확인하고, 그 Phase 범위 밖 기능은 만들지 않는다.
4. `docs/archive/`는 기본으로 읽지 않는다(과거 스냅샷).

## 작업 → 읽을 문서

| 작업 | 먼저 읽을 문서 | 원본 파일 |
| :--- | :--- | :--- |
| 비전 (`ready2go_vision`) | [vision.md](vision.md), [interfaces.md](interfaces.md) | `contracts/` |
| 모션·서랍 개폐 (`ready2go_skills`) | [domain.md](domain.md), [runner.md](runner.md) 7.1, [safety.md](safety.md), [hardware.md](hardware.md) | `config/` |
| Runner·로그 (`ready2go_runner`) | [runner.md](runner.md), [ontology.md](ontology.md) 7.8 | `contracts/task.schema.json`, `tasks/` |
| 플래너 (Phase 2~) | [planner.md](planner.md), [ontology.md](ontology.md) | `knowledge/robot_ontology.jsonld` |
| 온톨로지 (`ready2go_knowledge`) | [ontology.md](ontology.md) | `knowledge/` |
| 음성·LLM (`ready2go_voice`) | [voice_llm.md](voice_llm.md), [interfaces.md](interfaces.md) | `contracts/intent.schema.json` |
| Docker·네트워크 | [docker.md](docker.md) | `compose.yaml`, `config/cyclonedds.*.xml` |
| Isaac Sim 트윈 (Phase 2~) | [twin.md](twin.md) | `sim/` |
| 일정·담당 확인 | [schedule.md](schedule.md), [overview.md](overview.md) 0장 | — |
| 결정 사항 확인·추가 | [decisions.md](decisions.md) | — |
| 시연 준비 | [demo_scenario.md](demo_scenario.md), [safety.md](safety.md) | — |

## 문서 목록

| 문서 | 내용 | 기획서 v4.1 장 |
| :--- | :--- | :--- |
| [phases.md](phases.md) | 기능 Phase 구분과 완료 기준 | (신규) |
| [overview.md](overview.md) | 팀 R&R, 배경·목적·강사 챌린지, 선행 사례 대비 차별점 | 0, 1 |
| [hardware.md](hardware.md) | 작업 공간, 서랍장 구매 기준, 물품 선정 기준, 장비·노트북 구성 | 2 |
| [architecture.md](architecture.md) | 시스템 구조, 백엔드(real/sim/mock), 기술 스택 | 3, 12 |
| [docker.md](docker.md) | 서비스 구성, compose 프로파일, CycloneDDS, 운영 함정 | 4 |
| [interfaces.md](interfaces.md) | ICD(토픽·서비스·액션), ROS 외 호출 | 5 |
| [voice_llm.md](voice_llm.md) | 음성 파이프라인, 인텐트, LLM 파서 | 6 |
| [runner.md](runner.md) | 원자 동작, 제어 블록, 변수·조사 규칙, 실패 처리, 태스크 스키마, 실행 로그 | 7 (7.1~7.4) |
| [ontology.md](ontology.md) | 로봇 온톨로지(동작·상태·세계), 스킬 추가, 상태 추적, 지식 그래프 | 7 (7.5, 7.6, 7.8, 7.9) |
| [planner.md](planner.md) | 명령 → 스킬 조합 (BFS) | 7 (7.7) |
| [domain.md](domain.md) | 목록 탐색, Unpacking, 복구, 서랍 개폐 구현 | 8 |
| [vision.md](vision.md) | 비전 단계(V0~V3), 모델 결정 | 9 |
| [twin.md](twin.md) | Isaac Sim 역할, 기존 자산, 단계·중단 기준 | 10 |
| [safety.md](safety.md) | 비상정지, 실물 실행 절차, 안전 게이트 | 11 |
| [schedule.md](schedule.md) | 14일 일정, 체크포인트 | 13 |
| [metrics_risks.md](metrics_risks.md) | 성공 지표, 리스크 | 14, 15 |
| [decisions.md](decisions.md) | 결정 로그 | 16 |
| [demo_scenario.md](demo_scenario.md) | 최종 시연 시나리오 "출근 준비 도우미" | 17 |
| [changelog.md](changelog.md) | 변경 이력 | (머리말) |
| [research/prior_art_report.md](research/prior_art_report.md) | 선행 사례 조사 보고서 | (별도) |

> 문서 본문의 "(7.5)", "8.4절" 같은 번호는 위 표의 "기획서 v4.1 장" 열로 찾으면 됨.
