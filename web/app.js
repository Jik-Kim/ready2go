(function () {
  "use strict";

  // 기본 화면 객체는 정적 목업에서 시작하지만 기본 시나리오에서는 상태와 등록 정의를 REST 결과로 교체한다.
  const state = window.ROKEY_DEMO_DATA;

  // status-api.js가 제공하는 polling 구현을 렌더링 코드에서 한 번만 참조한다.
  const statusApi = window.ROKEY_STATUS_API;

  // Runner 요청·결과 형식을 화면 표시 전에 검증하는 순수 파서 모듈이다.
  const runnerStatusModel = window.ROKEY_RUNNER_STATUS_MODEL;

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

  // 5단계 정의 API가 제공한 물품 표시명을 Runner 원본 ID와 연결한다.
  const itemLabels = {};

  // 정의보다 상태 응답이 먼저 도착해도 나중에 등록명을 다시 적용할 수 있게 마지막 source를 보관한다.
  let latestRobotStateSource = null;

  // 요청·결과 표시는 후속 단계에서 연결하며 지금은 검증된 내부 모델만 보관한다.
  let latestRunnerRecords = runnerStatusModel.parseRunnerRecords(null);

  // Runner core의 실제 phase 세 값만 사용자 표시 문구와 기존 화면 색상 키로 변환한다.
  const runnerPhaseViews = {
    idle: { label: "대기", status: "waiting" },
    running: { label: "실행 중", status: "running" },
    halted: { label: "정지(잠김)", status: "stopped" },
  };

  // 출근 준비물 영역은 등록 목록 중 의미가 확정된 commute_set만 사용한다.
  const DASHBOARD_LIST_ID = "commute_set";

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

  function getRobotConnection() {
    // 상단 로봇 배지는 /robot_state 기억값이 아니라 B의 JointState 수신 진단을 표시한다.
    return state.connections.find((connection) => connection.id === "robot");
  }

  function getCameraConnection() {
    // 상단 카메라 배지는 CameraInfo의 최근 수신 여부만 표시한다.
    return state.connections.find((connection) => connection.id === "camera");
  }

  function getVoiceConnection() {
    // 상단 음성 배지는 /voice/intent publisher 존재 여부만 표시한다.
    return state.connections.find((connection) => connection.id === "voice");
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
    // source가 유효하지 않으면 과거 요청·결과 내부 모델도 현재값으로 유지하지 않는다.
    latestRunnerRecords = runnerStatusModel.parseRunnerRecords(null);
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
    // last_intent와 last는 표시·연결 전에 독립적으로 형식을 검사하고 새 객체로 복사한다.
    latestRunnerRecords = runnerStatusModel.parseRunnerRecords(data);
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

  function applyRobotConnectionSource(source, runtimeProfile, robotTopic) {
    // 로봇 관절 상태 source를 상단 배지에 반영하되 모션 가능 상태로 확대 해석하지 않는다.
    const connection = getRobotConnection();
    if (!connection) return;
    const simulation = runtimeProfile === "sim" || runtimeProfile === "dev";
    const receivedAt = formatReceivedTime(source?.last_valid_received_at);
    const disclaimer = "모션 가능·E-stop 해제·그리퍼·스킬 서버 준비를 의미하지 않습니다.";

    if (source?.last_error) {
      Object.assign(connection, {
        status: "error",
        statusLabel: "로봇 상태 확인 오류",
        description: `${source.last_error} · ${disclaimer}`,
      });
      return;
    }
    if (source?.connection_state === "receiving" && source.message_valid === true) {
      Object.assign(connection, {
        status: "ok",
        statusLabel: "관절 상태 수신",
        description: `${robotTopic} 최근 수신 ${receivedAt} · ${disclaimer}`,
      });
      return;
    }
    // sim/dev에서 한 번도 받은 적 없는 미기동만 `확인 전`으로 둔다. 한 번 수신한 뒤
    // 발행이 멈춘 경우에는 아래의 `수신 끊김`으로 내려 실제 단절을 숨기지 않는다.
    if (simulation && source?.publisher_present !== true && source?.message_received !== true) {
      Object.assign(connection, {
        status: "waiting",
        statusLabel: "확인 전(시뮬레이션)",
        description: `${runtimeProfile} 프로필에서 로봇 드라이버를 실행하지 않았습니다.`,
      });
      return;
    }
    if (source?.connection_state === "waiting") {
      Object.assign(connection, {
        status: "pending",
        statusLabel: "관절 상태 수신 대기",
        description: `ROS 발행자는 있으나 유효 JointState를 아직 받지 못했습니다. ${disclaimer}`,
      });
      return;
    }
    Object.assign(connection, {
      status: "disconnected",
      statusLabel: "관절 상태 수신 끊김",
      description: `JointState 발행자 없음 또는 ${source?.freshness_timeout_sec ?? 2}초 무수신 · ${disclaimer}`,
    });
  }

  function applyCameraConnectionSource(source, runtimeProfile) {
    // CameraInfo가 최근 2초 안에 들어왔을 때만 카메라 정보 수신으로 표시한다.
    const connection = getCameraConnection();
    if (!connection) return;
    // sim/dev의 의도된 미기동과 한 번 수신한 뒤 발생한 실제 단절을 구분한다.
    const simulation = runtimeProfile === "sim" || runtimeProfile === "dev";
    const receivedAt = formatReceivedTime(source?.last_valid_received_at);
    if (source?.last_error) {
      Object.assign(connection, {
        status: "error",
        statusLabel: "카메라 상태 확인 오류",
        description: source.last_error,
      });
      return;
    }
    if (source?.connection_state === "receiving" && source.message_valid === true) {
      Object.assign(connection, {
        status: "ok",
        statusLabel: "카메라 정보 수신",
        description: `/wrist_cam/color/camera_info 최근 수신 ${receivedAt}`,
      });
      return;
    }
    // sim/dev에서 한 번도 받은 적 없는 미발행만 장애로 표시하지 않는다. 과거 수신
    // 기록이 있으면 아래의 `수신 끊김`으로 내려 카메라 단절을 숨기지 않는다.
    if (simulation && source?.publisher_present !== true && source?.message_received !== true) {
      Object.assign(connection, {
        status: "waiting",
        statusLabel: "확인 전(시뮬레이션)",
        description: `${runtimeProfile} 프로필에서 카메라 publisher를 실행하지 않았습니다.`,
      });
      return;
    }
    if (source?.connection_state === "unknown") {
      Object.assign(connection, {
        status: "waiting",
        statusLabel: "확인 전",
        description: "카메라 publisher를 아직 확인하지 못했습니다.",
      });
      return;
    }
    if (source?.connection_state === "waiting") {
      Object.assign(connection, {
        status: "pending",
        statusLabel: "카메라 정보 수신 대기",
        description: "publisher는 있으나 CameraInfo를 아직 받지 못했습니다.",
      });
      return;
    }
    Object.assign(connection, {
      status: "disconnected",
      statusLabel: "카메라 정보 수신 끊김",
      description: `publisher 없음 또는 ${source?.freshness_timeout_sec ?? 2}초 무수신`,
    });
  }

  function applyVoiceConnectionSource(source) {
    // Voice는 간헐적 intent 메시지 대신 /voice/intent publisher 존재 여부만 표시한다.
    const connection = getVoiceConnection();
    if (!connection) return;
    const scope = "마이크·STT 처리 성공을 의미하지 않습니다.";
    if (source?.last_error) {
      Object.assign(connection, {
        status: "error",
        statusLabel: "Voice 상태 확인 오류",
        description: `${source.last_error} · ${scope}`,
      });
      return;
    }
    if (source?.publisher_present === true) {
      Object.assign(connection, {
        status: "ok",
        statusLabel: "publisher 확인",
        description: `/voice/intent 발행자 존재 · ${scope}`,
      });
      return;
    }
    if (source?.publisher_present === false) {
      Object.assign(connection, {
        status: "disconnected",
        statusLabel: "publisher 없음",
        description: `/voice/intent 발행자를 찾지 못했습니다. ${scope}`,
      });
      return;
    }
    Object.assign(connection, {
      status: "waiting",
      statusLabel: "확인 전",
      description: "/voice/intent publisher를 아직 확인하지 못했습니다.",
    });
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
    // 등록 정의에 전용 아이콘 정보가 없으므로 기존 화면과 명확히 일치하는 ID만 재사용한다.
    const normalized = itemId.replaceAll("_", "-");
    if (normalized === "car-key") return "key";
    if (["wallet", "watch", "note", "box", "charger"].includes(normalized)) return normalized;
    return "box";
  }

  function itemLabelForId(itemId) {
    // 공통 온톨로지에서 읽은 한국어 이름이 있으면 사용하고 없으면 원본 ID를 보존한다.
    return itemLabels[itemId] || itemId;
  }

  function definitionConditionSummary(value) {
    // 조건·효과 배열은 개수로 표시해 원본 의미를 임의의 자연어 규칙으로 재해석하지 않는다.
    if (Array.isArray(value)) return value.length === 0 ? "없음" : `${value.length}개 정의`;
    // composite 스킬의 sensing 같은 문자열 효과는 원본 값을 그대로 보여준다.
    if (typeof value === "string" && value) return value;
    // null·누락 값은 정의가 없다는 뜻으로만 표시한다.
    return "없음";
  }

  function setDefinitionsUnknown(detail) {
    // 정의 API 수신 전이나 실패 시 목업 정의를 실제 등록값처럼 남겨 두지 않는다.
    state.definitionsLive = false;
    // 고정 목업 시나리오와 실제 정의 확인 실패를 렌더러가 구분할 수 있게 상태를 기록한다.
    state.definitionsStatus = "unknown";
    // 등록 준비물도 목업 목록을 제거해 원본을 확인하지 못한 상태를 분명히 한다.
    state.supplies = [];
    // 준비물 집계가 빈 요청이 아니라 정의 확인 전임을 렌더러에 알린다.
    state.suppliesDefinitionName = "등록 정의 확인 전";
    // 관리자 온톨로지 탭에는 오류 원인과 확인 전 카드만 제공한다.
    state.adminReview.ontology = {
      live: false,
      loadedAt: null,
      sourcePath: null,
      manifestSha: null,
      error: detail || "등록 정의를 아직 읽지 못했습니다.",
      relations: [
        { title: "등록 정의", value: "확인 전", meta: detail || "정의 API 미수신" },
      ],
      skills: [],
    };
  }

  function applyDefinitionSnapshot(snapshot) {
    // status-api.js가 검증한 여섯 정의 구역을 화면 모델로 변환한다.
    const definitions = snapshot.definitions;
    // 물품 ID와 한국어 등록명을 이후 /robot_state 렌더링에서 재사용한다.
    definitions.items.forEach((item) => {
      // ID가 없거나 문자열이 아니면 해당 항목만 표시명 사전에서 제외한다.
      if (!item || typeof item.id !== "string") return;
      // 한국어 이름이 없으면 원본 ID를 그대로 사용하도록 사전에 넣지 않는다.
      if (typeof item.name_ko === "string" && item.name_ko) itemLabels[item.id] = item.name_ko;
    });
    // 장소 등록명도 서랍 및 물품 위치 표시에 같은 방식으로 적용한다.
    definitions.places.forEach((place) => {
      // 장소 ID와 이름이 모두 문자열일 때만 안전하게 표시명 사전을 갱신한다.
      if (place && typeof place.id === "string" && typeof place.name_ko === "string"
        && place.name_ko) drawerLabels[place.id] = place.name_ko;
    });

    // 관리자 카드에서 긴 객체 전체 대신 등록 ID와 표시명을 대조할 수 있게 만든다.
    const itemNames = definitions.items.map((item) => item.name_ko || item.id).join(" · ") || "없음";
    // 장소도 같은 방식으로 실제 등록 순서를 사용한다.
    const placeNames = definitions.places.map((place) => place.name_ko || place.id).join(" · ") || "없음";
    // 태스크는 화면 진행률이 아니라 등록 파일 목록임을 source_file 메타로 구분한다.
    const taskIds = definitions.tasks.map((task) => task.id).join(" · ") || "없음";
    // P3 목록 정의는 목록 이름과 구성 물품 수만 요약한다.
    const listDescriptions = definitions.lists.map((entry) => {
      const label = entry.name_ko || entry.id;
      return `${label}(${entry.item_ids.length}개)`;
    }).join(" · ") || "없음";

    // 실제 manifest 경로와 해시를 관리자 메타데이터에 보존한다.
    const manifest = snapshot.sources?.ontology_manifest || {};
    // 화면 모델을 실제 정의 스냅샷으로 교체한다.
    state.adminReview.ontology = {
      live: true,
      loadedAt: snapshot.loaded_at,
      sourcePath: manifest.path || "확인 전",
      manifestSha: manifest.sha256 || null,
      error: null,
      relations: [
        { title: "등록 물품", value: itemNames, meta: `${definitions.items.length}개 · 웹 파일 스냅샷` },
        { title: "등록 장소", value: placeNames, meta: `${definitions.places.length}개 · 웹 파일 스냅샷` },
        { title: "등록 목록", value: listDescriptions, meta: `${definitions.lists.length}개 · 목록 정의` },
        { title: "등록 태스크", value: taskIds, meta: `${definitions.tasks.length}개 · 실행 상태 아님` },
      ],
      skills: definitions.skills.map((skill) => ({
        title: skill.name_ko ? `${skill.name_ko} (${skill.id})` : skill.id,
        before: definitionConditionSummary(skill.pre),
        after: definitionConditionSummary(skill.effect),
      })),
    };
    // 정의가 정상 적용됐음을 다른 렌더러가 확인할 수 있게 기록한다.
    state.definitionsLive = true;

    // 배열 순서에 기대지 않고 출근 준비물 화면과 의미가 일치하는 목록 ID를 선택한다.
    const registeredList = definitions.lists.find((entry) => entry?.id === DASHBOARD_LIST_ID) || null;
    // commute_set이 없으면 다른 목록을 대신 보여 주지 않고 확인 전 상태를 유지한다.
    const registeredItemIds = registeredList ? registeredList.item_ids : [];
    // 준비물 카드는 전달 상태가 아니라 등록 여부만 표시한다.
    state.supplies = registeredItemIds.map((itemId) => ({
      id: itemId,
      name: itemLabelForId(itemId),
      icon: itemIconForId(itemId),
      status: "pending",
      statusLabel: "등록 정의",
    }));
    // 집계 문구에서 어떤 등록 목록인지 표시한다.
    state.suppliesDefinitionName = registeredList?.name_ko || registeredList?.id || "출근 준비물 정의 확인 전";
    // 정의 API 자체는 정상이며 화면이 사용할 등록 목록 선택까지 마쳤음을 기록한다.
    state.definitionsStatus = "live";

    // 상태가 먼저 수신됐다면 새 등록명을 현재 서랍·물품 화면에 즉시 다시 적용한다.
    if (latestRobotStateSource) applyRobotStateSource(latestRobotStateSource);
    // 호출자는 실제 정의 적용 성공 여부를 사용할 수 있다.
    return true;
  }

  function applyDefinitionsFailure(error) {
    // 네트워크·HTTP·형식 오류 모두 정의를 확인 전으로 전환한다.
    setDefinitionsUnknown(error instanceof Error ? error.message : "정의 API 오류");
    // 상태 REST와 정의 REST의 현재 조합으로 상단 안내를 다시 계산한다.
    refreshDefinitionAwareMetaDescription();
    // 기본 화면의 준비물과 관리자 온톨로지 탭을 즉시 다시 그린다.
    renderMockNotice();
    renderSupplies();
    renderAdminOntology();
    renderAdminDataMeta();
  }

  function applyDefinitionsSuccess(snapshot) {
    // 검증된 스냅샷을 화면 모델에 적용한다.
    applyDefinitionSnapshot(snapshot);
    // 상태 요청보다 늦게 성공해도 현재 조합에 맞는 상단 안내로 다시 계산한다.
    refreshDefinitionAwareMetaDescription();
    // 등록 준비물·현재 위치 표시·관리자 정의 탭을 새 정의명으로 다시 그린다.
    renderMockNotice();
    renderSupplies();
    renderDrawerSelectors();
    renderInventory();
    renderAdminOntology();
    renderAdminDataMeta();
  }

  function refreshDefinitionAwareMetaDescription() {
    // 상태 REST 오류 중에도 이미 읽은 정의 스냅샷의 성공 여부는 독립적으로 알린다.
    if (state.meta.mode === "rest-error") {
      state.meta.description = state.definitionsLive
        ? "Runner 현재 상태를 조회할 수 없습니다. 등록 정의 파일 스냅샷만 표시합니다."
        : "Runner 현재 상태와 등록 정의가 확인 전입니다.";
      return;
    }
    // 상태 REST 성공 시에는 /robot_state 적용 여부와 정의 스냅샷 여부를 함께 설명한다.
    if (state.meta.mode === "partial-live") {
      if (!state.definitionsLive) {
        state.meta.description = "Runner 상태는 실제 데이터이며 등록 정의는 확인 전입니다. 작업 진행은 목업입니다.";
        return;
      }
      state.meta.description = state.robotStateLive
        ? "Runner 연결과 기억 상태는 실제 데이터이며 등록 정의는 웹 파일 스냅샷입니다. 작업 진행은 목업입니다."
        : "Runner 연결은 실제 데이터이고 등록 정의는 웹 파일 스냅샷이며 /robot_state는 확인 전입니다. 작업 진행은 목업입니다.";
      return;
    }
    // 상태 응답 전에도 정의만 먼저 도착했다면 현재 사용할 수 있는 범위를 정확히 표시한다.
    state.meta.description = state.definitionsLive
      ? "등록 정의는 웹 파일 스냅샷이며 Runner 현재 상태는 확인 전입니다. 작업 진행은 목업입니다."
      : "Runner 현재 상태와 등록 정의가 확인 전입니다.";
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
    // 정의가 준비됐으면 등록명을 사용하고, 없으면 추정하지 않고 원본 ID를 유지한다.
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
          name: itemLabelForId(itemId),
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
      ? Object.entries(data.located_in).map(([id, value]) => `${itemLabelForId(id)} → ${drawerLabels[value] || value}`).join(" · ")
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
    // validatePayload를 통과한 상태와 장치 연결 source를 각 화면 영역에 사용한다.
    const source = payload.sources.runner;
    const robotStateSource = payload.sources.robot_state;
    const robotConnectionSource = payload.sources.robot;
    const cameraConnectionSource = payload.sources.camera;
    const voiceConnectionSource = payload.sources.voice;
    // 정의 API가 나중에 도착해도 등록명을 다시 적용할 수 있도록 최신 source를 보관한다.
    latestRobotStateSource = robotStateSource;
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
    // B의 관절 상태는 Runner 기억 상태와 별도 연결 진단으로 상단 로봇 배지에만 반영한다.
    applyRobotConnectionSource(robotConnectionSource, payload.runtime_profile, payload.robot_topic);
    // 카메라 최근 수신과 Voice publisher 존재를 각각의 상단 장치 배지에 반영한다.
    applyCameraConnectionSource(cameraConnectionSource, payload.runtime_profile);
    applyVoiceConnectionSource(voiceConnectionSource);
    // 정의 연결 여부를 상태 연결과 구분해 현재 화면에 실제인 범위를 정확히 설명한다.
    const definitionText = state.definitionsLive
      ? "등록 정의는 웹 시작 시 읽은 파일 스냅샷입니다."
      : "등록 정의는 확인 전입니다.";
    // 현재 상태와 정의의 출처를 합치지 않고 각각의 범위를 문장으로 알린다.
    state.meta.description = robotStateApplied
      ? `Runner 연결과 기억 상태는 실제 데이터입니다. ${definitionText} 작업 진행은 목업입니다.`
      : `Runner 연결은 실제 데이터이며 /robot_state 표시는 확인 전입니다. ${definitionText} 작업 진행은 목업입니다.`;

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
    // REST 단절 뒤 이전 JointState 수신값이 계속 정상처럼 보이지 않도록 로봇 배지도 전환한다.
    const robotConnection = getRobotConnection();
    if (robotConnection) {
      Object.assign(robotConnection, {
        status: "error",
        statusLabel: "REST 연결 오류",
        description: `현재 로봇 관절 상태를 사용할 수 없습니다. REST 마지막 성공 ${lastSuccess}`,
      });
    }
    // 같은 REST 응답을 사용하는 카메라·Voice도 이전 정상 배지를 즉시 무효화한다.
    for (const deviceConnection of [getCameraConnection(), getVoiceConnection()]) {
      if (!deviceConnection) continue;
      Object.assign(deviceConnection, {
        status: "error",
        statusLabel: "REST 연결 오류",
        description: `현재 장치 상태를 사용할 수 없습니다. REST 마지막 성공 ${lastSuccess}`,
      });
    }
    state.meta.mode = "rest-error";
    state.meta.label = "REST 연결 오류 · 상태 확인 전";
    // 상태 REST 실패가 이미 읽은 정의 파일 스냅샷까지 무효화한 것처럼 표현하지 않는다.
    state.meta.description = state.definitionsLive
      ? "Runner 현재 상태를 조회할 수 없습니다. 등록 정의 파일 스냅샷만 표시합니다."
      : "Runner 현재 상태와 등록 정의를 확인할 수 없습니다.";

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
    // 실제 정의를 확인하지 못한 기본 화면은 빈 요청이나 전달 완료 결과로 단정하지 않는다.
    getById("completionCount").textContent = state.definitionsStatus === "unknown"
      ? "등록 정의 확인 전"
      // 정상 정의는 실행 결과가 아니라 등록된 목록의 개수와 이름만 표시한다.
      : state.definitionsLive
        ? `${state.supplies.length}개 등록 · ${state.suppliesDefinitionName}`
        // 고정 URL 목업 시나리오는 기존 전달 완료 예시를 그대로 유지한다.
        : `${completed} / ${state.supplies.length} 전달 완료`;
    // 빈 목록 안내도 정의 실패·정상 빈 정의·고정 목업을 서로 다른 문구로 구분한다.
    getById("suppliesEmpty").textContent = state.definitionsStatus === "unknown"
      ? "등록 정의를 확인하지 못했습니다."
      : state.definitionsLive
        ? "등록된 출근 준비물이 없습니다."
        : "요청된 준비물이 없습니다.";
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
    // 현재 상태와 등록 정의의 연결 여부를 각각 표시하고 후속 탭은 그대로 유지한다.
    const current = state.adminReview.current;
    const connected = current.liveConnected === true;
    // 온톨로지 탭은 Runner 상태와 독립적인 웹 파일 스냅샷 연결 상태를 사용한다.
    const definitionsConnected = state.adminReview.ontology?.live === true;
    const restError = state.meta.mode === "rest-error";
    getById("adminDataNotice").textContent = connected
      ? definitionsConnected
        ? "부분 실데이터 · 현재 상태는 Runner에서 수신하고 등록 정의는 웹 시작 시 파일에서 읽었습니다. 계획 근거·실행 기록은 후속 연결입니다."
        : "부분 실데이터 · 현재 상태는 Runner에서 수신하며 등록 정의는 확인 전입니다. 계획 근거·실행 기록은 후속 연결입니다."
      : restError
        ? definitionsConnected
          ? "상태 REST 연결 오류 · 현재 상태는 확인 전이며 등록 정의 파일 스냅샷만 사용할 수 있습니다."
          : "REST 연결 오류 · 현재 상태와 등록 정의가 확인 전입니다."
        : state.meta.mode === "partial-live"
          ? "부분 실데이터 · 인증 미구현 읽기 전용 화면 · Runner 응답은 수신했지만 현재 상태 일부는 확인 전입니다."
          : definitionsConnected
            ? "등록 정의 연결됨 · 현재 Runner 상태는 확인 전이며 등록 정의는 웹 파일 스냅샷입니다."
            : "확인 전 · 현재 상태와 등록 정의를 아직 조회하지 못했습니다.";
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

    // 탭 머리말은 정의 스냅샷 성공 여부를 상태 REST와 독립적으로 표시한다.
    getById("adminOntologySourceLabel").textContent = ontology.live
      ? "공통 ontology.load · 웹 파일 스냅샷"
      : "등록 정의 확인 전";
    // 목업 배지 대신 실제 정의 또는 확인 전 상태를 표시한다.
    getById("adminOntologyDataLabel").textContent = ontology.live ? "등록 정의" : "확인 전";
    // 경로·로딩 시각·manifest 해시 앞 12자를 한 줄로 제공해 배포 원본을 대조할 수 있게 한다.
    getById("adminOntologyMeta").textContent = ontology.live
      ? `원본 ${ontology.sourcePath} · 웹 로딩 ${formatReceivedTime(ontology.loadedAt)} · SHA-256 ${ontology.manifestSha?.slice(0, 12) || "확인 전"}`
      : ontology.error || "등록 정의를 읽지 못했습니다.";

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
    // 정의 API 응답 전에는 demo-data.js의 샘플 정의와 준비물을 실제 등록값처럼 보이지 않게 한다.
    setDefinitionsUnknown("/api/definitions 수신 전");
  }

  renderAll();
  renderAdmin();
  selectAdminTab("current", false);
  syncViewFromHash();

  // long·empty·error URL은 고정 목업 검토용으로 유지하고 기본 화면에서만 REST를 연결한다.
  if (statusApi && window.ROKEY_DEMO_SCENARIO === "default") {
    // 등록 정의는 서버 기동 시 고정된 스냅샷이므로 상태 polling과 달리 페이지에서 한 번만 요청한다.
    void statusApi.loadDefinitions(window.fetch.bind(window))
      // 정상 스냅샷은 물품·장소 이름, 등록 목록, 태스크와 스킬 카드에 적용한다.
      .then(applyDefinitionsSuccess)
      // 정의만 실패해도 상태 polling은 계속 유지하고 정의 영역만 확인 전으로 둔다.
      .catch(applyDefinitionsFailure);
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
