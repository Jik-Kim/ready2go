"""음성 인텐트 → Runner 할 일 (ROS 비의존) — #17 "/voice/intent find_item → 태스크 실행 라우팅".

/voice/intent(std_msgs/String JSON, contracts/intent.schema.json)를 받아 무엇을 할지 정한다.
E 음성 노드가 형식·어휘·신뢰도를 먼저 검증하고 통과한 것만 발행하지만(docs/voice_llm.md 6.4),
Runner 는 로봇을 움직이는 쪽이라 한 번 더 확인하고 애매하면 실행하지 않는다(보류).

- run    : 실행. find_item 등 tasks 의 trigger.intent 와 맞는 태스크를 inputs.target = targets[0] 으로
- cancel : 실행 중이면 halt() (음성 "멈춰" = 보조 정지 수단, docs/safety.md). 실행 중이 아니면 할 일 없음
- status : /runner/status 를 바로 다시 발행
- hold   : 실행하지 않음 (형식 오류·모호·미지원·저신뢰·미등록 물품·태스크 없음·태스크가 받지 않는 물품). 재질문 TTS 는 E 음성 노드
- reject : 지금은 실행할 수 없음 (실행 중 = 중복 요청, 중단 잠김)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import jsonschema

RUN, CANCEL, STATUS, HOLD, REJECT = "run", "cancel", "status", "hold", "reject"
PLAN = "plan"                           # achieve_goal: 노드가 플래너로 계획한 뒤 run 또는 hold 로 바꿈 (#150)
# 보류·거절 이유 (/runner/status last_intent.reason, 로그)
BAD_INTENT = "BAD_INTENT"               # JSON 이 아니거나 intent.schema.json 위반
NEEDS_CLARIFY = "NEEDS_CLARIFY"         # intent = unknown·clarify (E 음성 노드가 재질문)
UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"   # 연결된 태스크가 없는 인텐트 (P1 은 find_item 만, 목록·목표형은 P2/P3)
LOW_CONFIDENCE = "LOW_CONFIDENCE"       # confidence < min_confidence
NO_TARGET = "NO_TARGET"                 # targets 없음
MULTI_TARGET = "MULTI_TARGET"           # P1 은 물품 하나만 (단일 물품 전달)
UNKNOWN_ITEM = "UNKNOWN_ITEM"           # 온톨로지 items 에 없는 물품
UNSUPPORTED_ITEM = "UNSUPPORTED_ITEM"   # 태스크 trigger.targets 에 없는 물품 (시연용 지우개 태스크에 차키 요청 등, #89 PM·D 리뷰)
BUSY = "BUSY"                           # 이미 태스크 실행 중 → 중복 요청 거절 (줄 세우지 않음)
LOCKED = "LOCKED"                       # 중단 잠김 (사람 확인 전 새 태스크 없음, docs/safety.md)
NOT_RUNNING = "NOT_RUNNING"             # cancel 을 받았지만 멈출 태스크가 없음
STOPPED_BEFORE_START = "STOPPED_BEFORE_START"   # 이 요청을 처리하는 사이 "멈춰"가 와서 시작 안 함 (#187)
NOT_READY = "NOT_READY"                 # 태스크에 필요한 /skills/* 서버가 아직 안 뜸 (기동 직후, #108) → 로봇 동작 없이 거절
NO_GOAL = "NO_GOAL"                     # achieve_goal 인데 goals 가 없음
PLAN_SATISFIED = "PLAN_SATISFIED"       # 목표가 이미 만족 → 실행 안 함 (플래너 근거는 로그, #150)
UNPLANNABLE = "UNPLANNABLE"             # 목표를 만족하는 스킬 순서가 없음 → 실행 안 함 (원인은 로그, #150)
CONTROL_INTENTS = {"cancel", "status"}


@dataclass
class Decision:
    kind: str                           # run / cancel / status / hold / reject
    reason: str | None = None           # hold·reject 이유 (위 코드), cancel 인데 실행 중이 아니면 NOT_RUNNING
    task: dict | None = None            # run 일 때 실행할 태스크
    inputs: dict = field(default_factory=dict)   # run 일 때 태스크 inputs 덮어쓰기 (target, source, stt_text)
    intent: dict | None = None          # 받은 인텐트 (해석 실패면 None) — 실행 기록 헤더에 그대로
    goals: list | None = None           # plan 일 때 목표 (achieve_goal)
    plan: list | None = None            # 플래너 결과 설명 줄 (실행 기록 헤더 extra.plan, #150)
    run_id: str | None = None           # 계약07: 실제로 수락(run)해 시작한 실행 ID — 노드가 수락할 때 정해 고정

    def summary(self) -> dict:
        """/runner/status last_intent 에 싣는 짧은 요약 (D 시연 화면 #59)."""
        intent = self.intent or {}
        return {"intent": intent.get("intent"), "targets": intent.get("targets"),
                "confidence": intent.get("confidence"),
                "stt_text": (intent.get("source") or {}).get("stt_text"),
                "decision": self.kind, "reason": self.reason,
                "task_id": self.task.get("task_id") if self.task else None,
                "request_id": intent.get("request_id"),          # 계약07: 받은 최상위 request_id (없으면 null)
                "run_id": self.run_id if self.kind == RUN else None}   # 계약07: 수락한 run 만, 보류·거절은 null


def tasks_by_intent(tasks: list[dict], overrides: dict[str, dict] | None = None) -> dict[str, dict]:
    """trigger.intent → 태스크. overrides(인텐트 → 태스크)가 우선 (시연 조합: find_item → p1_demo_eraser).
    같은 인텐트의 태스크가 둘 이상이면 어느 쪽을 실행할지 모르므로 ValueError (시작할 때 알림)."""
    table: dict[str, dict] = {}
    for task in tasks:
        name = (task.get("trigger") or {}).get("intent")
        if not name or name in (overrides or {}):
            continue
        if name in table:
            raise ValueError(f"trigger.intent '{name}' 태스크가 둘 이상: "
                             f"{table[name].get('task_id')}, {task.get('task_id')} → intent_tasks 로 하나를 지정")
        table[name] = task
    table.update(overrides or {})
    return table


def parse_overrides(text: str) -> dict[str, str]:
    """"find_item=/tasks/p1_demo_eraser.json,..." → {인텐트: 파일 경로}."""
    result = {}
    for entry in filter(None, (part.strip() for part in text.split(","))):
        name, _, path = entry.partition("=")
        if not name.strip() or not path.strip():
            raise ValueError(f"intent_tasks 형식은 인텐트=태스크파일: {entry!r}")
        result[name.strip()] = path.strip()
    return result


class IntentRouter:
    def __init__(self, schema: dict, tasks: dict[str, dict], items: dict, min_confidence: float):
        self.schema = schema                # contracts/intent.schema.json
        self.tasks = tasks                  # 인텐트 → 태스크 (tasks_by_intent)
        self.items = items                  # 온톨로지 world.items (물품 키 확인)
        self.min_confidence = min_confidence

    def decide(self, text: str, running: bool, locked: bool) -> Decision:
        try:
            intent = json.loads(text)
            jsonschema.validate(intent, self.schema)
        except (json.JSONDecodeError, jsonschema.ValidationError):
            return Decision(HOLD, BAD_INTENT)
        name = intent["intent"]
        if name == "cancel":                # 정지는 신뢰도·잠김과 상관없이 받는다 (멈추는 쪽은 언제나 안전)
            return Decision(CANCEL, None if running else NOT_RUNNING, intent=intent)
        if name == "status":
            return Decision(STATUS, intent=intent)
        if name in ("unknown", "clarify"):
            return Decision(HOLD, NEEDS_CLARIFY, intent=intent)
        if name == "achieve_goal" and name not in self.tasks:     # 목표형: 동작 순서는 플래너가 (#150, FR-PLN-02)
            return self._goal(intent, running, locked)
        task = self.tasks.get(name)
        if task is None:
            return Decision(HOLD, UNSUPPORTED_INTENT, intent=intent)
        if intent["confidence"] < self.min_confidence:
            return Decision(HOLD, LOW_CONFIDENCE, intent=intent)
        targets = intent.get("targets") or []
        if not targets:
            return Decision(HOLD, NO_TARGET, intent=intent)
        if len(targets) > 1:
            return Decision(HOLD, MULTI_TARGET, intent=intent)
        if targets[0] not in self.items:
            return Decision(HOLD, UNKNOWN_ITEM, intent=intent)
        allowed = (task.get("trigger") or {}).get("targets")
        if allowed is not None and not (isinstance(allowed, list) and targets[0] in allowed):
            # 물품이 정해진 태스크: 다른 물품이면 움직이기 전에 보류. 목록이 아니면(문자열 등, 스키마 위반) 부분 문자열로
            # 통과시키지 않고 보류 (#89 D P1: "car_key_eraser" 에 car_key 가 들어가던 것)
            return Decision(HOLD, UNSUPPORTED_ITEM, intent=intent)
        if locked:
            return Decision(REJECT, LOCKED, intent=intent)
        if running:
            return Decision(REJECT, BUSY, intent=intent)
        return Decision(RUN, task=task, inputs=_inputs(targets[0], intent), intent=intent)

    def _goal(self, intent: dict, running: bool, locked: bool) -> Decision:
        """achieve_goal: 형식·신뢰도·물품 이름만 보고 plan 으로 넘김. 계획 자체는 노드가 현재 상태로 (core/planner)."""
        if intent["confidence"] < self.min_confidence:
            return Decision(HOLD, LOW_CONFIDENCE, intent=intent)
        goals = intent.get("goals") or []
        if not goals:
            return Decision(HOLD, NO_GOAL, intent=intent)
        if any(g["predicate"] == "located_in" and g["subject"] not in self.items for g in goals):
            return Decision(HOLD, UNKNOWN_ITEM, intent=intent)
        if locked:
            return Decision(REJECT, LOCKED, intent=intent)
        if running:
            return Decision(REJECT, BUSY, intent=intent)
        return Decision(PLAN, inputs=_goal_inputs(intent), intent=intent, goals=goals)


def _goal_inputs(intent: dict) -> dict[str, Any]:
    """목표형 실행의 inputs (입력 명령 기록, FR-LOG-01)."""
    inputs: dict[str, Any] = {"source": "voice", "goals": intent["goals"], "intent_confidence": intent["confidence"]}
    if (intent.get("source") or {}).get("stt_text"):
        inputs["stt_text"] = intent["source"]["stt_text"]
    _accept_text(inputs, intent)
    return inputs


def _inputs(target: str, intent: dict) -> dict[str, Any]:
    """태스크 inputs 덮어쓰기. 입력 명령 기록(FR-LOG-01): contracts/examples/execution_log.json 의 inputs 모양."""
    inputs: dict[str, Any] = {"target": target, "source": "voice"}
    source = intent.get("source") or {}
    if source.get("stt_text"):
        inputs["stt_text"] = source["stt_text"]
    inputs["intent_confidence"] = intent["confidence"]
    _accept_text(inputs, intent)
    return inputs


def _accept_text(inputs: dict[str, Any], intent: dict) -> None:
    """계약07: E 가 검증한 수락 문장 — 수락된 그 run 의 첫 안내 1회에만 (태스크 find_item s2·계획 맨 앞 안내).
    없거나 null·빈 문자열이면 넣지 않음 → 태스크 기존 안내 (P1 호환)."""
    text = intent.get("accept_text")
    if isinstance(text, str) and text.strip():
        inputs["accept_text"] = text


def add_accept_speak(task: dict, inputs: dict) -> dict:
    """계약07: 목표형 계획 태스크 앞(p0 다음)에 수락 문장 안내 1회. 안내 speak 가 실패하면 **로봇 동작 0번**으로 실패
    (find_item s2 와 같은 규칙) — 안내 직전 announce_pending 을 켜고 성공하면 끄는데, 안내가 실패해 켜진 채면 finally 홈 이동(fh)도
    보내지 않음(#249 E 리뷰 P1). 연 서랍 닫기(fc)는 연 서랍이 없어 동작 없음. accept_text 가 없으면 태스크 그대로 (P1 호환)."""
    if inputs.get("accept_text"):
        task["sequence"][1:1] = [
            {"id": "pa0", "action": "set_var", "params": {"name": "announce_pending", "value": True}},
            {"id": "pa", "action": "speak", "params": {"text": "$inputs.accept_text"}},
            {"id": "pak", "action": "set_var", "params": {"name": "announce_pending", "value": False}}]
        task["finally"] = [{"id": "fg", "action": "if", "cond": {"op": "==", "args": ["$announce_pending", False]},
                            "then": [step]} if step.get("id") == "fh" else step for step in task["finally"]]
    return task
