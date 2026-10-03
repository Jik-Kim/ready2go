# ready2go 문서 인덱스

음성 명령으로 실물 Doosan M0609 + RG2가 서랍 속 물건을 찾아 꺼내고 원상 복구하는 시스템. 로봇의 동작·상태를 JSON 온톨로지로 정의하고 명령에 맞춰 조합하며, 모든 동작의 성공 여부를 기록함.

* **요구사항 기준 원본(SOT)**: [requirements.md](requirements.md) — 목표, 기능·비기능 요구사항 ID, Phase 범위 및 완료 기준.
* **기술 상세**: 각 주제 문서는 구현 방법과 계약을 설명하고 관련 요구사항 ID를 참조한다. 범위·Phase·완료 기준은 `requirements.md`가 우선한다.
* **변경 이력**: [changelog.md](changelog.md).

## 읽는 규칙 (사람·AI 에이전트 공통)

1. 이 인덱스를 먼저 읽고, **작업에 필요한 문서만** 연다. 전체를 한 번에 읽지 않는다.
2. JSON은 문서가 아니라 **원본 파일**을 본다: `contracts/`(스키마·예시), `knowledge/`(온톨로지), `tasks/`(태스크).
3. 작업 관련 요구사항 ID와 Phase는 [requirements.md](requirements.md)의 해당 항목에서 확인한다. 문서 전체를 읽지 않고 필요한 FR/NFR과 완료 기준만 본다.
4. `docs/archive/`는 기본으로 읽지 않는다(과거 스냅샷).
5. Phase 배정이 바뀌면 `requirements.md`의 FR/NFR 표를 먼저 수정하고, 관련 기능 문서의 요구사항 ID와 안내를 같은 PR에서 확인·갱신한다.

## 작업 → 읽을 문서

| 작업 | 요구사항 기준 | 먼저 읽을 상세 문서 | 원본 파일 |
| :--- | :--- | :--- | :--- |
| 비전 (`ready2go_vision`) | [FR-VIS-01–04](requirements.md#fr-vis-01), [FR-ML-01](requirements.md#fr-ml-01) | [vision.md](vision.md), [interfaces.md](interfaces.md) | `contracts/` |
| 모션·서랍 개폐 (`ready2go_skills`) | [FR-ACT-01–04](requirements.md#fr-act-01), [NFR-SAF-01–02](requirements.md#nfr-saf-01) | [domain.md](domain.md), [runner.md](runner.md), [safety.md](safety.md), [hardware.md](hardware.md) | `config/` |
| Runner·로그 (`ready2go_runner`) | [FR-PLN-01](requirements.md#fr-pln-01), [FR-LOG-01–02](requirements.md#fr-log-01) | [runner.md](runner.md), [ontology.md](ontology.md) | `contracts/task.schema.json`, `tasks/` |
| 플래너 (Phase 2~) | [FR-PLN-02](requirements.md#fr-pln-02), [FR-ONT-02](requirements.md#fr-ont-02) | [planner.md](planner.md), [ontology.md](ontology.md) | `knowledge/robot_ontology.jsonld` |
| 온톨로지 (`ready2go_knowledge`) | [FR-ONT-01–03](requirements.md#fr-ont-01) | [ontology.md](ontology.md) | `knowledge/` |
| 음성·LLM (`ready2go_voice`) | [FR-INT-01–03](requirements.md#fr-int-01) | [voice_llm.md](voice_llm.md), [interfaces.md](interfaces.md) | `contracts/intent.schema.json` |
| Docker·네트워크·DB | [NFR-ENV-01](requirements.md#nfr-env-01), [FR-COM-01–02](requirements.md#fr-com-01), [NFR-DB-01](requirements.md#nfr-db-01) | [docker.md](docker.md), [interfaces.md](interfaces.md) | `compose.yaml`, `config/cyclonedds.*.xml` |
| Isaac Sim 트윈 | [FR-TWN-01–02](requirements.md#fr-twn-01), [NFR-TWN-01](requirements.md#nfr-twn-01) | [twin.md](twin.md) | `sim/` |
| 일정·담당 확인 | [schedule.md](schedule.md), [overview.md](overview.md) 0장 | — |
| 시연 준비 | [demo_scenario.md](demo_scenario.md), [safety.md](safety.md) | — |

## 문서 목록

| 문서 | 내용 | 기획서 v4.1 장 |
| :--- | :--- | :--- |
| [requirements.md](requirements.md) | BRD/SRD 요구사항, ID, Phase 범위·완료 기준 (기준 원본) | (신규) |
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
| [demo_scenario.md](demo_scenario.md) | 최종 시연 시나리오 "출근 준비 도우미" | 17 |
| [changelog.md](changelog.md) | 변경 이력 | (머리말) |
| [research/prior_art_report.md](research/prior_art_report.md) | 선행 사례 조사 보고서 | (별도) |

> 문서 본문의 "(7.5)", "8.4절" 같은 번호는 위 표의 "기획서 v4.1 장" 열로 찾으면 됨.
