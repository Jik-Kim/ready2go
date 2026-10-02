# 기능 Phase 요약

> **기준 원본:** [requirements.md](requirements.md) — 요구사항 범위, Phase 배정 및 완료 기준.
> 이 문서는 시연 수준을 빠르게 확인하기 위한 요약이며, 요구사항 원본과 충돌하면 `requirements.md`가 우선한다.

| Phase | 핵심 시연 | 주요 요구사항 |
|---|---|---|
| **1 — 음성으로 보이는 물건 꺼내기** | 음성 명령 → RealSense·YOLO 위치 인식 → 실물 Doosan/RG2 Pick and Place → MongoDB 실행 이력. Docker와 다중 PC/컨테이너 통신도 검증한다. | [FR-INT-01–03](requirements.md#fr-index), [FR-VIS-01–02](requirements.md#fr-index), [FR-ML-01](requirements.md#fr-ml-01), [FR-ACT-01–03](requirements.md#fr-index), [FR-LOG-01](requirements.md#fr-log-01), [NFR-ENV-01](requirements.md#nfr-env-01), [FR-COM-02](requirements.md#fr-com-02) |
| **2 — 온톨로지 계획과 가림 복구** | 플래너가 스킬 조건·결과에서 계획을 만들고, 가림 물체를 임시 이동한 뒤 LIFO 복구한다. 상세 실행 상태를 저장하고 트윈 미러링을 추가한다. | [FR-ONT-02](requirements.md#fr-ont-02), [FR-PLN-02](requirements.md#fr-pln-02), [FR-VIS-03](requirements.md#fr-vis-03), [FR-ACT-04](requirements.md#fr-act-04), [FR-LOG-02](requirements.md#fr-log-02), [FR-TWN-01](requirements.md#fr-twn-01) |
| **3 — 목록·다중 서랍·상태 보정** | 목록/분류형 음성 명령으로 여러 서랍을 탐색하고 상태 불일치를 안전하게 처리한다. 트윈 사전 검증과 선택 분할 기능을 확장한다. | [FR-INT-02](requirements.md#fr-int-02), [FR-ONT-03](requirements.md#fr-ont-03), [FR-REC-01](requirements.md#fr-rec-01), [FR-TWN-02](requirements.md#fr-twn-02), [FR-VIS-04](requirements.md#fr-vis-04) |

담당자와 일정은 [schedule.md](schedule.md), 기술 설계는 [문서 인덱스](README.md)의 주제별 문서를 참조한다.
