# 시스템 아키텍처 · 기술 스택

> 관련 요구사항: [NFR-ABS-01](requirements.md#nfr-abs-01), [NFR-ENV-01](requirements.md#nfr-env-01), [FR-COM-01](requirements.md#fr-com-01). 기술 상세와 구현 경계는 이 문서에서 다룹니다.

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

[/runner/status · /robot_state] → 단일 rclpy 웹 브리지 → 잠금 캐시 → Flask 상태 REST
[knowledge manifest · tasks/] → 공통 ontology.load · 시작 시 파일 스냅샷 → Flask 정의 REST
                                                                    ↓
                                                        PC·모바일 읽기 전용 UI
```

[코드: 이슈 #267 1~5단계] 웹은 ROS 상태와 등록 정의를 서로 다른 원본·시점으로 취급한다. `/api/status`는 약 1초마다 최신 캐시를 조회하고, `/api/definitions`는 Flask 시작 때 읽은 `web_file_snapshot`을 페이지 시작 시 한 번 조회한다. 웹의 파일 스냅샷은 Runner 내부 상태 변경이나 hot reload를 뜻하지 않으며 상세 실행·오류 형식은 [web README](../web/README.md)를 참조한다.

### 3.1 백엔드별 구성

| 구성 요소 | `real` (최종 시연) | `sim` (사전 검증) | `mock` (개발) |
| :--- | :--- | :--- | :--- |
| 로봇 모션 | DSR 드라이버 → **실물 M0609** | 같은 DSR 드라이버 → `dsr-emulator`, Isaac Sim이 조인트 미러링 | 즉시 성공 반환 |
| 그리퍼 | RG2 (강의 `onrobot.py` 방식) | Isaac Sim `ParallelGripper` (+ attach 폴백) | 즉시 성공 반환 |
| 인식 | 손목 RealSense + YOLO + 뎁스 | Isaac Sim 손목 카메라 + oracle(정답) 또는 YOLO | 미리 정의한 결과 재생 |
| 서랍 | 실물 서랍장 | Isaac Sim Prismatic Joint | 상태 변수 |

* **핵심 설계**: 모션은 real·sim 모두 **같은 DSR 드라이버·같은 스킬 코드**를 사용하고 접속 대상(실물 제어기 / 에뮬레이터)만 바뀜. 사전 검증에서 통과한 JSON은 실물에서도 같은 경로로 실행됨.
* 그리퍼·카메라처럼 에뮬레이터에 없는 부분만 백엔드별로 구현함.

## 12. 기술 스택

| 구분 | 기술 스택 | 세부 용도 |
| :--- | :--- | :--- |
| **Container** | Docker, Docker Compose(프로파일) | 장비·역할별 서비스 구성, 오디오·USB 패스스루 |
| **Robot** | Doosan M0609 + OnRobot RG2, DSR ROS 2 드라이버·DRL(컴플라이언스·힘 제어), DSR 에뮬레이터 | 실물 제어, 사전 검증용 가상 제어기 |
| **Robotics Framework** | ROS 2 Jazzy, CycloneDDS(강사 제공, Domain 70) | 노드 통신, Action Server/Client, 다중 PC 통신 |
| **Action Orchestration** | Python JSON Runner + `jsonschema` | 원자 동작 디스패칭, 변수·조건·반복·finally 해석, 실행 로그 |
| **Vision** | Intel RealSense(손목), YOLO(ultralytics), 뎁스 기반 3D 위치, 핸드-아이 캘리브레이션 | 물품 검출, 가림 순서, 인스턴스 ID 추적 |
| **Robot Ontology · Planner** | Python, JSON-LD, BFS 플래너 | 스킬(조건·결과)·상태·세계 정의, 명령 → 스킬 조합, 상태 추적, 별칭·클래스 추론 |
| **Database** | MongoDB 7.0 (컨테이너, 이슈 #34) + pymongo, JSONL 폴백, rosbag2(MCAP) | 실행 로그·스텝 기록·상태 스냅샷 저장·조회, 원시 토픽 녹화 |
| **Speech · LLM (필수)** | openWakeWord, OpenAI Whisper API / faster-whisper, LangChain + GPT(강의 방식), Piper·espeak-ng | 웨이크워드, STT, LLM 인텐트 파싱, TTS |
| **Digital Twin (팀 선택)** | NVIDIA Isaac Sim 5.1.0 (네이티브), Lula IK·RMPflow(폴백) | 실물 미러링, JSON 사전 검증 |
| **Read-only Web** | Flask, rclpy, HTML/CSS/JavaScript | Runner 상태 polling, 등록 정의 파일 스냅샷, PC·모바일 읽기 전용 표시 |
