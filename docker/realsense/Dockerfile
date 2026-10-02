# realsense: 손목 RealSense RGB-D 발행, 표준 토픽명(/wrist_cam/...) (docs/interfaces.md, 결정 #24)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-realsense2-camera \
    && rm -rf /var/lib/apt/lists/*
# [실측 10/02, PC1 D435i] __node만 wrist_cam으로 주면 /camera/wrist_cam/... 으로 발행됨(기본 네임스페이스 camera).
#   `-r __ns:=/` 를 함께 줘야 /wrist_cam/color/image_raw, /wrist_cam/aligned_depth_to_color/image_raw 로 발행됨.
# IMU·적외선은 이 프로젝트에서 쓰지 않으므로 끔(USB 대역폭 절약). 해상도는 강의 값 그대로.
# TODO(A 김병직): 강의 alias(realsense) 파라미터 반영
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && ros2 run realsense2_camera realsense2_camera_node --ros-args -r __ns:=/ -r __node:=wrist_cam -p camera_name:=wrist_cam -p enable_color:=true -p enable_depth:=true -p align_depth.enable:=true -p enable_infra1:=false -p enable_infra2:=false -p enable_accel:=false -p enable_gyro:=false -p rgb_camera.color_profile:=1280x720x30 -p depth_module.depth_profile:=848x480x30"]
