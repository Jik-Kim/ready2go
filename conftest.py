"""pytest가 ROS 빌드 없이 각 패키지 core/를 import 하도록 경로 추가."""
import sys
from pathlib import Path

for pkg in (Path(__file__).parent / "ros2_ws" / "src").iterdir():
    if (pkg / "setup.py").exists():
        sys.path.insert(0, str(pkg))
