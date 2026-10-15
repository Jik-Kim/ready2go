(function () {
  "use strict";

  const baseData = {
    meta: {
      mode: "mock",
      deviceConnected: false,
      label: "목업 데이터",
      description: "실제 장치와 연결되지 않은 화면입니다. 아래 상태·시각·결과는 모두 화면 검토용 예시입니다.",
    },
    connections: [
      {
        id: "voice",
        label: "음성",
        status: "waiting",
        statusLabel: "확인 전",
        description: "/voice/intent publisher 확인 전",
      },
      { id: "robot", label: "로봇", status: "waiting", statusLabel: "확인 전", description: "/dsr01/joint_states 수신 전" },
      { id: "camera", label: "카메라", status: "waiting", statusLabel: "확인 전", description: "/wrist_cam/color/camera_info 수신 전" },
      { id: "runner", label: "Runner", status: "pending", statusLabel: "상태 수신 대기", description: "향후 /runner/status로 연결 예정" },
    ],
    command: {
      // 현재 작업과 같은 목업 요청을 사용한다. 실제 commute_set 정의는 변경하지 않는다.
      understood: "차 키·지우개·시계를 찾아 전달합니다.",
      interpretation: { status: "confirmed", label: "요청 해석 완료 · 목업 예시" },
      receipt: { status: "accepted", label: "명령 접수 · 목업 예시" },
      processing: { status: "verifying", label: "관측 결과 확인 중 · 목업 예시" },
      confirmation: null,
    },
    selectedDrawerId: "top",
    drawers: [
      {
        id: "top",
        label: "위 서랍",
        items: [
          { id: "watch", name: "시계", icon: "watch", status: "waiting", statusLabel: "대기", checkedAt: null },
          { id: "note", name: "노트", icon: "note", status: "confirmed", statusLabel: "확인됨", checkedAt: "08:12:15" },
          { id: "box", name: "상자", icon: "box", status: "confirmed", statusLabel: "확인됨", checkedAt: "08:12:15" },
        ],
      },
      {
        id: "bottom",
        label: "아래 서랍",
        items: [
          { id: "wallet-spare", name: "예비 지갑", icon: "wallet", status: "confirmed", statusLabel: "확인됨", checkedAt: "08:11:42" },
          { id: "charger", name: "휴대전화 충전기", icon: "charger", status: "waiting", statusLabel: "확인 전", checkedAt: null },
        ],
      },
    ],
    supplies: [
      { id: "car-key", name: "차 키", icon: "key", status: "delivered", statusLabel: "전달 완료" },
      { id: "eraser", name: "지우개", icon: "eraser", status: "verifying", statusLabel: "결과 확인 중" },
      { id: "watch", name: "시계", icon: "watch", status: "waiting", statusLabel: "대기" },
    ],
    task: {
      status: "verifying",
      workDrawerId: "bottom",
      currentItemId: "eraser",
      currentItemIcon: "eraser",
      currentAction: "지우개의 전달 결과를 확인하는 중",
      detailsExpanded: true,
      steps: [
        { id: "open-bottom", label: "아래 서랍 열기", status: "complete", statusLabel: "완료", reason: "등록 위치의 물품에 접근", observation: "목업 예시 · 서랍 열림 상태 확인" },
        { id: "pick-eraser", label: "지우개 확인·집기", status: "complete", statusLabel: "완료", reason: "요청 물품과 등록 물품 일치 확인", observation: "목업 예시 · 지우개 집기 완료" },
        { id: "place-eraser", label: "전달 위치에 놓기", status: "complete", statusLabel: "완료", reason: "사용자에게 물품 전달", observation: "목업 예시 · 전달 위치 배치 완료" },
        { id: "verify-eraser", label: "배치 결과 검증", status: "current", statusLabel: "진행 중", reason: "지우개가 전달 위치에 놓였는지 확인", observation: "목업 예시 · 확인 대기" },
        { id: "close-bottom", label: "아래 서랍 닫기", status: "waiting", statusLabel: "대기", reason: "작업 후 서랍 상태 복구", observation: "목업 예시 · 미수행" },
      ],
    },
    adminReview: {
      current: {
        runId: "demo_001",
        rows: [
          { id: "bottom-drawer", icon: "drawer", label: "아래 서랍", value: "열림", valueStatus: "confirmed", source: "목업 · Runner 저장 상태 예시", receivedAt: "08:12:19" },
          { id: "gripper", icon: "gripper", label: "그리퍼", value: "열림", valueStatus: "confirmed", source: "목업 · Runner 저장 상태 예시", receivedAt: "08:12:20" },
          { id: "eraser-placement", icon: "eraser", label: "지우개 배치", value: "확인 대기", valueStatus: "verifying", source: "목업 · 관측 결과 미수신", receivedAt: null },
        ],
        error: { label: "현재 오류: 미수신", detail: "오류 데이터 제공 경로가 연결되지 않아 오류 유무를 판단할 수 없습니다." },
      },
      ontology: {
        relations: [
          { title: "등록 물품", value: "차 키 · 지우개 · 시계", meta: "샘플 정의" },
          { title: "등록 장소", value: "위 서랍 · 아래 서랍", meta: "샘플 정의" },
          { title: "관계", value: "지우개 → 아래 서랍", meta: "샘플 관계" },
        ],
        skills: [
          { title: "pick", before: "대상 위치 확인", after: "그리퍼가 대상 물품 보유" },
          { title: "place", before: "그리퍼가 대상 물품 보유", after: "지정 위치 배치 결과 확인 대상" },
        ],
      },
      plan: {
        connected: false,
        message: "현재 제공 경로가 확정되지 않았습니다. 녹화 우선 범위에서는 실시간 계획이나 선택 이유를 표시하지 않습니다.",
      },
      history: {
        connected: false,
        message: "표시할 실제 실행 기록이 연결되지 않았습니다. MongoDB·JSONL 조회는 녹화 이후 후속 연결 범위입니다.",
      },
    },
  };

  // 실행 순서 예시는 등록 목록과 독립적이다. 시나리오별 변경은 아래 함수에만 둔다.
  baseData.task.executionItems = [
    {
      id: "car-key", name: "차 키", statusLabel: "완료",
      resultLabel: "예시 · 전달 확인 · 복구 완료",
      steps: [
        { id: "key-open", label: "서랍 열기", status: "complete", statusLabel: "완료", reason: "예시 · 요청 물품 접근", observation: "예시 · 열림 확인" },
        { id: "key-pick", label: "차 키 집기", status: "complete", statusLabel: "완료", reason: "예시 · 요청 물품 일치", observation: "예시 · 파지 확인" },
        { id: "key-deliver", label: "전달 검증", status: "complete", statusLabel: "완료", reason: "예시 · 전달 트레이 확인", observation: "예시 · 차 키 전달 확인" },
        { id: "key-restore", label: "서랍 닫기·복귀", status: "complete", statusLabel: "완료", reason: "예시 · 작업 정리", observation: "예시 · 복구 완료" },
      ],
    },
    {
      id: "eraser", name: "지우개", statusLabel: "진행 중",
      resultLabel: "예시 · 전달 결과 미확정", steps: [],
    },
    {
      id: "watch", name: "시계",
      statusLabel: "대기", resultLabel: "예시 · 미실행",
      steps: [
        { id: "watch-open", label: "서랍 열기", status: "waiting", statusLabel: "미실행" },
        { id: "watch-pick", label: "시계 집기", status: "waiting", statusLabel: "미실행" },
        { id: "watch-deliver", label: "전달 검증", status: "waiting", statusLabel: "미실행", reason: "예시 · 아직 실행하지 않음", observation: "관측 결과 없음" },
      ],
    },
  ];

  const scenarios = {
    preview(_data) {
      // 명시적 미리보기는 기본 예시를 그대로 사용한다.
    },
    error(data) {
      data.meta.label = "목업 오류 시나리오";
      data.meta.description = "실제 장치 오류가 아닙니다. 확인 전·상태 수신 실패·오류·데이터 없음 표시를 검토합니다.";
      data.connections[0].statusLabel = "연결 확인 전";
      data.connections[1] = {
        id: "robot",
        label: "로봇",
        status: "error",
        statusLabel: "오류",
        description: "목업 오류 시나리오",
      };
      data.connections[2] = {
        id: "camera",
        label: "카메라",
        status: "pending",
        statusLabel: "데이터 없음",
        description: "목업 오류 시나리오 · camera_info 미수신 예시",
      };
      data.connections[3] = {
        id: "runner",
        label: "Runner",
        status: "disconnected",
        statusLabel: "상태 수신 실패",
        description: "목업 오류 시나리오 · /runner/status 미수신 예시",
      };
      data.command.processing = { status: "error", label: "처리 상태 확인 불가 · 목업 예시" };
      data.task.status = "error";
      data.task.executionItems[1].statusLabel = "오류";
      data.task.currentAction = "상태 데이터 없음 · 확인 필요 (목업 예시)";
      data.task.steps[3] = {
        ...data.task.steps[3],
        status: "error",
        statusLabel: "오류",
        reason: "배치 결과 상태를 수신하지 못해 확인 필요",
        observation: "데이터 없음",
      };
      data.adminReview.current.rows = [
        { id: "runner", icon: "drawer", label: "Runner 상태", value: "데이터 없음", valueStatus: "waiting", source: "목업 오류 시나리오", receivedAt: null },
      ];
      data.adminReview.current.error = {
        label: "목업 오류 시나리오",
        detail: "실제 장치 오류가 아니라 상태 수신 실패 화면을 검토하기 위한 예시입니다.",
      };
    },
    empty(data) {
      data.drawers[1].items = [];
      data.selectedDrawerId = "bottom";
      data.supplies = [];
    },
    long(data) {
      data.drawers[0].items[0].name = "손목시계 충전 거치대가 포함된 매우 긴 등록 물품명";
      const watchName = "업무용 손목시계 및 교통카드 케이스";
      data.supplies[2].name = watchName;
      data.task.executionItems[2].name = watchName;
      data.command.understood = `차 키·지우개·${watchName}를 찾아 전달합니다.`;
    },
  };

  const params = new URLSearchParams(window.location.search);
  // 미정의 이름은 운영 경로로 정규화해 예시/polling 우회를 방지한다.
  const requested = params.get("scenario");
  const scenarioName = Object.hasOwn(scenarios, requested) ? requested : "default";
  const data = JSON.parse(JSON.stringify(baseData));

  // 깊은 복사 후 현재 물품 단계와 선택 상세가 같은 예시 배열을 사용하게 한다.
  data.task.executionItems[1].steps = data.task.steps;
  if (scenarios[scenarioName]) {
    scenarios[scenarioName](data);
  }

  // 초기 선택은 현재 예시 물품과 일치할 때만 설정한다.
  data.task.selectedExecutionItemId = data.task.executionItems.some(item => item.id === data.task.currentItemId)
    ? data.task.currentItemId : null;
  if (scenarioName === "default") {
    data.meta = { mode: "waiting", label: "상태 확인 전", description: "Runner 요청·결과 수신 전입니다. 실행 상세는 아직 연결되지 않았습니다." };
    data.command = {
      understood: "확인 전",
      interpretation: { status: "waiting", label: "해석 정보 확인 전" },
      receipt: { status: "waiting", label: "접수 상태 확인 전" },
      processing: { status: "waiting", label: "처리 결과 확인 전" },
      confirmation: null,
    };
    data.task = {
      status: "waiting", workDrawerId: null, currentItemId: null, currentItemIcon: null,
      currentAction: "현재 작업 확인 전", detailsExpanded: true, steps: [],
      executionItems: [], selectedExecutionItemId: null,
    };
    data.drawers = [];
    data.selectedDrawerId = null;
    data.supplies = [];
    data.definitionsStatus = "unknown";
    data.adminReview.current = { runId: null, rows: [], error: null };
    data.adminReview.ontology = { relations: [], skills: [] };
  }

  window.ROKEY_DEMO_DATA = data;
  window.ROKEY_DEMO_SCENARIO = scenarioName;
})();
