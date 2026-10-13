(function () {
  "use strict";

  // 실제 연동 시 이 데이터 공급원만 웹 API 어댑터 값으로 교체합니다. 자세한 내용: web/README.md
  const state = window.ROKEY_DEMO_DATA;

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
    return state.drawers.find((drawer) => drawer.id === state.selectedDrawerId) || state.drawers[0];
  }

  function getWorkDrawer() {
    return state.drawers.find((drawer) => drawer.id === state.task.workDrawerId);
  }

  function renderMockNotice() {
    getById("mockDataLabel").textContent = state.meta.label || "목업 데이터";
    getById("mockDataDescription").textContent = state.meta.description
      || "실제 장치와 연결되지 않은 화면입니다.";
    getById("mockDataNotice").classList.toggle("is-error-scenario", window.ROKEY_DEMO_SCENARIO === "error");
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

    getById("inventoryTitle").textContent = `${drawer.label} · 등록 물품`;
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
    const currentStep = getCurrentTaskStep();
    const executionStatus = getTaskExecutionStatus();
    const summary = getById("adminRunSummary");
    summary.replaceChildren();

    [
      { label: "실행 ID", value: data.runId || "미수신", icon: "▧" },
      { label: "현재 단계", value: currentStep?.label || "확인 전", icon: "⚙" },
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

  renderAll();
  renderAdmin();
  selectAdminTab("current", false);
  syncViewFromHash();
})();
