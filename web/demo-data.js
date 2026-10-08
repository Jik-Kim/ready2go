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
      status: "running",
      workDrawerId: "bottom",
      currentItemIcon: "wallet",
      currentAction: "지갑의 전달 결과를 확인하는 중",
      detailsExpanded: true,
      steps: [
        { id: "open-bottom", label: "아래 서랍 열기", status: "complete", statusLabel: "완료" },
        { id: "pick-wallet", label: "지갑 확인·집기", status: "complete", statusLabel: "완료" },
        { id: "place-wallet", label: "전달 위치에 놓기", status: "complete", statusLabel: "완료" },
        { id: "verify-wallet", label: "배치 결과 검증", status: "current", statusLabel: "진행 중" },
        { id: "close-bottom", label: "아래 서랍 닫기", status: "waiting", statusLabel: "대기" },
      ],
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
