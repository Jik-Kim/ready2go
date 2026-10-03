# 변경 이력

> 상위 인덱스: [docs/README.md](README.md)

- **v4.1**: 선행 사례 조사([`docs/research/prior_art_report.md`](research/prior_art_report.md)) 권고 15건 반영 — 조건 레코드 형식·`hold`·`verify`(7.5), 사후 관측 기반 성공 판정(7.4), Runner에 `timeout`·`fallback`·`recovery`·`on_halt` 추가와 BT 대응표(7.1), MongoDB 8.0 확정·JSONL 폴백, 장애물 제거 순서·LIFO 복구·서랍 닫힘 판정 보완(8장), 얇은 물품 제외(2.3), LLM 출력 고정 키 배열·예시 필수(6.4), 트윈 검증 범위·지표 조정(10, 14장), Doosan Real 모드 판정, 실물 안전 게이트 8단계(11장), 선행 사례 대비 차별점(1.3), SAM2 선택 활용(9장). 지식 그래프 초안 그림 추가(7.9). 외부 검토 반영: ICD 호출 방식 명시(5장), 스킬 파라미터명 통일(7.5), 서랍 닫힘 실패 복구(8.4), 한국어 조사 처리(7.1), 시연 표 보완(17.3).
- **v4**: 강사 챌린지에 맞춰 "로봇 온톨로지(동작·상태·세계)" 중심으로 재편 — 스킬의 조건·결과 정의(7.5), 명령 → 스킬 조합 플래너(7.7), 상태 추적(7.8), 로그에 전후 상태 기록 + DB 저장(7.4, 4장), 시연 2막을 "명령 조합"으로 교체(17.4).
- **v3.2**: 최종 시연 시나리오(팀 공동 목표) 추가(17장) — 시연 레벨 L1~L3, 태스크 레지스트리(7.6), 일정·지표를 시나리오 기준으로 정렬.
- **v3.1**: 담당자 실명 반영(A 김병직, B 서동권, C 이영훈, D 김민준, E 고희태), 통합은 조장(E) 지휘 하에 모듈 담당이 공동 수행, LLM 인텐트 파싱을 주 경로로 승격(6.4), LLM 태스크 생성 Stretch 조건 명시(6.5), 온톨로지는 E 담당.
- **v3**: 최종 시연 플랫폼을 실물 M0609 + 실물 서랍장으로 전환(Isaac Sim은 디지털 트윈·사전 검증용 보조 도구로 재정의, 네이티브 실행), 팀 5인 체제 R&R 재편, 실물 작업 공간·서랍장 구매 기준 추가, 비전을 실물 RealSense 중심으로 재편, 일정·지표·리스크 재작성.
- **v2**: 로봇 기종 확정(M0609 + RG2), 다중 노트북 구성·compose 프로파일, 원자 동작 백엔드 추상화, ICD, 스키마 정합성 수정(조건식·변수 문법·`finally`), 안전 요구사항.
- **v1**: 초안 (Docker·음성 필수 요건, JSON 스키마, 14일 일정).
- **v5 (분할)**: 기획서 v4.1을 `docs/` 주제별 문서로 분할하고 JSON 예시를 원본 파일(`contracts/`, `knowledge/`, `tasks/`)로 이동. 저장소 이름 `ready2go`, 패키지 접두어 `ready2go_`.
- **v5.1**: 기능 Phase 구분(P1 최소 · P2 발전 · P3 = 기획서 전체) 추가(당시 phases.md, v5.5에서 requirements.md로 통합·삭제), 각 문서 상단에 Phase 범위 표시, 결정 로그 #21.
- **v5.2**: 비전 이슈(#5·#7·#14·#18) 검토 반영 — ICD 카메라 토픽을 정렬 뎁스(`aligned_depth_to_color`)·컬러 `camera_info`로 수정, 고정 TF는 `ready2go_bringup`이 발행(결정 #22~#24). #5 실측 반영 — realsense는 `-r __ns:=/`를 줘야 `/wrist_cam/...`으로 발행됨(Dockerfile 주석의 [추정] 정정), 컬러·정렬 뎁스 약 30 Hz 확인, 손목 카메라 TF는 `link_6 → wrist_cam_link`만 bringup이 발행하고 광학 프레임은 드라이버 TF 사용(ICD 5장 TF 표, 결정 #23 확장).
- **v5.3**: Isaac Sim ROS 2 Bridge 환경 실측 반영 — 시스템 ROS를 source하지 않고 번들 내부 ROS 라이브러리 + CycloneDDS(Domain 70)를 쓰도록 `sim/isaac_env.sh` 추가(`docs/docker.md`, `docs/twin.md`, `sim/README.md` 정정), `/clock` 스모크 테스트로 호스트·컨테이너 수신 확인.
- **v5.4**: 트윈 T1 씬(`sim/scenes/ready2go_t1.usd`, `sim/scripts/build_scene.py`·`verify_scene.py`, `sim/drawer_dimensions.yaml`)과 T2 미러링(`sim/scripts/mirror_joint_states.py`) 구현·실측 반영(`docs/twin.md` 10.3 상태 열, 근거 `sim/README.md`). DSR 모션 서비스 이름이 `/dsr01/dsr_controller2/motion/...`임을 실측으로 확인(`/dsr01/motion/...` 아님).
- **v5.5**: `docs/requirements.md`를 범위·Phase·수용 기준의 단일 기준으로 문서화하고 `phases.md` 삭제, AGENTS·PR 템플릿 정리, 목표 수치를 AC 표로 이동(PR #25, 결정 #25~#27). `places.yaml` tf 블록 형식(#6, 결정 #23), 결정 #28 프로젝트 TCP·툴(PR #32), `drawer_top` max_travel 0.17 m(#29), 핸드-아이 5점 검증 반영(`calibration_meta.yaml` accepted, TCP 이름 `GripperDA_v1`), 트윈 T2 미러링 "P2 선행 구현" 표기(#31), 결정 #23 확정.
- **v5.6**: 비전 도구 추가 — `inspect_region` stub(`config/vision_stub.yaml`, `ready: false` 기본, 에러 코드 표는 runner.md)과 YOLO 학습 파이프라인(`tools/yolo/`, 세션 단위 분할, 문서 [`tools/yolo/README.md`](../tools/yolo/README.md)), 캘리브레이션 채택 확정. `docs/vision.md`에 학습 통과 기준(mAP50 0.9, 결정 #22) 명시, ICD 인식 서비스 응답을 `success`·`error_code`·`result_json`으로 정정.
- **v5.7**: 벽 인접 물체 밀어오기(`nudge_object`, FR-ACT-05, 이슈 #37) 반영 — `requirements.md` FR-ACT-05·AC-ACT-05, `runner.md` 7.1 `nudge_object` 행과 에러 코드 표, `domain.md` 8.5, 서랍 내부 치수 정본을 `config/places.yaml`의 `drawer_top.interior_m`으로 이관(트윈 `build_scene.py`가 읽음, `sim/drawer_dimensions.yaml`의 `interior_cm` 삭제). `contracts/task.schema.json`에 `nudge_object` 추가와 예시 태스크 `contracts/examples/task_nudge_then_pick.json`(밀기는 1회 호출 = 1회 밀기, `check_only`로 재판단 — P1 Runner 블록만 사용). 서랍 처짐(최대 인출에서 약 1.25 cm) 실측을 `places.yaml`의 `sag_m_at_max_travel`로 기록하고 `domain.md` 8.5·`vision.md`에 반영.
