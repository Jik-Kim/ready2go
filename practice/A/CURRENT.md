# CURRENT — A 김병직

- **담당**: 비전 · Isaac Sim 트윈 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-02

## 지금 상태
- #5 완료: realsense 컨테이너에서 컬러·정렬 뎁스를 `/wrist_cam/...`으로 발행, 수신 확인 (PR #24 머지).
- #7: 핸드-아이 결과 **잠정 채택(개발용), 5점 `verify.py` 검증 대기**. `link_6 → wrist_cam_link` 계산과 재계산 스크립트 완료, PR #26 리뷰 중.

## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 카메라 토픽 | `/wrist_cam/color/image_raw`, `/wrist_cam/aligned_depth_to_color/image_raw` (각 약 30 Hz) | [실측] 10/02 |
| 토픽 경로 설정 | `-r __ns:=/ -r __node:=wrist_cam` (`__node`만 주면 `/camera/wrist_cam/...`) | [실측] 10/02 |
| 캘리브레이션 값·TCP·`derived_tf` | [calibration_meta.yaml](../../config/calibration/calibration_meta.yaml) (절차: 같은 폴더 README) | [실측]/[계산]/[사용자 확인] |

## 막힌 점 · 필요한 도움
- 5점 `verify.py` 측정에 로봇 시간 필요 → B와 조율.
- B 확인(#7 코멘트): `link_6` 원점이 플랜지 면인지, TCP 오프셋·툴 무게가 실제 RG2와 맞는지, 프레임 이름 접두어, `set_tcp` 반환값. 결과에 따라 `derived_tf` 재계산.
- C 확인(#3, 결정 #23): bringup static TF의 설정 파일 형식.
- 카메라 `207222073543`이 10/01 캘리브레이션에 쓴 개체와 같은지 [팀 확정 필요].

## 다음 할 일
- [ ] 5점 `verify.py` 측정 → `verified.error_cm` 기록, 1.0 cm 이내(결정 #22)면 `accepted`로 확정
- [ ] #14 실물 데이터 수집(로봇 슬롯)·라벨링·YOLO 학습
- [ ] #18 Day 4까지 `inspect_region` stub 제공 (B #15용), 이후 V2
- [ ] (P2 선행, 병행 가능) 트윈 T1 씬: 실측 치수로 서랍장 씬 구성

## Phase 2 이슈 후보 (P1 마무리 후 생성)
- 가림 순서(`top_z` 정렬) + V3 미지 물체 + ID 추적 (Day 6, Day 9 Unpacking에 필요)
- 트윈 T1 씬 → T2 미러링 (Day 5 중단 기준 판정, `docs/twin.md`)
- 비전 정확도 측정·튜닝 (Day 7)

## 철회한 결론
- #14 선행에서 캘리브레이션(#7) 제외: 이미지 수집·학습에는 불필요, 3D 변환(#18)에만 필요.
- ~~realsense `__node:=wrist_cam`만 주면 `/wrist_cam/...`으로 발행된다~~ → 실측 결과 `/camera/wrist_cam/...`, `-r __ns:=/`가 필요 (10/02).
- ~~10/01 캘리브레이션 때 `set_tcp("2FG_TCP")`가 무시돼 `GripperDA_V1`이 쓰였다~~ → 사용자가 `set_tcp("GripperDA_V1")`로 직접 실행했다고 확인 (10/02). 이 PC의 강의 사본 코드만 보고 한 추정이었음.
