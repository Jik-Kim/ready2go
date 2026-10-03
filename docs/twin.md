# Isaac Sim 디지털 트윈

> 관련 요구사항: [FR-TWN-01–02](requirements.md#fr-twn-01), [NFR-TWN-01](requirements.md#nfr-twn-01). 디지털 트윈 검증 경계와 구현 상세는 이 문서에서 다룹니다.

## 10. Isaac Sim 디지털 트윈 (담당 A, 보조 경로)

### 10.1 역할
| 모드 | 내용 | 효과 |
| :--- | :--- | :--- |
| **사전 검증** (`BACKEND=sim`) | 새 JSON을 DSR 에뮬레이터 + Isaac Sim + oracle 비전으로 먼저 실행. **검증 범위는 도달성·충돌·관절 한계·스킬 순서**로 한정 | 실물 로봇 사용 시간 절약, 위험 동작 사전 차단, B(실물)와 A(트윈)의 동시 테스트 |
| **실물 미러링** | 실물 실행 중 `/dsr01/joint_states`, `/gripper/state`, `/drawers/state`를 받아 트윈에 실시간 반영 | 디지털 트윈 검증, 시연에서 실물·트윈 화면 병렬 표시 |

> **트윈이 검증하지 못하는 것 (문서·발표에 명시)**: 접촉·마찰·힘 제어(컴플라이언스 인출), 가벼운 서랍장의 밀림, 실제 파지 성공, RealSense 뎁스 결손. 이 항목은 실물 시험으로만 확인함.

### 10.2 기존 자산 재사용 (A의 이전 Isaac Sim 5.1.0 프로젝트, `~/isaac_legacy/M0609_jik`)
* M0609 + RG2 + 손목 카메라 조립 USD (`Collected_m0609_camera_cube/`), M0609 URDF·USD (`doosan-robot2/`)
* RG2: `finger_joint` 구동 + 나머지 mimic 관절을 `ParallelGripper`로 제어하는 방식 검증 완료
* Lula IK 디스크립터(`descriptor/`), RMPflow 설정·pick & place 컨트롤러(`rmpflow/`), 단계별 예제(`lula_ik/`)
* → 로봇 모델링은 새로 하지 않고 **이관·재검증**만 함. 서랍장은 **실물 실측 치수**로 새로 모델링.

### 10.3 작업 단계와 중단 기준
| 단계 | 내용 | 기한 |
| :--- | :--- | :--- |
| T1 씬 | 기존 M0609 조립본 + 실측 서랍장(Prismatic Joint) + 트레이, 호스트 ROS 2 + CycloneDDS로 Bridge 동작 확인 | Day 2~3 |
| T2 미러링 | `/dsr01/joint_states` → 트윈 조인트 위치 구동 (에뮬레이터·실물 공통) | Day 4 |
| T3 사전 검증 | 손목 카메라 oracle, 시뮬 그리퍼(attach 폴백), `BACKEND=sim`으로 7.3 예시 실행 | Day 6~7 |

* **중단 기준**: Day 5 1차 점검까지 T2가 안 되면 사전 검증(T3)은 포기하고 시각화만 유지, A는 비전에 집중. **트윈이 없어도 실물 경로는 영향 없음.**
* **폴백**: 에뮬레이터 미러링이 불안정하면 사전 검증에 한해 기존 Lula IK / RMPflow 컨트롤러 사용(실물과 제어 경로가 다르다는 점은 문서에 명시).
* **USD 관리**: USD는 Git 병합이 불가능하므로 **A만 편집**(단일 편집자). 백업은 Git LFS로 매일 push. PC2는 받기만 함(편집 금지).
* **PC2 활용 (RTX 4060)**: PC2에도 Isaac Sim 5.1.0을 설치해 두면 B가 실물 로봇을 기다리는 동안 직접 사전 검증을 돌릴 수 있고, PC1 고장 시 트윈 예비 장비가 됨. 설치·자산 복사는 여유 시(Day 3~4) A가 지원하며 핵심 경로가 아님. 두 PC 모두 VRAM 8GB급이므로 시연 중 PC2에서는 Isaac Sim을 띄우지 않음(실물 제어·비전 전용).
