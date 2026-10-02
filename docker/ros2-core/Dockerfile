# ros2-core: Runner · 플래너 · 온톨로지 · 모션 스킬 · DSR 드라이버 (docs/docker.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp python3-pip python3-pytest \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir jsonschema pymongo pymodbus
# TODO(B 서동권): DSR 드라이버(doosan-robot2, m0609_rg2_bringup) 빌드 단계 추가
WORKDIR /ros2_ws
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && colcon build --symlink-install && source install/setup.bash && ros2 launch ready2go_bringup ready2go.launch.py"]
