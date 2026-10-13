(function () {
  "use strict";

  // 작업·준비물·정의는 아직 목업이며 4단계에서는 Runner 연결 진단과 기억 상태만 REST로 덮어쓴다.
  const state = window.ROKEY_DEMO_DATA;

  // status-api.js가 제공하는 polling 구현을 렌더링 코드에서 한 번만 참조한다.
  const statusApi = window.ROKEY_STATUS_API;

  const statusIcons = {
    waiting: "○",
    pending: "…",
    ok: "✓",
    disconnected: "×",
    listening: "≋",
    error: "!",
    accepted: "✓",
    confirmed: "✓",
    restore: "↶",
    delivered: "✓",
    searching: "●",
    verifying: "●",
    complete: "✓",
    current: "●",
    stopped: "■",
    unavailable: "?",
  };

  const itemIcons = {
    key: "🔑",
    wallet: "▰",
    watch: "◷",
    note: "▱",
    box: "◆",
    charger: "⌁",
    drawer: "▣",
    gripper: "⌘",
  };

  // 5단계 온톨로지 정의를 읽기 전에도 현재 화면의 두 서랍 ID는 일관되게 표시한다.
  // 그 밖의 ID는 임의 번역하지 않고 Runner 원본을 그대로 보여준다.
  const drawerLabels = {
    drawer_top: "위 서랍",
    drawer_bottom: "아래 서랍",
  };

  // Runner core의 실제 phase 세 값만 사용자 표시 문구와 기존 화면 색상 키로 변환한다.
  const runnerPhaseViews = {
    idle: { label: "대기", status: "waiting" },
    running: { label: "실행 중", status: "running" },
    halted: { label: "정지(잠김)", status: "stopped" },
  };

  // 서랍 ID의 문자순에서는 bottom이 top보다 먼저 오므로 실제 위·아래 위치를
  // 명시한다. 새 ID는 두 기본 서랍 뒤에서 이름순으로 정렬한다.
  const drawerOrder = {
    drawer_top: 0,
    drawer_bottom: 1,
  };

  function getById(id) {
    return document.getElementById(id);
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function makeStatus(status, label, extraClass) {
    const wrapper = makeElement("span", `status status--${status}${extraClass ? ` ${extraClass}` : ""}`);
    const icon = makeElement("span", "status-icon", statusIcons[status] || "○");
    icon.setAttribute("aria-hidden", "true");
    wrapper.append(icon, makeElement("span", "status-text", label));
    return wrapper;
  }

  function makeItemVisual(item) {
    const visual = makeElement("span", `item-visual item-visual--${item.icon}`);
    visual.setAttribute("aria-hidden", "true");
    visual.textContent = itemIcons[item.icon] || "●";
    return visual;
  }

  function getSelectedDrawer() {
    return state.drawers.find((drawer) => drawer.id === state.selectedDrawerId)
      || state.drawers[0]
      || { id: "unknown", label: "확인 전", items: [] };
  }

  function getWorkDrawer() {
    return state.drawers.find((drawer) => drawer.id === state.task.workDrawerId);
  }

  function renderMockNotice() {
    getById("mockDataLabel").textContent = state.meta.label || "목업 데이터";
    getById("mockDataDescription").textContent = state.meta.description
      || "실제 장치와 연결되지 않은 화면입니다.";
    // 목업 오류 시나리오와 실제 REST 오류를 같은 경고 색으로 분명히 표시한다.
    const showError = window.ROKEY_DEMO_SCENARIO === "error" || state.meta.mode === "rest-error";
    getById("mockDataNotice").classList.toggle("is-error-scenario", showError);
  }

  function getRunnerConnection() {
    // id로 찾으면 연결 카드 순서가 바뀌어도 Runner 항목을 안전하게 갱신할 수 있다.
    return state.connections.find((connection) => connection.id === "runner");
  }

  function formatReceivedTime(value) {
    // 수신 전 null과 잘못된 시각을 화면에서 임의의 현재 시각으로 바꾸지 않는다.
    if (!value) return "미수신";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "확인 전";
    // PC·휴대폰의 로컬 시간대로 시·분·초를 읽기 쉽게 표시한다.
    return parsed.toLocaleTimeString("ko-KR", { hour12: false });
  }

  function runnerConnectionView(source) {
    // StateCache의 상세 필드는 유지하고 connection_state만 카드 표시값으로 변환한다.
    const views = {
      unknown: { status: "waiting", label: "확인 전" },
      waiting: { status: "pending", label: "상태 수신 대기" },
      receiving: { status: "ok", label: "상태 수신" },
      disconnected: { status: "disconnected", label: "연결 끊김" },
      error: { status: "error", label: "브리지 오류" },
    };
    return views[source.connection_state] || views.unknown;
  }

  function updateAdminRunnerRow(view, source, sourceLabel) {
    // 검토 화면에는 작업 의미를 추정하지 않고 연결 진단과 원본 수신 시각만 반영한다.
    const rows = state.adminReview?.current?.rows;
    if (!rows) return;
    let runnerRow = rows.find((row) => row.id === "runner");
    if (!runnerRow) {
      runnerRow = { id: "runner", icon: "drawer", label: "Runner 상태" };
      rows.unshift(runnerRow);
    }
    runnerRow.value = view.label;
    runnerRow.valueStatus = view.status;
    runnerRow.source = sourceLabel;
    runnerRow.receivedAt = source ? formatReceivedTime(source.last_received_at) : null;
  }

  function isRecord(value) {
    // 배열·null을 제외한 JSON 객체만 Runner 상태 map으로 허용한다.
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function compareDrawerIds(left, right) {
    // 정의된 물리 순서를 먼저 적용하고 같은 순위의 추가 ID만 이름순으로 정렬한다.
    const leftOrder = drawerOrder[left] ?? 100;
    const rightOrder = drawerOrder[right] ?? 100;
    return leftOrder - rightOrder || left.localeCompare(right);
  }

  function setRunnerSummaryUnknown() {
    // 기본 화면에서 목업 실행 요약이 실제 Runner 값처럼 보이지 않게 초기화한다.
    state.adminReview.current.liveSummary = {
      taskId: "확인 전",
      currentStep: "확인 전",
      phase: "확인 전",
      status: "waiting",
    };
  }

  function applyRunnerSummary(source) {
    // JSON 객체 수신이 정상일 때만 Runner 요약 필드를 관리자 화면에 사용한다.
    const data = source?.connection_state === "receiving" && source.message_valid === true
      && isRecord(source.data) ? source.data : null;
    if (!data) {
      setRunnerSummaryUnknown();
      return false;
    }
    // 계약에 없는 phase를 대기로 추정하지 않고 확인이 필요한 값으로 표시한다.
    const phaseView = typeof data.phase === "string" ? runnerPhaseViews[data.phase] : null;
    state.adminReview.current.liveSummary = {
      taskId: typeof data.task_id === "string" ? data.task_id : "확인 전",
      currentStep: typeof data.current_step === "string" ? data.current_step : "확인 전",
      phase: phaseView?.label || "확인 전",
      status: phaseView?.status || "waiting",
    };
    return true;
  }

  function validateRobotStateData(source) {
    // 연결·파싱이 정상이어도 네 필드가 현재 Runner 형식과 다르면 UI가 목업을
    // 대신 보여주지 않고 전체 robot_state 표시를 `확인 전`으로 유지한다.
    if (!source || source.connection_state !== "receiving" || source.message_valid !== true) return null;
    const data = source.data;
    if (!isRecord(data)) return null;
    const fields = ["robot_pose", "gripper", "open", "located_in"];
    if (!fields.every((field) => isRecord(data[field]))) return null;
    if (!Object.values(data.robot_pose).every((value) => typeof value === "string")) return null;
    if (!Object.values(data.gripper).every((value) => typeof value === "string")) return null;
    if (!Object.values(data.open).every((value) => typeof value === "boolean")) return null;
    if (!Object.values(data.located_in).every((value) => typeof value === "string")) return null;
    return data;
  }

  function itemIconForId(itemId) {
    // 5단계 정의 로딩 전에는 기존 화면 아이콘과 명확히 일치하는 ID만 재사용한다.
    const normalized = itemId.replaceAll("_", "-");
    if (normalized === "car-key") return "key";
    if (["wallet", "watch", "note", "box", "charger"].includes(normalized)) return normalized;
    return "box";
  }

  function setRobotStateUnknown(source, detail) {
    // 초기 수신 전·연결 끊김·필드 누락·형식 불일치 모두 같은 사용자 문구를 쓴다.
    state.robotStateLive = false;
    state.drawers = [{ id: "unknown", label: "확인 전", items: [] }];
    state.selectedDrawerId = "unknown";
    const receivedAt = source ? formatReceivedTime(source.last_received_at) : null;
    const sourceLabel = detail || "/robot_state · 확인 전";
    state.adminReview.current.rows = [
      { id: "robot-pose", icon: "drawer", label: "로봇 위치", value: "확인 전", valueStatus: "waiting", source: sourceLabel, receivedAt },
      { id: "gripper", icon: "gripper", label: "그리퍼", value: "확인 전", valueStatus: "waiting", source: sourceLabel, receivedAt },
      { id: "drawer-state", icon: "drawer", label: "서랍 상태", value: "확인 전", valueStatus: "waiting", source: sourceLabel, receivedAt },
      { id: "item-location", icon: "box", label: "물품 위치", value: "확인 전", valueStatus: "waiting", source: sourceLabel, receivedAt },
    ];
  }

  function applyRobotStateSource(source) {
    const data = validateRobotStateData(source);
    if (!data) {
      const detail = source?.last_error
        ? `/robot_state · ${source.last_error}`
        : "/robot_state · 값 누락 또는 형식 불일치";
      setRobotStateUnknown(source, detail);
      return false;
    }

    // open과 located_in의 현재 Runner 기억값으로 서랍·물품 행을 다시 만든다.
    // 등록명·별칭은 5단계 범위이므로 여기서는 원본 ID를 그대로 사용한다.
    const drawerIds = new Set(
      Object.keys(data.open).filter((id) => id.startsWith("drawer_")),
    );
    Object.values(data.located_in)
      .filter((id) => id.startsWith("drawer_"))
      .forEach((id) => drawerIds.add(id));

    const receivedAt = formatReceivedTime(source.last_received_at);
    state.drawers = [...drawerIds].sort(compareDrawerIds).map((drawerId) => {
      const open = data.open[drawerId];
      const openLabel = typeof open === "boolean" ? (open ? "열림" : "닫힘") : "확인 전";
      const items = Object.entries(data.located_in)
        .filter(([, location]) => location === drawerId)
        .map(([itemId]) => ({
          id: itemId,
          name: itemId,
          icon: itemIconForId(itemId),
          status: "pending",
          statusLabel: "Runner 기억 위치",
          checkedAt: receivedAt,
        }));
      return {
        id: drawerId,
        label: `${drawerLabels[drawerId] || drawerId} · ${openLabel}`,
        items,
      };
    });
    if (state.drawers.length === 0) {
      state.drawers = [{ id: "unknown", label: "확인 전", items: [] }];
    }
    if (!state.drawers.some((drawer) => drawer.id === state.selectedDrawerId)) {
      state.selectedDrawerId = state.drawers[0].id;
    }

    const pose = typeof data.robot_pose.robot === "string" ? data.robot_pose.robot : "확인 전";
    const gripper = typeof data.gripper.robot === "string" ? data.gripper.robot : "확인 전";
    // 전달 트레이 같은 비서랍 장소는 상태 원본에 보존하되 관리자 서랍 요약에서는 제외한다.
    const openEntries = Object.entries(data.open)
      .filter(([id]) => id.startsWith("drawer_"))
      .sort(([left], [right]) => compareDrawerIds(left, right));
    const openSummary = openEntries.length
      ? openEntries.map(([id, value]) => `${drawerLabels[id] || id}: ${value ? "열림" : "닫힘"}`).join(" · ")
      : "확인 전";
    const locationSummary = Object.entries(data.located_in).length
      ? Object.entries(data.located_in).map(([id, value]) => `${id} → ${drawerLabels[value] || value}`).join(" · ")
      : "확인 전";
    const sourceLabel = "/robot_state · Runner 기억 상태";
    state.adminReview.current.rows = [
      { id: "robot-pose", icon: "drawer", label: "로봇 위치", value: pose, valueStatus: pose === "확인 전" ? "waiting" : "pending", source: sourceLabel, receivedAt },
      { id: "gripper", icon: "gripper", label: "그리퍼", value: gripper, valueStatus: gripper === "확인 전" ? "waiting" : "pending", source: sourceLabel, receivedAt },
      { id: "drawer-state", icon: "drawer", label: "서랍 상태", value: openSummary, valueStatus: openSummary === "확인 전" ? "waiting" : "pending", source: sourceLabel, receivedAt },
      { id: "item-location", icon: "box", label: "물품 위치", value: locationSummary, valueStatus: locationSummary === "확인 전" ? "waiting" : "pending", source: sourceLabel, receivedAt },
    ];
    state.robotStateLive = true;
    return true;
  }

  function applyStatusApiSuccess(payload, lastSuccessAt) {
    // validatePayload를 통과한 두 source를 Runner 연결과 기억 상태에 각각 사용한다.
    const source = payload.sources.runner;
    const robotStateSource = payload.sources.robot_state;
    const view = runnerConnectionView(source);
    const connection = getRunnerConnection();
    if (!connection) return;

    const publisher = source.publisher_present === true
      ? "ROS 발행자 발견"
      : source.publisher_present === false
        ? "ROS 발행자 없음"
        : "ROS 발행자 확인 전";
    const received = formatReceivedTime(source.last_received_at);
    const restSuccess = formatReceivedTime(lastSuccessAt);

    // REST 성공과 ROS 수신 상태를 한 문구로 합치지 않고 각각 설명한다.
    Object.assign(connection, {
      status: view.status,
      statusLabel: view.label,
      description: `${publisher} · ROS 최근 수신 ${received} · REST 최근 성공 ${restSuccess}`,
    });
    state.meta.mode = "partial-live";
    state.meta.label = "REST 연결됨 · 부분 실데이터";
    const runnerSummaryApplied = applyRunnerSummary(source);
    const robotStateApplied = applyRobotStateSource(robotStateSource);
    state.meta.description = robotStateApplied
      ? "Runner 연결과 기억 상태는 실제 데이터입니다. 작업·준비물·등록 정의는 아직 목업입니다."
      : "Runner 연결은 실제 데이터이며 /robot_state 표시는 확인 전입니다. 작업·준비물·등록 정의는 아직 목업입니다.";

    updateAdminRunnerRow(view, source, "/runner/status · Flask REST");
    state.adminReview.current.liveConnected = runnerSummaryApplied && robotStateApplied;
    state.adminReview.current.error = source.last_error
      ? { label: "현재 오류: Runner", detail: source.last_error }
      : robotStateSource.last_error
        ? { label: "현재 오류: robot_state", detail: robotStateSource.last_error }
        : !robotStateApplied
          ? { label: "현재 오류: robot_state 형식", detail: "필수 필드가 없거나 예상한 형식과 달라 확인 전으로 표시합니다." }
          : { label: "현재 오류: 없음", detail: "Runner 상태 캐시를 정상 조회했습니다." };

    // 바뀐 부분만 다시 그려 사용자가 연 펼침·선택 상태를 불필요하게 초기화하지 않는다.
    renderMockNotice();
    renderConnections();
    renderDrawerSelectors();
    renderInventory();
    renderAdminSummary();
    renderAdminDataMeta();
    renderAdminCurrentState();
  }

  function applyStatusApiFailure(_error, lastSuccessAt) {
    // 이전 성공 응답이 있어도 현재 REST 단절 뒤 정상 연결로 계속 보이지 않게 즉시 덮어쓴다.
    const connection = getRunnerConnection();
    if (!connection) return;
    const lastSuccess = formatReceivedTime(lastSuccessAt);
    Object.assign(connection, {
      status: "error",
      statusLabel: "REST 연결 오류",
      description: `현재 상태를 사용하지 않습니다. REST 마지막 성공 ${lastSuccess}`,
    });
    state.meta.mode = "rest-error";
    state.meta.label = "REST 연결 오류 · 목업 화면";
    state.meta.description = "Runner 현재 상태를 조회할 수 없습니다. 나머지 화면 값은 목업입니다.";

    setRobotStateUnknown(null, "Flask REST 미수신");
    setRunnerSummaryUnknown();
    state.adminReview.current.liveConnected = false;

    const view = { status: "error", label: "REST 연결 오류" };
    updateAdminRunnerRow(view, null, "Flask REST 미수신");
    state.adminReview.current.error = {
      label: "현재 오류: REST 연결",
      detail: "이전 Runner 값을 현재 정상 상태로 표시하지 않습니다.",
    };

    renderMockNotice();
    renderConnections();
    renderDrawerSelectors();
    renderInventory();
    renderAdminSummary();
    renderAdminDataMeta();
    renderAdminCurrentState();
  }

  function renderConnections() {
    const container = getById("connectionStatus");
    container.replaceChildren();

    state.connections.forEach((connection) => {
      const block = makeElement("div", `connection-block connection-block--${connection.status}`);
      block.setAttribute("role", "img");
      block.setAttribute("aria-label", `${connection.label}: ${connection.statusLabel || "확인 전"}. ${connection.description}`);
      const icon = makeElement("span", "connection-icon", statusIcons[connection.status] || "○");
      icon.setAttribute("aria-hidden", "true");
      const text = makeElement("span", "connection-text");
      text.append(
        makeElement("span", "connection-label", connection.label),
        makeElement("small", "connection-detail", connection.statusLabel || "확인 전"),
      );
      block.append(icon, text);
      container.append(block);
    });
  }

  function renderCommand() {
    getById("understoodText").textContent = state.command.understood;
    getById("mobileCommandHeading").textContent = state.command.understood;
    getById("mobileUnderstoodText").textContent = state.command.understood;

    getById("commandInterpretationStatus").replaceChildren(
      makeStatus(state.command.interpretation.status, state.command.interpretation.label),
    );
    getById("mobileInterpretationStatus").replaceChildren(
      makeStatus(state.command.interpretation.status, state.command.interpretation.label),
    );

    getById("commandProcessingStatus").replaceChildren(
      makeStatus(state.command.processing.status, state.command.processing.label),
    );
    getById("mobileProcessingStatus").replaceChildren(
      makeStatus(state.command.processing.status, state.command.processing.label),
    );
    getById("mobileReceiptStatus").replaceChildren(
      makeStatus(state.command.receipt.status, state.command.receipt.label),
    );

    const confirmationRow = getById("mobileConfirmationRow");
    confirmationRow.hidden = !state.command.confirmation;
    getById("mobileConfirmationText").textContent = state.command.confirmation || "";
  }

  function createDrawerButton(drawer, compact) {
    const selected = drawer.id === state.selectedDrawerId;
    const button = makeElement("button", `${compact ? "drawer-tab" : "drawer-unit"}${selected ? " is-selected" : ""}`);
    button.type = "button";
    button.dataset.drawerId = drawer.id;
    button.setAttribute("aria-pressed", String(selected));
    button.setAttribute("aria-label", `${drawer.label} 물품 조회${selected ? ", 선택됨" : ""}`);

    if (compact) {
      button.textContent = drawer.label;
    } else {
      const handle = makeElement("span", "drawer-handle");
      handle.setAttribute("aria-hidden", "true");
      const label = makeElement("span", "drawer-label", drawer.label);
      const mark = makeElement("span", "drawer-check", selected ? "✓" : "");
      mark.setAttribute("aria-hidden", "true");
      button.append(handle, label, mark);
    }

    button.addEventListener("click", () => selectDrawer(drawer.id));
    return button;
  }

  function renderDrawerSelectors() {
    const desktop = getById("drawerSelector");
    const mobile = getById("mobileDrawerSelector");
    desktop.replaceChildren();
    mobile.replaceChildren();

    state.drawers.forEach((drawer) => {
      desktop.append(createDrawerButton(drawer, false));
      mobile.append(createDrawerButton(drawer, true));
    });
  }

  function renderInventory() {
    const drawer = getSelectedDrawer();
    const tableBody = getById("inventoryTableBody");
    const mobileList = getById("mobileInventoryList");
    tableBody.replaceChildren();
    mobileList.replaceChildren();

    getById("inventoryTitle").textContent = state.robotStateLive === true
      ? `${drawer.label} · Runner 기억 물품`
      : state.robotStateLive === false
        ? `${drawer.label} · 확인 전`
        : `${drawer.label} · 등록 물품`;
    getById("inventoryCount").textContent = `${drawer.items.length}개`;
    getById("selectedDrawerLabel").textContent = drawer.label;

    const isEmpty = drawer.items.length === 0;
    getById("inventoryEmpty").hidden = !isEmpty;
    getById("mobileInventoryEmpty").hidden = !isEmpty;

    drawer.items.forEach((item) => {
      const row = document.createElement("tr");
      const visualCell = document.createElement("td");
      visualCell.append(makeItemVisual(item));
      const nameCell = makeElement("td", "inventory-name", item.name);
      const statusCell = document.createElement("td");
      statusCell.append(makeStatus(item.status, item.statusLabel));
      const timeCell = makeElement("td", "time-cell", item.checkedAt || "—");
      row.append(visualCell, nameCell, statusCell, timeCell);
      tableBody.append(row);

      const card = makeElement("article", "mobile-inventory-item");
      const text = makeElement("div", "mobile-inventory-text");
      text.append(makeElement("strong", "", item.name), makeElement("span", "", `확인 시각 ${item.checkedAt || "—"}`));
      card.append(makeItemVisual(item), text, makeStatus(item.status, item.statusLabel));
      mobileList.append(card);
    });
  }

  function renderSupplies() {
    const list = getById("supplyList");
    list.replaceChildren();

    const completed = state.supplies.filter((item) => item.status === "delivered").length;
    getById("completionCount").textContent = `${completed} / ${state.supplies.length} 전달 완료`;
    getById("suppliesEmpty").hidden = state.supplies.length !== 0;

    state.supplies.forEach((item) => {
      const row = makeElement("article", "supply-item");
      const nameWrap = makeElement("div", "supply-name");
      nameWrap.append(makeItemVisual(item), makeElement("strong", "", item.name));
      row.append(nameWrap, makeStatus(item.status, item.statusLabel));
      list.append(row);
    });
  }

  function renderTask() {
    const workDrawer = getWorkDrawer();
    const location = workDrawer ? workDrawer.label : "확인 전";
    getById("taskLocation").textContent = location;
    getById("mobileTaskLocation").textContent = location;
    getById("currentAction").textContent = state.task.currentAction;
    const currentItem = getById("currentItemVisual");
    currentItem.className = `item-visual item-visual--${state.task.currentItemIcon}`;
    currentItem.textContent = itemIcons[state.task.currentItemIcon] || "●";

    getById("receiptStatus").replaceChildren(
      makeStatus(state.command.receipt.status, state.command.receipt.label),
    );

    const details = getById("taskDetails");
    const toggle = getById("taskDetailsToggle");
    details.hidden = !state.task.detailsExpanded;
    toggle.setAttribute("aria-expanded", String(state.task.detailsExpanded));

    const progress = getById("progressSteps");
    progress.replaceChildren();
    progress.style.gridTemplateColumns = `repeat(${state.task.steps.length}, minmax(132px, 1fr))`;
    progress.style.minWidth = `${Math.max(state.task.steps.length * 150, 600)}px`;
    state.task.steps.forEach((step, index) => {
      const item = makeElement("li", `is-${step.status}`);
      const dotText = step.status === "complete"
        ? "✓"
        : step.status === "current"
          ? "●"
          : step.status === "stopped"
            ? "■"
            : step.status === "error"
              ? "!"
            : String(index + 1);
      const dot = makeElement("span", "step-dot", dotText);
      dot.setAttribute("aria-hidden", "true");
      const text = makeElement("span", "step-text");
      text.append(
        makeElement("span", "step-label", step.label),
        makeElement("span", "step-status", step.statusLabel),
      );
      item.append(dot, text);
      if (step.status === "current") item.setAttribute("aria-current", "step");
      progress.append(item);
    });

    const evidenceStep = getCurrentTaskStep();
    getById("currentStepReason").textContent = evidenceStep?.reason || "확인 전";
    getById("currentStepObservation").textContent = evidenceStep?.observation || "미수신";

  }

  function getCurrentTaskStep() {
    return state.task.steps.find((step) => step.status === "current")
      || state.task.steps.find((step) => step.status === "error")
      || state.task.steps.find((step) => step.status === "unavailable")
      || state.task.steps.find((step) => step.status === "stopped")
      || state.task.steps.at(-1);
  }

  function getTaskExecutionStatus() {
    const statuses = {
      running: { label: "진행 중", key: "running" },
      verifying: { label: "확인 중", key: "verifying" },
      complete: { label: "완료", key: "complete" },
      stopped: { label: "중단됨", key: "stopped" },
      error: { label: "오류", key: "error" },
      unavailable: { label: "확인 불가", key: "unavailable" },
    };
    return statuses[state.task.status] || { label: "확인 전", key: "waiting" };
  }

  function renderAdminSummary() {
    const data = state.adminReview.current;
    // 기본 화면은 Runner 실데이터 요약을 사용하고 고정 검토 시나리오는 기존 목업을 유지한다.
    const liveSummary = data.liveSummary;
    const currentStep = liveSummary ? null : getCurrentTaskStep();
    const executionStatus = liveSummary
      ? { label: liveSummary.phase, key: liveSummary.status }
      : getTaskExecutionStatus();
    const summary = getById("adminRunSummary");
    summary.replaceChildren();

    [
      { label: liveSummary ? "태스크 ID" : "실행 ID", value: liveSummary?.taskId || data.runId || "미수신", icon: "▧" },
      { label: "현재 단계", value: liveSummary?.currentStep || currentStep?.label || "확인 전", icon: "⚙" },
      { label: "실행 상태", value: executionStatus.label, icon: "●", status: executionStatus.key },
    ].forEach((entry) => {
      const item = makeElement("article", `admin-summary-item${entry.status ? ` is-${entry.status}` : ""}`);
      const icon = makeElement("span", "admin-summary-icon", entry.icon);
      icon.setAttribute("aria-hidden", "true");
      const text = makeElement("div");
      text.append(makeElement("span", "eyebrow", entry.label), makeElement("strong", "", entry.value));
      item.append(icon, text);
      summary.append(item);
    });
  }

  function renderAdminDataMeta() {
    // 현재 상태 탭만 실데이터 연결 여부를 표시하며 후속 탭의 목업 표시는 유지한다.
    const current = state.adminReview.current;
    const connected = current.liveConnected === true;
    const restError = state.meta.mode === "rest-error";
    getById("adminDataNotice").textContent = connected
      ? "부분 실데이터 · 인증 미구현 읽기 전용 화면 · 현재 상태는 Runner에서 수신하며 온톨로지·계획 근거·실행 기록은 아직 목업 또는 후속 연결입니다."
      : restError
        ? "REST 연결 오류 · 현재 상태는 확인 전이며 온톨로지·계획 근거·실행 기록은 아직 목업 또는 후속 연결입니다."
        : state.meta.mode === "partial-live"
          ? "부분 실데이터 · 인증 미구현 읽기 전용 화면 · Runner 응답은 수신했지만 현재 상태 일부는 확인 전입니다."
          : "목업 데이터 · 인증 미구현 읽기 전용 화면 · 현재 상태와 온톨로지만 녹화 우선 연결 예정입니다.";
    getById("adminCurrentTabStatus").textContent = connected ? "연결됨" : "확인 전";
    getById("adminCurrentSourceLabel").textContent = connected
      ? "/runner/status · /robot_state 연결됨"
      : "/runner/status · /robot_state 확인 전";
    getById("adminCurrentDataLabel").textContent = connected ? "실데이터" : "확인 전";
  }

  function renderAdminCurrentState() {
    const current = state.adminReview.current;
    const body = getById("adminCurrentStateBody");
    body.replaceChildren();

    current.rows.forEach((entry) => {
      const row = document.createElement("tr");
      const itemCell = document.createElement("td");
      const item = makeElement("div", "admin-state-item");
      item.append(makeItemVisual(entry), makeElement("strong", "", entry.label));
      itemCell.append(item);
      const valueCell = document.createElement("td");
      valueCell.append(makeStatus(entry.valueStatus || "waiting", entry.value || "확인 전"));
      row.append(
        itemCell,
        valueCell,
        makeElement("td", "admin-source-cell", entry.source || "미수신"),
        makeElement("td", "time-cell", entry.receivedAt || "—"),
      );
      body.append(row);
    });

    const error = current.error;
    const errorStatus = getById("adminErrorStatus");
    errorStatus.replaceChildren(
      makeElement("strong", "", error?.label || "현재 오류: 미수신"),
      makeElement("span", "", error?.detail || "오류 정보가 수신되지 않았습니다."),
    );
  }

  function renderAdminOntology() {
    const ontology = state.adminReview.ontology;
    const relations = getById("adminOntologyRelations");
    const skills = getById("adminSkillDefinitions");
    relations.replaceChildren();
    skills.replaceChildren();

    ontology.relations.forEach((entry) => {
      const card = makeElement("article", "definition-item");
      card.append(
        makeElement("span", "eyebrow", entry.title),
        makeElement("strong", "", entry.value),
        makeElement("small", "", entry.meta),
      );
      relations.append(card);
    });

    ontology.skills.forEach((entry) => {
      const card = makeElement("article", "definition-item skill-definition");
      card.append(makeElement("h3", "", entry.title));
      const list = document.createElement("dl");
      [
        ["사전 조건", entry.before],
        ["예상 결과", entry.after],
      ].forEach(([label, value]) => {
        const row = document.createElement("div");
        row.append(makeElement("dt", "", label), makeElement("dd", "", value || "미수신"));
        list.append(row);
      });
      card.append(list);
      skills.append(card);
    });
  }

  function renderAdmin() {
    if (!state.adminReview) return;
    renderAdminSummary();
    renderAdminDataMeta();
    renderAdminCurrentState();
    renderAdminOntology();
    getById("adminPlanMessage").textContent = state.adminReview.plan.message;
    getById("adminHistoryMessage").textContent = state.adminReview.history.message;
  }

  function selectAdminTab(tabName, moveFocus) {
    document.querySelectorAll("[data-admin-tab]").forEach((tab) => {
      const selected = tab.dataset.adminTab === tabName;
      tab.classList.toggle("is-selected", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && moveFocus) tab.focus();
    });
    document.querySelectorAll("[data-admin-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.adminPanel !== tabName;
    });
  }

  function syncViewFromHash() {
    const adminVisible = window.location.hash === "#admin";
    getById("dashboardView").hidden = adminVisible;
    getById("adminView").hidden = !adminVisible;
    document.title = adminVisible ? "ROKEY · 읽기 전용 검토 화면" : "ROKEY · 출근 준비 도우미";
    if (adminVisible) {
      window.scrollTo(0, 0);
      getById("exitAdminView").focus();
    }
  }

  function renderAll() {
    renderMockNotice();
    renderConnections();
    renderCommand();
    renderDrawerSelectors();
    renderInventory();
    renderSupplies();
    renderTask();
  }

  function selectDrawer(drawerId) {
    if (!state.drawers.some((drawer) => drawer.id === drawerId)) return;
    state.selectedDrawerId = drawerId;
    renderDrawerSelectors();
    renderInventory();
  }

  function toggleTaskDetails() {
    state.task.detailsExpanded = !state.task.detailsExpanded;
    renderTask();
  }

  function openDialog(dialogId, trigger) {
    const dialog = getById(dialogId);
    dialog.dataset.returnFocus = trigger.id;
    dialog.showModal();
    const closeButton = dialog.querySelector("[data-close-dialog]");
    if (closeButton) closeButton.focus();
  }

  function closeDialog(dialog) {
    const returnFocusId = dialog.dataset.returnFocus;
    dialog.close();
    if (returnFocusId) getById(returnFocusId)?.focus();
  }

  getById("openCommandDetails").addEventListener("click", (event) => openDialog("commandDialog", event.currentTarget));
  getById("openDrawerPanel").addEventListener("click", (event) => openDialog("drawerDialog", event.currentTarget));
  getById("taskDetailsToggle").addEventListener("click", toggleTaskDetails);
  getById("openAdminView").addEventListener("click", () => {
    selectAdminTab("current", false);
    window.location.hash = "admin";
  });
  getById("exitAdminView").addEventListener("click", () => {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    syncViewFromHash();
    getById("openAdminView").focus();
  });

  document.querySelectorAll("[data-admin-tab]").forEach((tab) => {
    tab.addEventListener("click", () => selectAdminTab(tab.dataset.adminTab, false));
    tab.addEventListener("keydown", (event) => {
      const tabs = [...document.querySelectorAll("[data-admin-tab]")];
      const index = tabs.indexOf(event.currentTarget);
      let nextIndex;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === undefined) return;
      event.preventDefault();
      selectAdminTab(tabs[nextIndex].dataset.adminTab, true);
    });
  });
  window.addEventListener("hashchange", syncViewFromHash);

  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => closeDialog(getById(button.dataset.closeDialog)));
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeDialog(dialog);
    });
  });

  // 기본 화면은 첫 REST 응답 전부터 robot_state 목업을 숨기고 `확인 전`으로 시작한다.
  // 고정 long·empty·error 시나리오는 UI 검토용 목업이므로 기존 데이터를 유지한다.
  if (window.ROKEY_DEMO_SCENARIO === "default") {
    setRunnerSummaryUnknown();
    state.adminReview.current.liveConnected = false;
    setRobotStateUnknown(null, "/robot_state · 수신 전");
  }

  renderAll();
  renderAdmin();
  selectAdminTab("current", false);
  syncViewFromHash();

  // long·empty·error URL은 고정 목업 검토용으로 유지하고 기본 화면에서만 REST를 연결한다.
  if (statusApi && window.ROKEY_DEMO_SCENARIO === "default") {
    const poller = statusApi.createPoller({
      fetchStatus: window.fetch.bind(window),
      onSuccess: applyStatusApiSuccess,
      onFailure: applyStatusApiFailure,
    });
    poller.start();
    // 페이지를 떠날 때 예약 timer를 정리해 백그라운드 요청이 남지 않게 한다.
    window.addEventListener("pagehide", () => poller.stop(), { once: true });
  }
})();
