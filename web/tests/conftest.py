"""저장소 루트와 web/ 양쪽에서 같은 테스트 명령을 사용할 수 있게 한다.

아직 web 패키지를 wheel로 설치하지 않는 초기 구현 단계이므로 테스트 수집 시에만
web/ 디렉터리를 import 경로에 추가한다. 제품 실행 경로를 바꾸는 설정은 아니다.
"""

from pathlib import Path
import sys


# 이 파일은 web/tests/conftest.py이므로 부모의 부모가 패키지가 있는 web/이다.
WEB_ROOT = Path(__file__).resolve().parents[1]
# 이미 경로가 있으면 중복 삽입하지 않고, 없을 때만 가장 먼저 탐색하도록 추가한다.
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))
