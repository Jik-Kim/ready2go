# 🤖 프로젝트 기획서: 온톨로지 기반 지능형 서랍 탐색 및 Skill-based 로봇 제어 프레임워크

> **부제**: **실물 Doosan M0609 + OnRobot RG2 + 실물 서랍장**에서 **음성 명령**으로 구동되는, 로봇 동작의 JSON 규격화·조합을 통한 오클루전(Occlusion) 극복 물품 탐색 및 동적 행동 실행 시스템 — Isaac Sim 디지털 트윈으로 사전 검증, 전 소프트웨어 **Docker 컨테이너화**

> **문서 버전: v4.1 (2026-10-02)**
>
> **변경 이력 (최신순)**
> - **v4.1**: 선행 사례 조사(`reports/로봇 온톨로지 서랍 탐색 선행 사례.md`) 권고 15건 반영 — 조건 레코드 형식·`hold`·`verify`(7.5), 사후 관측 기반 성공 판정(7.4), Runner에 `timeout`·`fallback`·`recovery`·`on_halt` 추가와 BT 대응표(7.1), MongoDB 8.0 확정·JSONL 폴백, 장애물 제거 순서·LIFO 복구·서랍 닫힘 판정 보완(8장), 얇은 물품 제외(2.3), LLM 출력 고정 키 배열·예시 필수(6.4), 트윈 검증 범위·지표 조정(10, 14장), Doosan Real 모드 판정, 실물 안전 게이트 8단계(11장), 선행 사례 대비 차별점(1.3), SAM2 선택 활용(9장). 지식 그래프 초안 그림 추가(7.9). 외부 검토 반영: ICD 호출 방식 명시(5장), 스킬 파라미터명 통일(7.5), 서랍 닫힘 실패 복구(8.4), 한국어 조사 처리(7.1), 시연 표 보완(17.3).
> - **v4**: 강사 챌린지에 맞춰 "로봇 온톨로지(동작·상태·세계)" 중심으로 재편 — 스킬의 조건·결과 정의(7.5), 명령 → 스킬 조합 플래너(7.7), 상태 추적(7.8), 로그에 전후 상태 기록 + DB 저장(7.4, 4장), 시연 2막을 "명령 조합"으로 교체(17.4).
> - **v3.2**: 최종 시연 시나리오(팀 공동 목표) 추가(17장) — 시연 레벨 L1~L3, 태스크 레지스트리(7.6), 일정·지표를 시나리오 기준으로 정렬.
> - **v3.1**: 담당자 실명 반영(A 김병직, B 서동권, C 이영훈, D 김민준, E 고희태), 통합은 조장(E) 지휘 하에 모듈 담당이 공동 수행, LLM 인텐트 파싱을 주 경로로 승격(6.4), LLM 태스크 생성 Stretch 조건 명시(6.5), 온톨로지는 E 담당.
> - **v3**: 최종 시연 플랫폼을 실물 M0609 + 실물 서랍장으로 전환(Isaac Sim은 디지털 트윈·사전 검증용 보조 도구로 재정의, 네이티브 실행), 팀 5인 체제 R&R 재편, 실물 작업 공간·서랍장 구매 기준 추가, 비전을 실물 RealSense 중심으로 재편, 일정·지표·리스크 재작성.
> - **v2**: 로봇 기종 확정(M0609 + RG2), 다중 노트북 구성·compose 프로파일, 원자 동작 백엔드 추상화, ICD, 스키마 정합성 수정(조건식·변수 문법·`finally`), 안전 요구사항.
> - **v1**: 초안 (Docker·음성 필수 요건, JSON 스키마, 14일 일정).

---

## 0. 팀 구성 및 역할 (R&R)

| 코드 | 담당 | 범위 | 주요 산출물 | 핵심 경로 |
| :--- | :--- | :--- | :--- | :--- |
| **A** | 김병직 | **비전(주) + Isaac Sim 디지털 트윈(보조)** | 손목 RealSense 파이프라인, 핸드-아이 캘리브레이션, 실물 데이터셋·YOLO 학습, `inspect_region`(3D 위치·가림 순서·ID 추적) / 트윈 씬·미러링·사전 검증 모드 | 비전: O / 트윈: X |
| **B** | 서동권 | **실물 로봇 모션 원자 동작** | DSR 드라이버 컨테이너, 기준 포즈 직접교시, `move_to_named_pose`·`drawer_control`·`pick_object`·`place_object`, RG2 제어, 실물 안전 설정, 모션 스킬의 조건·결과·에러 정의 검토 | O |
| **C** | 이영훈 | **프레임워크 · 기술 통합** | JSON 스키마, `ActionDispatcher`(Runner), `ExecutionLogger`, 플래너, Skill 액션 인터페이스(`query_ontology`·`update_ontology` 래핑 포함), mock 백엔드, compose 구성, **상태 추적(조건 확인·결과 반영)**, **플래너(명령 → 스킬 조합)**, **로그·상태 DB**. Runner를 중심으로 각 모듈 인터페이스 연결 | O |
| **E** | 고희태 (조장) | **통합 지휘 · 작업 공간 하드웨어 → 음성 · LLM · 온톨로지** | 통합 방향·우선순위 결정, 체크포인트 판정, 결정 로그 승인, 강사 소통, 최종 제출 / (Day 0~2) 서랍장·트레이·물품 구매, 조립·고정·손잡이 보강 / (Day 3~) `voice` 컨테이너(웨이크워드·STT·TTS), **LLM 인텐트 파서**, **로봇 온톨로지**(스킬·상태·세계 정의, `OntologyManager`) | Day 0~2: O |
| **D** | 김민준 (지원) | **기록 · 문서 · 평가 자료** | 음성 평가 문장 세트·녹음, 실험 기록 양식·측정 기록, 회의록·결정 로그 관리, README·발표자료 초안, 시연 촬영 | X |

**운영 원칙**
* **실물이 핵심 경로**, Isaac Sim은 보조 경로. A의 시간 배분은 **비전 우선**(Isaac Sim 작업은 전체의 30% 이내, 10장의 중단 기준 적용).
* **통합 방식 (E 지휘 + 공동 수행)**: 통합 작업은 한 사람에게 몰지 않고 **각 모듈 담당이 자기 모듈의 연결까지 책임**짐(A: 비전↔Runner, B: 모션↔Runner, E: 음성·온톨로지↔Runner). C는 Runner 쪽 인터페이스와 통합 테스트 환경(mock·compose)을 제공. E는 통합 순서·우선순위를 정하고, 체크포인트(Day 5·10·11)를 판정하며, 일정 지연 시 우선순위(15장) 적용을 결정함.
* **E의 부하 관리**: 통합 실무는 모듈 담당이 나눠 맡고 E는 지휘만 함. 온톨로지와 LLM 파서는 같은 어휘(물품 키·별칭·클래스)를 쓰므로 한 사람이 맡아 중복을 없애고, 온톨로지 조회 인터페이스(액션 래핑)는 C가 Runner 쪽에서 구현. 서랍장 조립·고정은 B와 함께, 로봇 시간표는 B가 작성, 회의록·측정 기록은 D가 작성.
* **지원 업무 원칙**: 지원 업무는 핵심 경로에 두지 않고, 다른 작업의 선행 조건이 되지 않도록 배치하며, 마감 2일 전 중간 점검을 둠. 최종본 정리는 해당 영역 담당(C·E)이 맡음.
* **실물 로봇 사용 시간표**를 운영함(작성: B, 승인: E): 기본은 B 우선, A의 데이터 수집·캘리브레이션 슬롯과 전원 통합 슬롯(Day 5·8·9·10·11 오후)을 사전 예약.
* 매일 저녁 15분 스탠드업(진행: E) + main 브랜치 통합. 결정 사항은 16장 결정 로그에 기록(작성: D, 승인: E).

---

## 1. 프로젝트 개요

### 1.1 배경 및 목적
* 서랍장 내부는 물품들이 겹쳐 있거나(Occlusion) 가려져 있어 단순 1회 비전 스캔만으로는 탐색에 한계가 존재함.
* 사용자의 **음성 명령**(예: "출근 준비물 찾아줘")과 번들(리스트) 단위 요청을 이해하고, 지식 베이스(온톨로지)를 기반으로 **실물 서랍장** 내부를 능동적으로 탐색/배출하여 원하는 물건을 찾아주고, 결과를 **음성으로 피드백**하는 시스템을 구축함.
* **[강사 챌린지]** "로봇의 움직임, 상태 등을 JSON(온톨로지)으로 다 만들고, 명령을 내리면 그 조합으로 다양한 행동을 할 수 있도록 한다. 로봇의 세부 동작 및 성공 여부까지 로그로 남긴다." → **로봇 온톨로지**(동작·상태·세계, 7.5)에 스킬마다 조건·결과를 정의하고, **플래너가 명령의 목표를 만족하는 스킬 조합을 자동 생성**(7.7)하며, 모든 스텝의 성공 여부와 전후 상태를 로그·DB에 기록함(7.4).
* **[프레임워크]** 로봇 동작을 특정 시나리오에 하드코딩하지 않고, **로봇의 모든 움직임을 최소 단위 동작(Primitive Actions)으로 JSON 규격화**함. 이를 **변수·조건·반복·정리 제어 블록과 함께 조합(Action Composition)**하여 사전 입력되지 않은 새로운 시나리오까지 코드 수정 없이 수행하고, 전 과정을 JSON으로 기록·추적함.
* 원자 동작은 **백엔드 인터페이스(real / sim / mock)** 뒤에 둠. 같은 JSON과 같은 DSR 제어 코드가 실물 M0609, DSR 에뮬레이터 + Isaac Sim, GPU 없는 mock에서 동일하게 실행됨.
* **Isaac Sim 디지털 트윈(팀 선택 도구)**: ① 새 JSON 시나리오를 실물 투입 전에 사전 검증하여 **실물 로봇 사용 시간을 절약**하고 위험 동작을 걸러냄, ② 로봇 담당(실물)과 A(시뮬레이터)가 **동시에 테스트**하여 일정 단축, ③ 실물 실행 중 로봇 상태를 실시간 미러링하여 시연에서 실물·트윈을 나란히 보여줌.
* **[필수 요건]** ① 팀이 작성한 모든 소프트웨어는 **Docker 컨테이너**로 패키징하여 장비별 `docker compose --profile <역할> up` 한 번으로 재현 가능해야 함(Isaac Sim은 팀 선택 외부 도구로 네이티브 실행, 4.1). ② **음성 인식(STT)은 필수 입력 인터페이스**이며, 텍스트 입력은 디버깅용 보조 수단으로만 둠.

### 1.2 핵심 기능 및 차별점 요약
1. **음성 + LLM 기반 물품 탐색 (필수)**: 웨이크워드 → STT → **LLM 인텐트 파싱**(강의 LangChain 방식, 규칙 폴백) → 단일 물품 / 리스트 / 클래스(예: "귀중품") 단위 탐색, 진행·결과 TTS 응답
2. **로봇 온톨로지 + 행동 조합**: 동작(스킬의 조건·결과)·상태·세계를 JSON-LD로 정의, **플래너가 명령 목표에서 스킬 조합을 자동 생성**, 탐색형 작업은 제어 블록(`$ref`·`if`·`while`·`for_each`·`finally`) JSON으로 표현
3. **실행 이력 자동 기록**: 모든 스텝의 타임스탬프, 성공 여부, 재시도, 에러 코드, **조건 확인 결과와 전후 상태**를 JSON으로 DB에 저장
4. **오클루전 극복 전수 탐색(Unpacking)**: 목표 미발견 시 위에 있는 물품부터 트레이로 순차 배출하며 탐색
5. **스마트 복구 (Rollback)**: 서랍 로컬 좌표 스택(LIFO) 기반 원위치 복구, **실패 시에도 `finally`로 복구 보장**
6. **상태 자동 수정 (Self-Correction)**: 관측이 온톨로지 상태와 다르면 관측값으로 고치고 기록(`STATE_MISMATCH`)
7. **Isaac Sim 디지털 트윈**: 실측 치수 기반 트윈 씬, 실물 상태 미러링, JSON 사전 검증
8. **백엔드 추상화**: real / sim / mock 교체만으로 동일 JSON 실행
9. **컨테이너 기반 재현성**: 서비스 단위 Docker Compose + 장비별 프로파일

> **팀 공동 목표는 17장의 최종 시연 시나리오 "출근 준비 도우미"**이며, 모든 작업의 우선순위는 이 시나리오 기준으로 정함.

### 1.3 선행 사례와 차별점 (상세: `reports/로봇 온톨로지 서랍 탐색 선행 사례.md`)

| 선행 사례 | 내용 | 우리와의 차이 |
| :--- | :--- | :--- |
| [mi1nn/voice-controlled-kit-assembly](https://github.com/mi1nn/voice-controlled-kit-assembly) | M0609 + RG2 + Jazzy + "hello rokey" + Whisper + GPT-4o(LangChain), 거의 같은 스택 | LLM은 물품·수량만 추출, **작업 순서는 손으로 짠 상태 머신** |
| [seb000423/Seek6D](https://github.com/seb000423/Seek6D) | M0609로 서랍·상자를 열어 물건 탐색 | 탐색 절차가 고정, 가려진 물체 치우기·원위치 복구 없음 |
| [NASA JPL ROSA](https://github.com/nasa-jpl/rosa), [Auromix ROS-LLM](https://github.com/Auromix/ROS-LLM) | LLM이 ROS 도구를 직접 호출 | 심볼릭 플래너·실행 전 검증 없음 |
| [SkiROS2](https://arxiv.org/abs/2306.17030) (IROS 2023) | 스킬의 사전·유지·사후 조건 + 온톨로지 + PDDL 자동 생성 | 구조는 가장 유사하나 ROS 2 Jazzy 지원 미확인 → 설계만 참고 |
| [LLM+P](https://arxiv.org/abs/2304.11477) (2023) | LLM은 목표만 번역, 고전 플래너가 계획 | 같은 원리를 실물 협동로봇·음성·한국어에 적용 |
| [Mechanical Search](https://arxiv.org/abs/1903.01588) (ICRA 2019) | 쌓인 물체를 치우며 목표 탐색, 실물 90~98% 성공 | 서랍 안에서 탐색 + **LIFO 원위치 복구**까지 수행 |

> **우리 차별점 두 가지**: ① 동작 순서를 하드코딩하지 않고 **로봇 온톨로지의 조건·결과에서 도출**, ② 모든 스텝의 **조건 확인·사후 관측·전후 상태를 DB에 기록**. "음성으로 서랍에서 물건 찾기" 자체는 선행 프로젝트가 있으므로 차별점으로 내세우지 않음.

---

## 2. 실물 작업 공간 · 하드웨어 구성

### 2.1 작업 공간 배치
```
          [실물 서랍장 (작업대에 고정)]
               ▲ 인출 방향
   [스테이징 트레이]   [M0609 + RG2 + 손목 RealSense]   [전달 트레이(handover_zone)]
                                                       ▲ 사용자 위치
```
* 서랍장·트레이 2개(장애물 임시 배출용 `staging_tray`, 사용자 전달용 `handover_zone`)는 모두 **M0609 작업 반경(900mm) 안**, 작업대에 고정.
* 사람에게 직접 건네지 않고 **전달 트레이에 내려놓음**(11장 안전).

### 2.2 실물 서랍장 구매 · 설치 기준 (담당 E, Day 0~2)
가벼운 플라스틱 서랍장을 사용하므로 아래 기준으로 구매·보강함.

| 항목 | 기준 | 이유 |
| :--- | :--- | :--- |
| 재질·색 | **불투명·무광**, 내부는 밝은 단색 | 반투명·광택 플라스틱은 RealSense 뎁스가 투과·반사로 깨짐. 물품과 배경 대비 확보 |
| 단 수·크기 | 2~3단, 작업 반경 안에 들어오는 크기 | 사용 서랍은 2개(`drawer_top`, `drawer_bottom`) |
| 인출 | 스토퍼 있음(완전히 빠지지 않음), 깊이의 절반 이상 인출 가능 | 아래 서랍은 윗 서랍에 가려 **인출된 부분만** 위에서 보이고 집을 수 있음 |
| 손잡이 | **돌출형 손잡이**, 없으면 막대형 손잡이를 부착 | 홈형 손잡이는 RG2로 파지 불가. 손잡이 뒤 손가락 들어갈 공간 확보 |
| 고정 | 클램프·양면테이프·볼트로 **작업대에 고정**, 필요 시 무게 추가 | 가벼운 서랍장은 당길 때 함께 끌려오거나 넘어짐. 위치가 바뀌면 교시 포즈가 무효 |
| 레일 | 걸림 없이 부드럽게 움직이는지 구매 전 확인 | 플라스틱 레일은 비스듬히 당기면 걸림 → 인출 축 방향 정렬 + 컴플라이언스 제어(8.4) |

* 설치 후 서랍장 위치를 바꾸지 않음. 위치를 바꾸면 기준 포즈 재교시 + 서랍 좌표계 재측정 + 트윈 씬 수정이 필요함.
* **서랍 좌표계 등록**: TCP로 서랍 모서리 3점을 터치하여 로봇 베이스 기준 서랍 좌표계(`drawer_<id>`)를 측정하고, 실측 치수는 A에게 전달하여 트윈 씬에 반영.

### 2.3 물품 선정 기준 (Day 2 실물 파지 테스트로 확정)
* RG2 개폐 폭(최대 약 110mm) 안, **높이 1.5cm 이상**(바닥에 납작한 물체는 파지 곤란), 무게 부담 없음.
* **얇은 물품은 쓰지 않음 (확정)**: 손끝 인서트 등 그리퍼 개조는 하지 않고, **물품 선정 단계에서 높이 1.5cm 미만 물품을 제외**함. 파지 높이 기준은 물체별 뎁스(오차 수 mm)가 아니라 **서랍 바닥 평면**으로 잡고, 파지 성공은 RG2 폭 피드백으로 확인.
* 무광·밝은 색 위주(검정·투명·거울면은 뎁스 품질 저하), 날카로운 물품은 제외하거나 보호 처리.
* 후보: 시계(케이스째), 지갑, 차키(**두꺼운 키홀더·키 케이스를 달아 그 부분을 파지**), 펜 케이스, 자는 케이스에 넣거나 제외, 작은 박스류 + 장애물용 임의 물체(높이 1.5cm 이상). **각 물품을 실물 RG2로 집어 보고 목록 확정**.

### 2.4 장비 · 노트북 구성

| 장비 | 위치·역할 | 실행 서비스 (compose profile) | 비고 |
| :--- | :--- | :--- | :--- |
| **PC2** (서동권, RTX 4060) | 로봇 옆 · 실물 제어 | `ros2-core`(BACKEND=real), `vision`, `realsense`, `voice` (`real`) | 로봇 제어기·그리퍼와 유선 연결, 손목 RealSense USB 연결. **비전 추론은 PC2 GPU 사용**. Isaac Sim 실행도 가능하므로 B가 실물 대기 중 직접 사전 검증하거나 PC1 고장 시 트윈 예비 장비로 사용(시연 중에는 실물 제어 전용) |
| **PC1** (김병직, RTX 5060 8GB) | 트윈 · 사전 검증 · 학습 | Isaac Sim 5.1.0(네이티브) + `ros2-core`(BACKEND=sim), `dsr-emulator`, `vision` (`sim`) | YOLO 학습, 시연 중에는 실물 미러링 트윈 화면 |
| 팀원 노트북 | 개발 | `ros2-core`(BACKEND=mock), `mock-sim`, `voice` (`dev`) | GPU 불필요 |
| 네트워크 | 팀 전용 공유기 | - | 로봇 제어기 네트워크와 분리. PC1↔PC2 DDS 통신은 공유기 쪽 인터페이스로 고정 |

* 실행 로그 타임스탬프는 **Runner 한 곳에서만** 기록하여 PC 간 시계 오차 문제를 피함.
* 마이크는 시연 위치에 두고 PC2에 연결(또는 USB 마이크).

---

## 3. 시스템 아키텍처

```
[사용자 음성] ─▶ voice: 웨이크워드 → STT → 인텐트 파서 ──┐            ◀── TTS(speak)
                                                         ▼ intent
┌──────────────────────────── ros2-core ──────────────────────────────────────┐
│ 로봇 온톨로지(스킬·상태·세계) → 플래너(목표 → 스킬 조합) → Runner(조건 확인·  │
│ 실행·상태 갱신) → 실행 로거 → DB(로그·상태)                                   │
│                                     │ 원자 동작 (ROS 2 Action / Service)      │
│                  [Backend: real | sim | mock]                                 │
└──────────────┬──────────────────────────┬───────────────────┬───────────────┘
               ▼                          ▼                   ▼
     모션 (B): DSR 드라이버          인식 (A): vision        그리퍼
       real → 실물 M0609 제어기        real → RealSense       real → RG2
       sim  → dsr-emulator             sim  → Isaac 카메라     sim  → Isaac 그리퍼
               │ /dsr01/joint_states (real·sim 공통)
               ▼
   Isaac Sim 디지털 트윈 (PC1, 네이티브): 사전 검증 모드 / 실물 미러링 모드
```

### 3.1 백엔드별 구성

| 구성 요소 | `real` (최종 시연) | `sim` (사전 검증) | `mock` (개발) |
| :--- | :--- | :--- | :--- |
| 로봇 모션 | DSR 드라이버 → **실물 M0609** | 같은 DSR 드라이버 → `dsr-emulator`, Isaac Sim이 조인트 미러링 | 즉시 성공 반환 |
| 그리퍼 | RG2 (강의 `onrobot.py` 방식) | Isaac Sim `ParallelGripper` (+ attach 폴백) | 즉시 성공 반환 |
| 인식 | 손목 RealSense + YOLO + 뎁스 | Isaac Sim 손목 카메라 + oracle(정답) 또는 YOLO | 미리 정의한 결과 재생 |
| 서랍 | 실물 서랍장 | Isaac Sim Prismatic Joint | 상태 변수 |

* **핵심 설계**: 모션은 real·sim 모두 **같은 DSR 드라이버·같은 스킬 코드**를 사용하고 접속 대상(실물 제어기 / 에뮬레이터)만 바뀜. 사전 검증에서 통과한 JSON은 실물에서도 같은 경로로 실행됨.
* 그리퍼·카메라처럼 에뮬레이터에 없는 부분만 백엔드별로 구현함.

---

## 4. Docker / 컨테이너 구성 (필수)

### 4.1 서비스 구성

| 서비스 | 베이스 이미지 | 프로파일 | 역할 |
| :--- | :--- | :--- | :--- |
| `ros2-core` | `ros:jazzy` 기반 커스텀 | `real`, `sim`, `dev` | Runner(상태 추적), Logger, 로봇 온톨로지, 플래너, 모션 스킬, DSR 드라이버, 그리퍼 제어 |
| `db` | `mongo:8.0` (버전 고정, 지원 2029-10까지) | `real`, `sim`, `dev` | 실행 로그·스텝 기록·상태 스냅샷 저장(JSON 문서 그대로 저장). 과목 목표 "DataBase 활용" 대응 |
| `vision` | `ros:jazzy` + ultralytics (+CUDA 선택) | `real`, `sim` | 검출, 3D 위치, 가림 순서, 인스턴스 ID 추적 |
| `realsense` | `ros:jazzy` + realsense2_camera | `real` | 손목 RealSense RGB-D 발행 (표준 토픽명으로 remap) |
| `voice` | `ros:jazzy` + 음성 스택 | `real`, `sim`, `dev` | 웨이크워드 → STT → 인텐트, TTS |
| `dsr-emulator` | `doosanrobot/dsr_emulator:3.0.1` | `sim`, `dev` | M0609 가상 제어기 |
| `mock-sim` | `ros:jazzy` + Python | `dev` | 가짜 조인트·서랍·카메라 토픽, 미리 정의한 검출 결과 |

* **Isaac Sim은 컨테이너에 넣지 않음**: 과목 필수 요소가 아닌 팀 선택 도구로, 실물 로봇·카메라처럼 외부 환경으로 취급함. PC1의 네이티브 설치본(`~/isaac-sim-5.1.0`)을 호스트 ROS 2 Jazzy + CycloneDDS를 source한 뒤 실행함. **팀 로직은 Isaac Sim 안에 두지 않고**(씬 로드·ROS 2 Bridge·조인트 미러링만), 전부 컨테이너의 ROS 노드에 둠.
* 기존 `ros:jazzy-ros-base-noble` 기반 `yolo-detection` 컨테이너를 `vision`의 시작점으로 재사용함.
* ROS 2 배포판은 **Jazzy(Ubuntu 24.04)로 확정**.

### 4.2 `docker-compose.yml` 골격

```yaml
x-ros-env: &ros-env
  ROS_DOMAIN_ID: "70"                                  # 강사 배정 조별 Domain ID (확정)
  RMW_IMPLEMENTATION: rmw_cyclonedds_cpp               # 강사 제공 표준 (확정)
  CYCLONEDDS_URI: file:///config/cyclonedds.${DDS_MODE:-local}.xml   # local | multi
  DDS_IFACE: ${DDS_IFACE}        # multi 모드: 팀 공유기에 연결된 NIC 이름
  PEER_PC1: ${PEER_PC1}          # multi 모드: 장비 IP
  PEER_PC2: ${PEER_PC2}

services:
  ros2-core:
    profiles: ["real", "sim", "dev"]
    build: ./docker/ros2-core
    network_mode: host
    environment: { <<: *ros-env, BACKEND: "${BACKEND:-mock}", ROBOT_HOST: "${ROBOT_HOST:-127.0.0.1}" }  # real: 실물 제어기 IP
    volumes:
      - ./ros2_ws:/ros2_ws
      - ./schema:/schema:ro
      - ./tasks:/tasks:ro            # JSON 태스크 템플릿
      - ./knowledge:/knowledge       # 온톨로지 (런타임 갱신)
      - ./logs:/logs                 # 실행 로그 JSON
      - ./config:/config:ro          # 기준 포즈, 서랍 좌표계, 캘리브레이션 결과

  vision:
    profiles: ["real", "sim"]
    build: ./docker/vision
    network_mode: host
    environment: { <<: *ros-env, VISION_MODE: "${VISION_MODE:-yolo}" }   # yolo | yolo_sam2(조건부) | oracle(sim 전용)
    volumes: [./models:/models:ro, ./config:/config:ro]

  realsense:
    profiles: ["real"]
    build: ./docker/realsense
    network_mode: host
    privileged: true                 # USB 재연결 시 장치 번호가 바뀌므로 /dev 전체 공유
    environment: *ros-env
    volumes: ["/dev:/dev"]

  voice:
    profiles: ["real", "sim", "dev"]
    build: ./docker/voice
    network_mode: host
    env_file: [./secrets/voice.env]  # OPENAI_API_KEY (Git 제외)
    environment: { <<: *ros-env, PULSE_SERVER: "unix:${XDG_RUNTIME_DIR}/pulse/native" }
    volumes:
      - ${XDG_RUNTIME_DIR}/pulse/native:${XDG_RUNTIME_DIR}/pulse/native
      - ./knowledge:/knowledge:ro
      - ./models:/models:ro
      - ./config:/config:ro

  db:
    profiles: ["real", "sim", "dev"]
    image: mongo:8.0
    network_mode: host
    volumes: ["./db_data:/data/db"]    # 로그·상태 영속 저장

  dsr-emulator:
    profiles: ["sim", "dev"]
    image: doosanrobot/dsr_emulator:3.0.1
    network_mode: host

  mock-sim:
    profiles: ["dev"]
    build: ./docker/mock-sim
    network_mode: host
    environment: *ros-env
```

**CycloneDDS 설정 (강사 제공본 기반)**
* `config/cyclonedds.local.xml`: 강사 제공 `cyclonedds.xml` **원본 그대로** (`lo` 전용). 단일 PC 개발에 사용.
* `config/cyclonedds.multi.xml`: 강사 제공본에서 **인터페이스와 탐색 방식만 변경**한 다중 PC용. 버퍼 설정은 원본과 동일.

```xml
<!-- config/cyclonedds.multi.xml -->
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <General>
      <Interfaces><NetworkInterface name="${DDS_IFACE}" priority="default"/></Interfaces>  <!-- 원본: lo -->
      <AllowMulticast>false</AllowMulticast>                                                <!-- 원본: true -->
    </General>
    <Discovery>
      <ParticipantIndex>auto</ParticipantIndex>
      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
      <Peers>
        <Peer address="${PEER_PC1}"/>
        <Peer address="${PEER_PC2}"/>
      </Peers>
    </Discovery>
    <Internal>
      <SocketReceiveBufferSize min="64MB"/>
      <SocketSendBufferSize min="64MB"/>
    </Internal>
  </Domain>
</CycloneDDS>
```

**실행 절차 (장비별 명령 1개)**
* PC2 (실물): `docker compose --profile real up` (`.env`: `BACKEND=real`, `ROBOT_HOST=<제어기 IP>`, `DDS_MODE=multi`)
* PC1 (사전 검증): Isaac Sim 네이티브 실행 후 `docker compose --profile sim up` (`.env`: `BACKEND=sim`, `VISION_MODE=oracle`)
* PC1 (실물 미러링 트윈): Isaac Sim 네이티브만 실행 (`DDS_MODE=multi`로 PC2의 `/dsr01/joint_states` 수신)
* 개발: `docker compose --profile dev up`
* 장비별 값은 각 PC의 `.env`에 고정하여 실제 실행은 명령 1개로 유지.

### 4.3 운영 규칙 및 알려진 함정 (이미 겪은 이슈 포함)
* **RMW (확정)**: 강사 제공 **CycloneDDS**(`rmw_cyclonedds_cpp`)를 모든 컨테이너, 호스트, 네이티브 Isaac Sim에서 사용함. 호스트 `.bashrc`의 `RMW_IMPLEMENTATION`/`CYCLONEDDS_URI`/`ROS_DOMAIN_ID=70`도 컨테이너와 같은 값으로 맞춤(10/02 전 팀원 확인 완료).
* **커널 버퍼 설정**: 강사 스크립트(`a08_cyclone.sh`)의 sysctl 버퍼 설정을 **모든 PC 호스트에 적용**함. `network_mode: host` 컨테이너는 호스트 네트워크 설정을 그대로 따름.
* **다중 PC 통신**: 강사 제공 원본은 `lo` 전용이라 PC 간 통신이 되지 않으므로 다중 PC는 `multi` 설정을 사용하고, 방화벽(ufw)에서 DDS UDP 포트를 허용함. PC2는 로봇 제어기용 유선 + 팀 공유기 2개 네트워크에 연결되므로 `DDS_IFACE`를 **팀 공유기 쪽**으로 지정.
* **GUI 표시**: GUI 컨테이너(RViz 등)는 호스트에서 `xhost +local:root`, `DISPLAY`와 `/tmp/.X11-unix` 전달. **`DISPLAY` 값은 세션마다 다를 수 있음**(현재 PC1은 Xwayland `:1`).
* **오디오**: Ubuntu 24.04는 PipeWire가 ALSA 장치를 점유하므로 `/dev/snd` 직접 패스스루 대신 **PulseAudio 소켓을 마운트**함.
* **카메라 장치 독점**: `realsense2_camera`와 `cv2.VideoCapture`가 같은 장치를 동시에 열 수 없음. 항상 **ROS 토픽 구독 방식으로 통일**하고 `/dev/videoN` 번호는 하드코딩하지 않음.
* **RealSense 하드웨어 점검**: `Left MIPI error`는 USB 3.0 포트 직결 + 정품 케이블 + 재연결로 먼저 확인(10/02 재연결로 해결된 이력). 로봇 팔 움직임에 케이블이 당기지 않도록 케이블 고정.
* **비밀정보**: OpenAI API 키는 `secrets/*.env`로 분리하고 `.gitignore`에 등록.
* **재현성**: 이미지 태그 `latest` 금지, 버전 고정. 빌드 컨텍스트는 `docker/<서비스>/Dockerfile`로 관리.

---

## 5. 인터페이스 계약 (ICD)

Day 1에 확정하고, 이후 변경은 전원 합의 후 이 표를 먼저 수정함. 커스텀 메시지는 `cobot2_interfaces` 패키지의 **2종(`Skill.action`, `InspectRegion.srv`)으로 제한**하고, 나머지 페이로드는 JSON 문자열로 주고받음.

| 인터페이스 | 이름 | 타입 | 제공 → 사용 |
| :--- | :--- | :--- | :--- |
| 인텐트 | `/voice/intent` | topic `std_msgs/String` (JSON) | voice → ros2-core |
| 로봇 상태 | `/robot_state` | topic `std_msgs/String` (온톨로지 `state` JSON) | ros2-core → 시연 화면·트윈·voice(상태 질의) |
| 생성된 계획 | `/planner/plan` | topic `std_msgs/String` (7.2 형식 JSON) | ros2-core → 시연 화면 |
| 텍스트 디버그 입력 | `/voice/text_override` | topic `std_msgs/String` | 테스트 → voice |
| TTS 요청 (`speak` 원자 동작) | `/voice/speak` | action `Skill` | ros2-core → voice |
| 인식 | `/vision/inspect_region` | service `InspectRegion` (req: `region`, `search_target` / res: `result_json`) | ros2-core → vision |
| 로봇 원자 동작 | `/skills/<action_name>` | action `Skill` (goal: `params_json` / result: `success`, `error_code`, `output_json` / feedback: `stage`) | Runner → 백엔드 |
| 로봇 조인트 상태 | `/dsr01/joint_states` | `sensor_msgs/JointState` | DSR 드라이버(real·sim) → Isaac Sim 트윈 |
| 그리퍼 상태 | `/gripper/state` | JSON 문자열 (`width`, `grasp_detected`) | 백엔드 → Runner·트윈 |
| 그리퍼 명령 (sim 전용) | `/gripper/command` | JSON 문자열 | sim 백엔드 → Isaac Sim |
| 서랍 상태 | `/drawers/state` | JSON 문자열 (`drawer_id`, `displacement`) | 백엔드 → Runner·트윈 |
| 카메라 | `/wrist_cam/color/image_raw`, `/wrist_cam/depth/image_rect_raw`, `/wrist_cam/camera_info` | `sensor_msgs` | realsense(remap) / Isaac Sim → vision |
| Runner 상태 · 비상정지 | `/runner/status`, `/runner/estop` | `std_msgs/String`, `std_srvs/Trigger` | ros2-core ↔ 전체 |
| TF 프레임 | `world`, `base_link`, `link_6`, `wrist_cam_optical`, `drawer_<id>`, `staging_tray`, `handover_zone` | TF2 | ros2-core (캘리브레이션·서랍 좌표계 결과 발행) |

**ROS 인터페이스가 아닌 호출 (같은 프로세스 또는 외부 서비스)**

| 대상 | 호출 방식 | 사용 위치 |
| :--- | :--- | :--- |
| `query_ontology` · `update_ontology` 원자 동작 | **ROS 인터페이스 없음.** `ros2-core` 프로세스 안에서 Runner가 `OntologyManager` 메서드를 직접 호출 | Runner (7.1 ②) |
| 로그·상태 저장 | Python `pymongo`로 MongoDB(`cobot2` DB: `runs`·`steps`·`states`) 직접 연결, `LogStore` 인터페이스 경유. 연결 실패 시 `logs/*.jsonl` 폴백 | Runner·Logger (7.4) |
| STT · LLM | HTTPS로 OpenAI API 호출 (`secrets/voice.env`의 키 사용) | `voice` 컨테이너 (6장) |

---

## 6. 음성 · LLM 인터페이스 (필수, 담당 E)

### 6.1 파이프라인

```
마이크 → 웨이크워드("hello rokey") → 녹음 → STT → 텍스트
      → 인텐트 파서 → {intent, targets[], scenario} → 플래너
      → (진행 상황/결과) TTS 음성 출력
```

| 단계 | 구현 방안 | 비고 |
| :--- | :--- | :--- |
| 음성 입력 | 강의 웨이크워드 모델(`hello_rokey_8332_32.tflite`) 재사용, Push-to-talk(키 입력) 병행 | 오탐 시 Push-to-talk로 전환 |
| STT | 1순위: OpenAI `whisper-1` (강의 코드 재사용, `prompt`에 물품 어휘 주입 — 지원 여부는 현재 API 문서로 확인) / 폴백: `faster-whisper small` (CPU, 오프라인) | 지연 목표 2초 이내 |
| 인텐트 파서 | **주 경로: LLM**(강의 `get_keyword`·LangChain 방식)이 문장을 인텐트·목표 JSON으로 변환(6.4) / **폴백(시연 보험): 규칙 + 온톨로지 별칭(`aliases_ko`) 퍼지 매칭** — API 응답 3~5초 초과·네트워크 오류 시 **자동 전환** | LLM 출력도 같은 별칭 정규화·검증을 거쳐 하나의 검증된 목표로 수렴. 저신뢰·검증 실패 시 재확인 질의 |
| 확인 응답 | "출근 준비물 3개를 찾겠습니다" TTS 후 실행 | 모호하면 재질문 |
| TTS | Piper(오프라인 한국어) 또는 `espeak-ng` | 결과 피드백은 JSON `speak` 원자 동작으로 실행 |

### 6.2 지원 인텐트 (최소 세트)
* `find_item`: "가위 찾아줘"
* `find_list`: "출근 준비물 찾아줘"
* `find_class`: "귀중품 다 찾아줘" → 온톨로지 클래스 계층 추론(`Valuables`의 하위 클래스 포함)
* `achieve_goal` (플래너 조합): "지갑은 아래 서랍에 넣어 둬", "위 서랍 시계를 아래 서랍으로 옮겨줘", "아래 서랍 닫아줘" → 목표 상태로 변환(7.7)
* `query_state`: "지금 뭐 들고 있어?", "위 서랍 열려 있어?" → `/robot_state`로 응답
* 태스크 레지스트리 인텐트: 스킬 파일의 `trigger`로 자동 추가(예: `return_items` "정리해줘", 7.6)
* `cancel` / `status`: "멈춰", "지금 뭐 해?"

### 6.3 비기능 요구사항
* 인식 실패/저신뢰(confidence 임계값 미만) 시 실행하지 않고 TTS로 재요청.
* 텍스트 입력 토픽(`/voice/text_override`)은 **디버깅/자동화 테스트 전용**이며, 시연은 반드시 음성으로 수행.
* 음성 "멈춰"는 **보조 정지 수단**임. 1차 정지는 티치 펜던트 비상정지 버튼과 키보드/서비스 E-stop(11장).
* 평가용 **한국어 명령 40문장 세트**(화자 2명 이상)로 **인텐트 정확도**를 측정(목표 90% 이상). 시연 장소 소음 조건에서도 측정.

### 6.4 LLM 인텐트 파서 (주 경로, 담당 E)

강의 `get_keyword.py`(LangChain + GPT)의 구조를 재사용하되, 출력을 **자유 텍스트가 아닌 검증 가능한 JSON**으로 바꿈.

```
STT 텍스트 + 온톨로지 어휘(물품·리스트·클래스 키, 한국어 이름·별칭)
   → LLM (temperature 0, JSON 출력 강제)
   → 검증: 형식 / intent 허용값 / targets가 온톨로지 키인지
   → 통과: /voice/intent 발행  |  실패·저신뢰: 규칙·별칭 폴백 → 그래도 실패 시 재질문
```

* **출력 형식 (구조화 출력 strict 모드 + 온톨로지에서 생성한 enum)**: `{"intent": "find_item|find_list|find_class|achieve_goal|query_state|<레지스트리 인텐트>|cancel|status|unknown|clarify", "targets": ["<온톨로지 키 enum>"], "goals": [{"predicate": "located_in|open", "subject": "<키 enum>", "value": "<장소·값 enum>"}], "query": {"predicate": "...", "subject": "..."} 또는 null, "clarify_question": "..." 또는 null, "confidence": 0.0~1.0}`
* **고정 키 배열**: 목표는 `{"located_in.wallet": ...}` 같은 동적 키 객체가 아니라 `goals: [{predicate, subject, value}]` 배열로 받음(구조화 출력의 enum 검증이 가능하고 7.5 조건 형식과 동일).
* **탈출값 필수**: enum에 `unknown`·`clarify`가 없으면 모델이 어휘 밖 요청에도 아무 물품이나 고르게 됨. 스키마는 형식만 보장하므로 의미(존재하는 물품인지, 현재 상태와 다른 목표인지)는 코드로 다시 검증.
* **목표만 출력**: `achieve_goal`에서 LLM은 목표 상태만 내고 동작 순서는 만들지 않음. 순서는 플래너가 스킬 조건에서 도출(7.7). LLM+P(2023) 실험에서 같은 GPT-4가 계획을 직접 짜면 0~35%, 목표만 번역하고 플래너에 맡기면 85~95% 성공(선행 사례 보고서 참고).
* **어휘 제한**: 프롬프트에 온톨로지의 키·한국어 이름·별칭 목록과 레지스트리 인텐트를 자동 주입하고, 목록에 없는 물품은 `unknown`으로 답하도록 지시(하드코딩 금지). 공간 표현("위 서랍", "앞 트레이")은 장소 enum 기호로만 받음.
* **예시 필수**: 한국어 발화 → 출력 JSON 예시를 **1~3개** 프롬프트에 넣음(LLM+P에서 예시가 없으면 모든 도메인 0%).
* **모델**: 추론형이 아닌 빠른 모델 사용. 정확성은 플래너·검증 코드가 보장하므로 속도를 우선.
* **장점**: "차 탈 때 쓰는 열쇠", "아침에 들고 나가는 것들"처럼 별칭에 없는 자유 표현도 처리. 규칙 파서만으로는 불가능한 부분이 LLM 활용의 시연 포인트.
* **로그**: STT 텍스트, LLM 원문 응답, 검증 결과, 폴백 사용 여부, 지연 시간을 실행 로그의 `inputs`에 함께 기록.
* **지연 예산**: STT + LLM 합계 2.5초 이내(확인 TTS 시작까지 3초 목표, 14장).

### 6.5 (Stretch) LLM 태스크 JSON 생성

* **착수 조건**: Day 11 3차 챌린지 점검 통과 후, 담당 C·E.
* **흐름**: 템플릿에 없는 자연어 요청 → LLM이 7.1의 원자 동작·제어 블록만으로 태스크 JSON 생성 → **스키마 검증(7.2)** → **기호적 드라이런**(온톨로지 상태 위에서 조건·결과만으로 모의 실행) → **트윈 사전 검증(10장)** → 통과한 경우에만 실물 실행.
* **안전 장치**: 생성 JSON은 스키마 검증과 사전 검증을 통과하지 않으면 실물에 보내지 않음. `while`의 `max_iter`, 작업 영역 제한, E-stop 규칙은 그대로 적용.
* **의미**: 챌린지 과제("코드 수정 없이 미정의 시나리오 수행")를 사람이 아닌 LLM이 JSON을 작성하는 수준까지 확장하고, 디지털 트윈이 그 안전 관문 역할을 함.

---

## 7. 로봇 온톨로지 및 JSON 규격 (강사 챌린지 핵심)

> **강사 챌린지**: "로봇의 움직임, 상태 등을 JSON(온톨로지)으로 다 만들고, 명령을 내리면 그 조합으로 다양한 행동을 할 수 있도록 한다. 로봇의 세부 동작 및 성공 여부까지 로그로 남긴다."

| 챌린지 요소 | 이 장의 구성 |
| :--- | :--- |
| 로봇의 **움직임** | 7.1 원자 동작 규격 + 7.5 스킬 정의(조건·결과·원자 동작 전개) |
| 로봇의 **상태** | 7.5 `state` + 7.8 상태 추적 규칙 |
| 명령 → **조합**으로 다양한 행동 | 7.7 플래너(스킬 자동 조합) + 7.2·7.3 제어 블록 JSON(탐색형 작업) + 7.6 스킬 추가 |
| **세부 동작·성공 여부 로그** | 7.4 실행 로그(성공 여부·조건 확인·상태 변화) + DB 저장 |

### 7.1 원자 동작(Primitive Action) 정의 규격

**동작 이름과 파라미터 명은 본 표를 단일 기준(Single Source of Truth)으로 하고, 코드/일정/예시 전체에서 그대로 사용합니다.**

**① 로봇/인식 동작**

| 동작명 (`action`) | 주요 파라미터 (`params`) | 반환값 (`output`으로 저장 가능) | 설명 |
| :--- | :--- | :--- | :--- |
| `move_to_named_pose` | `pose_name`: `"home"`, `"drawer_approach"`, `"drawer_top_view"`, `"tray_view"` / `drawer_id`(서랍 관련 포즈일 때) | - | 사전 정의된 로봇 관절 포즈로 이동 |
| `drawer_control` | `drawer_id`, `state`: `"open"`/`"close"`, `distance`(선택, 기본 = `max_travel_m`) | `{drawer_displacement, close_confirmed}` | 손잡이 파지 및 슬라이딩 개폐 (real: 컴플라이언스 인출, **닫힘 = 닫힘 위치 도달 AND 미는 축 힘 임계 초과**, 8.4 / sim: 조인트 직접 구동 폴백) |
| `inspect_region` | `region`: 서랍 ID, `"staging_tray"`, `"handover_zone"`, `search_target`(클래스명, 선택) | `{target_found, target, candidates[], visible_count}` | 검출 + 3D 위치 + 가림 순서. `target`은 `{id, class, pose, top_z}` 또는 `null`, `candidates`는 목표를 제외한 물체를 **위에 있는 순서(서랍 좌표계 `top_z` 내림차순)**로 정렬 |
| `pick_object` | `object_id`(인스턴스 ID), `approach_offset`, `grip_force`(선택, 기본 = 온톨로지 값), `source_slot`(선택, 트레이에서 집을 때) | `{object_id, class, pick_pose_drawer_frame, grasp_ok}` | 접근 → 파지 → 안전 높이 상승 |
| `place_object` | `location`: `"staging_tray"`(빈 슬롯 자동 할당) / `"handover_zone"` / 슬롯명, 또는 `pose` + `frame` | `{slot, placed_pose}` | 지정 위치에 거치 후 그리퍼 해제. `frame: "drawer"`일 때는 배치 직전 재촬영으로 높이(z) 보정. **`location`이 서랍(`Drawer` 클래스)이면 백엔드가 `frame: "drawer"`, 현재 인출 거리 반영 서랍 좌표, z 보정을 자동 적용**(서랍의 `return_slot` 또는 지정 `pose` 사용) |

* **ID 규칙**: `object_id`는 비전이 부여한 **인스턴스 ID**(예: `watch#1`, `unknown#3`), `search_target`과 온톨로지 키는 **클래스명**(예: `watch`). 둘을 섞지 않음.
* **포즈 vs 위치**: `pose_name`은 로봇 관절 포즈, `location`은 월드의 물체 거치 장소. 이름 공간을 분리함.

**② 지식/상호작용 동작**

| 동작명 (`action`) | 주요 파라미터 | 반환값 | 설명 |
| :--- | :--- | :--- | :--- |
| `query_ontology` | `item` / `list` / `class` / `state`(상태 경로) 중 하나 | 단일: `{item, name_ko, drawer_id, grip_force}` / 다중: `{items[], groups[{drawer_id, items[]}]}` / 상태: `{path, value}` | 물품 위치, 리스트·클래스 구성, 현재 상태 조회 (다중 결과는 서랍별로 묶어 반환) |
| `update_ontology` | `item`, `drawer_id`, `pose`(선택) | - | 발견된 실제 위치로 지식 베이스 갱신 |
| `speak` | `text` | - | TTS 음성 피드백 |

**③ 제어 블록 (Runner가 해석, 코드에는 시나리오가 들어가지 않음)**

| 블록 | 필드 | 설명 |
| :--- | :--- | :--- |
| `set_var` | `params.name`, `params.value` | 블랙보드 변수 설정 |
| `push` / `pop` | `params.stack`, `params.value` / `params.stack` + `output` | 리스트형 변수를 LIFO 스택으로 사용 (Rollback용) |
| `if` | `cond`, `then[]`, `else[]` | 조건 분기 |
| `while` | `cond`, `body[]`, `max_iter`(필수) | 조건 반복. 초과 시 `LOOP_LIMIT` 에러 |
| `for_each` | `in`, `as`, `body[]` | 리스트 순회 (번들 요청 처리) |
| `fallback` | `options[]` (각 항목은 스텝 배열) | 첫 대안부터 시도해 하나라도 성공하면 성공 (예: 손잡이 파지 실패 → 다른 접근 포즈) |
| `finally` (태스크 최상위 필드) | `finally[]` | `sequence`가 성공·실패 어느 쪽으로 끝나도 실행 (복구·서랍 닫기·홈 복귀) |
| `on_halt` (태스크 최상위 필드) | `on_halt[]` | 사용자 취소·비상정지 시 실행. **로봇 동작 없이** 상태 저장·로그·TTS 안내만 수행 |
| 스텝 공통 필드 | `timeout_sec`, `recovery[]` | `timeout_sec` 초과 시 `TIMEOUT` 실패. 실패 시 `recovery[]`(예: 그리퍼 열고 후퇴)를 실행한 뒤 `retry` 횟수만큼 재시도 |

**BehaviorTree 대응표 (발표 질의 대비: "왜 BT 프레임워크를 쓰지 않았나")**

| 우리 Runner | BehaviorTree.CPP / Nav2 | 차이 |
| :--- | :--- | :--- |
| `sequence` | Sequence | 동일 |
| `if` / `while` / `for_each` | IfThenElse / WhileDoElse / LoopNode | 동일 의미 |
| `retry` + `recovery[]` | RetryUntilSuccessful / Nav2 RecoveryNode | 동일 의미 |
| `fallback` | Fallback | 동일 의미 |
| `timeout_sec` | Timeout | 동일 의미 |
| `finally` | TryCatch(v4.9) | **TryCatch는 실패 시에만 정리 실행, 우리 `finally`는 성공 시에도 실행** |
| `on_halt` | TryCatch `catch_on_halt` / `_onHalted` | 동일 의미 |
| 스텝별 `pre_check`·`post_check`·`state_diff` 로그 | (기본 로거에 없음) | 우리 고유 기능 |

> **자체 Runner를 유지하는 사유**: BehaviorTree.CPP는 C++ 기반이라 14일 일정에서 개발·빌드 부담이 크고, 실시간 시각화 도구(Groot2)는 유료 버전에서만 제공됨. py_trees는 JSON 태스크 파일을 읽는 로더와 무조건 실행되는 정리 노드(`finally`)를 기본 제공하지 않음. 따라서 기존 프레임워크를 새로 익히기보다 그 핵심 제어 의미만 차용해 경량 자체 Runner를 구축하는 편이 일정과 성공 가능성 면에서 유리하다고 판단함(결정 로그 #19).

**변수 문법 (2종만 허용)**
* **값 전체 참조**: `"$scan.target.id"`, `"$scan.candidates[0].id"` → 원래 타입(불리언·숫자·객체) 그대로 치환.
* **문자열 보간**: `"{{loc.name_ko}} 찾기를 시작합니다"` → 문자열로 치환.
* **한국어 조사 필터**: `"{{loc.name_ko|을}}"`처럼 조사를 붙이면 Runner가 앞 단어의 받침 유무(유니코드 한글 음절 계산)로 `을/를`, `이/가`, `은/는`, `과/와`, `으로/로`를 자동 선택함. 목록은 `"{{list.items_ko|목록|을}}"` → "차키, 지갑, 시계를"처럼 쉼표로 잇고 마지막 단어 기준으로 조사를 붙임. 영문·숫자로 끝나면 받침 없음으로 처리.
* `eval`을 사용하지 않고 Runner가 경로를 해석함. 존재하지 않는 변수는 `VAR_UNDEFINED` 에러.
* **변수 스코프 (블랙보드)**: `output`·`set_var`로 만든 변수(`loc`, `scan`, `picked` 등)는 **태스크 단위 전역 블랙보드**에 저장되어 `sequence`·`finally`·`on_halt` 어디서든 태스크 종료 시까지 유지됨. 같은 이름으로 다시 `output`하면 덮어씀(예: Unpacking 루프의 `scan`은 재촬영마다 갱신, `loc`은 처음 값 유지). 예외로 `for_each`의 `as` 변수만 루프 안에서 유효함. 블랙보드는 태스크가 끝나면 사라지고(최종 값은 로그에 기록), **태스크 사이에 이어지는 정보는 상태 온톨로지(7.8)만** 사용함.

**조건식 (단일 형태)**: `{ "op": "<연산자>", "args": [ ... ] }`
* 비교 `==, !=, <, >, <=, >=` (args 2개) / 논리 `and, or` (2개 이상), `not` (1개) / 컬렉션 `empty, not_empty` (1개)

**실패 처리 규칙**
* 스텝별 `on_failure`: `abort`(기본) / `retry`(`retry` 횟수만큼) / `skip` / `safe_home`.
* `abort`로 `sequence`가 중단되면 `finally`가 실행되고 `overall_status = FAILED`.
* **비상정지(E-stop)로 인한 `ABORTED`에서는 `finally`의 로봇 동작을 실행하지 않음.** 사람이 상태를 확인한 뒤 재개 명령으로 복구함.

### 7.2 태스크 시퀀스 스키마

`action` 값에 따라 `params`를 검증하여 **오타나 잘못된 파라미터를 실행 전에 차단**합니다. 스텝은 재귀 구조(`if/while/for_each` 내부에 스텝)입니다.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TaskSequence",
  "type": "object",
  "required": ["task_id", "sequence"],
  "properties": {
    "task_id": { "type": "string" },
    "description": { "type": "string" },
    "inputs": { "type": "object", "description": "음성 인텐트에서 바인딩되는 입력 (예: target, list_name)" },
    "trigger": { "type": "object", "description": "태스크 레지스트리용 음성 트리거 (7.6)" },
    "params": { "type": "object", "description": "복합 스킬 입력 선언 (이름: 클래스)" },
    "pre": { "type": "object", "description": "실행 조건 (상태 경로: 값, 7.5)" },
    "effect": { "description": "결과 (상태 경로: 값) 또는 \"sensing\"" },
    "sequence": { "type": "array", "items": { "$ref": "#/definitions/step" } },
    "finally":  { "type": "array", "items": { "$ref": "#/definitions/step" } },
    "on_halt":  { "type": "array", "items": { "$ref": "#/definitions/step" } }
  },
  "definitions": {
    "cond": {
      "type": "object",
      "required": ["op", "args"],
      "properties": {
        "op": { "enum": ["==", "!=", "<", ">", "<=", ">=", "and", "or", "not", "empty", "not_empty"] },
        "args": { "type": "array", "minItems": 1 }
      }
    },
    "step": {
      "type": "object",
      "required": ["id", "action"],
      "properties": {
        "id": { "type": "string", "description": "로그 추적용 고유 ID (예: s7, s7.1)" },
        "action": { "enum": [
          "move_to_named_pose", "drawer_control", "inspect_region", "pick_object", "place_object",
          "query_ontology", "update_ontology", "speak",
          "set_var", "push", "pop", "if", "while", "for_each", "fallback"
        ]},
        "params": { "type": "object" },
        "output": { "type": "string", "description": "반환값을 저장할 변수명" },
        "cond": { "$ref": "#/definitions/cond" },
        "then": { "type": "array", "items": { "$ref": "#/definitions/step" } },
        "else": { "type": "array", "items": { "$ref": "#/definitions/step" } },
        "body": { "type": "array", "items": { "$ref": "#/definitions/step" } },
        "in":   { "type": "string" },
        "as":   { "type": "string" },
        "max_iter": { "type": "integer", "minimum": 1 },
        "on_failure": { "enum": ["abort", "retry", "skip", "safe_home"], "default": "abort" },
        "timeout_sec": { "type": "number", "exclusiveMinimum": 0 },
        "recovery": { "type": "array", "items": { "$ref": "#/definitions/step" } },
        "options": { "type": "array", "items": { "type": "array", "items": { "$ref": "#/definitions/step" } } },
        "retry": { "type": "integer", "minimum": 0, "default": 0 }
      }
    }
  }
}
```

> 구현 시 `params`는 7.1의 동작별 표를 기준으로 `allOf/if-then`으로 세분화하여 `schema/actions/*.json`으로 분리 관리하고, `while`은 `max_iter`를 필수로 강제함.

### 7.3 실제 인스턴스 예시: 오클루전 탐색 + 복구 (하드코딩 ID 없음)

음성으로 "시계 찾아줘" → `inputs.target = "watch"`로 바인딩되어 실행됩니다. 장애물 ID는 미리 알 수 없으므로 `inspect_region`의 반환값을 변수로 받아 사용합니다.

```json
{
  "task_id": "find_with_unpack",
  "description": "목표 물품 탐색: 가려지면 장애물을 트레이로 배출하며 탐색, 종료(성공/실패 무관) 후 원위치 복구",
  "inputs": { "target": "watch" },
  "sequence": [
    { "id": "s1", "action": "query_ontology", "params": { "item": "$inputs.target" }, "output": "loc" },
    { "id": "s2", "action": "speak", "params": { "text": "{{loc.name_ko}} 찾기를 시작합니다" } },
    { "id": "s3", "action": "move_to_named_pose", "params": { "pose_name": "drawer_approach", "drawer_id": "$loc.drawer_id" } },
    { "id": "s4", "action": "drawer_control", "params": { "drawer_id": "$loc.drawer_id", "state": "open" } },
    { "id": "s5", "action": "move_to_named_pose", "params": { "pose_name": "drawer_top_view", "drawer_id": "$loc.drawer_id" } },
    { "id": "s6", "action": "inspect_region", "params": { "region": "$loc.drawer_id", "search_target": "$inputs.target" }, "output": "scan" },

    { "id": "s7", "action": "while",
      "cond": { "op": "and", "args": [
        { "op": "==", "args": ["$scan.target_found", false] },
        { "op": ">",  "args": ["$scan.visible_count", 0] } ] },
      "max_iter": 8,
      "body": [
        { "id": "s7.1", "action": "pick_object", "params": { "object_id": "$scan.candidates[0].id", "approach_offset": [0, 0, 0.1] },
          "output": "picked", "on_failure": "retry", "retry": 1 },
        { "id": "s7.2", "action": "place_object", "params": { "location": "staging_tray" }, "output": "placed" },
        { "id": "s7.3", "action": "push", "params": { "stack": "restore_stack",
            "value": { "object_id": "$picked.object_id", "origin_pose": "$picked.pick_pose_drawer_frame", "slot": "$placed.slot" } } },
        { "id": "s7.4", "action": "move_to_named_pose", "params": { "pose_name": "drawer_top_view", "drawer_id": "$loc.drawer_id" } },
        { "id": "s7.5", "action": "inspect_region", "params": { "region": "$loc.drawer_id", "search_target": "$inputs.target" }, "output": "scan" }
      ] },

    { "id": "s8", "action": "if",
      "cond": { "op": "==", "args": ["$scan.target_found", true] },
      "then": [
        { "id": "s8.1", "action": "pick_object", "params": { "object_id": "$scan.target.id", "approach_offset": [0, 0, 0.1] } },
        { "id": "s8.2", "action": "place_object", "params": { "location": "handover_zone" } },
        { "id": "s8.3", "action": "update_ontology", "params": { "item": "$inputs.target", "drawer_id": "$loc.drawer_id" } },
        { "id": "s8.4", "action": "speak", "params": { "text": "{{loc.name_ko|을}} 찾았습니다. 앞쪽 트레이에서 가져가세요" } }
      ],
      "else": [
        { "id": "s8.5", "action": "speak", "params": { "text": "서랍장에서 {{loc.name_ko|을}} 찾지 못했습니다" } }
      ] }
  ],
  "finally": [
    { "id": "f1", "action": "while",
      "cond": { "op": "not_empty", "args": ["$restore_stack"] }, "max_iter": 8,
      "body": [
        { "id": "f1.1", "action": "pop", "params": { "stack": "restore_stack" }, "output": "item" },
        { "id": "f1.2", "action": "move_to_named_pose", "params": { "pose_name": "tray_view" } },
        { "id": "f1.3", "action": "pick_object", "params": { "object_id": "$item.object_id", "source_slot": "$item.slot", "approach_offset": [0, 0, 0.1] } },
        { "id": "f1.4", "action": "place_object", "params": { "pose": "$item.origin_pose", "frame": "drawer" } }
      ] },
    { "id": "f2", "action": "drawer_control", "params": { "drawer_id": "$loc.drawer_id", "state": "close" } },
    { "id": "f3", "action": "move_to_named_pose", "params": { "pose_name": "home" } }
  ]
}
```

* 이 한 파일로 **Unpacking(s7), 미발견 처리(s8 else), Rollback(f1), 서랍 닫기(f2)** 가 모두 표현되며, 중간에 실패해도 `finally`로 복구가 보장됨. Python 코드에는 시나리오 로직이 없음.
* **번들 요청**(`find_list`, `find_class`)은 별도 템플릿 `find_group_by_drawer`로 처리함: `query_ontology`의 `groups[]`를 `for_each`로 순회하여 **서랍당 한 번만 열고**, 서랍 내부에서는 목표 목록이 모두 발견되거나 비워질 때까지 Unpacking 루프를 돈 뒤 복구·닫기.

### 7.4 실행 이력 자동 로깅 스키마 (Execution Log)

각 스텝(중첩 스텝 포함)마다 시작 시각, 소요 시간, 반복 인덱스, 시도 횟수, **성공 여부·결과 코드, 에러 정보, 조건 확인 결과(`pre_check`), 상태 변화(`state_diff`)**를 기록합니다. 플래너가 만든 실행은 `plan`(스킬 조합)도 함께 기록합니다.

```json
{
  "task_id": "find_with_unpack",
  "run_id": "2026-10-11T14:03:00Z_001",
  "backend": "real",
  "inputs": { "target": "watch", "source": "voice", "stt_text": "시계 찾아줘", "stt_confidence": 0.93 },
  "overall_status": "COMPLETED",
  "outcome": "FOUND",
  "started_at": "2026-10-11T14:03:00.000Z",
  "total_duration_sec": 96.4,
  "logs": [
    { "id": "s6", "action": "inspect_region", "status": "SUCCESS", "started_at": "2026-10-11T14:03:18.200Z", "duration_sec": 0.8,
      "result": { "target_found": false, "visible_count": 2, "candidates": ["unknown#1", "notebook#1"] } },
    { "id": "s7.1", "iteration": 1, "attempt": 1, "action": "pick_object", "status": "FAILURE", "duration_sec": 3.1,
      "error": { "code": "GRASP_FAILED", "message": "gripper closed with no object" } },
    { "id": "s7.1", "iteration": 1, "attempt": 2, "action": "pick_object", "status": "SUCCESS", "duration_sec": 4.2,
      "pre_check": { "result": "PASS", "conditions": [ { "subject": "robot", "predicate": "gripper", "op": "==", "value": "empty", "actual": "empty", "pass": true } ] },
      "post_check": { "result": "PASS", "verify": "gripper_width > min_width AND grasp_detected", "observed": { "gripper_width_mm": 41.5 } },
      "result": { "object_id": "unknown#1", "pick_pose_drawer_frame": [0.12, 0.05, 0.03, 0.0, 0.707, 0.0, 0.707], "grasp_ok": true },
      "state_diff": { "gripper": ["empty", "unknown#1"], "located_in.unknown#1": ["drawer_top", "gripper"] } },
    { "id": "s7.2", "iteration": 1, "attempt": 1, "action": "place_object", "status": "SUCCESS", "duration_sec": 4.0,
      "result": { "slot": "staging_tray_slot_1" } }
  ]
}
```

* `overall_status`: `COMPLETED`(시퀀스 정상 종료) / `FAILED`(스텝 abort, `finally` 실행됨) / `ABORTED`(사용자 취소·비상정지).
* `outcome`: 작업 결과 의미(`FOUND` / `NOT_FOUND` / `PARTIAL`)는 상태와 분리하여 기록.
* **시간 규칙**: `total_duration_sec`는 실행 전체의 **실제 경과 시간(wall-clock)**. 제어 블록(`while`/`if`)의 소요 시간은 자식 스텝을 포함하므로 합산에서 제외하고, **원자 동작(리프) 스텝 소요 시간의 합 ≤ `total_duration_sec`**를 검증함.
* **성공 여부**: 모든 스텝은 `status`(`SUCCESS`/`FAILURE`/`SKIPPED`)를 가짐. 실패 시 `error.code`(7.5 스킬의 `errors` 목록 기준)를 기록.
* **조건 확인**: `pre_check`는 `PASS` / `PRE_UNMET`과 함께 **조건별 결과 배열**(조건, 실제 값, 통과 여부)을 기록. `PRE_UNMET`이면 동작을 보내지 않음.
* **성공 판정**: 스텝 성공 = **액션 결과 성공 AND 사후 관측 확인(`post_check`) 통과**. 관측 기준은 스킬의 `verify`(그리퍼 폭, 서랍 변위, 재스캔). 액션은 성공했지만 관측이 안 맞으면 `POST_UNCONFIRMED`로 실패 처리.
* **안전 게이트**: 실물 실행 전 8단계 게이트(11장)의 단계별 통과 여부를 `runs` 헤더에 기록.
* **상태 변화**: `state_diff`는 `{상태 경로: [이전 값, 이후 값]}`. 관측으로 고친 경우 `STATE_MISMATCH` 항목으로 따로 표시.
* **플래너 실행**: 헤더에 `goal`과 `plan`(스킬 조합 목록), 스킬 단위 기록과 그 아래 원자 동작 기록을 함께 저장.
* **저장**: 스텝이 끝날 때마다 `LogStore`를 통해 MongoDB(`runs`·`steps`·`states` 컬렉션)에 저장. `runs` 헤더에는 **온톨로지 파일 해시**, STT 원문, LLM 원문 응답, 안전 게이트 결과를 포함. DB 연결 실패 시 **JSONL 파일로 자동 폴백**하여 시연이 멈추지 않게 하고, 제출·발표용으로 `logs/*.json`도 내보냄. 원시 토픽(카메라·조인트)은 rosbag2(MCAP)로 별도 녹화.
* 위 예시는 지면상 일부 스텝만 표기. 실제 로그에는 `finally` 스텝을 포함한 모든 스텝이 기록됨.

### 7.5 로봇 온톨로지 (동작 · 상태 · 세계, JSON-LD)

강사 챌린지의 중심. 로봇이 **할 수 있는 동작(skills)**, **현재 상태(state)**, **다루는 세계(world)**를 하나의 온톨로지로 정의하고, 플래너·Runner·LLM 파서·로거가 모두 이 파일을 기준으로 동작함.

```json
{
  "@context": { "@vocab": "https://cobot2.local/onto#" },
  "classes": {
    "Item": {}, "Valuables": { "subClassOf": "Item", "name_ko": "귀중품" }, "Key": { "subClassOf": "Valuables", "name_ko": "열쇠류" },
    "Obstacle": { "subClassOf": "Item" },
    "Place": {}, "Drawer": { "subClassOf": "Place" }, "Tray": { "subClassOf": "Place" }
  },
  "world": {
    "items": {
      "car_key": { "class": "Key",       "name_ko": "차키", "aliases_ko": ["차키", "자동차 열쇠"], "size_m": [0.06, 0.03, 0.02], "grip_force": 20 },
      "wallet":  { "class": "Valuables", "name_ko": "지갑", "aliases_ko": ["지갑"],             "size_m": [0.11, 0.09, 0.02], "grip_force": 25 },
      "watch":   { "class": "Valuables", "name_ko": "시계", "aliases_ko": ["시계", "손목시계"], "size_m": [0.06, 0.06, 0.04], "grip_force": 15 }
    },
    "lists": {
      "commute_set": { "name_ko": "출근 준비물", "aliases_ko": ["출근 준비물", "출근 세트"], "items": ["car_key", "wallet", "watch"] }
    },
    "places": {
      "drawer_top":    { "class": "Drawer", "name_ko": "위 서랍",   "max_travel_m": 0.25, "return_slot": [0.20, 0.08, 0.0] },
      "drawer_bottom": { "class": "Drawer", "name_ko": "아래 서랍", "max_travel_m": 0.25, "return_slot": [0.20, 0.08, 0.0] },
      "staging_tray":  { "class": "Tray",   "name_ko": "임시 트레이", "slots": 3 },
      "handover_zone": { "class": "Tray",   "name_ko": "전달 트레이", "slots": 3 }
    }
  },
  "state": {
    "robot_pose": { "robot": "home" },
    "gripper":    { "robot": "empty" },
    "open":       { "drawer_top": false, "drawer_bottom": false, "staging_tray": true, "handover_zone": true },
    "located_in": { "car_key": "drawer_bottom", "wallet": "drawer_bottom", "watch": "drawer_top" }
  },
  "skills": {
    "open_drawer": {
      "kind": "primitive", "name_ko": "서랍 열기", "params": { "drawer_id": "Drawer" },
      "pre": [
        { "subject": "$drawer_id", "predicate": "open",    "op": "==", "value": false },
        { "subject": "robot",   "predicate": "gripper", "op": "==", "value": "empty" }
      ],
      "effect": [ { "subject": "$drawer_id", "predicate": "open", "value": true } ],
      "verify": "drawer_displacement >= 0.9 * distance",
      "expand": [
        { "action": "move_to_named_pose", "params": { "pose_name": "drawer_approach", "drawer_id": "$drawer_id" } },
        { "action": "drawer_control", "params": { "drawer_id": "$drawer_id", "state": "open" } }
      ],
      "errors": ["DRAWER_STUCK", "GRASP_FAILED"]
    },
    "close_drawer": {
      "kind": "primitive", "name_ko": "서랍 닫기", "params": { "drawer_id": "Drawer" },
      "pre": [
        { "subject": "$drawer_id", "predicate": "open",    "op": "==", "value": true },
        { "subject": "robot",   "predicate": "gripper", "op": "==", "value": "empty" }
      ],
      "effect": [ { "subject": "$drawer_id", "predicate": "open", "value": false } ],
      "verify": "closed_position_reached AND push_axis_force > threshold",
      "expand": [ { "action": "drawer_control", "params": { "drawer_id": "$drawer_id", "state": "close" } } ],
      "errors": ["DRAWER_STUCK", "CLOSE_NOT_CONFIRMED"]
    },
    "pick": {
      "kind": "primitive", "name_ko": "집기", "params": { "item": "Item", "from": "Place" },
      "pre": [
        { "subject": "robot", "predicate": "gripper",    "op": "==", "value": "empty" },
        { "subject": "$item", "predicate": "located_in", "op": "==", "value": "$from" },
        { "subject": "$from", "predicate": "open",       "op": "==", "value": true }
      ],
      "hold": [ { "subject": "$from", "predicate": "open", "op": "==", "value": true } ],
      "effect": [
        { "subject": "robot", "predicate": "gripper",    "value": "$item" },
        { "subject": "$item", "predicate": "located_in", "value": "gripper" }
      ],
      "verify": "gripper_width > min_width AND grasp_detected",
      "expand": [
        { "action": "inspect_region", "params": { "region": "$from", "search_target": "$item" }, "output": "scan" },
        { "action": "pick_object", "params": { "object_id": "$scan.target.id", "approach_offset": [0, 0, 0.1] } }
      ],
      "errors": ["NOT_VISIBLE", "GRASP_FAILED"]
    },
    "place": {
      "kind": "primitive", "name_ko": "놓기", "params": { "item": "Item", "to": "Place" },
      "pre": [
        { "subject": "robot", "predicate": "gripper", "op": "==", "value": "$item" },
        { "subject": "$to",   "predicate": "open",    "op": "==", "value": true }
      ],
      "hold": [ { "subject": "$to", "predicate": "open", "op": "==", "value": true } ],
      "effect": [
        { "subject": "robot", "predicate": "gripper",    "value": "empty" },
        { "subject": "$item", "predicate": "located_in", "value": "$to" }
      ],
      "verify": "rescan: $item visible in $to",
      "expand": [ { "action": "place_object", "params": { "location": "$to" } } ],
      "errors": ["TRAY_FULL", "PLACE_FAILED"]
    },
    "fetch_with_unpack": {
      "kind": "composite", "name_ko": "가려진 물건까지 찾아 꺼내기", "params": { "target": "Item" },
      "task": "tasks/find_with_unpack.json",
      "pre": [ { "subject": "robot", "predicate": "gripper", "op": "==", "value": "empty" } ],
      "effect": "sensing",
      "trigger": { "intent": "find_item", "examples_ko": ["시계 찾아줘"] }
    }
  }
}
```

* **classes / world**: 물품·리스트·장소의 지식 (기존 물품 지식 베이스는 여기로 통합). `lists.*.items`에 쓰인 키는 반드시 `world.items`에 정의되어야 함(로딩 시 검증).
* **state**: 로봇과 세계의 **현재 상태**. `상태[predicate][subject] = value` 한 가지 형태로 통일(예: `open.drawer_top`, `located_in.watch`, `gripper.robot`). 서랍과 트레이를 `open` 하나로 다뤄 "집거나 놓을 수 있는 곳인가"를 단순하게 판단함.
* **skills**: 로봇 동작의 정의.
  * `primitive` 스킬: **실행 조건(`pre`)·실행 중 유지 조건(`hold`)·결과(`effect`)·관측 확인 기준(`verify`)·원자 동작 전개(`expand`)·발생 가능 에러**를 가짐. 조건·결과는 모두 `{subject, predicate, op, value}` 레코드 형식으로 통일. 플래너가 조합에 사용함.
  * `hold`는 스킬 실행 중 주기적으로 확인(예: 집는 동안 서랍이 열려 있어야 함). 깨지면 즉시 중단하고 `HOLD_VIOLATED` 기록.
  * `composite` 스킬: 7.3 같은 태스크 JSON을 하나의 스킬로 등록. 결과가 관측에 따라 달라지는(`effect: "sensing"`) 탐색형 작업은 플래너 조합 대상이 아니라 인텐트로 직접 호출함.
* 물품 목록·`size_m`·`grip_force`·`max_travel_m`·`return_slot`은 예시값이며, Day 2 실물 파지 테스트와 서랍장 실측 후 갱신함(2.2, 2.3).
* **원천은 JSON-LD, PDDL은 내보내기만**: 조건·결과 레코드는 PDDL의 술어 형식과 1:1로 대응하므로, 여유가 있으면 PDDL 내보내기 스크립트로 "표준 플래닝 언어와 호환"을 증빙함. PlanSys2·SkiROS2 같은 외부 프레임워크 도입은 향후 과제로 둠(ROS 2 Jazzy 지원·C++ 부담, 선행 사례 보고서 참고).
* **파라미터 이름 규칙**: 스킬 파라미터가 원자 동작 파라미터(7.1)와 같은 대상을 가리키면 **같은 이름**을 씀(예: `drawer_id`). 스킬 수준에서만 쓰는 개념(`item`, `from`, `to`)은 `expand`에서 원자 동작 파라미터(`search_target`, `region`, `location`)로 명시적으로 매핑하며, 정합성 검사(아래)가 매핑 누락을 잡아냄.
* **목적지 종류에 따른 자동 처리**: `place` 스킬은 `location: "$to"`만 넘기고, 목적지가 서랍이면 `place_object` 백엔드가 서랍 좌표계·z 보정을 자동 적용함(7.1 `place_object`). 원위치 복구처럼 정확한 자리가 필요하면 태스크 JSON에서 `pose` + `frame: "drawer"`를 직접 지정함(7.3 `f1.4`).
* **시작 시 정합성 검사**: 로딩 시 ① 모든 스킬에 실행 구현이 있고 그 역도 성립, ② 모든 조건이 존재하는 상태 경로를 참조, ③ 모든 에러 코드가 정의됨을 검증하고, 실패하면 Runner를 시작하지 않음.

### 7.6 새 작업 추가 = 온톨로지에 스킬 추가 (코드 수정 0줄)

* 새 작업은 `tasks/<이름>.json`(7.2 스키마) 파일을 추가하고 온톨로지 `skills`에 `composite`로 등록하면 끝. 파일에 `trigger`(인텐트 이름·예문)를 적으면 **LLM 인텐트 파서(6.4)의 프롬프트와 플래너에 자동 반영**되어 음성 명령까지 함께 추가됨.
* 새 원자 수준 능력은 `primitive` 스킬로 추가(예: "트레이 흔들어 정렬하기"). 기존 원자 동작의 조합으로 `expand`를 적을 수 있으면 역시 코드 수정이 필요 없음.

```json
{
  "task_id": "return_items",
  "description": "전달 트레이의 물건을 온톨로지에 기록된 서랍으로 반납",
  "trigger": { "intent": "return_items", "examples_ko": ["꺼낸 물건들 다시 서랍에 정리해줘", "원래대로 넣어줘"] },
  "sequence": [
    { "id": "s1", "action": "inspect_region", "params": { "region": "handover_zone" }, "output": "tray" }
  ]
}
```

> 위 예시의 `sequence`는 지면상 첫 스텝만 표기. 시연 2막(17.4)의 "정리해줘"가 이 방식의 증빙임.

### 7.7 플래너: 명령 → 스킬 조합 (담당 C)

강사 챌린지의 "명령을 내리면 그 조합으로 다양한 행동"을 담당. **동작 순서는 하드코딩하지 않고 스킬의 조건·결과에서 도출**함.

```
음성 명령 → LLM(6.4)이 목표 추출: goals = [{predicate: located_in, subject: wallet, value: drawer_bottom}]
         → 플래너: 현재 state에서 primitive 스킬을 너비 우선 탐색(BFS)하여 목표를 만족하는 최단 조합 탐색
            (기본 목표에 "이번 계획에서 연 서랍은 닫기"를 자동 추가)
         → 계획(7.2 형식 JSON) 생성 → 스키마 검증 → 화면 표시 → Runner 실행
```

**예: "지갑 아래 서랍에 넣어줘"** (지갑은 전달 트레이, 아래 서랍은 닫힘, 그리퍼 비어 있음)

| 순서 | 스킬 | 이 순서가 나온 이유 (조건) |
| :--- | :--- | :--- |
| 1 | `open_drawer(drawer_bottom)` | `place`는 `open.drawer_bottom = true`가 필요. `open_drawer`는 `gripper = empty`가 필요하므로 **집기 전에** 열어야 함 |
| 2 | `pick(wallet, handover_zone)` | `place`는 `gripper = wallet`이 필요 |
| 3 | `place(wallet, drawer_bottom)` | 목표 `located_in.wallet = drawer_bottom` 달성 |
| 4 | `close_drawer(drawer_bottom)` | 자동 추가 목표(연 서랍 닫기), `place` 후 그리퍼가 비어 있어 가능 |

* **탐색 범위**: 스킬 수가 10개 안팎인 작은 세계이므로 BFS(깊이 제한 8)로 충분함. 외부 플래닝 라이브러리 없이 Python으로 구현.
* **계획 불가 시**: 어떤 조건을 만족할 수 없는지 설명하여 TTS로 응답(예: "임시 트레이가 가득 차서 옮길 수 없습니다").
* **이미 만족된 목표**: 계획 길이 0 → "이미 아래 서랍에 있습니다" / "이미 닫혀 있습니다"처럼 상태를 근거로 응답.
* **실행 중 실패 시 재계획**: 스텝이 실패하면 관측으로 갱신된 상태에서 1회 재계획, 그래도 실패하면 안전 정지.
* LLM은 **목표만** 출력하고 동작 순서는 만들지 않음 → LLM이 위험한 순서를 지어낼 여지를 없앰.

### 7.8 상태 추적 규칙 (담당 C, 온톨로지 데이터 E)

* **Runner가 상태의 단일 관리자**. 스킬 실행 전 `pre`를 확인하고(`PRE_UNMET`이면 실행하지 않음), 실행 중 `hold`를 확인하며, 액션 성공 후 `verify` 관측이 통과해야 `effect`를 반영.
* **관측이 우선**: `inspect_region` 결과(물품 위치), `/drawers/state`(서랍), `/gripper/state`(그리퍼)가 상태와 다르면 **관측값으로 고치고 `STATE_MISMATCH`를 로그**에 남김. 1막의 차키 위치 자동 수정도 이 규칙으로 동작함.
* 현재 상태는 `/robot_state` 토픽(JSON)으로 계속 발행 → 시연 화면·Isaac Sim 트윈이 사용.
* 상태는 DB에 저장하여 작업 사이에 유지됨(2막에서 1막의 수정 결과 사용).

### 7.9 지식 그래프 (초안)

7.5 로봇 온톨로지를 그림으로 나타낸 초안. 물품·시나리오가 확정되면 최종본으로 한 번에 다시 그림(원본: `지식 그래프_초안.pdf`).

**① 분류 계층(TBox)과 개체(ABox)** — 하위 클래스(실선), 개체의 종류(점선), 목록 구성. "귀중품 다 찾아줘"는 Valuables 아래 개체를 따라가는 추론으로 처리됨.

![분류 계층과 개체](images/knowledge_graph_1.jpg)

**② 상태 스냅샷 — 시연 시작 시점(17.2)** — `located_in` 기록과, 1막 1-7에서 관측 후 수정되는 차키 위치(주황 점선).

![상태 스냅샷](images/knowledge_graph_2.jpg)

**③ 스킬 인과 체인 — 2막 "지갑은 아래 서랍에 넣어 둬"** — 각 스킬의 결과가 다음 스킬의 조건을 채우는 관계. 서랍을 먼저 여는 순서가 조건에서 도출됨(7.7).

![스킬 인과 체인](images/knowledge_graph_3.jpg)

> **최종본 작성 시 확인**: Day 2 파지 테스트로 확정된 물품, 실제 서랍·트레이 구성, 17.2 초기 배치, 2막 명령 문장, 그림 속 용어(`located_in`, `open`, `gripper`)와 7.5 온톨로지 키 일치.

---

## 8. 메인 도메인 기능 상세

### 8.1 온톨로지 기반 물품-서랍 추론
* "출근 준비물 찾아줘" → 별칭 매칭으로 `commute_set` 식별 → 구성 물품 추출 → `groups[]`로 서랍별로 묶어 **서랍당 한 번만 개방**.
* "귀중품 다 찾아줘" → `Valuables`와 하위 클래스(`Key`)에 속한 물품 전체를 추론하여 동일하게 처리.

### 8.2 오클루전 극복 순차 탐색 (Unpacking Loop)
1. **1차 스캔**: 서랍 개방 후 탑뷰 촬영. 목표 물품이 보이면 바로 꺼내 `handover_zone`(사용자 앞 트레이)에 배치.
2. **미발견 시 (오클루전 발생)**:
   * **장애물 선택 정책**: 위에 다른 물체가 얹혀 있지 않은 물체만 후보로 하고(**`top_z` 높은 것부터는 안전 제약**), 후보끼리는 **마스크 면적이 큰 것부터** 파지(Mechanical Search 실물 실험: 큰 것부터 평균 4.85회 vs 무작위 10.87회). 파지 전 손가락이 들어갈 부피와 목표 물체 마스크의 겹침을 검사하여 목표를 건드리는 파지는 피함.
   * **시연 배치 주의**: 선행 연구 실패의 85~90%가 벽·모서리에 붙은 물체였음 → 물품을 서랍 벽에서 띄워 배치.
   * 스테이징 트레이의 빈 슬롯에 배치. 슬롯이 가득 차면 `FAILURE(TRAY_FULL)` → `finally`로 복구 (슬롯 수 = 실물 트레이 구획 수, `config`에 정의).
   * 꺼낼 때의 **서랍 로컬 좌표계 기준 Pick Pose**와 트레이 슬롯을 스택(LIFO)에 `push`.
   * 장애물을 하나 뺄 때마다 재촬영하여 반복 (`while`, `max_iter` 제한).
3. **완전 부재 처리**: 서랍 내부가 빌 때까지 목표가 없으면 TTS로 미발견 피드백.

### 8.3 스마트 원위치 복구 (Rollback) & 동적 온톨로지 갱신
* **스마트 복구**: `finally`에서 스택을 `pop`하며 트레이에서 파지해 **서랍 로컬 좌표**로 역순 배치. 복구 직전에 서랍 좌표계를 재추정(현재 인출 거리 반영)하고, 원래 자리가 점유되어 있으면 최근접 빈 자리로 재계획. 높이(z)는 **현재 지지면**(바닥 또는 아래 물체 윗면)을 재촬영하여 정함.
* **복구 정확도 측정**: 선행 연구에 정량 자료가 없으므로 위치·요(yaw) 오차를 같은 카메라로 직접 측정해 지표로 보고(14장).
* **동적 온톨로지 업데이트**: 목표 발견 시 `update_ontology`로 명시 갱신하고, 추가로 `inspect_region` 결과에 포함된 **이미 알려진 물품은 관측 우선 규칙(7.8)으로 상태가 자동 수정**됨.

### 8.4 실물 서랍 개폐 구현 (담당 B)
* **열기**: 손잡이 접근 → 파지 → **컴플라이언스 제어**(강의 DRL `task_compliance_ctrl`)로 인출 축 외 방향은 부드럽게, 인출 축은 `movel`로 지정 거리만큼 당김 → 해제 → 후퇴. 비스듬히 당겨 레일이 걸리는 문제와 가벼운 서랍장이 끌려오는 문제를 줄임.
* **닫기**: 그리퍼를 닫은 상태로 서랍 앞면을 밀고, **닫힘 = TCP 변위가 닫힘 위치에 도달 AND 미는 축 힘이 임계 초과** 두 조건을 모두 만족할 때만 판정. DRL `check_force_condition`은 힘의 크기만 보고 방향을 보지 않아, 힘만으로 판정하면 레일 걸림·다른 물체 충돌도 "닫힘"으로 오판함. 확인 실패 시 `CLOSE_NOT_CONFIRMED`.
* **센서 영점**: 각 컴플라이언스 구간 시작 전에 외력 센서 영점을 초기화(DRL 외력 리셋 함수)하고, 인출 축 외 방향은 낮은 강성으로 설정.
* **걸림 감지 (열기)**: 인출 중 기준 이상의 힘이 걸리면 즉시 정지하고 `DRAWER_STUCK` 에러로 보고 → `finally` 실행.
* **닫힘 실패 복구 (닫기)**: 닫힘 위치에 도달하기 전에 힘 임계를 넘으면(튀어나온 물품·레일 이물질) `CLOSE_NOT_CONFIRMED` → ① 서랍을 약 5cm 다시 열고 ② 서랍 앞쪽을 재촬영해 튀어나온 물품이 있으면 안쪽으로 밀어 넣거나 재배치 ③ 다시 닫기를 1회 재시도. 그래도 실패하면 `DRAWER_STUCK`으로 안전 정지하고 TTS로 사람의 확인을 요청(서랍이 열린 상태를 상태 온톨로지에 그대로 유지).
* `drawer_displacement`는 실제 이동 거리(TCP 이동량)로 반환하고 `/drawers/state`로 발행하여 비전의 서랍 좌표 변환과 트윈에 사용.

---

## 9. 비전 파이프라인 상세 (담당 A, 핵심 경로)

| 단계 | 내용 | 완료 시점 |
| :--- | :--- | :--- |
| **V0 카메라·캘리브레이션** | 손목 RealSense 컨테이너, 표준 토픽 remap. 강의 `Calibration_Tutorial`로 **핸드-아이 캘리브레이션**(`T_gripper2camera`) 재수행, 서랍 좌표계와 함께 TF 발행 | Day 2 |
| **V1 실물 데이터셋** | 로봇을 `drawer_top_view` 포즈에 두고 물품 배치·겹침·조명을 바꿔 가며 촬영(클래스당 150~300장). 사전 라벨링(YOLO-World 등, **SAM2 마스크 → 박스 변환으로 보조**) 후 수동 보정. 오프라인 작업(PC1) | Day 3~4 |
| **V2 YOLO + Depth** | YOLO(v8n/s) 검출 → 뎁스로 3D 위치 → 서랍 좌표 변환 → `top_z` 내림차순 정렬 | Day 5~6 |
| **V3 미지 물체 · ID 추적** | 서랍 바닥 평면 위 뎁스 덩어리 중 검출되지 않은 것을 `unknown#n`으로 생성(클래스 무관). 재촬영 간 ID는 서랍 좌표 최근접 매칭(3cm 이내 + 같은 클래스)으로 유지. (조건부) Day 6에 뎁스 덩어리 방식이 정확도 기준(위치 1.5cm, 가림 순서 90%)에 못 미치면 덩어리를 SAM2 점·박스 프롬프트로 넘겨 마스크 정밀화(`VISION_MODE=yolo_sam2`, 출력 형식 동일) | Day 6~7 |
| **V-sim (보조)** | Isaac Sim 손목 카메라 + **oracle(시뮬레이터 정답)** 으로 `inspect_region`과 동일 형식 출력 → 사전 검증 모드 전용 | Day 4 (트윈 일정 내) |

* **모델 결정**: 학습 중인 `Fruits/best.pt`는 서랍 물품과 클래스가 달라 사용하지 않음. **실물 데이터로 학습**하고, Isaac Sim Replicator 합성 데이터는 여유 시 보강용으로만 사용.
* **실물 특유 리스크**: 반사·검정·투명 물체의 뎁스 결손, 조명 변화, 서랍 내부 그림자 → 물품 선정 기준(2.3), 무광 서랍장(2.2), 조명 고정으로 대응.
* **평가**: 실측(자·격자 시트) 대비 3D 위치 오차, 검출 정밀도·재현율, 가림 순서 정확도.

---

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

---

## 11. 안전 요구사항 (실물)

* **비상정지**: 티치 펜던트 비상정지 버튼을 1차, `/runner/estop` 서비스 + PC2 키보드 단축키를 2차, 음성 "멈춰"는 보조 수단으로 둠.
* **실물 실행 절차**: 새 JSON·새 동작은 ① mock 또는 sim에서 먼저 통과 → ② 실물 저속 실행 → ③ 정상 속도. 실물 실행 중에는 **1인이 비상정지 버튼을 잡고 대기**(2인 운용).
* **실물 실행 전 안전 게이트 (Runner가 순서대로 확인, 단계별 결과를 로그에 기록)**
  1. 스키마 검증(LLM 출력·태스크 JSON)
  2. 온톨로지·현재 상태 검증(존재하는 물품인지, 목표가 현재 상태와 다른지)
  3. 계획 존재 확인(BFS 실패 시 이유를 TTS로 알리고 실행하지 않음)
  4. **목표형 명령은 계획을 화면·TTS로 제시하고 사용자 확인**("진행할까요?" → "응")
  5. 새 JSON·LLM 생성 JSON은 기호적 드라이런 + 트윈 사전 검증
  6. 스킬별 실행 시점 조건 재확인(관측 기반: 서랍이 실제로 열렸는가)
  7. 협동 모드 속도·힘 제한, 작업 영역 제한, 비상정지 버튼 2인 운용
  8. 사후 관측 확인(`verify`) 후에만 상태 갱신
* **속도·힘 제한**: DSR 협동 모드 속도·힘 제한 적용. `handover_zone`·서랍 접근 시 감속.
* **전달 방식**: 사람 손에 직접 건네지 않고 전달 트레이에 내려놓음.
* **작업 영역 제한**: 백엔드에서 작업 영역 밖 목표 포즈는 실행 전에 거부(`WORKSPACE_VIOLATION`).
* **비상정지 후 처리**: E-stop으로 `ABORTED`된 경우 `finally`의 로봇 동작을 자동 실행하지 않고, 사람이 확인한 뒤 재개(7.1 실패 처리 규칙).
* 시연 시 관람 인원은 작업 반경 밖에 위치하도록 바닥 표시.

---

## 12. 기술 스택

| 구분 | 기술 스택 | 세부 용도 |
| :--- | :--- | :--- |
| **Container** | Docker, Docker Compose(프로파일) | 장비·역할별 서비스 구성, 오디오·USB 패스스루 |
| **Robot** | Doosan M0609 + OnRobot RG2, DSR ROS 2 드라이버·DRL(컴플라이언스·힘 제어), DSR 에뮬레이터 | 실물 제어, 사전 검증용 가상 제어기 |
| **Robotics Framework** | ROS 2 Jazzy, CycloneDDS(강사 제공, Domain 70) | 노드 통신, Action Server/Client, 다중 PC 통신 |
| **Action Orchestration** | Python JSON Runner + `jsonschema` | 원자 동작 디스패칭, 변수·조건·반복·finally 해석, 실행 로그 |
| **Vision** | Intel RealSense(손목), YOLO(ultralytics), 뎁스 기반 3D 위치, 핸드-아이 캘리브레이션 | 물품 검출, 가림 순서, 인스턴스 ID 추적 |
| **Robot Ontology · Planner** | Python, JSON-LD, BFS 플래너 | 스킬(조건·결과)·상태·세계 정의, 명령 → 스킬 조합, 상태 추적, 별칭·클래스 추론 |
| **Database** | MongoDB 8.0 (컨테이너) + pymongo, JSONL 폴백, rosbag2(MCAP) | 실행 로그·스텝 기록·상태 스냅샷 저장·조회, 원시 토픽 녹화 |
| **Speech · LLM (필수)** | openWakeWord, OpenAI Whisper API / faster-whisper, LangChain + GPT(강의 방식), Piper·espeak-ng | 웨이크워드, STT, LLM 인텐트 파싱, TTS |
| **Digital Twin (팀 선택)** | NVIDIA Isaac Sim 5.1.0 (네이티브), Lula IK·RMPflow(폴백) | 실물 미러링, JSON 사전 검증 |

---

## 13. 14일 풀타임 스프린트 일정 및 마일스톤 (10/03 ~ 10/16)

> **전략 원칙**: 실물 작업 공간(서랍장·포즈·캘리브레이션)을 **Day 2까지** 고정하고, 그동안 C는 mock으로 Runner를 완성. 실물 모션(B)과 실물 비전(A)이 핵심 경로이며, Isaac Sim 트윈은 A의 보조 작업으로 병행. 새 JSON은 **mock/sim에서 먼저 통과시킨 뒤 실물에 투입**. Day 12는 예비일.

**Day 0 (10/02, 오늘) 사전 준비**
* [E] **서랍장 구매**(2.2 기준), 트레이 2개·물품 후보 구매 목록 작성
* [B] ~~실물 로봇 사용 가능 시간 확인~~ (확정: 타 조와 공유 없이 전 기간 전용), DSR 드라이버로 **Real 모드 기동 확인**(Jazzy에서 Real 기동이 가상 모드로 떨어지는 이슈 #340 보고됨 — 판정 기준은 "접속"이 아니라 "Real 모드로 실물이 움직임")
* [A] 기존 Isaac Sim 자산을 프로젝트 `sim_assets/`로 복사, 손목 RealSense 토픽 동작 확인
* [C] Git 저장소 생성, 디렉터리 구조(`docker/`, `schema/`, `tasks/`, `knowledge/`, `config/`, `ros2_ws/`) 확정
* [D] 결정 로그·회의록 문서 개설, 음성 평가 문장 작성 시작 (마감 Day 6)

| 일차 | 날짜 | 단계 | 세부 작업 (담당) | 완료 기준 |
| :--- | :--- | :--- | :--- | :--- |
| **Day 1** | 10/03 (토) | **환경 · 계약 · 작업 공간** | [B] `ros2-core` 실물 백엔드 골격: DSR 드라이버 컨테이너 → 실물 M0609 접속, RG2 제어 확인<br>[A] `realsense`·`vision` 컨테이너, 호스트 ROS 2로 Isaac Sim Bridge(CycloneDDS) 확인<br>[C] compose 골격·프로파일, **ICD(5장)·스키마(7장) 확정**, **[C·E, B 검토] 로봇 온톨로지 구조(스킬·상태·세계, 7.5) 확정**, Runner 착수, PC1↔PC2 `multi` 통신 검증<br>[E] 서랍장 조립·손잡이 보강·작업대 고정, 트레이 배치, 물품 구매<br>[D] 음성 평가 문장 작성 | 컨테이너에서 **Real 모드로** 실물 로봇·그리퍼 제어, 손목 카메라 토픽 수신, ICD·스키마 커밋 |
| **Day 2** | 10/04 (일) | **작업 공간 확정 · 캘리브레이션** | [B·E] 기준 포즈 직접교시(`home`, 서랍별 `drawer_approach`·`drawer_top_view`, `tray_view`), TCP 3점 터치로 서랍 좌표계 측정<br>[A·B] 핸드-아이 캘리브레이션(로봇 슬롯), [A] 실측 치수로 트윈 씬 T1 착수<br>[B·E] 물품별 RG2 파지 테스트 → **물품 목록 확정**<br>[C] Runner 핵심(블랙보드·`$ref`·문자열 보간) + mock 백엔드 + 상태 저장소(경로 읽기·쓰기)<br>[B·E] 포즈 교시하며 모션 스킬의 조건·결과·에러 초안 작성 | 포즈·서랍 좌표계·캘리브레이션 결과가 `config/`에 커밋, 물품 확정 |
| **Day 3** | 10/05 (월) | **서랍 개폐 · Runner 완성** | [B] `drawer_control` 실물 구현(컴플라이언스 인출, 변위 + 힘 닫힘 판정, 걸림 감지) — 로봇 오후 슬롯<br>[A] 실물 데이터 수집 — 로봇 오전 슬롯, 사전 라벨링<br>[C] `if`/`while`/`for_each`/`push`/`pop`/`finally` + 스키마 검증 + `ExecutionLogger` 완성, **스킬 `pre` 확인·`effect` 반영·`state_diff` 로그**, mock으로 7.3 예시 실행<br>[E] **로봇 온톨로지 데이터 작성(세계·상태·스킬)**, LLM 인텐트·목표 추출 프롬프트 설계(6.4), 라벨링 보정 지원(반나절)<br>[D] 실험 기록 양식(측정 항목별 시트) 작성 | 실물 서랍 열기/닫기 JSON 단독 실행, mock에서 `find_with_unpack` 로그 생성 |
| **Day 4** | 10/06 (화) | **파지 · 학습 · 음성** | [B] `pick_object`·`place_object` 실물(트레이 슬롯, `grasp_ok` 판정, `TRAY_FULL`)<br>[A] YOLO 학습(PC1), 트윈 T2 미러링<br>[C] Skill 액션 인터페이스 ↔ B 백엔드 연결, **BFS 플래너(7.7) 착수**, `db` 컨테이너 + 로거 DB 저장<br>[E] `voice` 컨테이너(웨이크워드 → STT → `/voice/intent`), `OntologyManager`, LLM 인텐트 파서 1차<br>[D] 음성 평가 문장 녹음 | 단일 물품 Pick & Place JSON 실물 실행 |
| **Day 5** | 10/07 (수) | **1차 점검** | [A] `inspect_region` V2(YOLO + 뎁스 → 서랍 좌표, `top_z` 정렬)<br>[C] mock으로 "코드 수정 0줄" 신규 JSON 사전 시연 + **플래너로 "지갑 아래 서랍에 넣어줘" 계획 생성·mock 실행**<br>**[전원, 오후 통합 슬롯] 1차 점검 (진행·판정: E)**: 실물에서 JSON만으로 서랍 열기 → 인식 → Pick → 트레이 → 원위치 → 닫기 + 로그. 트윈 T2가 되면 실물 미러링 동시 확인 | 1차 점검 통과 / 트윈 중단 기준 판정 |
| **Day 6** | 10/08 (목) | **인식 고도화 · 예외 처리** | [A] V3 미지 물체·ID 추적, 트윈 T3 사전 검증 모드<br>[B] `on_failure`(retry/safe_home), E-stop, 작업 영역 제한, `DRAWER_STUCK`<br>[C] 플래너 완성(계획 불가 설명, 실패 시 1회 재계획), 인텐트 → 스킬/계획 라우팅, 번들 템플릿 `find_group_by_drawer`<br>[E] LLM 인텐트·목표 검증 로직 + 규칙 폴백, 상태 질의 응답(`query_state`), TTS, 확인 응답·재질문<br>[D] 음성 평가 문장 세트 마감 | 실물 서랍에서 겹친 물체의 가림 순서 반환 |
| **Day 7** | 10/09 (금) | **반복 시험 · 음성 통합** | [A] 비전 정확도 측정·튜닝(조명·겹침)<br>[B] 서랍 개폐 20회·파지 반복 시험<br>[C·E] 음성 → 인텐트 → 플래너 → Runner 엔드투엔드(mock → 실물)<br>[D] 측정 결과 기록 | "출근 준비물 찾아줘" 음성 → 서랍별 계획 → 확인 TTS |
| **Day 8** | 10/10 (토) | **시나리오 1 실물 통합 (음성)** | **[전원, 통합 슬롯]** 음성 → 온톨로지 → 서랍 열기 → 바로 보일 때 Pick → 전달 트레이 → 음성 보고 | **음성으로** 실물 시나리오 1 엔드투엔드 성공 = **시연 L1**(17.7) |
| **Day 9** | 10/11 (일) | **오클루전 탐색 (Unpacking)** | 오전: [A] 트윈 사전 검증 / 오후: **[전원, 통합 슬롯]** 실물 Unpacking(장애물 순차 파지 → 트레이 → 재촬영), 미발견 TTS<br>[D] 배치 무작위화 10회 결과 기록 | 실물에서 장애물 2개를 꺼내 가려진 물건 발견 |
| **Day 10** | 10/12 (월) | **복구 (Rollback) · 2차 점검** | **[A·B·C]** `finally` 기반 역순 복원(서랍 로컬 좌표, z 재보정), 중간 실패 시 복구 검증<br>**[B·C·E]** 2막 2-1·2-2(플래너 조합 명령) 실물 실행<br>**2차 핵심 점검 (진행·판정: E)** | 성공·실패 양쪽에서 원위치 복구 + 서랍 닫힘, 오차 2cm 이내 = **시연 L2** |
| **Day 11** | 10/13 (화) | **[챌린지] 미정의 행동 조합** | [C·E] 신규 스킬 JSON 2종 이상 추가(**시연 2막 `return_items` "정리해줘"** 필수 + 1종) → mock/트윈 사전 검증 → 실물 실행, 2막 전체(플래너 명령 + 상태 질의 + 정리해줘) 실물 통합<br>**3차 챌린지 점검 (진행·판정: E)**<br>(Stretch, 3차 점검 통과 시) [C·E] LLM 태스크 JSON 생성(6.5) 착수 | **Python 코드 수정 0줄**(Git diff) + 실물 로그 비교표, 1막 전체 1회 성공 |
| **Day 12** | 10/14 (수) | **시연 리허설 · 예비일** | **[전원] 17장 시나리오 리허설 반복 → 시연 레벨 결정(판정: E)**, [D] 리셋 체크리스트 검증. 실패 주입 테스트(파지 실패·`TRAY_FULL`·`DRAWER_STUCK`·E-stop), 음성 취소, 연속 구동 스트레스 테스트, 밀린 작업 해소. (Stretch 진행 시) LLM 생성 JSON 트윈 사전 검증 → 실물 실행 | 선택 레벨 3회 연속 성공, 실패 시 비정상 종료 없이 안전 상태 |
| **Day 13** | 10/15 (목) | **시연 녹화** | [전원] **17장 시나리오(선택 레벨)** 실물 음성 시연 녹화(당일 백업 영상 겸용), 트윈 화면 병렬 녹화, 실패 주입 보조 영상<br>[C] 지표 정리, [E] 발표 자료 총괄(D 초안 기반) | 데모 영상, 발표 슬라이드 |
| **Day 14** | 10/16 (금) | **최종 점검 · 제출** | [C·E] README 최종본(D 초안 기반: 장비별 `docker compose` 실행법, JSON 작성법, 아키텍처), **클린 환경 재구축 검증**<br>[전원] 챌린지 증빙 첨부, 최종 리허설, [E] 제출 | 최종 릴리즈 및 제출 |

> 시연 영상은 Day 13까지 미루지 않고 Day 8·9·10 통합 성공 시마다 **중간 녹화**해 둠.

### 핵심 체크포인트
* **1차 중간 점검 (10/07, Day 5)**: 실물 로봇이 JSON만으로 서랍을 열고 물건을 집어 옮긴 뒤 원위치·닫기까지 하고 로그를 남기는가? (트윈 진행 여부도 이때 판정)
* **2차 핵심 점검 (10/12, Day 10)**: **음성 명령으로** 실물 서랍을 열고 장애물을 치우며 찾은 뒤, 성공·실패와 무관하게 원래대로 되돌려 놓는가?
* **3차 챌린지 점검 (10/13, Day 11)**: 코드 수정 없이 새로운 JSON 파일만으로 실물 로봇이 완전히 다른 동작을 수행하고 그 이력이 기록되는가?

---

## 14. 성공 지표 (정량 기준)

| 항목 | 목표 | 측정 방법 (담당) |
| :--- | :--- | :--- |
| 재현성 | 클린 환경에서 장비별 `docker compose --profile` 명령만으로 팀 소프트웨어 전체 기동 | Day 14 재구축 테스트 (C·E) |
| 음성 인텐트 정확도 | 40문장·화자 2명 이상 **90% 이상** (자유 표현 문장 10개 포함) | 인텐트 결과 vs 정답, LLM 경로·규칙 폴백 각각 측정 (E, 기록 D) |
| LLM 출력 검증 실패율 | **5% 이하** (실패 시 폴백으로 처리되어 실행 오류 0건) | 인텐트 로그의 검증 결과 (E) |
| 음성 응답 지연 | 발화 종료 → 확인 TTS 시작 **3초 이내** | 타임스탬프 로그 (E) |
| 서랍 개폐 성공률 | 실물 **90% 이상** | 반복 20회 (B, 기록 D) |
| 비전 정확도 | 실측 대비 3D 위치 오차 **1.5cm 이내**, 가림 순서 정확도 90% 이상 | 격자 시트·자 실측 비교 (A) |
| 오클루전 탐색 성공률 | 목표물이 있을 때 발견 **80% 이상**, **평균 제거 횟수**와 실패 유형(파지 불가 위치·목표 건드림·시간 초과) 함께 보고 | 실물 배치 무작위화 10회 (A·C, 기록 D) |
| 복구 위치 오차 | 원위치 대비 위치 **2cm 이내**, 요(yaw) 오차 함께 보고 | 서랍 바닥 격자 시트 기준 전후 비교 (C, 기록 D) |
| 실패 후 안전 복귀 | 실패 주입 시 `finally` 복구 + 서랍 닫힘 **100%** | 실패 주입 10회 (B·C) |
| 단일 물품 E2E 시간 | 장애물 없을 때 발화 → 전달 **120초 이내** (협동 모드 속도 기준) | 실행 로그 (C) |
| 명령 조합 (플래너) | 목표형 명령 **5종 이상**에서 계획 자동 생성 + 실물 성공 (이미 만족·계획 불가 응답 포함) | 계획 로그 + 실행 로그 (C·E) |
| 상태 추적 정확도 | 실행 후 온톨로지 상태(그리퍼·서랍·물품 위치)와 실제 일치 **100%** (불일치는 `STATE_MISMATCH`로 감지·수정) | 실행 후 실물 확인 vs `/robot_state` (C, 기록 D) |
| 로그 완전성 | 모든 스텝에 성공 여부·소요 시간·`pre_check`·`state_diff` 기록 **100%**, DB 저장 누락 0건 | 로그 검증 스크립트 (C) |
| 최종 시연 리허설 | 17장 시나리오 **L3 기준 3회 연속 성공** (최소 L2) | Day 12 리허설 기록 (E, 기록 D) |
| 미정의 시나리오 | **코드 수정 0줄**로 2종 이상 실물 성공 | Git diff + 실행 로그 (C) |
| (Stretch) LLM 생성 태스크 | 자연어 요청 3건 이상에서 스키마 검증·트윈 사전 검증 통과 후 실물 성공 | 생성 JSON + 실행 로그 (C·E) |
| 트윈 사전 검증 효과 (트윈 진행 시) | **트윈이 실물 투입 전에 걸러낸 문제 수**(도달성·충돌·관절 한계·순서 오류) + 실물 미러링 시 명령 대비 관절 편차 | 사전 검증 로그·미러링 로그 (A) |

---

## 15. 리스크 및 대응

| 리스크 | 영향 | 대응 |
| :--- | :--- | :--- |
| 서랍장 구매·조립 지연 | 실물 핵심 경로 전체 지연 | Day 0 구매(오프라인 매장 우선), 미도착 시 임시로 상자형 서랍 대체 |
| 가벼운 서랍장이 당길 때 끌려오거나 넘어짐 | 개폐 실패, 교시 포즈 무효 | 작업대 고정(클램프·볼트), 무게 추가, 컴플라이언스 인출 |
| 플라스틱 레일 걸림 | 개폐 성공률 저하 | 인출 축 정렬, 컴플라이언스 제어, 힘 기준 걸림 감지(`DRAWER_STUCK`) |
| 손잡이 파지 불가 (홈형 손잡이) | `drawer_control` 불가 | 구매 기준에 돌출 손잡이 포함, 없으면 막대 손잡이 부착 |
| 반투명·반사 재질로 뎁스 결손 | 3D 위치·가림 순서 오류 | 무광·불투명 서랍장, 물품 선정 기준, 조명 고정 |
| 실물 로봇 사용 시간 부족 | 통합·시험 지연 | **리스크 하향**: 로봇을 타 조와 공유하지 않고 전 기간 전용으로 사용(10/02 확정). 팀 내부 시간표(B 우선, A 데이터 수집, 통합 슬롯)만 운영 |
| 핸드-아이 캘리브레이션 오차 | 파지 위치 오차 | 강의 튜토리얼 절차 준수, 검증 스크립트(`verify.py`)로 오차 기록, 필요 시 재수행 |
| 얇은·작은 물품 파지 실패 | 탐색·복구 실패 | 높이 1.5cm 미만 물품 제외(그리퍼 개조 없음), 차키는 두꺼운 키홀더 부분 파지, Day 2 파지 테스트로 목록 확정 |
| 실물 데이터 라벨링 부담 | 비전 지연 → 통합 지연 | 사전 라벨링 도구(YOLO-World·SAM2)로 보정만 수행, E 지원, 클래스 수 최소화 |
| A의 업무 과부하 (비전 + 트윈) | 비전 지연 | 비전 우선 원칙, 트윈 30% 상한, Day 5 트윈 중단 기준 |
| 다중 PC DDS 통신 불안정 | 트윈 미러링·음성 연동 끊김 | 팀 전용 공유기, 강사 CycloneDDS + `multi` 설정, 전 PC sysctl, 방화벽 설정 |
| RealSense `MIPI error`·케이블 당김 | 인식 불가 | USB 3.0 직결·정품 케이블, 팔 동작 시 케이블 고정 |
| 컨테이너 내 마이크 접근 실패 | 필수 기능 불가 | Day 4 이전 PoC, PulseAudio 소켓 마운트 |
| OpenAI API 장애·네트워크 단절 | STT·LLM 파싱 불가 | STT는 faster-whisper CPU 폴백, 인텐트는 규칙·별칭 폴백 |
| LLM 오출력(없는 물품·형식 오류) | 잘못된 탐색 실행 | 온톨로지 키로 출력 제한, JSON 형식 강제, 코드 검증 후 실패 시 폴백·재질문, temperature 0 |
| 조장(E) 업무 과부하 (통합 지휘 + 하드웨어 + 음성·LLM + 온톨로지) | 통합 의사결정·음성 지연 | 통합 실무는 모듈 담당이 공동 수행, 로봇 시간표는 B 작성, 온톨로지 조회 인터페이스는 C가 구현, 조립은 B와 공동, 기록은 D, 강의 코드 재사용으로 음성 구현량 축소 |
| 플래너·상태 추적 구현 지연 | 챌린지 핵심 미달 | 스킬 4종(열기·닫기·집기·놓기)으로 시작, BFS는 수십 줄 규모(프로토타입으로 예시 계획 생성 확인), Day 5 mock 시연으로 조기 검증 |
| 모델 상태와 실제 불일치 (사람 개입·파지 실패 등) | 잘못된 계획 | 관측 우선 규칙(7.8), 스텝 실패 시 재관측 후 1회 재계획, 시연 전 상태 스냅샷 복원 |
| 스킬 조건 정의 오류 | 불가능한 계획 또는 계획 불가 | B가 모션 스킬 조건 검토, mock에서 명령 세트 자동 테스트 |
| Doosan Jazzy 드라이버가 Real 모드로 기동되지 않음 (이슈 #340) | 실물 경로 전체 지연 | Day 0~1 판정 기준을 "Real 모드로 실물이 움직임"으로, 문제 시 즉시 강사·조교 문의, 강의 bringup 설정과 비교 |
| 서랍 닫힘 오판 (힘만으로 판정 시 걸림을 닫힘으로 인식) | 서랍 열린 채 다음 동작 → 충돌 | 변위 + 미는 축 힘 동시 판정(8.4), `CLOSE_NOT_CONFIRMED` 시 재시도 후 정지 |
| 손잡이 미끄러짐·핸들 인식 실패 (선행 연구 실패 원인 1위) | 서랍 열기 실패 | 돌출 손잡이·교시 포즈 고정, 파지 후 그리퍼 폭 확인, 컴플라이언스 인출 |
| DB 장애 | 로그 유실·시연 중단 | `LogStore` JSONL 폴백, 시연 전 DB 상태 점검 |
| 선행 프로젝트와의 유사성 (같은 스택의 GitHub 프로젝트 존재) | 차별점 약화 | 1.3의 차별점(조건에서 순서 도출, 조건·상태 로그)을 발표에서 명시적으로 비교 |
| 일정 지연 | 마감 불이행 | Day 12 예비일. 우선순위: 음성 + 실물 시나리오 1 > Unpacking + Rollback > 챌린지 > 트윈 |

---

## 16. 팀 합의 항목 (결정 로그)

결정이 나면 상태를 `확정`으로 바꾸고 결정 내용을 기록함. 기한이 지난 `미결` 항목은 그날 스탠드업 첫 안건으로 처리함.

| # | 항목 | 상태 | 현재안 / 결정 내용 | 결정 기한 | 결정 담당 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 로봇 기종 | **확정** | Doosan M0609 + OnRobot RG2 | - | 전원 |
| 2 | Docker · 음성 필수 여부 | **확정** | 둘 다 필수 (과목 요건). 텍스트 입력은 디버깅 전용 | - | 전원 |
| 3 | 최종 시연 플랫폼 | **확정** | **실물 M0609 + 실물 플라스틱 서랍장**. Isaac Sim은 디지털 트윈·사전 검증 보조 | - | 전원 |
| 4 | 담당 배정 | **확정** | A = 김병직(비전 + 트윈), B = 서동권(실물 로봇 모션), C = 이영훈(프레임워크·기술 통합), D = 김민준(지원), E = 고희태(조장·통합 지휘·음성·LLM·온톨로지). 통합 실무는 모듈 담당 공동 수행 | - | 전원 |
| 5 | RMW · Domain | **확정** | 강사 제공 CycloneDDS, `ROS_DOMAIN_ID=70` (10/02 전 팀원 호스트·Docker 일치 확인) | - | 전원 |
| 6 | Isaac Sim | **확정** | 5.1.0, **네이티브 실행(Docker 제외, 팀 선택 도구)**, 팀 로직은 컨테이너에 둠. GUI 기본 | - | A |
| 7 | 서랍장 구매 | 미결 (구매 전, 10/02 기준) | 2.2 기준(불투명·무광, 돌출 손잡이, 스토퍼, 2~3단)으로 구매. **배송 대기 없이 오프라인 매장 구매 우선** — Day 1 조립·고정, Day 2 포즈 교시의 선행 조건 | 10/02 | E |
| 8 | 실물 로봇 사용 시간 | **확정** | 타 조와 공유하지 않고 **전 기간 전용 사용**. 팀 내부 시간표(B 우선, A의 데이터 수집·캘리브레이션 슬롯, 통합 슬롯)만 B가 작성 | - | B |
| 9 | 시연 장비 구성 | **확정** | PC2 = 서동권 노트북(RTX 4060, 로봇 옆, `real`, 비전 GPU 추론), PC1 = 김병직 노트북(RTX 5060, 트윈). PC2도 Isaac Sim 실행 가능 → 사전 검증 보조·트윈 예비 장비 | - | B · A |
| 10 | STT 엔진 · LLM 모델 | 미결 | STT 1순위 OpenAI `whisper-1` / 폴백 faster-whisper CPU. LLM은 강의 코드의 GPT 모델 기준. API 키·비용·시연장 인터넷 확인 필요 | Day 3 (10/05) | E |
| 11 | 물품 목록 | 미결 | 2.3 기준 후보를 Day 2 실물 파지 테스트로 확정, 온톨로지 반영. **높이 1.5cm 미만 제외, 손끝 인서트 미사용(확정)** | Day 2 (10/04) | B · E |
| 12 | 비전 모델 | **확정(조건부)** | `Fruits/best.pt` 미사용. 실물 데이터로 학습, 합성 데이터는 보강용 | Day 4 (10/06) 학습 착수 | A |
| 13 | 새 시나리오 생성 주체 | **확정** | 사람이 작성한 JSON 템플릿을 플래너가 선택·바인딩. LLM 자동 생성은 Stretch(Day 11 3차 점검 통과 시 착수, 6.5) | - | 전원 |
| 14 | 평가 기준 확인 | 미결 | 보고서 양식 등 필수 산출물 요구 여부, LLM 활용 평가 비중 확인 | Day 1 (10/03) | E |
| 15 | LLM 역할 | **확정** | 인텐트 파싱의 **주 경로**(강의 LangChain 방식), 규칙·별칭 매칭은 폴백. 모델·API 키는 STT와 함께 #10에서 결정 | - | E |
| 16 | 최종 시연 시나리오 | **확정** (10/02 팀 합의) | 17장 "출근 준비 도우미" (1막 출근 준비물 찾기 + 2막 명령 조합). 물품·배치는 #11 물품 확정 후 조정 | - | 전원 (판정 E) |
| 17 | 로봇 온톨로지 구조 | **확정** | 강사 챌린지 해석: 로봇의 동작(스킬 조건·결과)·상태·세계를 하나의 JSON-LD 온톨로지로 정의, 플래너가 명령 목표에서 스킬 조합 생성(7장). 조건은 `{subject, predicate, op, value}` 레코드 + `hold`·`verify`, 원천은 JSON-LD·PDDL은 내보내기만(선행 사례 SkiROS2와 같은 구조). 세부 스키마는 Day 1 확정 | Day 1 (10/03) 세부 확정 | C·E (B 검토) |
| 18 | 데이터베이스 | **확정** | **MongoDB 8.0** 컨테이너(JSON 로그를 그대로 저장). Jazzy용 ROS MongoDB 도구가 없으므로 pymongo로 직접 쓰고 JSONL 폴백. 선행 사례: KnowRob NEEM 로그도 MongoDB 사용 | - | C |
| 19 | 실행 프레임워크 | **확정** | **자체 JSON Runner 유지**(BehaviorTree.CPP·py_trees·PlanSys2 미채택). 근거: C++ 부담, run-always `finally`·조건별 로그 미지원. BT의 `timeout`·`fallback`·`recovery`·`on_halt` 의미만 차용(7.1) | - | C |
| 20 | SAM2 활용 범위 | 미결 (제안) | **과목 필수 아님(선택 사항, 10/02 확인)**. 비전 보조 도구로 한정: ① 데이터셋 라벨링 보조 우선 도입, ② 미지 물체 분할은 Day 6 정확도 미달 시에만 도입, ③ 영상 트래킹은 미사용(요청 시 1프레임 촬영 구조라 이점이 적고 서랍 좌표 매칭이 더 단순). YOLO를 대체하지 않으며 일정 추가 없이 진행. GPU(#9)·PyTorch 호환은 사용 전 확인 | Day 3 (10/05, 라벨링 시작 전) | A |

---

## 17. 최종 시연 시나리오 (팀 공동 목표) — 확정 (10/02 팀 합의)

> 모든 담당의 작업은 이 시나리오를 실물에서 성공시키는 것을 기준으로 우선순위를 정함. 시나리오에 쓰이지 않는 기능은 후순위.

### 17.1 스토리: "출근 준비 도우미"

아침에 출근 준비를 하는 사용자가 말로 부탁하면, 로봇이 서랍장을 뒤져 준비물을 꺼내 주고 뒤진 서랍은 원래대로 정리해 둔다(1막). 이어서 사용자가 여러 가지 짧은 명령을 내리면, 로봇은 **자기 동작·상태 온톨로지를 조합해** 그때그때 행동을 만들어 낸다(2막). 모든 동작과 성공 여부, 상태 변화는 로그로 남는다.

**강사 챌린지와의 대응**

| 챌린지 요구 | 시연에서 보여주는 장면 | 관련 장 |
| :--- | :--- | :--- |
| 로봇의 움직임·상태를 JSON(온톨로지)으로 | 화면의 **로봇 온톨로지 실시간 상태**(그리퍼·서랍·물품 위치)가 동작마다 바뀜 | 7.5, 7.8 |
| 명령을 내리면 그 조합으로 다양한 행동 | 2막: 명령마다 **플래너가 스킬 조합을 생성**해 화면에 먼저 보여주고 실행 (순서는 조건에서 도출) | 7.7 |
| 세부 동작과 성공 여부 로그 | 마무리: DB에 쌓인 로그에서 스텝별 성공/실패·재시도·전후 상태 조회 | 7.4 |

**그 밖의 시연 포인트**

| 시연 포인트 | 보여주는 기능 | 관련 장 |
| :--- | :--- | :--- |
| 자유로운 말로 요청 | 음성(필수) + LLM 인텐트·목표 추출 | 6장 |
| 가려진 시계 찾기 | 오클루전 Unpacking | 8.2 |
| 뒤진 서랍 원상 복구 | LIFO Rollback, `finally` | 8.3 |
| 기록이 틀린 차키 | 관측 우선 상태 수정(`STATE_MISMATCH`) | 7.8 |
| 명령한 장소로 옮기기 | 과목 최종 결과물 요건("명령한 장소로 이동") | 7.7 |
| 새 작업 "정리해줘" | 스킬 파일 추가만으로 기능 확장(코드 수정 0줄) | 7.6 |
| 옆 화면의 트윈 | Isaac Sim 실물 미러링 + 사전 검증 | 10장 |

### 17.2 초기 배치 (매 회 동일하게 리셋)

| 위치 | 실제 배치 | 온톨로지 `state.located_in` (시연 시작 시점) |
| :--- | :--- | :--- |
| 아래 서랍 (`drawer_bottom`) | 지갑(위에 보임) + 장애물 O1(아래에 아무것도 없음) | 차키, 지갑 |
| 위 서랍 (`drawer_top`) | **차키(위에 보임, 기록과 다름)** + **시계 위를 장애물 O2가 덮음** | 시계 |
| 임시 트레이 | 비어 있음 (슬롯 3개) | - |
| 전달 트레이 | 비어 있음 (슬롯 3개) | - |

* 서랍 바닥에 테이프로 물품 위치를 표시하고 배치 사진을 붙여 둠 → 리셋 체크리스트(담당 D).
* 온톨로지 상태는 시연 시작 전 초기 스냅샷으로 복원.

### 17.3 1막: 출근 준비물 찾기 (약 5~6분)

| # | 사용자 / 로봇 | 시스템 동작 | 보여줄 것 | 담당 |
| :--- | :--- | :--- | :--- | :--- |
| 1-1 | 사용자: "헬로 로키" → **"나 이제 출근하려는데 챙길 거 좀 찾아줘"** | 웨이크워드 → STT → LLM이 `find_list(commute_set)`로 해석(별칭에 없는 표현) | 화면: STT 텍스트, LLM 결과 JSON | E |
| 1-2 | TTS: "출근 준비물 차키, 지갑, 시계를 찾겠습니다. 아래 서랍부터 볼게요." (템플릿 `{{list.items_ko\|목록\|을}} 찾겠습니다`, 조사 자동 선택) | 온톨로지 조회 → 서랍별 묶음 `[drawer_bottom: 차키·지갑] [drawer_top: 시계]` | 화면: 계획된 서랍 순서 | E·C |
| 1-3 | 아래 서랍 열기 → 스캔 | `open_drawer` 스킬(조건 확인 → 실행 → 상태 `open.drawer_bottom = true`) | 실물 + 트윈 + **상태 패널** | B·A·C |
| 1-4 | 지갑을 집어 전달 트레이로 | `pick`·`place` | 상태: 그리퍼 → 지갑 → 비어 있음 | B·A |
| 1-5 | 차키가 안 보임 → O1을 임시 트레이로 치우고 재스캔 → 없음 | Unpacking 루프 → 완전 부재 판정 | O1이 임시 트레이로 옮겨지고 재스캔 결과 "차키 없음" 판정 | A·B·C |
| 1-6 | TTS: "아래 서랍에는 차키가 없네요." O1을 원위치에 되돌리고 서랍 닫기 | `finally` Rollback → `close_drawer` | 복구 위치 | B·C |
| 1-7 | 위 서랍 열기 → 스캔 | **차키 관측** → 상태 `located_in.car_key: drawer_bottom → drawer_top` (`STATE_MISMATCH` 기록) | 상태 패널에서 차키 위치가 바뀌는 장면 | A·C·E |
| 1-8 | TTS: "차키가 위 서랍에 있었네요. 위치 정보를 고쳐 둘게요." 차키를 전달 트레이로 | 남은 목표가 다른 서랍에서 발견되면 함께 처리 | 남은 목표 목록에서 차키가 지워지고 전달 트레이에 2개 | B·C·E |
| 1-9 | 시계가 안 보임 → O2를 치우고 재스캔 → 시계 발견 → 전달 트레이로 | Unpacking → 발견 | **가려진 물건 찾기 (핵심 장면)** | A·B |
| 1-10 | O2를 원위치로 되돌리고 서랍 닫기, 홈 복귀 | `finally` Rollback | O2가 원래 자리로 돌아간 모습(LIFO 역순 복구), 서랍 닫힘, 홈 포즈 | B·C |
| 1-11 | TTS: "차키, 지갑, 시계 모두 찾았습니다. 앞쪽 트레이에서 가져가세요." | | 전달 트레이에 3개 | E |

### 17.4 2막: 명령 조합 (약 3~4분, 강사 챌린지 핵심)

각 명령마다 **플래너가 만든 스킬 조합을 화면에 먼저 띄운 뒤** 실행함. 어떤 명령도 미리 짜 둔 시퀀스가 아님.

| # | 사용자 명령 | 플래너 결과 (화면 표시) | 보여주는 것 | 담당 |
| :--- | :--- | :--- | :--- | :--- |
| 2-1 | **"지갑은 아래 서랍에 넣어 둬"** | `open_drawer(아래)` → `pick(지갑, 전달 트레이)` → `place(지갑, 아래)` → `close_drawer(아래)` | **"서랍을 먼저 열어야 지갑을 넣을 수 있고, 지갑을 들고는 서랍을 못 연다"는 순서가 조건에서 도출됨**. TTS로 계획을 말하고 "진행할까요?" → 사용자 "응" 후 실행(안전 게이트 4단계). 과목 요건 "명령한 장소로 이동" 충족 | C·E·B |
| 2-2 | **"아래 서랍 닫아줘"** | 계획 길이 0 | TTS: "이미 닫혀 있습니다" — 상태를 근거로 판단 | C·E |
| 2-3 | **"지금 뭐 들고 있어?" / "위 서랍 열려 있어?"** | 상태 질의 | TTS: "아무것도 들고 있지 않습니다" / "위 서랍은 닫혀 있습니다" | E |
| 2-4 | 발표자가 `tasks/return_items.json` 1개 추가 → **"나머지도 다시 서랍에 정리해줘"** | 새 `composite` 스킬이 음성 트리거와 함께 자동 등록되어 실행 | **Git diff: Python 코드 0줄**. 트윈 사전 검증 통과 영상(10초) 후 실물 실행. **차키는 1막에서 고친 위치(위 서랍)로 반납** | C·E·A |
| 2-5 | TTS: "정리를 마쳤습니다." | | 장면이 초기 상태에 가깝게 복원(리셋 단축) | E |

### 17.5 마무리 (약 1분)
* **DB 로그 조회**: 이번 시연의 실행 수, 스텝별 성공/실패, 재시도, `STATE_MISMATCH` 1건(차키), 각 스텝 전후 상태 변화.
* 로봇 온톨로지 파일 화면과 지식 그래프(7.9): 스킬 정의(조건·결과) → "이 정의를 조합해서 방금의 행동들이 나왔다".
* (선택) 실패 주입 영상: 파지 실패 시 재계획·`finally` 복구 장면(사전 녹화, 담당 B·C).

### 17.6 (보너스) 3막: LLM이 만든 작업 — Stretch 완료 시에만
* "귀중품만 따로 꺼내서 앞에 놔줘"처럼 목표 하나로 표현하기 어려운 요청 → LLM이 태스크 JSON 생성 → 스키마 검증 → 트윈 사전 검증 → 실물 실행(6.5).

### 17.7 시연 레벨과 체크포인트
일정이 밀리면 아래 레벨 중 **리허설에서 3회 연속 성공한 가장 높은 레벨**로 시연함. 레벨 결정은 Day 12에 E가 판정.

| 레벨 | 범위 | 목표 시점 |
| :--- | :--- | :--- |
| **L1** | 음성 "시계 찾아줘" → 위 서랍, 바로 보이는 시계 → 전달 트레이 → 닫기, **상태 패널·스텝 로그 표시** | Day 8 |
| **L2** | L1 + 가려진 시계 Unpacking + Rollback (서랍 1개) + **2막 2-1·2-2(플래너 조합)** | Day 10 (2차 점검) |
| **L3** | 1막 전체(서랍 2개, 리스트, 상태 수정) + 2막 전체 | Day 11~12 |
| 보너스 | L3 + 3막(LLM 생성 작업) | Stretch |

> 플래너 조합(2막)은 강사 챌린지의 핵심이므로 L2부터 포함함. 1막의 규모를 줄이더라도 2-1·2-2는 유지.

### 17.8 시연을 위해 필요한 기능 (각 장에 반영)
| 기능 | 내용 | 담당 |
| :--- | :--- | :--- |
| 로봇 온톨로지 | 스킬(조건·결과·전개)·상태·세계 정의, 실측·파지 테스트 결과 반영 | E (스킬 조건은 B 검토) |
| 상태 추적 + 조건 확인 | Runner의 `pre` 확인·`effect` 반영·관측 우선 수정, `/robot_state` 발행 | C |
| 플래너 | 목표 → BFS 스킬 조합, 계획 불가 설명, 재계획 | C |
| LLM 목표 추출 | 명령 → `{intent, goal}` (6.4), 상태 질의 응답 | E |
| 다른 서랍에서 발견된 남은 목표 처리 | `find_group_by_drawer`가 남은 목표 목록 유지 | C |
| 로그·상태 DB | 스텝 로그·전후 상태·온톨로지 상태를 DB에 저장, 조회 스크립트 | C |
| 전달 트레이 인식 | `inspect_region`의 `region`에 `handover_zone` 추가 | A |
| 서랍 반납 슬롯 | 서랍마다 비워 둔 반납 위치(`return_slot`) | B·E |
| 시연 화면 | 실물 카메라 · 트윈 · 상태 패널 · 계획/현재 스텝 · STT·LLM 결과를 한 화면에 (없으면 터미널 출력으로 대체) | D (C 검토) |

### 17.9 시연 당일 리스크와 대비
| 상황 | 대비 |
| :--- | :--- |
| 시연장 인터넷 불안정 (STT·LLM API) | API 3~5초 초과·오류 시 faster-whisper + 규칙 파서로 **자동 전환**. 2막 명령은 규칙 파서로도 목표 추출이 되는 문형("지갑 아래 서랍에 넣어줘")으로 예비 대사 준비 |
| 웨이크워드 오작동 | Push-to-talk로 전환 |
| 파지 실패 | `retry`, 재계획, `finally` 복구가 설계에 포함됨 → 실패해도 복구 장면을 설명하며 진행 |
| 전체 실패 | Day 13 녹화한 전체 시연 영상으로 대체 |
| 리셋 지연 | 2막이 대부분 원상 복구, 나머지는 리셋 체크리스트(배치 사진·테이프 표시)로 2분 이내 |
