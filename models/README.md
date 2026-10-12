# models/

`.gitignore`가 `models/*.pt`를 막고 있고, 아래 **세 파일만 예외**로 Git LFS(`*.pt`)에 올린다.

| 파일 | 내용 |
| :--- | :--- |
| `yolo11n_ready2go_v1.pt` | **P1 박스 모델(가림 필드 없음).** 노드에서 쓰려면 `VISION_WEIGHTS=models/yolo11n_ready2go_v1.pt bash tools/dev/vision_real_check.sh node`. `yolo11n.pt`(COCO 사전학습)에서 우리 데이터로 미세조정한 11개 클래스 검출기. 학습 `tools/yolo/train.py --epochs 100`(imgsz 640, batch 16, seed 0, 이름 `11n`) 결과의 `best.pt` (epoch 46) |
| `yolo11s_seg_ready2go_v2.pt` | **노드 기본값(P2, 10/12 보강, #229)** — v1 과 같은 조건(`yolo11s-seg.pt`, imgsz 640, batch 16, 100 epoch, seed 0, 이름 `11s_seg_v2`)에 3단 쌓기·판 밑·립밤 자세 세션을 더해 학습한 `best.pt`. 비교·근거는 [`tools/yolo/README.md`](../tools/yolo/README.md) "3단 쌓기·판 밑 보강 v2" |
| `yolo11s_seg_ready2go_v1.pt` | **이전 분할 기본값(10/11~10/12)** — 되돌릴 때 `VISION_WEIGHTS=models/yolo11s_seg_ready2go_v1.pt`. 10/11 #196 항목 2 — 분할 모델이라 마스크 안 뎁스와 가림 필드(`occluded_by`·`visible_area_m2`)를 낸다. `yolo11s-seg.pt`(COCO 사전학습)에서 분할(마스크) 라벨로 미세조정한 11개 클래스 인스턴스 분할 모델. 학습 `tools/yolo/train.py` 조건 v1·v2와 같음(imgsz 640, batch 16, 100 epoch, seed 0, 이름 `11s_seg_v1`) 결과의 `best.pt`. 10/11~10/12 에는 노드 기본이었고(`VISION_WEIGHTS` 없이 실행), 지금은 위처럼 `VISION_WEIGHTS` 로 지정할 때만 쓴다. 판정 방법은 `docs/vision.md` 9장 |

- 클래스 번호: `config/yolo_classes.txt` 줄 번호(0 `airpods_case` … 10 `cover_plate`)
- 데이터 (`yolo11n_ready2go_v1.pt`): 학습 219장(`s01`~`s07`), 검증 20장(`s90_val_a`·`s91_val_b`), 10/04 수집분
- 검증 성능 (`yolo11n_ready2go_v1.pt`) [실측 10/06, 검증 20장 `s90`·`s91` 기준]: 정밀도 0.953, 재현율 0.959, F1 0.954, mAP50 0.989, mAP50-95 0.926 — 비교 표·결정 이유·한계는 [`tools/yolo/README.md`](../tools/yolo/README.md) "기본 가중치 비교"(값은 거기에만 적는다). 10/07 검증셋(30장, `s92` 추가·라벨 1개 수정) 기준 값은 같은 파일 "겹침 데이터 재학습 v2" 표에 따로 적는다(검증셋이 달라 위 값과 직접 비교하지 않는다)
- SHA-256 (`yolo11n_ready2go_v1.pt`): `0101aac6cd7ef416184933b1414b1d294781b24f9366f70bdabe21594ddefc53`
- `yolo11s_seg_ready2go_v1.pt`: 데이터 `data/yolo_seg_v1`(학습 261장 `s01`~`s09`, 검증 30장 `s90`~`s92`, 상자 라벨 → SAM2 초안 → Roboflow 사람 수정 윤곽 749개, 10/07). 검증셋 30장 상자 mAP50 0.967 / 50-95 0.929, 마스크 0.988 / 0.895 [실측 10/07, #109]. SHA-256 `5b9527b78ebf2f11bbfe6ffce83e8f991ee09648b1eb1567ad0e80480a304ef0`, 20,507,428 B. 180° 회전 강건성 #109(10/08)
- `yolo11s_seg_ready2go_v2.pt`: 데이터 `data/yolo_seg_v2`(학습 311장 = v1 의 `s01`~`s09` + `s10_stack3_v0` 20·`s11_under_plate_v0` 20·`s12_lipbalm_pose_v0` 10, 검증 40장 = `s90`~`s92` + `s95_val_stack` 10, 10/12 PC1 촬영 → v1 상자 초안 → Roboflow 상자 수정 → SAM2 윤곽 초안 → Roboflow 윤곽 수정). 마스크 mAP50 / 50-95: 기존 검증 30장 0.993 / 0.899(v1 0.985 / 0.895), s95 10장 0.995 / 0.814(v1 0.946 / 0.758) [실측 10/12]. SHA-256 `b2ae5af07e2dd22ea5d53444a839faf620c1d4d38962d6405a9dd88bb38438c3`, 20,507,428 B
- 새 모델로 바꿀 때: 파일 이름의 버전을 올리고(`_v2`), `.gitignore` 예외 한 줄과 이 표를 함께 갱신한다

## 받기·검증
- 위 세 파일은 Git LFS다. 받기 전에 한 번 `git lfs install`, 그다음 `git pull`(또는 `git lfs pull`). 설치하지 않으면 실제 파일(검출 v1 약 5 MB, 분할 약 20 MB) 대신 포인터 텍스트 3줄만 받아 로딩이 실패한다
- 받은 뒤 검증: `sha256sum models/*.pt` 값이 위 SHA-256과 같아야 한다

## 라이선스 [미확인]
- 기반이 `ultralytics`의 `yolo11n`이다. Ultralytics 코드·가중치는 AGPL-3.0(별도 상용 라이선스 있음)으로 알고 있으나 정확한 조건은 확인하지 않았다 [미확인]. 저장소·결과물을 공개하기 전에 확인한다
