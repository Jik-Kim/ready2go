# mock-sim: 로봇·GPU 없이 개발용 가짜 조인트·서랍·카메라 토픽 (docs/architecture.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
# TODO(C 이영훈): mock 백엔드 노드 추가
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && sleep infinity"]
