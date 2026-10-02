# realsense: 손목 RealSense RGB-D 발행, 표준 토픽명(/wrist_cam/...)으로 remap (docs/interfaces.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-realsense2-camera \
    && rm -rf /var/lib/apt/lists/*
# TODO(A 김병직): 강의 alias(realsense) 파라미터 반영. 아래 토픽 경로는 [추정] — 기동 후 `ros2 topic list | grep wrist_cam`으로 확인 (#5)
# 노드 이름을 wrist_cam으로 두면 /wrist_cam/color/image_raw, /wrist_cam/aligned_depth_to_color/image_raw로 발행됨 (__ns만 주면 /wrist_cam/camera/... 로 한 단계 깊어짐)
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && ros2 run realsense2_camera realsense2_camera_node --ros-args -r __node:=wrist_cam -p camera_name:=wrist_cam -p enable_color:=true -p enable_depth:=true -p align_depth.enable:=true"]
