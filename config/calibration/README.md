# 캘리브레이션 결과 (담당 A 김병직)
- `T_gripper2camera.npy`: 강의 Calibration_Tutorial로 재측정한 핸드-아이 결과 (광학 프레임 기준, `link_6 → wrist_cam_color_optical_frame`)
- 측정일·오차(`verify.py` 결과)를 [실측] 태그로 이 파일에 기록

## TF 구조 (결정 #23, A안)
- bringup이 발행하는 TF는 `link_6 → wrist_cam_link` **1개**. `wrist_cam_link` 아래 광학 프레임은 realsense 드라이버의 `/tf_static`을 그대로 사용.
- `T_link6→cam_link = T_link6→TCP × T_TCP→color_optical(핸드-아이) × (T_cam_link→color_optical)⁻¹` 로 변환해 저장.
  - 핸드-아이 결과(`T_gripper2camera.npy`)는 **TCP 프레임 기준**임(강의 코드가 `set_tcp` 후 `get_current_posx`를 읽음, 결정 #23 ①). 평행이동 mm, 회전 행렬 → TF에는 m와 쿼터니언으로 변환.
  - `T_link6→TCP`는 펜던트에 등록된 TCP 오프셋. `T_cam_link→color_optical`은 드라이버 `/tf_static`에서 읽은 값.
- 이 폴더에는 **핸드-아이 원본, 변환 결과, 변환에 사용한 드라이버 TF 값, TCP 오프셋** 을 모두 저장.

## 현재 파일 상태
- `T_gripper2camera.npy`: A가 2026-10-01에 직접 측정한 값(26장, 코드상 TCP `2FG_TCP`, 펜던트 표시는 `GripperDA_V1` — 어제 활성 TCP 확인 필요). **채택 후보이며 `calibration_meta.yaml`의 `verified.error_cm`이 채워지기 전에는 [추정]**.
- `calibration_meta.yaml`: 측정 조건(TCP 이름·오프셋·툴 무게는 펜던트 [실측], 이미지 수, 포즈 범위)과 아직 비어 있는 항목(어제 활성 TCP, 카메라 시리얼, 검증 오차).
- 강의 샘플 `T_gripper2camera.npy`(해시 `27cf64…`)는 쓰지 않음.

## 채택 절차
1. **TCP 확인**: 펜던트 표시는 `GripperDA_V1`, 오프셋 z=228 mm, 회전 0 [실측 10/02]. 강의 코드의 `set_tcp("2FG_TCP")`와 이름이 다르지만, 펜던트 TCP 목록에 `GripperDA_V1`만 있으므로(10/02 확인) `2FG_TCP`는 무효였고 어제 기준은 `GripperDA_V1`로 판단 [추정, 확신 높음]. 남은 일: B의 모션이 같은 TCP(`set_tcp("GripperDA_V1")`로 명시 지정, **반환값 확인**)를 쓰는지 확인.
2. 오차 확인: A가 `verify.py`로 확인(오차 1 cm 미만, 체스판 중앙 파지 육안 확인 [사용자 보고]), B가 팀 구성에서 적용 확인(10/02). **결정 #22 기준(1.0 cm 이내) 만족 → 채택.** 자로 잰 수치는 없으므로 정밀 수치가 필요하면 `verify.py`로 5점 이상 재측정.
3. 변환식으로 `link_6 → wrist_cam_link`를 계산해 `calibration_meta.yaml`의 `derived_tf`에 저장함(10/02 [계산]). 남은 일: bringup의 TF 설정 형식을 C와 합의해 반영.

## 캘리브레이션 시 기록할 것
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 측정일 | | |
| 펜던트 TCP 설정 (가능하면 해제) | | [실측] |
| `link_6`의 실제 프레임 이름 (`dsr01` 접두어 여부) | | [실측] `view_frames` |
| `posx` 단위 변환 (mm, ZYZ 오일러각 → m, 쿼터니언) | | [실측] |
| 사용한 드라이버 TF 값 (`T_cam_link→color_optical`) | | [실측] `/tf_static` |
| 검증 오차 (`verify.py`) | | [실측] |
