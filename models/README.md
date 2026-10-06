# models/

`.gitignore`가 `models/*.pt`를 막고 있고, 아래 **한 파일만 예외**로 Git LFS(`*.pt`)에 올린다.

| 파일 | 내용 |
| :--- | :--- |
| `yolo11n_ready2go_v1.pt` | `yolo11n.pt`(COCO 사전학습)에서 우리 데이터로 미세조정한 11개 클래스 검출기. 학습 `tools/yolo/train.py --epochs 100`(imgsz 640, batch 16, seed 0, 이름 `11n`) 결과의 `best.pt` (epoch 46) |

- 클래스 번호: `config/yolo_classes.txt` 줄 번호(0 `airpods_case` … 10 `cover_plate`)
- 데이터: 학습 219장(`s01`~`s07`), 검증 20장(`s90_val_a`·`s91_val_b`), 10/04 수집분
- 검증 성능 [실측 10/06]: 정밀도 0.953, 재현율 0.959, F1 0.954, mAP50 0.989, mAP50-95 0.926 — 비교 표·결정 이유·한계는 [`tools/yolo/README.md`](../tools/yolo/README.md) "기본 가중치 비교"(값은 거기에만 적는다)
- SHA-256: `0101aac6cd7ef416184933b1414b1d294781b24f9366f70bdabe21594ddefc53`
- 새 모델로 바꿀 때: 파일 이름의 버전을 올리고(`_v2`), `.gitignore` 예외 한 줄과 이 표를 함께 갱신한다

## 받기·검증
- 이 파일은 Git LFS다. 받기 전에 한 번 `git lfs install`, 그다음 `git pull`(또는 `git lfs pull`). 설치하지 않으면 5 MB 파일 대신 포인터 텍스트 3줄만 받아 로딩이 실패한다
- 받은 뒤 검증: `sha256sum models/yolo11n_ready2go_v1.pt` 값이 위 SHA-256과 같아야 한다

## 라이선스 [미확인]
- 기반이 `ultralytics`의 `yolo11n`이다. Ultralytics 코드·가중치는 AGPL-3.0(별도 상용 라이선스 있음)으로 알고 있으나 정확한 조건은 확인하지 않았다 [미확인]. 저장소·결과물을 공개하기 전에 확인한다
