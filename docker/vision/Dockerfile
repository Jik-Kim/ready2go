# vision: inspect_region (YOLO + 뎁스). 기존 yolo-detection 컨테이너를 시작점으로 사용 (docs/vision.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-cv-bridge python3-pip \
    && rm -rf /var/lib/apt/lists/*
# TODO(A 김병직): ultralytics·torch 버전 고정 (RTX 4060/5060 CUDA 호환 확인)
RUN pip3 install --break-system-packages --no-cache-dir ultralytics
WORKDIR /ros2_ws
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && sleep infinity"]
