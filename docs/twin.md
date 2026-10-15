# Isaac Sim 디지털 트윈

> 관련 요구사항: [FR-TWN-01–02](requirements.md#fr-twn-01), [NFR-TWN-01](requirements.md#nfr-twn-01). 디지털 트윈 검증 경계와 구현 상세는 이 문서에서 다룹니다.

## 10. Isaac Sim 디지털 트윈 (담당 A, 보조 경로)

### 10.1 역할
| 모드 | 내용 | 효과 |
| :--- | :--- | :--- |
| **사전 검증** (`BACKEND=sim`, [FR-TWN-02](requirements.md#fr-twn-02)) | 새 JSON을 DSR 에뮬레이터 + Isaac Sim + oracle 비전으로 먼저 실행. **검증 범위는 도달성·충돌·관절 한계·스킬 순서**로 한정 | 실물 로봇 사용 시간 절약, 위험 동작 사전 차단, B(실물)와 A(트윈)의 동시 테스트 |
| **실물 미러링** ([FR-TWN-01](requirements.md#fr-twn-01)) | 실물 실행 중 `/dsr01/joint_states`, `/gripper/state`, `/drawers/state`를 받아 트윈에 실시간 반영 | 디지털 트윈 검증, 시연에서 실물·트윈 화면 병렬 표시. **관절 미러링 실물 확인(10/11, PC1 local DDS) — 그리퍼·서랍 미연결**(아래 T2) |

> **트윈이 검증하지 못하는 것 (문서·발표에 명시)** — 검증 경계 기준은 [NFR-TWN-01](requirements.md#nfr-twn-01), 아래는 이 트윈의 구체 목록: 접촉·마찰·힘 제어(컴플라이언스 인출), 가벼운 서랍장의 밀림, 실제 파지 성공, RealSense 뎁스 결손. 이 항목은 실물 시험으로만 확인함.

### 10.2 기존 자산 재사용 (A의 이전 Isaac Sim 5.1.0 프로젝트, `~/isaac_legacy/M0609_jik`)
* M0609 + RG2 + 손목 카메라 조립 USD (`Collected_m0609_camera_cube/`), M0609 URDF·USD (`doosan-robot2/`)
* RG2: `finger_joint` 구동 + 나머지 mimic 관절을 `ParallelGripper`로 제어하는 방식 검증 완료
* Lula IK 디스크립터(`descriptor/`), RMPflow 설정·pick & place 컨트롤러(`rmpflow/`), 단계별 예제(`lula_ik/`)
* → 로봇 모델링은 새로 하지 않고 **이관·재검증**만 함. 서랍장은 **실물 실측 치수**로 새로 모델링.

### 10.3 작업 단계와 중단 기준
| 단계 | 내용 | 기한 | 상태 |
| :--- | :--- | :--- | :--- |
| T1 씬 | 기존 M0609 조립본 + 서랍장(Prismatic Joint) + 트레이 (서랍은 10/03에 원목 2단으로 교체, 새 실측값으로 복원), `sim/isaac_env.sh`(번들 ROS 라이브러리 + CycloneDDS)로 Bridge 동작 확인 | Day 2~3 | **완료(스토퍼·카메라·로봇 안정성)** [실측 10/03, 새 서랍 기준]: 손목 카메라 프레임이 `npy×TCP` 계산값과 일치(4 µm, 0.0007°), 로봇 중력 안정(0.5 mm), GUI 확인. 서랍 0~22.6 cm 가동과 한계 정지 확인(새 서랍; 10/03은 재생성 전 값 22.5 cm 기준). **#83 반영 재생성(PR #96, 10/06)**: 인출 22.60 cm·서랍 원점 −3.0 mm·`verify_scene.py` 전부 통과 [실측 10/06]. 임시 트레이(`staging_tray`)는 폐기(#6 확정), 전달 트레이(`handover_zone`)는 `places.yaml` 값으로 고정 물체 추가(PR #96, 외곽 일부 [추정]). 근거: [`sim/README.md`](../sim/README.md) |
| T2 미러링 | `/dsr01/joint_states` → 트윈 조인트 위치 구동 (에뮬레이터·실물 공통) | Day 4 | **에뮬레이터 미러링 구현([FR-TWN-01](requirements.md#fr-twn-01)), 실물 미러링 확인(관절 6축)** — 실물: [실측 PC1 10/11, local DDS] 실물 드라이버 `/dsr01/joint_states`(compose `ros2-core` real, 도메인 70) 100 Hz 를 `mirror_joint_states.py`(구독만)로 받아 트윈이 jog 이동을 따라감, 사용자 화면 확인·영상 3개(10/11, A PC1 보관) — [practice 10/11 6절](../practice/A/2026-10-11_practice.md). **실물 미확인**: PC1(Isaac)↔PC2(로봇) multi DDS 경로(10/03 와이파이 수신 86~96 Hz 만 측정, [docker.md](docker.md)), 실물 지연·추종 오차 수치, 그리퍼 `/gripper/state`·서랍 `/drawers/state` 연동(미연결). 에뮬레이터 [실측 10/03]: 입력은 `joint_1`~`joint_6`·라디안·약 100 Hz, 시험 토픽 50 Hz에서 지연 2.2 ms·추종 오차 0.24°, 사용자가 GUI에서 팔 추종 확인. 그리퍼는 이 토픽에 없어 열림(0°)으로 고정(안 붙잡으면 팔 이동 중 손가락이 닫힘 [실측 10/03]); 실물 그리퍼 폭 연동은 후속. 근거: [`sim/README.md`](../sim/README.md) |
| T3 사전 검증 | 손목 카메라 oracle, 시뮬 그리퍼(attach 폴백), `BACKEND=sim`으로 7.3 예시 실행 | Day 6~7 | **카메라 oracle·`BACKEND=sim`은 미착수, 궤적 검사는 선행 구현**(아래 T3 선행) |
| T3 선행: 스킬 흐름 궤적·특이점 검사 | `sim/motion_check/`(기구학 `m0609_kin.py`, 스킬 서버 흐름 `trace_skill_flow.py`, 시연 스크립트 흐름 `trace_b_demo.py`) + 재생 `sim/scripts/play_motion_trace.py` ([#92](https://github.com/Jik-Kim/ready2go/pull/92)) | 10/06 | **구현** [계산 10/06]: main(#83 머지 뒤) 스킬 서버 흐름·`b_demo.py` 모두 ◀ 없음. 사용법·결과: [`sim/README.md`](../sim/README.md) |
| T3 선행: Unpacking 사전 검증 (B unpack·clear 재생·물리 재생) | `sim/motion_check/trace_unpack.py` + 재생 `sim/scripts/play_unpack_trace.py`·`play_unpack_physics.py` + 물품 외형 `sim/scripts/build_object_meshes.py` | 10/13 | **선행 도구 구현** [트윈 10/13] — FR-TWN-02 완료 아님: 위 칸 S1·아래 칸 지우개 끝까지 재생, 트윈에서 찾은 B 복구 높이·free 기울임 구역 문제 B 전달. 사용법·결과·한계: [`sim/README.md`](../sim/README.md) |

* **T3 선행 도구(`sim/motion_check`)의 위치와 한계**:
  * [FR-TWN-02](requirements.md#fr-twn-02)(트윈 사전 검증)의 선행 도구다. 선행 작업 병행 기준은 [Phase 범위](requirements.md#phase-scope)를 따르며, FR-TWN-02 완료로 세지 않는다.
  * 기하만 본다. B 코드의 이동 명령을 가짜 로봇으로 받아 URDF 기구학으로 관절 경로를 계산한다. 두산 제어기의 실제 보간·특이점 처리·`movesj` 곡선과 다를 수 있다 `[추정]`. 힘 감시는 누르기 접촉만 흉내 내며 충돌 검사는 하지 않는다.
  * 검증 경계는 [NFR-TWN-01](requirements.md#nfr-twn-01). ◀가 없어도 실물 시험은 그대로 한다.
  * 특이점 판정 ◀은 직선 이동(`movel`)에만 적용하며, 기준값과 실물 대조 근거(실물 영상·사용자 확인 10/06)는 [`sim/README.md`](../sim/README.md) 한 곳에 둔다(숫자를 이 문서에 다시 적지 않음).
* **중단 기준**: Day 5 1차 점검까지 T2가 안 되면 사전 검증(T3)은 포기하고 시각화만 유지, A는 비전에 집중. **트윈이 없어도 실물 경로는 영향 없음.**
* **폴백**: 에뮬레이터 미러링이 불안정하면 사전 검증에 한해 기존 Lula IK / RMPflow 컨트롤러 사용(실물과 제어 경로가 다르다는 점은 문서에 명시).
* **USD 관리**: USD는 Git 병합이 불가능하므로 **A만 편집**(단일 편집자). 백업은 Git LFS로 매일 push. PC2는 받기만 함(편집 금지).
* **PC2 활용 (RTX 4060)**: PC2에도 Isaac Sim 5.1.0을 설치해 두면 B가 실물 로봇을 기다리는 동안 직접 사전 검증을 돌릴 수 있고, PC1 고장 시 트윈 예비 장비가 됨. 설치·자산 복사는 여유 시(Day 3~4) A가 지원하며 핵심 경로가 아님. 두 PC 모두 VRAM 8GB급이므로 시연 중 PC2에서는 Isaac Sim을 띄우지 않음(실물 제어·비전 전용).
