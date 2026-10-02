# 캘리브레이션 결과 (담당 A 김병직)
- `T_gripper2camera.npy`: 강의 Calibration_Tutorial로 재측정한 핸드-아이 결과 (광학 프레임 기준, `link_6 → wrist_cam_color_optical_frame`)
- 측정일·오차(`verify.py` 결과)를 [실측] 태그로 이 파일에 기록

## TF 구조 (결정 #23, A안)
- bringup이 발행하는 TF는 `link_6 → wrist_cam_link` **1개**. `wrist_cam_link` 아래 광학 프레임은 realsense 드라이버의 `/tf_static`을 그대로 사용.
- `T_link6→cam_link = T_link6→color_optical(핸드-아이) × (T_cam_link→color_optical)⁻¹` 로 변환해 저장. `T_cam_link→color_optical`은 드라이버 `/tf_static`에서 읽은 값.
- 이 폴더에는 **핸드-아이 원본, 변환 결과, 변환에 사용한 드라이버 TF 값(`T_cam_link→color_optical`)** 을 모두 저장.

## 캘리브레이션 시 기록할 것
| 항목 | 값 | 근거 |
| :--- | :--- | :--- |
| 측정일 | | |
| 펜던트 TCP 설정 (가능하면 해제) | | [실측] |
| `link_6`의 실제 프레임 이름 (`dsr01` 접두어 여부) | | [실측] `view_frames` |
| `posx` 단위 변환 (mm, ZYZ 오일러각 → m, 쿼터니언) | | [실측] |
| 사용한 드라이버 TF 값 (`T_cam_link→color_optical`) | | [실측] `/tf_static` |
| 검증 오차 (`verify.py`) | | [실측] |
