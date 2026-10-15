"""저장소 루트와 web/ 양쪽에서 같은 테스트 명령을 사용할 수 있게 한다.

아직 web 패키지를 wheel로 설치하지 않는 초기 구현 단계이므로 테스트 수집 시에만
web/ 디렉터리를 import 경로에 추가한다. 제품 실행 경로를 바꾸는 설정은 아니다.
"""

from pathlib import Path
import sys


# 이 파일은 web/tests/conftest.py이므로 부모의 부모가 패키지가 있는 web/이다.
WEB_ROOT = Path(__file__).resolve().parents[1]
# 5단계는 제품 코드와 같은 ready2go_knowledge 공통 로더를 직접 사용한다.
KNOWLEDGE_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "ready2go_knowledge"
)
# 이미 경로가 있으면 중복 삽입하지 않고, 없을 때만 가장 먼저 탐색하도록 추가한다.
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))
# colcon overlay를 source하지 않은 단위시험도 저장소의 실제 공통 로더를 사용하게 한다.
if str(KNOWLEDGE_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_PACKAGE_ROOT))

# 읽기 어댑터는 C 저장소의 파일명/조회 규칙을 공유한다. 시험에서도 같은 실제 모듈을 사용한다.
RUNNER_PACKAGE_ROOT = WEB_ROOT.parent / "ros2_ws" / "src" / "ready2go_runner"
if str(RUNNER_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_PACKAGE_ROOT))
