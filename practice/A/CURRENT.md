# CURRENT — A 김병직

- **담당**: 비전 · Isaac Sim 트윈 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-04

## 지금 상태
- #5 완료: realsense 컨테이너에서 컬러·정렬 뎁스를 `/wrist_cam/...`으로 발행, 수신 확인 (PR #24 머지).
- #7: 핸드-아이 결과 **채택 확정**: B의 5점 `verify.py`(10/03)에서 x·y 오차 ≤ 0.2 cm, `calibration_meta.yaml` accepted, TCP 이름은 제어기 실제 이름 `GripperDA_v1`(소문자 v). `link_6 → wrist_cam_link` 계산과 재계산 스크립트 완료, PR #26 머지됨.
- 트윈 T1 씬: 원목 2단 서랍장 씬 복원 완료(PR #49). 상자 2개 각각 Prismatic Joint 0~22.5 cm, 위 서랍 22.5 cm 가동·한계 초과 목표에서 정지 확인, 미러링 통과 [실측 10/03]. 스테이징·전달 트레이는 씬에 없음. 상자 앞·뒤벽·바닥판 등 일부 치수는 [추정]. 서랍장 위치는 PR #55부터 `config/places.yaml` `drawer_top.tf`(+`tf_at_travel_m`, 최대 인출 상태의 서랍 좌표계)에서 읽고, 둘 중 하나라도 비면 임시 배치(tf만 있고 인출 거리가 없으면 오류로 중단). B의 3점 터치 결과(PR #56)가 머지되면 씬이 그 위치로 바뀌므로 재생성·검증 필요.
- 트윈 T2 미러링은 **P2 선행 구현**(Phase 게이트 리뷰 지적은 있었으나 사용자 판단으로 PR #31 병합, 에뮬레이터 확인): `mirror_joint_states.py`가 `/dsr01/joint_states`(joint_1~6, 라디안, 약 100 Hz)를 받아 관절을 따라가게 함. 시험 토픽 50 Hz에서 지연 2.2 ms·추종 오차 0.24° [실측 10/03], 사용자가 GUI에서 팔 추종 확인. 그리퍼는 토픽에 없어 미반영(열림 고정으로 닫혀 보이는 문제 해결, PR #41). 실물 미러링은 B의 #4·multi DDS 이후.
- 벽 인접 물체 밀어오기(`nudge_object`, FR-ACT-05, B 구현 이슈 #37): 문서 반영 완료(FR-ACT-05·AC-ACT-05, runner.md, domain.md 8.5). 서랍 내부 치수 정본은 `config/places.yaml`(새 서랍 실측값 기록됨: 내부 20.5 × 29.5 × 7 cm, 인출 22.5 cm)
## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 카메라 토픽 | `/wrist_cam/color/image_raw`, `/wrist_cam/aligned_depth_to_color/image_raw` (각 약 30 Hz) | [실측] 10/02 |
| 토픽 경로 설정 | `-r __ns:=/ -r __node:=wrist_cam` (`__node`만 주면 `/camera/wrist_cam/...`) | [실측] 10/02 |
| 캘리브레이션 값·TCP·`derived_tf` | [calibration_meta.yaml](../../config/calibration/calibration_meta.yaml) (절차: 같은 폴더 README) | [실측]/[계산]/[사용자 확인] |

## 막힌 점 · 필요한 도움
- C: bringup static TF 구현(#3). 결정 #23은 확정(각 담당 파일을 직접 읽음).

## 다음 할 일
- [x] 5점 `verify.py` 결과 반영 (B 측정, meta accepted)
- [x] #14 학습 파이프라인 준비: `tools/yolo/`(촬영·데이터셋 구성·학습), RTX 5060 CUDA 확인, 합성 데이터로 종단 검증 [실측 10/03]
- [ ] #14 실물 데이터 수집(로봇 슬롯)·라벨링·YOLO 학습. 물품 11종·치수는 이슈 #8에 기록됨(클래스 ID `airpods_case`·`caramel_box`·`car_key`·`eraser`·`lip_balm`·`carrot_pen`·`masking_tape`·`toy_car`·`toy_wrench`·`toy_hammer`·`cover_plate`). **온톨로지 `world.items` 갱신(E) 후 `build_dataset.py --init-classes`로 클래스 번호를 고정하고 라벨링 시작** — 순서가 바뀌면 라벨 번호가 어긋남
- [x] #18 `inspect_region` stub (설정 파일 좌표 응답, 서비스 호출 확인 10/03) — 설정 `ready: false`로 배포(실측 전 STUB_NOT_READY로 차단, PR #33 리뷰). 좌표를 B와 실물로 재서 교체한 뒤 `ready: true`, `pose` 형식 B와 합의 필요
- [ ] #18 V2 (Day 5): YOLO+뎁스. **깊이 0·결손 픽셀 검사와 전용 `error_code`(예: `DEPTH_INVALID`) 필수** — B가 원본 `verify.py`에서 깊이 0 클릭 시 팔이 카메라 위치로 들어 올려진 사례 2회. 미발견(`success=true`, `target_found=false`)과 구분. 높이 오프셋(카메라 면 높이 + 약 10 mm)은 B 쪽에서 처리
- [x] (P2 선행, 병행 가능) 트윈 T1 씬: 실측 치수로 서랍장 씬 구성
- [x] `feat/a-isaac-env` push → PR #30 (기준 브랜치 `feat/a-drawer-measurements`, 리뷰어 C)
- [ ] 새 서랍 남은 실측·교체: 이미 기록한 값(외곽, 단 높이, 내부 치수, 손잡이, 인출 22.5 cm, 처짐 0, 앞판 1.8, 작업대 위치 등)은 PR #48·#49로 반영 완료. 남은 것: 상자 앞·뒤벽·바닥판·서랍장 판 두께 실측, 받침 선반 크기·위치 확인(윗면 −0.3 cm 확인 필요), #6 3점 터치로 서랍 위치 교체 → `drawer_dimensions.yaml`·`places.yaml`, 씬 재생성·검증
- [ ] B의 `drawer_top.tf` 결과 PR(#56) 머지 후: 씬 재생성·`verify_scene`(tf 일치 검사 포함) 실행, 결과를 #6에 기록
- [ ] 씬의 [추정] 값 교체: 로봇-작업대 각도(#6 결과), 트레이 크기
- [x] (P2 선행 구현) 트윈 T2 미러링(에뮬레이터): `/dsr01/joint_states` → 트윈 조인트
- [ ] 트윈 T2 실물 미러링: 실물 M0609의 `/dsr01/joint_states` 수신 확인 (B의 #4, PC1↔PC2 multi DDS). Day 5 중단 기준
- [x] 미러링 시 그리퍼가 닫혀 보이는 문제: 팔 순간이동 중 손가락이 닫힘(4초에 42.6°) → 열림 목표를 매 스텝 지정해 해결 [실측 10/03, PR #41]
- [ ] 트윈 그리퍼 폭을 실물 `/gripper/state`와 연동 — 트윈 미러링을 L2 시연(Day 10)에서 보여 준다면 그 전까지. 지금은 실물이 물건을 잡아도 트윈은 열린 채로 보임

## Phase 2 이슈 후보 (P1 마무리 후 생성)
- 가림 순서(`top_z` 정렬) + V3 미지 물체 + ID 추적 (Day 6, Day 9 Unpacking에 필요)
- 트윈 T1 씬 → T2 미러링 (Day 5 중단 기준 판정, `docs/twin.md`)
- 비전 정확도 측정·튜닝 (Day 7)

## 철회한 결론
- #14 선행에서 캘리브레이션(#7) 제외: 이미지 수집·학습에는 불필요, 3D 변환(#18)에만 필요.
- ~~realsense `__node:=wrist_cam`만 주면 `/wrist_cam/...`으로 발행된다~~ → 실측 결과 `/camera/wrist_cam/...`, `-r __ns:=/`가 필요 (10/02).
- ~~10/01 캘리브레이션 때 `set_tcp("2FG_TCP")`가 무시돼 `GripperDA_V1`이 쓰였다~~ → 사용자가 `set_tcp("GripperDA_V1")`로 직접 실행했다고 확인 (10/02). 이 PC의 강의 사본 코드만 보고 한 추정이었음.
- ~~TCP 이름 `GripperDA_V1`~~ → 실제 이름은 `GripperDA_v1`(소문자 v). 대문자 V는 오타였고 사용자가 직접 확인 (10/03), B의 `get_current_tcp` 실측과도 일치. 10/01 캘리브레이션도 이 TCP로 실행됨.
