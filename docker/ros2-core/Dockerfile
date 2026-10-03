# ros2-core: Runner · 플래너 · 온톨로지 · 모션 스킬 · DSR 드라이버 (docs/docker.md)
FROM ros:jazzy-ros-base-noble
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
ARG DEBIAN_FRONTEND=noninteractive

# 팀 패키지 의존 + DSR 드라이버 빌드·실행 의존 (강의 m0609_rg2_integration docker/Dockerfile.jazzy 기준, GUI·카메라·에뮬레이터 제외)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp python3-pip python3-pytest python3-numpy \
      git libpoco-dev libyaml-cpp-dev \
      ros-jazzy-robot-state-publisher ros-jazzy-xacro ros-jazzy-tf2-ros \
      ros-jazzy-ros2-control ros-jazzy-ros2-controllers ros-jazzy-control-msgs \
      ros-jazzy-realtime-tools ros-jazzy-moveit-msgs ros-jazzy-kdl-parser \
      ros-jazzy-eigen3-cmake-module ros-jazzy-example-interfaces \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir jsonschema pymongo pymodbus

# DSR 드라이버: 강의 포크를 커밋으로 고정 (원본 doosan-robot2와 libDRFL.a가 다름 — 포크 사용 필수)
ARG DSR_REPO=https://github.com/ROKEY-SPARK/doosan-robot2_jazzy.git
ARG DSR_REF=31750d68ed2855c780a8169c39aadb0a2cd80e1f   # main, 2026-10-03 확인
ARG DRCF_VER=2                                         # 포크 기본값. 제어기 3.x면 3 [팀 확정 필요]
RUN mkdir -p /opt/dsr_ws/src/doosan-robot2 && cd /opt/dsr_ws/src/doosan-robot2 \
    && git init -q && git remote add origin "${DSR_REPO}" \
    && git fetch -q --depth 1 origin "${DSR_REF}" && git checkout -q FETCH_HEAD
# gazebo·moveit·mobile·예제는 쓰지 않으므로 제외. build/ 삭제를 위해 --symlink-install 미사용
RUN source /opt/ros/jazzy/setup.bash && cd /opt/dsr_ws \
    && colcon build --cmake-args -DDRCF_VER=${DRCF_VER} \
         --packages-skip dsr_gazebo2 dsr_moveit2 dsr_mobile_wbc2 dsr_example2 dsr_tests \
    && rm -rf /opt/dsr_ws/build /opt/dsr_ws/log

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /ros2_ws
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash", "-c", "colcon build --symlink-install && source install/setup.bash && ros2 launch ready2go_bringup ready2go.launch.py"]
