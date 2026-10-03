"""OnRobot RG2 Modbus TCP 레지스터 규약 (ROS·통신 비의존, pytest 대상).

레지스터 주소와 단위는 OnRobot Compute Box Modbus 표 기준 [문서].
실물 동작은 adapters/rg2.py에서 확인 [실측 필요].
"""
from dataclasses import dataclass

UNIT_ID = 65                 # Compute Box의 RG2 Modbus unit(slave) ID

# 쓰기 레지스터
REG_TARGET_FORCE = 0         # 목표 힘, 1/10 N
REG_TARGET_WIDTH = 1         # 목표 폭, 1/10 mm
REG_CONTROL = 2              # 1 = grip, 8 = stop, 16 = grip(손끝 오프셋 반영)

# 읽기 레지스터
REG_WIDTH_WITH_OFFSET = 275  # 현재 폭(손끝 오프셋 반영), 1/10 mm
REG_STATUS = 268             # 상태 비트 (아래 STATUS_*)

CONTROL_GRIP = 16
CONTROL_STOP = 8

STATUS_BUSY = 1 << 0
STATUS_GRIP_DETECTED = 1 << 1
STATUS_SAFETY_ERROR = 1 << 6

MAX_WIDTH_MM = 110.0
MAX_FORCE_N = 40.0


def grip_command(width_mm: float, force_n: float) -> list[int]:
    """목표 폭·힘 → 레지스터 0~2에 쓸 값 [force, width, control]."""
    if not 0.0 <= width_mm <= MAX_WIDTH_MM:
        raise ValueError(f"width_mm는 0~{MAX_WIDTH_MM} 범위: {width_mm}")
    if not 0.0 < force_n <= MAX_FORCE_N:
        raise ValueError(f"force_n은 0 초과 {MAX_FORCE_N} 이하: {force_n}")
    return [round(force_n * 10), round(width_mm * 10), CONTROL_GRIP]


@dataclass(frozen=True)
class Rg2Status:
    width_mm: float
    busy: bool
    grip_detected: bool
    safety_error: bool


def gripper_state_payload(status: Rg2Status) -> dict:
    """/gripper/state JSON 본문 (ICD: width, grasp_detected). width 단위는 m."""
    return {"width": round(status.width_mm / 1000.0, 4), "grasp_detected": status.grip_detected}


def decode_status(width_raw: int, status_raw: int) -> Rg2Status:
    """폭 레지스터(1/10 mm)와 상태 레지스터 → Rg2Status."""
    return Rg2Status(
        width_mm=width_raw / 10.0,
        busy=bool(status_raw & STATUS_BUSY),
        grip_detected=bool(status_raw & STATUS_GRIP_DETECTED),
        safety_error=bool(status_raw & STATUS_SAFETY_ERROR),
    )
