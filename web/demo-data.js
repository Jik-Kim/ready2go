(function () {
  "use strict";

  const baseData = {
    meta: {
      mode: "demo",
      deviceConnected: false,
    },
    connections: [
      {
        id: "voice",
        label: "음성",
        status: "waiting",
        statusLabel: "장치 미연동",
        description: "실제 음성 장치 연결 정보 없음",
        callStatus: "listening",
        callStatusLabel: "호출: 데모 청취 중",
      },
      { id: "robot", label: "로봇", status: "waiting", statusLabel: "미연동", description: "실제 로봇 연결 정보 없음" },
      { id: "camera", label: "카메라", status: "waiting", statusLabel: "미연동", description: "실제 카메라 연결 정보 없음" },
    ],
    command: {
      heard: "헬로 로키, 출근 준비물 꺼내줘",
      understood: "차 키·지갑·시계를 찾아 전달합니다.",
      receipt: { status: "accepted", label: "명령 접수 완료" },
      recognition: { status: "listening", label: "데모 음성 원문" },
      interpretation: { status: "confirmed", label: "데모 명령 해석" },
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
      { id: "wallet", name: "지갑", icon: "wallet", status: "verifying", statusLabel: "결과 확인 중" },
      { id: "watch", name: "시계", icon: "watch", status: "waiting", statusLabel: "대기" },
    ],
    task: {
      status: "verifying",
      workDrawerId: "bottom",
      currentItemIcon: "wallet",
      currentAction: "지갑의 전달 결과를 확인하는 중",
      detailsExpanded: true,
      steps: [
        { id: "open-bottom", label: "아래 서랍 열기", status: "complete", statusLabel: "완료", reason: "등록 위치의 물품에 접근", observation: "서랍 열림 상태 확인" },
        { id: "pick-wallet", label: "지갑 확인·집기", status: "complete", statusLabel: "완료", reason: "요청 물품과 등록 물품 일치 확인", observation: "지갑 집기 완료" },
        { id: "place-wallet", label: "전달 위치에 놓기", status: "complete", statusLabel: "완료", reason: "사용자에게 물품 전달", observation: "전달 위치 배치 완료" },
        { id: "verify-wallet", label: "배치 결과 검증", status: "current", statusLabel: "진행 중", reason: "지갑이 전달 위치에 놓였는지 확인", observation: "확인 대기" },
        { id: "close-bottom", label: "아래 서랍 닫기", status: "waiting", statusLabel: "대기", reason: "작업 후 서랍 상태 복구", observation: "미수행" },
      ],
    },
    adminReview: {
      dataModeLabel: "데모 샘플 · 실제 관리자 API 미연동",
      current: {
        runId: "demo_001",
        rows: [
          { id: "bottom-drawer", icon: "drawer", label: "아래 서랍", value: "열림", valueStatus: "confirmed", source: "Runner 저장 상태", receivedAt: "08:12:19" },
          { id: "gripper", icon: "gripper", label: "그리퍼", value: "열림", valueStatus: "confirmed", source: "Runner 저장 상태", receivedAt: "08:12:20" },
          { id: "wallet-placement", icon: "wallet", label: "지갑 배치", value: "확인 대기", valueStatus: "verifying", source: "관측 결과 미수신", receivedAt: null },
        ],
        error: { label: "현재 오류: 미수신", detail: "오류 데이터 제공 경로가 연결되지 않아 오류 유무를 판단할 수 없습니다." },
      },
      ontology: {
        relations: [
          { title: "등록 물품", value: "차 키 · 지갑 · 시계", meta: "샘플 정의" },
          { title: "등록 장소", value: "위 서랍 · 아래 서랍", meta: "샘플 정의" },
          { title: "관계", value: "지갑 → 아래 서랍", meta: "샘플 관계" },
        ],
        skills: [
          { title: "pick", before: "대상 위치 확인", after: "그리퍼가 대상 물품 보유" },
          { title: "place", before: "그리퍼가 대상 물품 보유", after: "지정 위치 배치 결과 확인 대상" },
        ],
      },
      plan: {
        connected: false,
        message: "해당 실행의 목표·생성 순서·단계별 이유를 제공하는 웹 API 경로가 없습니다. 실제 제공 경로가 합의되기 전에는 프런트엔드에서 계획이나 선택 이유를 생성하지 않습니다.",
      },
      history: {
        connected: false,
        selectedRunId: "demo_history_001",
        runs: [
          { id: "demo_history_001", title: "출근 준비물 전달", status: "데모 완료", startedAt: "08:03:11" },
          { id: "demo_history_002", title: "등록 물품 확인", status: "데모 중단", startedAt: "07:54:26" },
        ],
        detailsByRun: {
          demo_history_001: [
            { step: "요청 확인", result: "완료", condition: "샘플 요청 있음", change: "데모 실행 생성", error: "미수신" },
            { step: "물품 탐색", result: "완료", condition: "샘플 등록 위치 있음", change: "대상 확인 표시", error: "미수신" },
            { step: "전달 결과 확인", result: "완료", condition: "샘플 관측값", change: "데모 완료 표시", error: "미수신" },
          ],
          demo_history_002: [
            { step: "등록 물품 확인", result: "중단", condition: "샘플 등록 정보 있음", change: "데모 중단 표시", error: "오류 정보 미수신" },
          ],
        },
      },
    },
  };

  const scenarios = {
    error(data) {
      data.connections[1] = {
        id: "robot",
        label: "로봇",
        status: "error",
        statusLabel: "연결 오류",
        description: "샘플 상태: 연결 오류",
      };
      data.task.currentAction = "로봇 연결 오류 · 확인 필요";
    },
    empty(data) {
      data.drawers[1].items = [];
      data.selectedDrawerId = "bottom";
      data.supplies = [];
    },
    long(data) {
      data.drawers[0].items[0].name = "손목시계 충전 거치대가 포함된 매우 긴 등록 물품명";
      data.supplies[2].name = "업무용 손목시계 및 교통카드 케이스";
      data.command.understood = "차 키·지갑·업무용 손목시계 및 교통카드 케이스를 찾아 전달합니다.";
    },
  };

  const params = new URLSearchParams(window.location.search);
  const scenarioName = params.get("scenario") || "default";
  const data = JSON.parse(JSON.stringify(baseData));

  if (scenarios[scenarioName]) {
    scenarios[scenarioName](data);
  }

  window.ROKEY_DEMO_DATA = data;
  window.ROKEY_DEMO_SCENARIO = scenarioName;
})();
