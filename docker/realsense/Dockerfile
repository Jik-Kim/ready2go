# realsense: 손목 RealSense RGB-D 발행, 표준 토픽명(/wrist_cam/...)으로 remap (docs/interfaces.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-realsense2-camera \
    && rm -rf /var/lib/apt/lists/*
# TODO(A 김병직): 강의 alias(realsense) 파라미터 + remap 반영
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && ros2 run realsense2_camera realsense2_camera_node --ros-args -r __ns:=/wrist_cam -p enable_color:=true -p enable_depth:=true -p align_depth.enable:=true"]
