"""계약07 요청 기억 (ROS 비의존) — 사용자(E) 승인 E-C-REQUEST-RUN-WIRE-20261011-07.

E 의 일반 실행 요청(find_item·achieve_goal)에 최상위 request_id 가 있으면, **이번 Runner 기동 동안** 그 ID 의 첫 결정을 기억한다.
- 같은 request_id + 같은 내용 재전송 → 첫 결정을 다시 발행, 재실행·TTS 없음
- 같은 request_id + 다른 내용 → 첫 결정 유지, 새 내용은 실행 안 함, 경고(새 오류 코드 없음)
- request_id 가 없으면(P1 text_override·task_file·시험) 기억하지 않음 — 지금 동작 그대로
- 재기동하면 비어 있음(노드마다 새로 만듦) → 이전 요청 연결 무효, 자동 재전송 없음
cancel·status·confirm 은 기억하지 않는다(정지는 언제나 받음).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass

REQUEST_INTENTS = {"find_item", "achieve_goal", "end_task"}   # end_task: 같은 ID 재전송 = 첫 결정 재발행 (#271 같은 ID 처리)


@dataclass
class Seen:
    fingerprint: str
    summary: dict


class RequestMemory:
    def __init__(self):
        self._seen: dict[str, Seen] = {}
        self.lock = threading.Lock()            # 같은 ID 가 동시에 두 번 와도 한 번만 결정 (노드 콜백이 동시에 돎)

    @staticmethod
    def key(text: str) -> tuple[str | None, str | None]:
        """(request_id, 내용 지문). 기억 대상이 아니면 (None, None). 지문 = 받은 JSON 전체를 키 정렬해 다시 쓴 것."""
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None, None
        if not isinstance(payload, dict) or payload.get("intent") not in REQUEST_INTENTS:
            return None, None
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return None, None                   # 없음·null·빈 문자열: null·빈 값은 스키마 위반으로 판단기가 보류
        return request_id, json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def lookup(self, request_id: str) -> Seen | None:
        return self._seen.get(request_id)

    def remember(self, request_id: str, fingerprint: str, summary: dict) -> None:
        self._seen.setdefault(request_id, Seen(fingerprint, summary))
