# CURRENT — A 김병직

- **담당**: 비전 · Isaac Sim 트윈 · **현재 Phase**: P1
- **최종 갱신**: 2026-10-06 (저녁, 10/07 08:00 실물 슬롯 전)

## 지금 상태
- #5 완료: realsense 컨테이너에서 컬러·정렬 뎁스를 `/wrist_cam/...`으로 발행, 수신 확인 (PR #24 머지).
- #7: 핸드-아이 결과 **채택 확정**: B의 5점 `verify.py`(10/03)에서 x·y 오차 ≤ 0.2 cm, `calibration_meta.yaml` accepted, TCP 이름은 제어기 실제 이름 `GripperDA_v1`(소문자 v). `link_6 → wrist_cam_link` 계산과 재계산 스크립트 완료, PR #26 머지됨.
- 트윈 T1 씬: 원목 2단 서랍장 씬 복원 완료(PR #49). 상자 2개 각각 Prismatic Joint 0~22.6 cm, 위 서랍 22.5 cm(당시 씬 값) 가동·한계 초과 목표에서 정지 확인, 미러링 통과 [실측 10/03]. 임시 트레이(staging_tray)는 폐기(#6). **#83 반영 재생성 완료(PR #96, 10/06)**: 서랍 원점 −3 mm·내부 높이 0.0711, 전달 트레이(handover_zone, 사다리꼴·둥근 모서리, 외곽 일부 [추정]) 추가, `verify_scene` 전부 통과(서랍 tf 0.017 mm, 트레이 원점 0.00 mm) [실측]. 상자 앞·뒤벽·바닥판 등 일부 치수는 [추정]. 서랍장 위치는 PR #55부터 `config/places.yaml` `drawer_top.tf`(+`tf_at_travel_m`, 최대 인출 상태의 서랍 좌표계)에서 읽고, 둘 중 하나라도 비면 임시 배치(tf만 있고 인출 거리가 없으면 오류로 중단). B의 3점 터치 결과(PR #56)가 머지되면 씬이 그 위치로 바뀌므로 재생성·검증 필요.
- 트윈 T2 미러링은 **P2 선행 구현**(Phase 게이트 리뷰 지적은 있었으나 사용자 판단으로 PR #31 병합, 에뮬레이터 확인): `mirror_joint_states.py`가 `/dsr01/joint_states`(joint_1~6, 라디안, 약 100 Hz)를 받아 관절을 따라가게 함. 시험 토픽 50 Hz에서 지연 2.2 ms·추종 오차 0.24° [실측 10/03], 사용자가 GUI에서 팔 추종 확인. 그리퍼는 토픽에 없어 미반영(열림 고정으로 닫혀 보이는 문제 해결, PR #41). 실물 미러링은 B의 #4·multi DDS 이후.
- 벽 인접 물체 밀어오기(`nudge_object`, FR-ACT-05, B 구현 이슈 #37): 문서 반영 완료(FR-ACT-05·AC-ACT-05, runner.md, domain.md 8.5). 서랍 내부 치수 정본은 `config/places.yaml`(새 서랍 실측값 기록됨: 내부 20.5 × 29.5 × 7 cm, 인출 22.6 cm)
- #14 실물 데이터 수집 완료(10/04): 세션 9개 **239장**(학습 219 / 검증 20), 기준 시점 `drawer_top_view`(최대 인출 22.6 cm, 스토퍼 실측 226.3 mm), 컬러+정렬 뎁스 [실측]. 라벨링은 Roboflow(자동 라벨 `Claude Opus 5.5 (Boxes)` + 사람 확인)로 끝내고 `tools/yolo/import_roboflow.py`로 우리 규칙(클래스 번호·세션·원본 PNG)에 되돌림. `build_dataset.py --val s90_val_a s91_val_b` 통과. 상세는 `2026-10-04_practice.md`. 기본 가중치 3종 비교(v8n/11n/26n, 검증 20장) 결과 **`yolo11n`으로 결정**(사용자 10/06): mAP50 0.989·F1 0.954로 최고, 약한 클래스 최소. 근거·한계·재검토 조건은 `tools/yolo/README.md` "기본 가중치 비교". 추가 라벨링은 필요할 때 [실측 10/06]
- **#14 학습·모델 결정 완료(10/06)**: v8n·11n·26n 같은 조건 비교, `yolo11n` 결정, 가중치 `models/yolo11n_ready2go_v1.pt`(LFS, PR #76 머지). 통과 기준 mAP50 0.9 [팀 확정 10/06]. 상세 `2026-10-06_practice.md`.
- **V2 `inspect_region` 실제 구현(PR #80 머지, 10/06)**: YOLO + 뎁스 덩어리 노드. 실물 첫 연결용 진단(바닥 z 로그, 요청별 프레임 덤프 `~/ready2go_vision_dump`, `tools/dev/replay_inspect_dump.py`, 시험 스크립트 `tools/dev/vision_real_check.sh`), `floor_margin_m` 0.007, `edge_tolerance_m` 0.015(벽면 배치; 모션 안전 경계는 B `WALL_TOO_CLOSE`). 실제 이미지 20장 서랍 바닥 z 0.4 mm(옛 원점 기준), 트윈 렌더 60장 위치 오차 최대 0.6 mm(이상적 센서), 가짜 카메라로 서비스 호출 확인 [실측]. 서랍 밖 검출 제외(D P1 반영). **실물 카메라·TF 연결과 실물 위치 오차는 미시험.**
- **1차 점검(#22, 10/06)은 stub만**(조장 결정, 위 서랍만, 비전 제외). stub은 A가 PC1에서 실행(multi DDS), 값은 E 전달 [0.1769, 0.2895, 0.0]·yaw 0·`top_z` 0.0115, 파일 `~/ready2go_stub/vision_stub.yaml`. 12:29 PC2 → PC1 호출 성공 [실측], 저녁 재기동(B: `b_demo.py` 실물 + 스킬 서버 흐름에서 stub 사용). 점검 판정은 #22에 아직 기록 없음 [미확인].
- **P1 일정 (#23)**: 10/09 공휴일 → **P1 테스트 10/08(목) 16:00**, 벽면 배치·nudge 포함(사용자 결정). A 로봇 슬롯 **10/07 08:00~09:00** — PC1 단독(로봇 전용선·카메라 USB를 PC1에), 1인 운용이라 자동 동작 없음, 진행표 #18. 시험 폴더 `/home/byeongjik/Cal2_proj/ready2go-vision`(main `23fd398`). nudge 후 재인식은 10/08 슬롯(B·비상정지 대기자) 요청 중.
- **모델**: E 요청으로 스몰 3종 추가 비교 → 지우개 기준 `yolo11s`가 가장 좋음(박스 중심 오차 0.98 px, AP50-95 0.973) → **실물에서 11n vs 11s 비교**(사용자 10/06): 10/07 슬롯은 11n, 저장 프레임에 11s 재검출(`WEIGHTS=... replay`). `models/`는 11n 그대로, 11s는 `~/yolo_run/runs/11s/`.
- **특이점 트윈 재현(PR #92 머지)**: `sim/motion_check/`(B `skill_server`·`b_demo.py` 실제 코드 + 기구학 가짜 로봇), `sim/scripts/play_motion_trace.py`(Isaac 재생). 실물에서 튄 구간(탑뷰 직선 하강 J3 10°, 들고 나오기 J3 0°) 재현, ◀ 기준을 실물에 맞춤(J3 < 15°). main 코드는 ◀ 없음. 손잡이 손목 해는 위·아래 서랍 통일로 지금 해(J5 −106°) 유지(사용자 결정).
- **카메라와 손끝 터치의 바닥 높이 차이 [계산 10/06]**: #83 원점(−3 mm, main 반영) 기준 카메라로 본 바닥 +2~3.5 mm. 원인 [미확인]. 바닥을 요청마다 재는 방식은 계약 검토가 필요한 별도 제안(E 검토) — 10/07 실측의 바닥 z 로그로 먼저 원인을 봄.
- `inspect_region` pose 정의 확정·계약 반영(PR #61·#65·#66): `position` = YOLO 박스 중심 x·y, z = 0, `yaw` = 긴 변 방향 (−π/2, π/2], 대칭(`size_m` 가로·세로 비 기준) yaw 0, `yaw_valid`(bool), 투영 평면 `z = top_z/2`. 형식 테스트만 완료, Day 5 실제 구현과 #10 Runner 연동은 미검증.
- 3점 터치 z 오류 발견·정정(PR #58): 측정 때 펜던트 TCP·tool weight가 풀려 z가 TCP 오프셋(228 mm)만큼 높았음 → 트윈 씬이 작업대에서 23 cm 떠 있어 발견 [실측]. 정정 후 `verify_scene` tf 일치 원점 0.024 mm·회전 0.0000°.
- `drawer_top_view`는 팔이 거의 펴진 자세(J3 ≈ 10°, J5 132.8°)라 Z를 올릴 수 없고(약 +5 mm가 한계) 내리기만 가능, J5 +4°(136.849°)는 이동이 안 됨(사용자 보고, J5 한계 135° 근처로 추정 [미확인]). `jog_gui`의 Z `−` 버튼이 비스듬히 움직인 원인은 단정하지 못함 [미확인]. B에게 확인 요청(#14, 10/04) — B가 10/06 로봇 작업 목록에 넣음(#6), 답 대기.
## 확정 값 (근거 태그 필수)
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 카메라 토픽 | `/wrist_cam/color/image_raw`, `/wrist_cam/aligned_depth_to_color/image_raw` (각 약 30 Hz) | [실측] 10/02 |
| 토픽 경로 설정 | `-r __ns:=/ -r __node:=wrist_cam` (`__node`만 주면 `/camera/wrist_cam/...`) | [실측] 10/02 |
| 캘리브레이션 값·TCP·`derived_tf` | [calibration_meta.yaml](../../config/calibration/calibration_meta.yaml) (절차: 같은 폴더 README) | [실측]/[계산]/[사용자 확인] |

## 막힌 점 · 필요한 도움
- B: J5 한계·`jog_gui` Z 답변 대기(#14, B가 J5 ±133° 제한을 코드에 넣음). 카메라-터치 바닥 z 차이 원인(10/03 5점 검증의 z 수치) 문의(#83).
- B·E: 벽에 붙인 지우개 중심이 `interior_m`보다 y 6.8 mm 밖으로 계산되는 이유(#23).
- E: 10/08 16:00 전 로봇 시간(실제 비전 한 바퀴·nudge 후 재인식) 배정(#23).

## 다음 할 일
- [x] 5점 `verify.py` 결과 반영 (B 측정, meta accepted)
- [x] #14 학습 파이프라인 준비: `tools/yolo/`(촬영·데이터셋 구성·학습), RTX 5060 CUDA 확인, 합성 데이터로 종단 검증 [실측 10/03]
- [x] **일정 변경(PM 10/04)**: 10/05 공휴일이라 Day 3의 데이터 수집을 10/04로 당겨 완료(위 참고). 남은 로봇 순서(B `tray_view` 교시, `staging_tray`(폐기됨, #6), `vision_stub` 물체 4개 손끝 실측, `drawer_control` 실물)는 B 소관.
- [x] #14 실물 데이터 수집·라벨링(10/04). `config/yolo_classes.txt` 11종 그대로 사용(`--init-classes` 실행 안 함).
- [x] #14 YOLO 학습·평가(10/06): 3종 비교 → `yolo11n` 결정(위 참고). 아래는 당시 메모: 통과 기준 mAP50 0.9는 [팀 확정 10/06, 사용자 전달]. 검증 인스턴스가 클래스당 5~7개로 적어 **10 미만이면 `s92_val_c`로 보충**. `s02_spread`는 계획표 1~5번 줄 조합만 반복해 찍음(조합 5가지) → 공존 편향 주의.
- [x] 도구 PR #76 머지(10/06). 당시 메모: 브랜치 `feat/a-auto-label`(`auto_label_single.py`, `review_boxes.py`, `import_roboflow.py`)을 PR로 올림(미작성). 단독 배치 자동 라벨은 뎁스 덩어리 + 빈 서랍 배경 색 차이, 가장자리에 닿는 물체는 ROI 밖까지 확장 필요(벽 인접 물체가 ROI에 잘리는 것 발견).
- [x] #18 `inspect_region` stub — 1차 점검용으로 정리·실측 값 반영(PR #81, 10/06). 이전: (설정 파일 좌표 응답, 서비스 호출 확인 10/03) — 설정 `ready: false`로 배포(실측 전 STUB_NOT_READY로 차단, PR #33 리뷰). 좌표를 B와 실물로 재서 교체한 뒤 `ready: true`, `pose` 형식 B와 합의 필요
- [x] #18 V2 구현 PR #80 머지(10/06)
- [ ] **10/07 08:00 슬롯**: PC1 이더넷 `eno1` 고정 IP(192.168.1.x)·카메라 USB3 연결 → `compose --profile real up ros2-core realsense` → `vision_real_check.sh check|node|call|measure` → 배치 3곳 위치 오차(AC-VIS-01 첫 측정)·바닥 z → #18·#23 기록, 11s 재검출 비교
- [ ] 10/08: 반복 측정·실제 비전 한 바퀴(16:00 P1 테스트 전), nudge 후 재인식 오차
- [ ] 이후: 바닥 높이 요청마다 측정(계약 검토), 경계 여유 0.01 환원 검토, compose `vision` 서비스로 노드 기동(C 제안) 당시 메모: YOLO+뎁스. **깊이 0·결손 픽셀 검사와 전용 `error_code`(예: `DEPTH_INVALID`) 필수** — B가 원본 `verify.py`에서 깊이 0 클릭 시 팔이 카메라 위치로 들어 올려진 사례 2회. 미발견(`success=true`, `target_found=false`)과 구분. 높이 오프셋(카메라 면 높이 + 약 10 mm)은 B 쪽에서 처리
- [x] (P2 선행, 병행 가능) 트윈 T1 씬: 실측 치수로 서랍장 씬 구성
- [x] `feat/a-isaac-env` push → PR #30 (기준 브랜치 `feat/a-drawer-measurements`, 리뷰어 C)
- [ ] 새 서랍 남은 실측·교체: 이미 기록한 값(외곽, 단 높이, 내부 치수, 손잡이, 인출 22.5 cm, 처짐 0, 앞판 1.8, 작업대 위치 등)은 PR #48·#49로 반영 완료. 남은 것: 상자 앞·뒤벽·바닥판·서랍장 판 두께 실측, 받침 선반 크기·위치 확인(윗면 −0.3 cm 확인 필요), #6 3점 터치로 서랍 위치 교체 → `drawer_dimensions.yaml`·`places.yaml`, 씬 재생성·검증
- [x] B의 `drawer_top.tf`(PR #56, z를 TCP 기준으로 정정한 #58)로 씬 재생성·`verify_scene` 통과: 서랍 좌표계 일치 원점 0.024 mm·회전 0.0000°, 서랍장 원점 [0.3838, -0.4597, 0.004] m(평면도 임시 배치와 x·y 2 mm 차이) [실측 10/04]. 3점 터치 때 펜던트 TCP·tool weight가 풀려 있어 z가 228 mm 높았던 것을 찾아 정정함
- [ ] 씬의 [추정] 값 교체: 로봇-작업대 각도(#6 결과), 전달 트레이 외곽·벽 두께·모서리 반경(자로 재면 `build_scene.py` `HANDOVER_*`)
- [x] PR #83 머지 후 트윈 재생성·`verify_scene.py` 통과, 전달 트레이 추가(PR #96)
- [ ] 1차 점검(#22) 판정이 기록되면 `2026-10-06_practice.md` 10장에 추가
- [ ] 시뮬 파지 데모(서랍 열기 → 관측 → 집기): 실물 파지를 본 뒤 만들기로 함(사용자 10/06)
- [ ] 아래 서랍(`drawer_bottom`): Phase 3. B의 3점 터치·자세 뒤 비전·stub·트윈에 region 추가
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
