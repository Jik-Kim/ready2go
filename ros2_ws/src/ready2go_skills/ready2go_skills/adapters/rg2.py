"""OnRobot RG2 Modbus TCP 어댑터 (강의 onrobot.py 방식, docs/architecture.md 3.1).

단독 실행 (ROS 불필요, 그리퍼만 움직임 — 손가락 사이에 손을 넣지 않는다):
    python3 rg2.py --ip <RG2 IP> close            # 완전히 닫기
    python3 rg2.py --ip <RG2 IP> open             # 완전히 열기
    python3 rg2.py --ip <RG2 IP> move --width 50  # 폭 50 mm로
    python3 rg2.py --ip <RG2 IP> status           # 현재 폭·상태만 읽기
RG2 IP는 [팀 확정 필요] — 코드에 고정하지 않고 인자로 받는다.
"""
import argparse
import inspect
import sys
import time
from pathlib import Path

from pymodbus.client import ModbusTcpClient

try:
    from ready2go_skills.core import rg2_protocol as proto
except ImportError:  # 파일을 직접 실행할 때
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ready2go_skills.core import rg2_protocol as proto


def _unit_kwarg(method) -> str:
    """pymodbus 버전별 unit ID 인자 이름 (3.10+ device_id, 3.x slave, 2.x unit)."""
    params = inspect.signature(method).parameters
    for name in ("device_id", "slave", "unit"):
        if name in params:
            return name
    raise RuntimeError("pymodbus unit ID 인자를 찾지 못함")


class Rg2:
    def __init__(self, ip: str, port: int = 502, timeout_s: float = 1.0):
        self._client = ModbusTcpClient(ip, port=port, timeout=timeout_s)
        if not self._client.connect():
            raise ConnectionError(f"RG2 Modbus 연결 실패: {ip}:{port}")
        self._unit = {_unit_kwarg(self._client.write_registers): proto.UNIT_ID}

    def close(self) -> None:
        self._client.close()

    def _read(self, address: int) -> int:
        res = self._client.read_holding_registers(address, count=1, **self._unit)
        if res.isError():
            raise IOError(f"RG2 레지스터 {address} 읽기 실패: {res}")
        return res.registers[0]

    def status(self) -> proto.Rg2Status:
        return proto.decode_status(self._read(proto.REG_WIDTH_WITH_OFFSET),
                                   self._read(proto.REG_STATUS))

    def move(self, width_mm: float, force_n: float, timeout_s: float = 5.0) -> proto.Rg2Status:
        """목표 폭으로 이동하고 동작이 끝날 때까지 기다린 뒤 상태를 반환."""
        values = proto.grip_command(width_mm, force_n)
        res = self._client.write_registers(proto.REG_TARGET_FORCE, values, **self._unit)
        if res.isError():
            raise IOError(f"RG2 명령 쓰기 실패: {res}")
        time.sleep(0.1)  # busy 비트가 올라올 시간
        deadline = time.monotonic() + timeout_s
        while True:
            st = self.status()
            if not st.busy:
                return st
            if time.monotonic() > deadline:
                raise TimeoutError(f"RG2 동작이 {timeout_s}s 안에 끝나지 않음: {st}")
            time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser(description="RG2 단독 제어 (Modbus TCP)")
    ap.add_argument("--ip", required=True, help="RG2(Compute Box) IP [팀 확정 필요]")
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--force", type=float, default=20.0, help="파지 힘 N (RG2 최대 40)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("close")
    sub.add_parser("open")
    sub.add_parser("status")
    mv = sub.add_parser("move")
    mv.add_argument("--width", type=float, required=True, help="목표 폭 mm (0~110)")
    args = ap.parse_args()

    g = Rg2(args.ip, args.port)
    try:
        if args.cmd == "status":
            st = g.status()
        else:
            width = {"close": 0.0, "open": proto.MAX_WIDTH_MM}.get(args.cmd)
            st = g.move(args.width if width is None else width, args.force)
    finally:
        g.close()
    print(f"width_mm={st.width_mm:.1f} grip_detected={st.grip_detected} "
          f"busy={st.busy} safety_error={st.safety_error}")
    return 1 if st.safety_error else 0


if __name__ == "__main__":
    sys.exit(main())
