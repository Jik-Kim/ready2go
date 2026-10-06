# YOLO 데이터 수집·학습 도구 (담당 A, #14)

실물 데이터로 물품 검출 모델을 만드는 도구. 순서: **촬영 → 라벨링 → 데이터셋 구성 → 학습·평가**. 학습은 `yolo-detection` 컨테이너(PC1, RTX 5060)에서 한다 — 저장소가 마운트돼 있지 않으므로 `docker cp tools knowledge yolo-detection:/작업폴더/`로 복사해 쓴다(스크립트는 자기 위치 기준으로 `data/`·`runs/`를 만든다).

| 단계 | 명령 | 비고 |
| :--- | :--- | :--- |
| 촬영 | `python3 tools/yolo/capture_session.py s01_basic --note "배치 메모" --interval 1 --count 30` | 세션 = 배치 하나. 컬러 + 정렬 뎁스를 `data/raw/<세션>/`에 저장. 구독만 하고 로봇은 움직이지 않음. 로봇은 `drawer_top_view` 포즈(B) |
| 라벨링 | (외부 도구) 결과를 `data/labeled/<세션>/images`, `labels`(YOLO txt)로 | 클래스 id = `config/yolo_classes.txt` 줄 번호. 학습 결과(`metrics.json`)에 사용한 클래스 목록이 기록된다 |
| 라벨링 보조 | `python3 tools/yolo/auto_label_single.py s01_single_v0` | **한 장에 물품 하나인 세션 전용.** `data/raw/<세션>/class_ranges.txt`(번호 구간 ↔ 물품; 한 줄에 `0000-0005 airpods_case`, `#`로 시작하면 주석, 물품 이름은 `yolo_classes.txt`와 같아야 함. **손으로 작성**한다 — `capture_session.py`가 만들지 않는다. 후속: 촬영 때 `session.yaml`에 구간을 기록) + 정렬 뎁스 덩어리 + 빈 서랍 배경과의 색 차이로 박스 초안을 만든다. 서랍 바닥 영역(ROI)은 기준 시점 `drawer_top_view` 기준이라 시점 변화 세션에는 쓰지 않는다. ROI(`FLOOR_ROI` = (268, 108, 1008, 614), 화면 좌표)는 `drawer_top_view`를 다시 가르치면 다시 재야 한다. `carrot_pen`은 색 분할로 끝까지 따라간다. **재실행**: 출력 폴더(`data/labeled/<세션>`)에 이전 결과가 있으면 기본은 중단한다(손으로 고친 라벨 보호). `--force`를 붙이면 작업 폴더(`data/.auto_label_work/<세션>`)에 전부 만들고 **끝까지 성공했을 때만** 한 번에 교체한다(중간에 오류로 끊기면 기존 출력은 그대로, 불완전한 세션이 남지 않음). 교체될 장수를 출력한다(원본 `data/raw`는 건드리지 않음). 박스는 몇 px 넉넉하고, 더 조이면(색 차이만) 흰색·주황색 물체가 잘려서 사람 확인이 필요하다 |
| 박스 수정 | `python3 tools/yolo/review_boxes.py <세션> --labeled data/labeled --out data/labeled_fixed` | 한 장에 박스 하나인 라벨을 OpenCV 창에서 드래그로 고친다(Enter 확정). 오프라인 대안이며, Roboflow를 쓰면 필요 없다 |
| Roboflow 복원 | `python3 tools/yolo/import_roboflow.py data/roboflow_export [--dry-run]` | Roboflow YOLOv8 내보내기를 우리 규칙으로 되돌린다: 클래스는 **이름으로** `yolo_classes.txt` 번호에 재매핑, 파일 이름 접두어(`s01_…`)로 세션 복원, 이미지는 원본 PNG. 버전을 만들 때 **Preprocessing(Auto-Orient, Resize)과 Augmentation은 모두 끄고** 내려받는다(좌표가 어긋남). 모르는 클래스 이름·범위 밖 좌표는 쓰기 전에 중단 |
| 클래스 고정 | `python3 tools/yolo/build_dataset.py --init-classes` | **라벨링 시작 전에 1회.** `config/yolo_classes.txt`(줄 번호 = 클래스 id, 깃으로 추적)를 만든다. 물품을 추가하면 맨 뒤에 덧붙이고 앞 번호는 바꾸지 않는다. **실행 시점**: 물품 목록(이슈 #8 11종)이 온톨로지 `world.items`에 반영(PR #46 머지)된 뒤. 그 전에는 파일이 없어 `main`에서 구성 단계가 중단되는 것이 정상 |
| 구성 | `python3 tools/yolo/build_dataset.py --val s90_val_a s91_val_b` (고정 파일이 없으면 **중단**, 합성 점검만 `--allow-ontology-order`) | **세션 단위** 분할. 라벨 오류(id 범위·좌표 범위·이미지와 라벨 파일명 불일치)가 있거나 `yolo_classes.txt`에 온톨로지에 없는 이름이 있으면 중단 |
| 학습·평가 | `python3 tools/yolo/train.py --base <yolov8n.pt> --epochs 100 --name v1` | 검증 세션 mAP50 을 `runs/<name>/metrics.json`에 기록, 0.9 이상이면 통과(이슈 #14, [팀 확정 10/06, 사용자 전달]). 모델 점검 기준일 뿐 실제 합격은 AC-VIS-01·02 실물 측정 |
| yaw 비교 실험 | (이슈 [#62](https://github.com/Jik-Kim/ready2go/issues/62) YOLO-OBB, [#63](https://github.com/Jik-Kim/ready2go/issues/63) SAM2) | 데모 경로 밖. 정답 yaw 기록법은 `capture_session.py --gt-yaw-method`로 방법만 `session.yaml`에 남기고 실제 방법(각도 지그/격자 시트)은 #62에서 정한다 `[팀 확정 필요]`. OBB 라벨은 현재 detect 형식과 공존해야 하므로 `build_dataset.py`에 라벨 형식 선택(detect/obb)을 추가하는 방향 |
| 점검용 | `python3 tools/yolo/make_synthetic.py` | 합성 데이터. **파이프라인 점검 전용**, 학습 결과를 모델로 쓰지 않음 |

촬영 계획표와 촬영 전 점검 목록: [shooting_plan.md](shooting_plan.md)

## inspect_region 실제 노드 실행 [실측 10/06, 가짜 카메라로 시험 — 실제 카메라·로봇 TF는 미시험]
`vision` 이미지(torch·ultralytics 포함)에서 실행한다. 카메라 토픽·`base_link`→`wrist_cam_color_optical_frame` TF가 같은 DDS 도메인에 있어야 한다(로봇 드라이버·`ready2go_bringup`·realsense가 발행). 서랍 좌표는 `config/places.yaml`의 `drawer_top.tf`(3점 터치)에서 읽는다.
```bash
cd <저장소> && docker run --rm --gpus all --network host --user $(id -u):$(id -g) -e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/y -e ROS_DOMAIN_ID=70 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///repo/config/cyclonedds.local.xml -v $PWD:/repo -v $PWD/knowledge:/knowledge:ro -v $PWD/models:/models:ro -w /repo/ros2_ws ready2go-vision:latest bash -lc 'source /opt/ros/jazzy/setup.bash && colcon build --packages-up-to ready2go_vision && source install/setup.bash && ros2 run ready2go_vision inspect_region --ros-args -p config_dir:=/repo/config'
```
다중 PC면 `cyclonedds.multi.xml`과 `DDS_IFACE`·`PEER_PC1`·`PEER_PC2`를 쓴다(IP·NIC는 팀 `.env` 기준). 호출: `ros2 service call /vision/inspect_region ready2go_interfaces/srv/InspectRegion "{region: drawer_top, search_target: eraser}"`. 모델·토픽·프레임 이름은 노드 파라미터(`weights`, `color_topic`, `camera_frame` 등)로 바꾼다.

## 점검 결과 [실측 10/03, PC1 RTX 5060, yolo-detection 컨테이너]
- GPU: torch 2.11.0+cu128, `sm_120` 지원, CUDA 행렬 연산 정상 (#14 "GPU 호환 확인" 항목, RTX 5060).
- 합성 3클래스(세션 4개×20장, 검증 1세션)로 15 epoch 학습 약 7초, 검증 mAP50 0.908 — 파이프라인 동작 확인용 숫자일 뿐 모델 성능이 아님.
- 촬영 스크립트는 가짜 카메라 퍼블리셔(rgb8·16UC1)로 확인: 색 순서·뎁스 16bit·세션 중복 방지·정상 종료. **실제 RealSense로는 아직 안 해 봄.**
- 오류 경로: 없는 검증 세션, 잘못된 클래스 id는 종료 코드 1로 중단.

## 기본 가중치 비교 [실측 10/06, PC1 RTX 5060, `ready2go-vision` 이미지(ultralytics 8.4.170)]
- 조건: 학습 219장(`s01`~`s07`), 검증 20장(`s90_val_a`·`s91_val_b`, 63개 인스턴스, 클래스당 5~7개), `train.py` 기본값(imgsz 640, batch 16, 100 epoch, seed 0), 모델만 다르게. COCO 사전학습 가중치를 PC에 있던 것으로 사용(내려받지 않음). 모델당 학습 약 2분
- 지표는 검증 세션 기준, 정밀도·재현율은 F1이 최대인 신뢰도 지점 값, F1은 클래스별 F1 평균

| 기본 가중치 | 정밀도 | 재현율 | F1 | mAP50 | mAP50-95 | 최고 epoch |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `yolov8n` | 0.961 | 0.936 | 0.946 | 0.986 | 0.930 | 23 |
| `yolo11n` | 0.953 | 0.959 | 0.954 | 0.989 | 0.926 | 46 |
| `yolo26n` | 0.931 | 0.939 | 0.933 | 0.972 | 0.926 | 61 |

- 세 모델 모두 통과 기준 mAP50 0.9([팀 확정 10/06, 사용자 전달], [이슈 #14](https://github.com/Jik-Kim/ready2go/issues/14))를 넘었다. 이는 **모델 점검 기준**이고, 시스템 합격은 [requirements.md](../../docs/requirements.md#ac-vis-01)의 AC-VIS-01·02 실물 측정으로 한다
- 클래스별 AP50이 1.0 미만인 것: `caramel_box` 0.938 / 0.962 / 0.786(v8n / 11n / 26n), `airpods_case` 0.955 / 0.995 / 0.955, `lip_balm` 0.995 / 0.962 / 0.995. 나머지 8개는 모두 0.995
- **한계**: 검증이 20장·클래스당 5~7개라 0.01 안팎 차이는 순위로 보기 어렵다. 또 ① 최고 epoch(46)를 같은 검증셋으로 골랐고 별도 시험셋이 없으며, ② 검증 세션(`s90`·`s91`)이 학습과 같은 서랍·자세·조명·같은 물품 개체라 mAP50 0.989는 **낙관적일 수 있다**. 보충: `s92_val_c`(조명·시점·물품 배치가 다른 검증 세션, 로봇 필요)를 찍어 같은 조건으로 다시 평가한다
- **결정 [사용자 확정 10/06]: 기본 가중치는 `yolo11n`으로 한다.** 이유: ① 전체 지표 중 재현율(0.959)·F1(0.954)·mAP50(0.989)이 가장 높고 정밀도(0.953)도 v8n(0.961)과 0.01 차이뿐이다 ② 약한 클래스가 가장 적고 `caramel_box`(0.962)·`airpods_case`(0.995)가 v8n보다 높다 ③ `yolo26n`은 `caramel_box`가 0.786으로 크게 낮아 이 데이터에서는 이점이 없었다 ④ 추론 시간은 RTX 5060에서 v8n 1.8 / 11n 2.1 / 26n 1.3 ms/장(검증 1회 측정, 편차 있음)으로 모두 데모 요구에 비해 충분히 빠르고, 11n이 조금 느려도 선택을 바꿀 차이는 아니다 [실측 10/06]. 한계: 검증이 작아 격차가 크지 않으므로, 이후 필요하면 **추가 라벨링·검증 세션(`s92_val_c` 등)을 더하고 같은 조건으로 다시 학습**해 확인한다. 재학습 때 11n이 뒤처지면 이 결정을 다시 연다
- 통과 기준 mAP50 0.9는 [팀 확정 10/06, 사용자 전달]. 확정 모델 파일은 `models/yolo11n_ready2go_v1.pt`(Git LFS, 이 파일만 `.gitignore` 예외, 설명은 `models/README.md`)
- 재현: 저장소를 컨테이너에 마운트하지 않으므로 `data/yolo`·`data/labeled`(이미지가 `data/labeled`로의 심볼릭 링크)를 같은 경로로 마운트하고 `train.py --base <가중치> --name <이름> --data <dataset.yaml>`을 실행한다. 결과(`runs/`)는 저장소 밖에 두면 깃 상태가 어지러워지지 않는다

## 주의
- `data/`, `runs/`는 `.gitignore`(용량). 확정한 가중치만 `models/`에 둔다 — `.gitignore`의 `models/*.pt` 때문에 한 파일씩 예외로 Git LFS에 올린다(해결: [`models/README.md`](../../models/README.md)).
- RTX 4060(PC2)에서의 동작은 미확인(`docker/vision/Dockerfile`의 TODO).
