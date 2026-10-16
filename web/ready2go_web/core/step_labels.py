"""파일 정의를 사용자용 단계명으로 요약한다. 계획·실행 순서·성공 상태는 만들지 않는다."""

# D 표시 어휘이며 실행 명령이나 계약 enum을 변경하지 않는다.
ACTION_LABELS = {
    "inspect_region": "물품 촬영·확인", "query_ontology": "물품 위치 기록 조회",
    "pick_object": "물품 집기", "place_object": "물품 놓기",
    "move_to_named_pose": "로봇 이동", "nudge_object": "물품 위치 조정",
    "speak": "음성 안내", "if": "작업 조건 확인", "while": "반복 조건 확인",
    "fallback": "실행 방법 확인", "set_var": "작업 정보 갱신",
    "assert": "작업 조건 검증", "wait": "대기",
}


def task_step_labels(task, skills):
    """원본 ID와 Runner의 expand ID 규칙으로 정적 이름 사전을 만든다. 조건은 실행하지 않는다."""
    labels = {}

    def label(node, scope):
        # 정적인 인자만 치환한다. 관측값/블랙보드 식은 평가하지 않는다.
        params = node.get("params", {})
        params = {k: scope.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v
                  for k, v in params.items()}
        action = node.get("action")
        if action == "place_object" and params.get("check_only") is True:
            return "물품 배치 공간 확인"
        if action == "place_object" and params.get("location") == "handover_zone":
            return "전달 트레이에 물품 놓기"
        if action == "drawer_control":
            return {"open": "서랍 열기", "close": "서랍 닫기"}.get(str(params.get("state")), "서랍 조작")
        if action == "move_to_named_pose":
            return {"home": "기본 자세로 이동", "drawer_top_view": "촬영 위치로 이동"}.get(
                str(params.get("pose_name")), "로봇 이동")
        return ACTION_LABELS.get(action)

    def expanded(node, step_id, scope):
        # interpreter._run_expand_item/fallback/if와 같은 ID만 생성한다. 단계 성공은 추정하지 않는다.
        text = label(node, scope)
        if text:
            labels[step_id] = text
        if node.get("action") == "fallback":
            for k, option in enumerate(node.get("options", []), 1):
                for m, child in enumerate(option, 1):
                    expanded(child, f"{step_id}.o{k}.{m}", scope)
        if node.get("action") == "if":
            for branch, suffix in (("then", "t"), ("else", "f")):
                for m, child in enumerate(node.get(branch, []), 1):
                    expanded(child, f"{step_id}.{suffix}{m}", scope)

    def visit(nodes):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            step_id = node.get("id")
            if isinstance(step_id, str):
                skill = skills.get(node.get("skill"), {})
                text = skill.get("name_ko") if skill else label(node, {})
                if isinstance(text, str) and text:
                    labels[step_id] = text
                for i, child in enumerate(skill.get("expand", []), 1):
                    expanded(child, f"{step_id}.e{i}", node.get("params", {}))
            # 태스크의 하위 ID는 원본을 사용하며 분기 배열을 실제 실행 순서로 해석하지 않는다.
            for key in ("then", "else", "body"):
                visit(node.get(key, []))
            for option in node.get("options", []):
                visit(option)

    visit(task.get("sequence", []))
    visit(task.get("finally", []))
    return labels
