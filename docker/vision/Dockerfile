# vision: inspect_region (YOLO + 뎁스). 기존 yolo-detection 컨테이너를 시작점으로 사용 (docs/vision.md)
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp ros-jazzy-cv-bridge python3-pip \
    && rm -rf /var/lib/apt/lists/*
# [실측 10/02, PC1 RTX 5060 (sm_120), 기존 yolo-detection 컨테이너] 아래 조합에서 torch.cuda.is_available()=True,
#   cv_bridge import OK, 토픽 수신 30Hz 확인. 이 Dockerfile로 새로 빌드한 이미지는 아직 검증하지 않음(기존 컨테이너를 재사용 중).
# TODO(A 김병직): RTX 4060(PC2)에서도 동작하는지 확인. 새로 빌드하면 위 조합과 같은 버전이 설치되는지 확인.
RUN pip3 install --break-system-packages --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cu128 \
      torch==2.11.0 torchvision==0.26.0 ultralytics==8.4.170 numpy==1.26.4 opencv-python==4.9.0.80
WORKDIR /ros2_ws
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && sleep infinity"]
