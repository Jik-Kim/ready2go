# voice: 웨이크워드 · STT · LLM 인텐트 · TTS (docs/voice_llm.md). 의존성은 강의 a11_voice.sh 기준
FROM ros:jazzy-ros-base-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp python3-pip python3-rdflib portaudio19-dev libportaudio2 libsndfile1 ffmpeg pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir "langchain<2" "langchain-openai<2" "openai<3" sounddevice python-dotenv "numpy<2" \
 && pip3 install --break-system-packages --no-cache-dir --no-deps "openwakeword==0.6.0"
# TODO(E 고희태): tflite runtime·웨이크워드 모델 설치(a11_voice.sh 4~5단계), TTS 엔진 결정
WORKDIR /ros2_ws
CMD ["bash", "-lc", "source /opt/ros/jazzy/setup.bash && sleep infinity"]
