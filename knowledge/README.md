# knowledge — 로봇 온톨로지 (담당 E 고희태)

> 문서: [`docs/ontology.md`](../docs/ontology.md) · 그림: `docs/images/knowledge_graph_*.jpg`

- `robot_ontology.jsonld`: classes · world · state · skills (조건·결과는 `{subject, predicate, op, value}` 레코드)
- `snapshots/demo_start.json`: 시연 시작 상태
- 물품·치수·`grip_force`는 예시값 — Day 2 파지 테스트·서랍 실측 후 갱신 [팀 확정 필요]
- 상태는 `state[predicate][subject] = value` 한 가지 형태
