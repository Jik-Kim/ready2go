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
