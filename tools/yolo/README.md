# YOLO 데이터 수집·학습 도구 (담당 A, #14)

실물 데이터로 물품 검출 모델을 만드는 도구. 순서: **촬영 → 라벨링 → 데이터셋 구성 → 학습·평가**. 학습은 `yolo-detection` 컨테이너(PC1, RTX 5060)에서 한다 — 저장소가 마운트돼 있지 않으므로 `docker cp tools knowledge yolo-detection:/작업폴더/`로 복사해 쓴다(스크립트는 자기 위치 기준으로 `data/`·`runs/`를 만든다).

| 단계 | 명령 | 비고 |
| :--- | :--- | :--- |
| 촬영 | `python3 tools/yolo/capture_session.py s01_basic --note "배치 메모" --interval 1 --count 30` | 세션 = 배치 하나. 컬러 + 정렬 뎁스를 `data/raw/<세션>/`에 저장. 구독만 하고 로봇은 움직이지 않음. 로봇은 `drawer_top_view` 포즈(B) |
| 라벨링 | (외부 도구) 결과를 `data/labeled/<세션>/images`, `labels`(YOLO txt)로 | 클래스 id = `config/yolo_classes.txt` 줄 번호. 학습 결과(`metrics.json`)에 사용한 클래스 목록이 기록된다 |
| 라벨링 보조 | `python3 tools/yolo/auto_label_single.py s01_single_v0` | **한 장에 물품 하나인 세션 전용.** `data/raw/<세션>/class_ranges.txt`(번호 구간 ↔ 물품; 한 줄에 `0000-0005 airpods_case`, `#`로 시작하면 주석, 물품 이름은 `yolo_classes.txt`와 같아야 함. **손으로 작성**한다 — `capture_session.py`가 만들지 않는다. 후속: 촬영 때 `session.yaml`에 구간을 기록) + 정렬 뎁스 덩어리 + 빈 서랍 배경과의 색 차이로 박스 초안을 만든다. 서랍 바닥 영역(ROI)은 기준 시점 `drawer_top_view` 기준이라 시점 변화 세션에는 쓰지 않는다. ROI(`FLOOR_ROI` = (268, 108, 1008, 614), 화면 좌표)는 `drawer_top_view`를 다시 가르치면 다시 재야 한다. `carrot_pen`은 색 분할로 끝까지 따라간다. **재실행**: 출력 폴더(`data/labeled/<세션>`)에 이전 결과가 있으면 기본은 중단한다(손으로 고친 라벨 보호). `--force`를 붙이면 작업 폴더(`data/.auto_label_work/<세션>`)에 전부 만들고 **끝까지 성공했을 때만** 한 번에 교체한다(중간에 오류로 끊기면 기존 출력은 그대로, 불완전한 세션이 남지 않음). 교체될 장수를 출력한다(원본 `data/raw`는 건드리지 않음). 박스는 몇 px 넉넉하고, 더 조이면(색 차이만) 흰색·주황색 물체가 잘려서 사람 확인이 필요하다 |
| 박스 수정 | `python3 tools/yolo/review_boxes.py <세션> --labeled data/labeled --out data/labeled_fixed` | 한 장에 박스 하나인 라벨을 OpenCV 창에서 드래그로 고친다(Enter 확정). 오프라인 대안이며, Roboflow를 쓰면 필요 없다 |
| Roboflow 복원 | `python3 tools/yolo/import_roboflow.py data/roboflow_export [--dry-run]` | Roboflow YOLOv8 내보내기를 우리 규칙으로 되돌린다: 클래스는 **이름으로** `yolo_classes.txt` 번호에 재매핑, 파일 이름 접두어(`s01_…`)로 세션 복원, 이미지는 원본 PNG. 버전을 만들 때 **Preprocessing(Auto-Orient, Resize)과 Augmentation은 모두 끄고** 내려받는다(좌표가 어긋남). 모르는 클래스 이름·범위 밖 좌표는 쓰기 전에 중단 |
| 윤곽 초안 (P2 분할, #109) | `python3 tools/yolo/sam_polygon_draft.py --sam <sam2.1_b.pt> [세션 ...] [--show --wait 0]` | 사람이 확인한 상자 라벨(`data/labeled`)을 SAM2에 상자 프롬프트로 넣어 윤곽(YOLO 분할 형식) 초안을 `data/roboflow_upload_seg/<세션>/`에 만든다(Roboflow 업로드용, `data.yaml` 포함). 같은 픽셀을 두 윤곽이 칠하면 작은 쪽(위에 얹힌 물체)에 주고, 가려져 조각난 물체는 조각을 이어 윤곽 하나로. 의심(겹침 뺏김·조각 여러 개·면적비) 목록은 업로드 폴더 밖 `_reports/<세션>.csv`(Roboflow 가 CSV 를 주석으로 읽어 업로드 오류), 미리보기 `_preview/`. `--show` 는 처리 과정을 창으로(컨테이너면 `DISPLAY`·`/tmp/.X11-unix`, `xhost +SI:localuser:$(whoami)`). 초안이므로 Roboflow 에서 전부 확인한다 |
| 분할 라벨 복원 | `python3 tools/yolo/import_roboflow.py <분할 내보내기> --seg [--boxes data/labeled]` | 폴리곤 라벨을 `data/labeled_seg`로. 가려져 조각난 물체는 같은 클래스 조각 여러 개로 그려 오므로, 상자 라벨 기준으로 조각을 물체에 배정해 하나로 합친다(`seg_merge.py`, 같은 클래스 상자가 하나뿐이면 상자 밖 조각도 그 물체로). 상자 라벨과 맞지 않는 장(새 물체·윤곽 없는 상자·상자 밖 조각)을 보고 → 상자 라벨 보정 근거 |
| 클래스 고정 | `python3 tools/yolo/build_dataset.py --init-classes` | **라벨링 시작 전에 1회.** `config/yolo_classes.txt`(줄 번호 = 클래스 id, 깃으로 추적)를 만든다. 물품을 추가하면 맨 뒤에 덧붙이고 앞 번호는 바꾸지 않는다. **실행 시점**: 물품 목록(이슈 #8 11종)이 온톨로지 `world.items`에 반영(PR #46 머지)된 뒤. 그 전에는 파일이 없어 `main`에서 구성 단계가 중단되는 것이 정상 |
| 구성 | `python3 tools/yolo/build_dataset.py --val s90_val_a s91_val_b` (고정 파일이 없으면 **중단**, 합성 점검만 `--allow-ontology-order`) | **세션 단위** 분할. 라벨 오류(id 범위·좌표 범위·이미지와 라벨 파일명 불일치)가 있거나 `yolo_classes.txt`에 온톨로지에 없는 이름이 있으면 중단 |
| 학습·평가 | `python3 tools/yolo/train.py --base <yolov8n.pt> --epochs 100 --name v1` | 검증 세션 mAP50 을 `runs/<name>/metrics.json`에 기록, 0.9 이상이면 통과(이슈 #14, [팀 확정 10/06, 사용자 전달]). 모델 점검 기준일 뿐 실제 합격은 AC-VIS-01·02 실물 측정 |
| yaw 비교 실험 | (이슈 [#62](https://github.com/Jik-Kim/ready2go/issues/62) YOLO-OBB, [#63](https://github.com/Jik-Kim/ready2go/issues/63) SAM2) | 데모 경로 밖. 정답 yaw 기록법은 `capture_session.py --gt-yaw-method`로 방법만 `session.yaml`에 남기고 실제 방법(각도 지그/격자 시트)은 #62에서 정한다 `[팀 확정 필요]`. OBB 라벨은 현재 detect 형식과 공존해야 하므로 `build_dataset.py`에 라벨 형식 선택(detect/obb)을 추가하는 방향 |
| 점검용 | `python3 tools/yolo/make_synthetic.py` | 합성 데이터. **파이프라인 점검 전용**, 학습 결과를 모델로 쓰지 않음 |

촬영 계획표와 촬영 전 점검 목록: [shooting_plan.md](shooting_plan.md)

## inspect_region 실제 노드 실행 [실측 10/06, 가짜 카메라로 시험 — 실제 카메라·로봇 TF는 미시험]
`vision` 이미지(torch·ultralytics 포함)에서 실행한다. 카메라 토픽·`base_link`→`wrist_cam_color_optical_frame` TF가 같은 DDS 도메인에 있어야 한다(로봇 드라이버·`ready2go_bringup`·realsense가 발행). 서랍 좌표는 `config/places.yaml`의 `drawer_top.tf`(3점 터치)에서 읽는다.
```bash
cd <저장소> && docker run --rm --gpus all --network host --user $(id -u):$(id -g) -e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/y -e ROS_DOMAIN_ID=70 -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///repo/config/cyclonedds.local.xml -v $PWD:/repo -v $PWD/knowledge:/knowledge:ro -v $PWD/models:/models:ro -w /repo/ros2_ws ready2go-vision:latest bash -lc 'source /opt/ros/jazzy/setup.bash && colcon build --build-base /tmp/build --install-base /tmp/install --packages-up-to ready2go_vision && source /tmp/install/setup.bash && ros2 run ready2go_vision inspect_region --ros-args -p config_dir:=/repo/config'
```
- 빌드는 컨테이너 안 `/tmp`에만 한다. 호스트 `ros2_ws/build`·`install`에 `/repo` 경로가 남으면 다른 컨테이너 빌드와 CMakeCache 경로가 충돌한다(#3, C 검토 #80).
- **stub 노드(`inspect_region_stub`)와 동시에 켜지 않는다.** 같은 서비스 이름 `/vision/inspect_region`이 둘이 된다.
- **서랍 영역 ROI (뎁스 전) [10/07]**: 박스 중심을 서랍 바닥(z=0)에 투영한 점이 서랍 안쪽 + `region.detect_roi_margin_m`(0.025) 밖이면 뎁스 계산 전에 뺀다(로그 `skip: 서랍 영역 밖`). 서랍 밖 책상 위 케이블·화면 끝 물체·그리퍼 손끝 오검출이 뎁스 실패로 호출 전체를 `DEPTH_INVALID`로 만들던 문제 [실측 PC2 10/07]. 실물 덤프 59장 재계산: 55장 결과 그대로, 서랍 밖 물체로 실패하던 4장만 성공으로 바뀜(0.02~0.04 모두 같음). 서랍 안 결과 물체의 투영 초과는 최대 3.3 mm, 그리퍼 손끝 자리는 36~46 mm 밖이라 0.025로 둠. 렌즈 가림처럼 **서랍 안** 뎁스가 빈 경우는 그대로 `DEPTH_INVALID`
- **경계 여유 점검**: `region.edge_tolerance_m`(0.015)이 AC-VIS-01 허용 오차(1.5 cm)와 같다. 서랍 밖으로 이만큼 나간 footprint까지 결과에 들어가므로, 실물 점검 때 서랍 테두리 위·바깥에 둔 물체가 `target`·`candidates`로 나오지 않는지 확인한다(검출별 로그의 `skip`·`xy`로 확인). **이 여유는 비전 측정 오차 허용이고 모션 안전 경계가 아니다**: 벽에 붙은 물체의 좌표는 정상 `target`으로 나가며, 그리퍼가 벽에 걸리는지는 B 스킬(끌기 `plan_drag`, `pick_object` 사전 검사)이 판단한다(D 재검토 P1, #80)
- 실물 첫 연결 시험은 `bash tools/dev/vision_real_check.sh camera|check|node|call|measure|replay`로 한다. 카메라·로봇이 같은 PC면 `DDS_MODE=local`, 카메라·비전은 PC1이고 로봇은 PC2면 양쪽 `DDS_MODE=multi`(+`DDS_IFACE`·`PEER_PC1`·`PEER_PC2`). 사용법은 스크립트 첫 부분. `node`는 `-p dump_dir:=` 로 요청마다 컬러·뎁스·K·TF·검출·결과를 `.npz`로 저장하고, `replay`(`tools/dev/replay_inspect_dump.py`)가 로봇 없이 다시 계산한다(`--truth X Y YAW`로 손끝 정답과 위치 오차, `--dz-mm`으로 서랍 원점 이동 영향).
- 진단 로그(결과에는 영향 없음): 요청마다 검출별 판단 근거(`top_z`, 덩어리 크기, 제외 사유)와 카메라로 본 서랍 바닥 z(`core/floor_probe.py`, 중앙값·10/90 백분위)를 남긴다. 시작 로그에 가중치·`places.yaml`·`vision_params.yaml` 해시와 `drawer_top.tf`를 남긴다.
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


### 스몰 모델 추가 비교 [실측 10/06, E 요청]
- 조건은 위와 같다(학습 219장, 검증 20장, 640, batch 16, 100 epoch, seed 0). 6개 모델을 같은 검증셋으로 다시 평가했다
- 사전학습 가중치 내려받기 **승인: 사용자, 10/06 약 14:50 KST**(A 작업 세션에서 파일명·출처·크기를 밝히고 승인받음, shooting_plan.md 1장 "내려받기 승인을 따로 받는다"). 출처 `https://github.com/ultralytics/assets/releases/download/v8.4.0/<파일명>`, PC1 `~/yolo_weights/`에 보관 [실측 10/06]
  - `yolov8s.pt` 22,588,772 B, sha256 `1f47a78bf100391c2a140b7ac73a1caae18c32779be7d310658112f7ac9aa78a`
  - `yolo11s.pt` 19,313,732 B, sha256 `85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5`
  - `yolo26s.pt` 20,422,725 B, sha256 `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`
- 추론 시간은 검증 20장을 1장씩 `predict`한 값(이미지 읽기·전처리 포함, 워밍업 뒤 3회 중앙값). 순수 GPU 추론은 학습 로그상 나노 약 2 ms, 스몰 약 6 ms

| 기본 가중치 | 정밀도 | 재현율 | F1 | mAP50 | mAP50-95 | 파라미터 | 파일 | ms/장 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `yolov8n` | 0.961 | 0.936 | 0.946 | 0.986 | 0.930 | 3.0M | 6 MB | 13.7 |
| `yolo11n` | 0.953 | 0.959 | 0.954 | 0.989 | 0.926 | 2.6M | 5 MB | 14.3 |
| `yolo26n` | 0.931 | 0.939 | 0.933 | 0.972 | 0.926 | 2.5M | 5 MB | 14.4 |
| `yolov8s` | 0.958 | 0.929 | 0.940 | 0.981 | 0.922 | 11.1M | 23 MB | 15.0 |
| `yolo11s` | 0.948 | 0.994 | 0.968 | 0.991 | 0.941 | 9.4M | 19 MB | 14.8 |
| `yolo26s` | 0.954 | 0.964 | 0.958 | 0.992 | 0.958 | 10.0M | 20 MB | 15.2 |

- 지우개(P1 대상, 검증 7개): 6개 모두 7개를 다 찾았다(AP50 0.995). 정답 박스와의 중심 오차 평균/최대(px)와 지우개 AP50-95: v8n 1.56/2.67·0.928, **11n 1.25/2.70·0.914**, 26n 1.57/3.34·0.917, v8s 1.22/2.68·0.936, **11s 0.98/1.76·0.973**, 26s 1.19/1.80·0.930. 1 px는 `drawer_top_view` 거리(약 0.37 m)에서 약 0.4 mm라 모두 AC-VIS-01(15 mm)에 비해 작다 [계산]
- 해석: 스몰 2종(11s·26s)이 전체 지표에서 조금 높지만 11n과의 재현율 차이 0.035는 63개 중 약 2개이고, 클래스별 F1은 모델마다 크게 흔들린다(`caramel_box` 0.72~0.97). 위 한계(검증 20장)를 그대로 받는다
- **결정 [사용자 10/06]: 실물에서 `yolo11n`(현재)과 `yolo11s` 두 개를 한 번 더 비교한다.** 스몰 중 11s를 고른 이유: 전체 재현율·F1이 가장 높고, P1 대상 지우개의 박스 중심 오차·AP50-95가 6개 중 가장 좋다(26s는 전체 mAP50-95는 가장 높지만 지우개에서는 11s보다 낮다). 방법: 실물 호출마다 저장한 프레임(`dump_dir`)에 `tools/dev/replay_inspect_dump.py --weights`로 11s를 다시 검출해, **같은 프레임·같은 손끝 정답**으로 위치 오차를 비교한다(로봇 시간 추가 없음, `bash tools/dev/vision_real_check.sh`의 `WEIGHTS=... replay`). 결과 전까지 `models/`의 모델은 `yolo11n` 그대로이며 11s 가중치는 저장소 밖에 둔다: PC1 `~/yolo_run/runs/11s/weights/best.pt`, sha256 `5a2aeb869c3423d34ff0427df0c6c67b7cfcdd3bf3ea13687466f73096c98e9c` [실측 10/06]. 백업은 아직 없음(실물 비교에서 채택되면 `models/`로 옮기고 LFS 예외를 바꾼다)
- **실물 비교 결과 [실측 10/07, #14·#18]**: 실물 슬롯 프레임 35장(지우개 측정 22 + 물품 10종 혼합 13)을 두 모델로 다시 검출. `conf_min` 0.25에서 호출 실패 11n 2·11s 9 — 11s는 화면 아래 그리퍼 아랫부분을 `toy_wrench`(conf 0.26~0.41, 매번 같은 픽셀 자리)로 6회 오검출, 중복 검출 11n 1·11s 5. 위치 오차(손끝 정답 3배치)는 같음(1.1~3.2 mm). 반대로 망치·렌치처럼 긴 물체가 겹치면 11n이 망치를 `toy_wrench`로 오분류·놓치고 11s는 맞게 잡음(2장면). `conf_min` 0.5 시뮬레이션: 그리퍼 오검출은 모두 걸러져 실패 11n 1·11s 3(남은 것은 서랍 밖 물체), 11s 중복 4건은 남음
- **겹침 장면 추가 [실측 10/07, #14 보충]**: 겹침 13장면을 더 찍어 같은 방식으로 비교하니, X자 망치·렌치에서 두 모델 모두 렌치를 놓쳤고 위의 "겹침은 11s가 나음"은 재현되지 않았다. 그리퍼 마스크 + `conf_min` 0.5 + 중복 병합 조건으로 누적 56장: 놓침 11n 10 · 11s 10, 헛검출 둘 다 1 — 동률
- **결정 [사용자 10/07]: P1·P2 모두 `yolo11n` 유지.** 겹친 긴 물체를 놓치는 것은 두 모델 공통이라 학습 데이터 문제로 본다. P2: 겹침 장면(10/07 프레임 21장부터) 라벨링·재학습, 그리퍼 영역 마스크·같은 클래스 중복 병합 추가, `conf_min` 0.5는 재학습 뒤 10/07 회귀 세트 56장으로 다시 정함. 11s 가중치는 위 경로(저장소 밖) 그대로

### 겹침 데이터 재학습 v2 [실측 10/07, #14]
**P1 운용에는 영향 없음 — P1은 `models/yolo11n_ready2go_v1.pt` 그대로.** 아래 v2와 P2 방침은 제안이며 노드에는 아직 없다(P2 구현 예정).
- 데이터: 겹침 세션 `s08_overlap_long_v0` 17장·`s09_overlap_mix_v0` 25장(학습), `s92_val_c` 10장(검증)을 `capture_session.py`로 새로 촬영(10/07 09:35~10:03 KST). 위 결정의 "10/07 프레임 21장부터"는 실물 호출 덤프였으나 실제로는 덤프를 학습에 쓰지 않고 새 세션을 찍었다. 라벨은 v1 박스 초안 + Roboflow에서 사람이 전부 수정. `s91_val_b/0008`에 빠져 있던 판 밑 `car_key` 라벨 1개를 추가함. 학습 261장, 검증 30장. 학습 조건은 위와 같음(640, batch 16, 100 epoch, seed 0)
- **검증셋이 바뀌었으므로 10/06 수치와 직접 비교하지 않는다.** 같은 v1이 10/06 검증(20장, `s90`·`s91`, 라벨 수정 전) mAP50 0.989, 10/07 검증(30장, `s92` 추가·라벨 1개 수정) 0.966이다

| 모델 | 검증셋 | 정밀도 | 재현율 | mAP50 | mAP50-95 | 최고 epoch |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| v1 `yolo11n` | 10/06 · 20장 | 0.953 | 0.959 | 0.989 | 0.926 | 46 |
| v1 `yolo11n` | 10/07 · 30장 | 0.948 | 0.927 | 0.966 | 0.874 | 46 |
| v2 `yolo11n` | 10/07 · 30장 | 0.976 | 0.935 | 0.981 | 0.894 | 66 |
| v2 `yolo11s` | 10/07 · 30장 | 0.945 | 0.973 | 0.990 | 0.913 | 81 |
| v2 `yolo26s` | 10/07 · 30장 | 0.959 | 0.975 | 0.992 | 0.932 | 90 |

- 모두 같은 검증셋 기준 통과 기준 mAP50 0.9 이상(10/07 · 30장에서 v1 0.966 포함)
- 실물 56장(10/07 실물 호출 덤프, 정답은 사진의 서랍 안 물품 목록, 그리퍼 마스크 + 같은 클래스 병합 + 서랍 밖 제외를 계산으로 적용, `conf_min` 0.30): 놓침 v1 8 · 11n v2 2 · 11s v2 2 · 26s v2 2, 병합 후 헛검출 2 · 2 · 1 · 5, 병합 전 헛검출 6 · 2 · 8 · 6. 놓침 중 `car_key` 1건은 네 모델 모두 검출했지만 footprint 검사(서랍 가장자리)에서 빠진 것
- **평가 프레임과 학습 이미지 겹침 없음**: 56장(덤프 `.npz` 컬러)과 학습·검증 이미지 291장의 픽셀 SHA-256 일치 0, 축소 영상 평균 밝기차 최소 4.1(같은 장면 반복 촬영은 0.7, 서로 다른 배치 장면이 가장 가까운 짝) [실측 10/07]. 다만 같은 물품·같은 서랍·비슷한 겹침 배치라 겹침 13장면의 개선 폭은 실제보다 좋을 수 있다
- `conf_min`(11n v2): 0.30 → 0.32·0.35·0.45에서 실물 놓침 2 → 3·4·5. 0.30~0.45에서 맞은 검출은 모두 다른 물체 밑에 깔린 물품. 0.25~0.35 헛검출 3건은 서랍 밖 투명 통(서랍 밖 제외로 해결)
- **P2 방침 [제안, #14]**: `yolo11n` v2 + `conf_min` 0.30 + 서랍 밖 검출 제외(뎁스 전) + 그리퍼 영역 마스크 + 같은 클래스 중복 병합. 11s·26s는 검증 수치는 높지만 실물에서 상자 쪼개기·중복이 많고 놓침은 같음. 표본(실물 56·검증 30)이 작아 P2 실물 시험에서 다시 확인. 인스턴스 분할(`yolo11n-seg`)은 [#109](https://github.com/Jik-Kim/ready2go/issues/109)에서 논의 중이며, 채택되면 v2 검출 모델을 대체한다. 방식 관계(분할·OBB·SAM2) 정본: [#109 PM 정리](https://github.com/Jik-Kim/ready2go/issues/109#issuecomment-6033256883)
- 가중치(저장소 밖, `models/`에 아직 넣지 않음): PC1 `~/yolo_run/runs/<이름>/weights/best.pt`
  - `11n_v2` 5,458,650 B, sha256 `3592425b0a96d1185e747157d7f618a9c660fc629786d4fc39c773f445313549`
  - `11s_v2` 19,167,706 B, sha256 `1aade00a95370d1b892c4475115dafc5158b0b76fe96d21db0a4d3e1715ed57b`
  - `26s_v2` 20,309,573 B, sha256 `54cfb435e1f5486442a6445ce24102738f9cd8567154f5dfdeca83394ccd1fd0`
  - 백업 [10/07, A 개인 Google Drive `내 드라이브/P2/backups/`]: `ready2go_yolo_v2_20261007.tar.gz`(67 MB, 위 가중치 3개·학습 설정·지표, 비교 사진·스크립트, Roboflow 내보내기, 현재·이전 라벨 `.txt`) sha256 `1f83a57e3f9b273f6990278545973387e09ab51719561548d497dc995d25917d`, `ready2go_raw_20261007.tar`(380 MB, 원본 촬영 `data/raw` 전체) sha256 `b9d336048b26921a35bbd8b47945c25846760e4bde9b0146365e1580d3ea581a`. 묶음의 PC1 사본은 업로드 뒤 지움(원본 파일은 위 경로에 그대로)
  - 비교 사진·스크립트 `~/yolo_run/compare_v2/`, 라벨 `data/labeled`(이전 라벨 `data/labeled_backup_1007`), Roboflow 내보내기 `data/roboflow_export_1007`

## 주의
- `data/`, `runs/`는 `.gitignore`(용량). 확정한 가중치만 `models/`에 둔다 — `.gitignore`의 `models/*.pt` 때문에 한 파일씩 예외로 Git LFS에 올린다(해결: [`models/README.md`](../../models/README.md)).
- RTX 4060(PC2)에서의 동작은 미확인(`docker/vision/Dockerfile`의 TODO).
