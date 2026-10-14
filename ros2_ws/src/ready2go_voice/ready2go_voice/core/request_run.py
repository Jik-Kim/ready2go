"""계약07의 E 로컬 요청 상관. 실행 상태나 Runner 결정을 만들지 않습니다."""
from copy import deepcopy


class RequestRun:
    def __init__(self):
        self.pending = None
        self.run_id = None
        self.seen_requests = set()
        self.decided = False
        self.finished = False

    def invalidate(self):
        self.pending = None
        self.run_id = None
        self.decided = self.finished = False

    def register(self, payload):
        if not isinstance(payload, dict):
            return False
        request_id = payload.get('request_id')
        if (not isinstance(request_id, str) or not request_id.strip()
                or request_id in self.seen_requests or payload.get('intent') not in ('find_item', 'achieve_goal')):
            return False
        if self.pending is not None and (not self.decided or (self.run_id and not self.finished)):
            return False  # 수락 대기·진행 중 run을 후속 요청으로 덮지 않습니다.
        self.seen_requests.add(request_id)
        self.pending = deepcopy(payload)
        self.run_id = None
        self.decided = self.finished = False
        return True

    def _matches(self, decision):
        if decision.get('intent') != self.pending['intent']:
            return False
        # 계약07 summary는 goals를 echo하지 않습니다. ID/intent/결정/run 상관은 observe에서,
        # 현재 source는 노드에서 검증하고 find_item의 targets 대조는 유지합니다.
        if self.pending['intent'] == 'achieve_goal':
            return True
        expected = self.pending.get('targets')
        actual = decision.get('targets')
        if not isinstance(expected, list) or not isinstance(actual, list):
            return False
        return actual == expected

    def observe(self, doc):
        """검증된 C 연결 어댑터/모의 호출자 전용. JSON만으로 발신 근거를 증명하지 않습니다."""
        if not isinstance(doc, dict) or doc.get('phase') not in ('idle', 'running', 'halted'):
            return []
        if (doc.get('halt_code') is not None and not isinstance(doc['halt_code'], str)
                or doc.get('last') is not None and not isinstance(doc['last'], dict)
                or doc.get('last_intent') is not None and not isinstance(doc['last_intent'], dict)
                or doc['phase'] == 'running' and (not isinstance(doc.get('task_id'), str)
                                                  or not doc['task_id'])):
            return []
        if self.pending is None:
            return []  # latched 결과를 새 요청 수락으로 사용하지 않습니다.
        events = []
        decision = doc.get('last_intent')
        if (self.run_id and isinstance(decision, dict) and decision.get('decision') == 'run'
                and isinstance(decision.get('run_id'), str) and decision['run_id'] != self.run_id):
            self.invalidate()  # A verified new run retires the old correlation; BUSY/status do not.
            return []
        if isinstance(decision, dict) and decision.get('request_id') == self.pending['request_id']:
            if not self.decided:
                if decision.get('decision') in ('hold', 'reject'):
                    self.decided = True
                    events.append(dict(event='request_decided', request_id=self.pending['request_id'],
                                       decision=decision['decision']))
                elif (decision.get('decision') == 'run' and self._matches(decision)
                      and isinstance(decision.get('run_id'), str) and decision['run_id'].strip()):
                    self.decided = True
                    self.run_id = decision['run_id']
                    events.append(dict(event='request_accepted', request_id=self.pending['request_id'],
                                       run_id=self.run_id))
            elif self.run_id and (decision.get('decision') != 'run'
                                 or decision.get('run_id') != self.run_id
                                 or not self._matches(decision)):
                self.invalidate()  # 같은 ID의 결정 충돌은 새 run으로 재연결하지 않습니다.
                return []
        last = doc.get('last')
        if (not self.finished and self.run_id and isinstance(last, dict)
                and last.get('run_id') == self.run_id
                and last.get('overall_status') in ('COMPLETED', 'FAILED', 'ABORTED')):
            if last['overall_status'] != 'COMPLETED':
                self.finished = True
            if (last['overall_status'] == 'COMPLETED' and doc['phase'] == 'idle'
                    and doc.get('halt_code') is None):
                self.finished = True
                events.append(dict(event='request_completed', request_id=self.pending['request_id'],
                                   run_id=self.run_id))
        return events
