"""Isaac Sim ROS 2 Bridge 스모크 테스트 (담당 A). 시뮬레이션 시계를 /clock 으로 발행해 컨테이너·호스트와 DDS 통신이 되는지만 본다.

실행: source sim/isaac_env.sh && ~/isaac-sim-5.1.0/python.sh sim/scripts/bridge_smoke_test.py [초]
확인: 다른 터미널에서 시스템 ROS를 source 하고 같은 DDS 값을 준 뒤 `ros2 topic echo --once /clock` (sim/README.md)
"""
import sys
import time

from isaacsim import SimulationApp

RUN_SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
app = SimulationApp({"headless": True})

import omni.graph.core as og  # noqa: E402
import omni.timeline  # noqa: E402
from isaacsim.core.utils.extensions import enable_extension  # noqa: E402

enable_extension("isaacsim.ros2.bridge")
app.update()

keys = og.Controller.Keys
og.Controller.edit(
    {"graph_path": "/ClockGraph", "evaluator_name": "execution"},
    {
        keys.CREATE_NODES: [
            ("tick", "omni.graph.action.OnPlaybackTick"),
            ("simtime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
            ("ctx", "isaacsim.ros2.bridge.ROS2Context"),
            ("clock", "isaacsim.ros2.bridge.ROS2PublishClock"),
        ],
        keys.CONNECT: [
            ("tick.outputs:tick", "clock.inputs:execIn"),
            ("simtime.outputs:simulationTime", "clock.inputs:timeStamp"),
            ("ctx.outputs:context", "clock.inputs:context"),
        ],
        keys.SET_VALUES: [("clock.inputs:topicName", "/clock")],
    },
)

omni.timeline.get_timeline_interface().play()
print(f"[smoke] /clock 발행 시작 ({RUN_SEC:.0f}초)", flush=True)
t0 = time.time()
while time.time() - t0 < RUN_SEC:
    app.update()
print("[smoke] 종료", flush=True)
app.close()
