"""JSON 태스크 해석기 — docs/runner.md 7.1~7.3.

Phase 1 범위: sequence, if, set_var, retry, timeout_sec, finally, 변수($ref·{{}} 보간·조사 필터),
스킬 실행 전 pre 확인 → 실행 → effect 반영(ready2go_knowledge.core.ontology), 스텝 로그(LogStore).
Phase 2: while · for_each · push/pop · recovery · fallback · on_halt, verify/post_check, state_diff 로그.
"""
# TODO(C 이영훈): Phase 1 해석기 구현. 원자 동작 실행은 백엔드(ready2go_skills / vision / voice) 액션 호출로 분리.
