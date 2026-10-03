# CURRENT — A 김병직

- **담당**: 비전 · Isaac Sim 트윈 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-03

## 지금 상태
- #5 완료: realsense 컨테이너에서 컬러·정렬 뎁스를 `/wrist_cam/...`으로 발행, 수신 확인 (PR #24 머지).
- #7: 핸드-아이 결과 **채택 확정**: B의 5점 `verify.py`(10/03)에서 x·y 오차 ≤ 0.2 cm, `calibration_meta.yaml` accepted, TCP 이름은 제어기 실제 이름 `GripperDA_v1`(소문자 v). `link_6 → wrist_cam_link` 계산과 재계산 스크립트 완료, PR #26 머지됨.
- 트윈 T1 씬 완료: `sim/scenes/ready2go_t1.usd`(작업대·3단 서랍장·M0609/RG2·손목 카메라, 서랍 Prismatic 0~0.17 m)를 `build_scene.py`로 생성하고 `verify_scene.py` 전부 통과, GUI에서 정상 확인 [실측 10/03]. 서랍 실측 치수·`drawer_top` 인출 거리 정정은 PR #29, 씬·실행 환경은 PR #30(기준 브랜치 `feat/a-drawer-measurements`) 리뷰 중.
- 트윈 T2 미러링은 **P2 선행 구현**(Phase 게이트 리뷰 지적은 있었으나 사용자 판단으로 PR #31 병합, 에뮬레이터 확인): `mirror_joint_states.py`가 `/dsr01/joint_states`(joint_1~6, 라디안, 약 100 Hz)를 받아 관절을 따라가게 함. 시험 토픽 50 Hz에서 지연 2.2 ms·추종 오차 0.24° [실측 10/03], 사용자가 GUI에서 팔 추종 확인. 그리퍼는 토픽에 없어 미반영(닫혀 보이는 원인은 확인 중). 실물 미러링은 B의 #4·multi DDS 이후.

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 카메라 토픽 | `/wrist_cam/color/image_raw`, `/wrist_cam/aligned_depth_to_color/image_raw` (각 약 30 Hz) | [실측] 10/02 |
| 토픽 경로 설정 | `-r __ns:=/ -r __node:=wrist_cam` (`__node`만 주면 `/camera/wrist_cam/...`) | [실측] 10/02 |
| 캘리브레이션 값·TCP·`derived_tf` | [calibration_meta.yaml](../../config/calibration/calibration_meta.yaml) (절차: 같은 폴더 README) | [실측]/[계산]/[사용자 확인] |

## 막힌 점 · 필요한 도움
- C: bringup static TF 구현(#3). 결정 #23은 확정(각 담당 파일을 직접 읽음).
- 카메라 `207222073543`이 10/01 캘리브레이션에 쓴 개체와 같은지 [팀 확정 필요].

## 다음 할 일
- [x] 5점 `verify.py` 결과 반영 (B 측정, meta accepted)
- [ ] #14 실물 데이터 수집(로봇 슬롯)·라벨링·YOLO 학습
- [x] #18 `inspect_region` stub (설정 파일 좌표 응답, 서비스 호출 확인 10/03) — 좌표를 B와 실물로 재서 교체, `pose` 형식 B와 합의 필요
- [ ] #18 V2 (Day 5): YOLO+뎁스. **깊이 0·결손 픽셀 검사와 전용 `error_code`(예: `DEPTH_INVALID`) 필수** — B가 원본 `verify.py`에서 깊이 0 클릭 시 팔이 카메라 위치로 들어 올려진 사례 2회. 미발견(`success=true`, `target_found=false`)과 구분. 높이 오프셋(카메라 면 높이 + 약 10 mm)은 B 쪽에서 처리
- [x] (P2 선행, 병행 가능) 트윈 T1 씬: 실측 치수로 서랍장 씬 구성
- [x] `feat/a-isaac-env` push → PR #30 (기준 브랜치 `feat/a-drawer-measurements`, 리뷰어 C)
- [ ] #29 머지 후 PR #30 기준 브랜치를 `main`으로 변경
- [ ] 씬의 [추정] 값 교체: 로봇-작업대 각도·서랍장 위치(#6 결과), 손잡이 돌출 길이, 트레이 크기 (표: `sim/README.md`)
- [x] (P2 선행 구현) 트윈 T2 미러링(에뮬레이터): `/dsr01/joint_states` → 트윈 조인트
- [ ] 트윈 T2 실물 미러링: 실물 M0609의 `/dsr01/joint_states` 수신 확인 (B의 #4, PC1↔PC2 multi DDS). Day 5 중단 기준
- [ ] 미러링 시 그리퍼 상태 처리: 닫혀 보이는 원인 확인, 기본 열림 유지 또는 `/gripper/state` 연동

## Phase 2 이슈 후보 (P1 마무리 후 생성)
- 가림 순서(`top_z` 정렬) + V3 미지 물체 + ID 추적 (Day 6, Day 9 Unpacking에 필요)
- 트윈 T1 씬 → T2 미러링 (Day 5 중단 기준 판정, `docs/twin.md`)
- 비전 정확도 측정·튜닝 (Day 7)

## 철회한 결론
- #14 선행에서 캘리브레이션(#7) 제외: 이미지 수집·학습에는 불필요, 3D 변환(#18)에만 필요.
- ~~realsense `__node:=wrist_cam`만 주면 `/wrist_cam/...`으로 발행된다~~ → 실측 결과 `/camera/wrist_cam/...`, `-r __ns:=/`가 필요 (10/02).
- ~~10/01 캘리브레이션 때 `set_tcp("2FG_TCP")`가 무시돼 `GripperDA_V1`이 쓰였다~~ → 사용자가 `set_tcp("GripperDA_V1")`로 직접 실행했다고 확인 (10/02). 이 PC의 강의 사본 코드만 보고 한 추정이었음.
- ~~TCP 이름 `GripperDA_V1`~~ → 실제 이름은 `GripperDA_v1`(소문자 v). 대문자 V는 오타였고 사용자가 직접 확인 (10/03), B의 `get_current_tcp` 실측과도 일치. 10/01 캘리브레이션도 이 TCP로 실행됨.
