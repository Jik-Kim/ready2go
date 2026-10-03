# 캘리브레이션 (담당 A 김병직)

> 값은 [calibration_meta.yaml](calibration_meta.yaml)에만 있다. 이 문서는 **절차**만 적는다. 결정: 이슈 #3(TF 구조), #7(캘리브레이션·프로젝트 TCP).

**상태: 채택 — B의 5점 `verify.py` 실측(10/03)으로 확정.** 기준은 이슈 #7의 합격 기준(오차 1.0 cm 이내), 결과는 meta의 `verified`.

> ⚠️ 강의 폴더 `corecode/Calibration_Tutorial/T_gripper2camera.npy`(2026-02, md5 `ed3c4a6c…`)는 이 폴더의 채택 값(md5 `dea4dee3…`)과 다르며 z가 약 31 mm 높게 계산된다. 강의 코드로 실행할 때는 이 폴더의 npy를 복사해 쓴다.

## 파일
| 파일 | 내용 |
| :--- | :--- |
| `T_gripper2camera.npy` | 핸드-아이 결과. **TCP 프레임 기준**(강의 코드가 `set_tcp` 후 `get_current_posx`를 읽음), 평행이동 mm |
| `calibration_meta.yaml` | 측정 조건, TCP·툴, 검증 상태, 드라이버 TF, 계산된 `derived_tf` |

강의 샘플 `T_gripper2camera.npy`(해시 `27cf64…`)는 쓰지 않는다. 강의 코드의 `2FG_TCP`는 이 로봇의 TCP 목록에 없는 이름이므로 그대로 쓰면 안 된다.

## TF 구조
bringup이 발행하는 TF는 `link_6 → wrist_cam_link` **1개**. `wrist_cam_link` 아래 광학 프레임은 realsense 드라이버의 `/tf_static`을 그대로 쓴다(한 프레임은 부모를 하나만 가질 수 있어 광학 프레임에 직접 걸면 충돌).

`T_link6→cam_link = T_link6→TCP × T_gripper2camera × (T_cam_link→color_optical)⁻¹`

## 재계산
```bash
python3 tools/calib_derive_tf.py          # 계산 + meta의 derived_tf와 비교 (불일치 시 종료 코드 1)
python3 tools/calib_derive_tf.py --print  # 계산 결과만 출력
```
- 허용 오차: 평행이동 `1e-5` m, 회전 `0.01`° (`--tol-m`, `--tol-deg`로 변경).
- 입력은 meta의 `tcp.offset_from_pendant`와 `driver_tf_used`, 그리고 `T_gripper2camera.npy`.
- 출력의 `derived_tf`로 meta의 `derived_tf`를 교체한다. 출력 쿼터니언은 `w ≥ 0`으로 정규화되어 있다.
- 단위: 평행이동 mm→m, TCP 회전은 두산 `posx`와 같은 ZYZ 오일러각(deg).

## 다시 계산해야 하는 경우
- **카메라를 바꿈**: `driver_tf_used`를 새 카메라의 `/tf_static`에서 다시 읽어 갱신(개체마다 조금 다름). 마운트(브래킷)를 다시 달았다면 캘리브레이션 자체를 다시 한다.
- **TCP 오프셋이 바뀜**(B 확인 결과 등): `tcp.offset_from_pendant` 갱신. 캘리브레이션 당시의 TCP가 달랐다면 `npy`도 영향을 받는다.
- 위 변경 후에는 스크립트를 돌리고 결과를 PR에 기록한다.

## bringup에 반영하기 전 확인
1. `link_6`의 실제 프레임 이름(`dsr01` 접두어 여부): `view_frames`로 확인.
2. `link_6` 원점이 플랜지 면과 같은 위치인지, TCP 오프셋 값과 툴 무게가 실제 RG2와 맞는지: B 확인 요청 중(#7).
3. TF 설정 파일 형식: C와 합의(#3).

## 확정 절차 (잠정 → 채택)
1. `verify.py`로 5점 이상 측정해 최대 오차를 `verified.error_cm`에 기록.
2. 이슈 #7 합격 기준(1.0 cm 이내)이면 `verified.status: accepted`로 바꾸고, 이 문서의 상태 줄과 meta 맨 위 상태 줄을 함께 고친다.
3. 기준을 넘으면 재측정한다.
