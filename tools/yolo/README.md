# YOLO 데이터 수집·학습 도구 (담당 A, #14)

실물 데이터로 물품 검출 모델을 만드는 도구. 순서: **촬영 → 라벨링 → 데이터셋 구성 → 학습·평가**. 학습은 `yolo-detection` 컨테이너(PC1, RTX 5060)에서 한다 — 저장소가 마운트돼 있지 않으므로 `docker cp tools knowledge yolo-detection:/작업폴더/`로 복사해 쓴다(스크립트는 자기 위치 기준으로 `data/`·`runs/`를 만든다).

| 단계 | 명령 | 비고 |
| :--- | :--- | :--- |
| 촬영 | `python3 tools/yolo/capture_session.py s01_basic --note "배치 메모" --interval 1 --count 30` | 세션 = 배치 하나. 컬러 + 정렬 뎁스를 `data/raw/<세션>/`에 저장. 구독만 하고 로봇은 움직이지 않음. 로봇은 `drawer_top_view` 포즈(B) |
| 라벨링 | (외부 도구) 결과를 `data/labeled/<세션>/images`, `labels`(YOLO txt)로 | 클래스 id = `config/yolo_classes.txt` 줄 번호. 학습 결과(`metrics.json`)에 사용한 클래스 목록이 기록된다 |
| 라벨링 보조 | `python3 tools/yolo/auto_label_single.py s01_single_v0` | **한 장에 물품 하나인 세션 전용.** `data/raw/<세션>/class_ranges.txt`(번호 구간 ↔ 물품; 한 줄에 `0000-0005 airpods_case`, `#`로 시작하면 주석, 물품 이름은 `yolo_classes.txt`와 같아야 함. **손으로 작성**한다 — `capture_session.py`가 만들지 않는다. 후속: 촬영 때 `session.yaml`에 구간을 기록) + 정렬 뎁스 덩어리 + 빈 서랍 배경과의 색 차이로 박스 초안을 만든다. 서랍 바닥 영역(ROI)은 기준 시점 `drawer_top_view` 기준이라 시점 변화 세션에는 쓰지 않는다. ROI(`FLOOR_ROI` = (268, 108, 1008, 614), 화면 좌표)는 `drawer_top_view`를 다시 가르치면 다시 재야 한다. `carrot_pen`은 색 분할로 끝까지 따라간다. 박스는 몇 px 넉넉하고, 더 조이면(색 차이만) 흰색·주황색 물체가 잘려서 사람 확인이 필요하다 |
| 박스 수정 | `python3 tools/yolo/review_boxes.py <세션> --labeled data/labeled --out data/labeled_fixed` | 한 장에 박스 하나인 라벨을 OpenCV 창에서 드래그로 고친다(Enter 확정). 오프라인 대안이며, Roboflow를 쓰면 필요 없다 |
| Roboflow 복원 | `python3 tools/yolo/import_roboflow.py data/roboflow_export [--dry-run]` | Roboflow YOLOv8 내보내기를 우리 규칙으로 되돌린다: 클래스는 **이름으로** `yolo_classes.txt` 번호에 재매핑, 파일 이름 접두어(`s01_…`)로 세션 복원, 이미지는 원본 PNG. 버전을 만들 때 **Preprocessing(Auto-Orient, Resize)과 Augmentation은 모두 끄고** 내려받는다(좌표가 어긋남). 모르는 클래스 이름·범위 밖 좌표는 쓰기 전에 중단 |
| 클래스 고정 | `python3 tools/yolo/build_dataset.py --init-classes` | **라벨링 시작 전에 1회.** `config/yolo_classes.txt`(줄 번호 = 클래스 id, 깃으로 추적)를 만든다. 물품을 추가하면 맨 뒤에 덧붙이고 앞 번호는 바꾸지 않는다. **실행 시점**: 물품 목록(이슈 #8 11종)이 온톨로지 `world.items`에 반영(PR #46 머지)된 뒤. 그 전에는 파일이 없어 `main`에서 구성 단계가 중단되는 것이 정상 |
| 구성 | `python3 tools/yolo/build_dataset.py --val s90_val_a s91_val_b` (고정 파일이 없으면 **중단**, 합성 점검만 `--allow-ontology-order`) | **세션 단위** 분할. 라벨 오류(id 범위·좌표 범위·이미지와 라벨 파일명 불일치)가 있거나 `yolo_classes.txt`에 온톨로지에 없는 이름이 있으면 중단 |
| 학습·평가 | `python3 tools/yolo/train.py --base <yolov8n.pt> --epochs 100 --name v1` | 검증 세션 mAP50 을 `runs/<name>/metrics.json`에 기록, 0.9 이상이면 통과(결정 #22 제안값 [팀 확정 필요]) |
| yaw 비교 실험 | (이슈 [#62](https://github.com/Jik-Kim/ready2go/issues/62) YOLO-OBB, [#63](https://github.com/Jik-Kim/ready2go/issues/63) SAM2) | 데모 경로 밖. 정답 yaw 기록법은 `capture_session.py --gt-yaw-method`로 방법만 `session.yaml`에 남기고 실제 방법(각도 지그/격자 시트)은 #62에서 정한다 `[팀 확정 필요]`. OBB 라벨은 현재 detect 형식과 공존해야 하므로 `build_dataset.py`에 라벨 형식 선택(detect/obb)을 추가하는 방향 |
| 점검용 | `python3 tools/yolo/make_synthetic.py` | 합성 데이터. **파이프라인 점검 전용**, 학습 결과를 모델로 쓰지 않음 |

촬영 계획표와 촬영 전 점검 목록: [shooting_plan.md](shooting_plan.md)

## 점검 결과 [실측 10/03, PC1 RTX 5060, yolo-detection 컨테이너]
- GPU: torch 2.11.0+cu128, `sm_120` 지원, CUDA 행렬 연산 정상 (#14 "GPU 호환 확인" 항목, RTX 5060).
- 합성 3클래스(세션 4개×20장, 검증 1세션)로 15 epoch 학습 약 7초, 검증 mAP50 0.908 — 파이프라인 동작 확인용 숫자일 뿐 모델 성능이 아님.
- 촬영 스크립트는 가짜 카메라 퍼블리셔(rgb8·16UC1)로 확인: 색 순서·뎁스 16bit·세션 중복 방지·정상 종료. **실제 RealSense로는 아직 안 해 봄.**
- 오류 경로: 없는 검증 세션, 잘못된 클래스 id는 종료 코드 1로 중단.

## 주의
- `data/`, `runs/`는 `.gitignore`(용량). 확정한 가중치만 `models/`에 둔다 — 그런데 `.gitignore`에 `models/*.pt`가 있어 Git LFS 커밋(#14)을 하려면 예외 규칙이 필요하다 `[팀 확정 필요]`.
- RTX 4060(PC2)에서의 동작은 미확인(`docker/vision/Dockerfile`의 TODO).
