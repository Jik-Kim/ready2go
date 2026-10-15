(function () {
  "use strict";

  // Flask와 같은 origin에서 제공하는 읽기 전용 상태 API다.
  const STATUS_API_PATH = "/api/status";

  // 등록 정의는 상태 polling과 분리해 페이지 시작 때 한 번만 읽는다.
  const DEFINITIONS_API_PATH = "/api/definitions";

  // 서버 응답이 간격을 제공하지 못한 오류 상황에도 약 1초 조회를 유지한다.
  const DEFAULT_POLL_INTERVAL_MS = 1000;

  // API가 제공할 수 있는 지나치게 짧거나 긴 값으로 브라우저가 폭주·정지하지 않게 제한한다.
  const MIN_POLL_INTERVAL_MS = 250;
  const MAX_POLL_INTERVAL_MS = 10000;

  function validateVisionOverlay(value) {
    // 사진 메타데이터는 장치 연결 source와 별도 계약이므로 독립 객체로 검사한다.
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("촬영 사진 상태가 응답에 없습니다.");
    }
    if (!["ok", "unavailable", "error"].includes(value.status)) {
      throw new Error("촬영 사진 상태를 확인할 수 없습니다.");
    }
    // 캐시가 없거나 메타데이터 생성이 실패한 응답은 app.js가 `확인 전`으로 표시한다.
    if (value.status !== "ok") return value;
    if (typeof value.image_available !== "boolean"
      || typeof value.stale !== "boolean") {
      throw new Error("촬영 사진 메타데이터 형식이 다릅니다.");
    }
    // 사진이 있을 때만 revision과 UTC 촬영 시각을 실제 JPEG 조회 근거로 사용한다.
    if (value.image_available
      && (!Number.isInteger(value.revision) || value.revision < 1
        || typeof value.captured_at !== "string")) {
      throw new Error("촬영 사진 revision 또는 촬영 시각이 올바르지 않습니다.");
    }
    if (value.capture_age_sec !== null
      && (typeof value.capture_age_sec !== "number" || value.capture_age_sec < 0)) {
      throw new Error("촬영 사진 경과 시간이 올바르지 않습니다.");
    }
    return value;
  }

  function validatePayload(payload) {
    // REST 성공 응답이 3단계 최소 형식을 만족하는지 검사한다.
    // null·배열은 JavaScript에서 object이므로 각각 명시적으로 제외한다.
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("상태 API 응답이 JSON 객체가 아닙니다.");
    }
    // 다른 형식 버전을 조용히 오해하지 않고 REST 오류 상태로 전환한다.
    if (payload.schema_version !== 1) {
      throw new Error("지원하지 않는 상태 API 버전입니다.");
    }
    // 4단계의 두 실데이터 source가 모두 객체인지 확인한다. 세부 robot_state
    // 필드 검사는 화면 어댑터가 담당해 누락·형식 불일치를 `확인 전`으로 표시한다.
    if (!payload.sources || typeof payload.sources.runner !== "object" || payload.sources.runner === null) {
      throw new Error("Runner 상태가 응답에 없습니다.");
    }
    if (typeof payload.sources.robot_state !== "object" || payload.sources.robot_state === null) {
      throw new Error("로봇 기억 상태가 응답에 없습니다.");
    }
    // B가 확정한 JointState source가 없으면 로봇 배지를 목업으로 남기지 않고 오류로 처리한다.
    if (typeof payload.sources.robot !== "object" || payload.sources.robot === null) {
      throw new Error("로봇 관절 상태가 응답에 없습니다.");
    }
    // 활성화한 카메라와 Voice source도 없으면 목업 배지를 그대로 두지 않고 오류로 처리한다.
    if (typeof payload.sources.camera !== "object" || payload.sources.camera === null) {
      throw new Error("카메라 상태가 응답에 없습니다.");
    }
    if (typeof payload.sources.voice !== "object" || payload.sources.voice === null) {
      throw new Error("Voice 상태가 응답에 없습니다.");
    }
    // JPEG 바이트는 별도 API에서 받고 상태 polling에서는 메타데이터만 검증한다.
    validateVisionOverlay(payload.vision_overlay);
    // 실행 프로필은 실물 단절과 sim/dev의 의도된 미기동을 구분하는 근거다.
    if (!["real", "sim", "dev"].includes(payload.runtime_profile)) {
      throw new Error("웹 실행 프로필을 확인할 수 없습니다.");
    }
    // UI 설명은 기본값을 하드코딩하지 않고 서버가 실제 구독한 절대 토픽명을 사용한다.
    if (typeof payload.robot_topic !== "string" || !payload.robot_topic.startsWith("/")) {
      throw new Error("로봇 관절 상태 토픽을 확인할 수 없습니다.");
    }
    return payload;
  }

  function normalizedPollInterval(value) {
    // 서버 권장 간격을 브라우저가 안전하게 사용할 정수 범위로 정규화한다.
    // 숫자가 아니거나 범위를 벗어나면 이슈 #267의 1초 기본값을 사용한다.
    if (!Number.isInteger(value) || value < MIN_POLL_INTERVAL_MS || value > MAX_POLL_INTERVAL_MS) {
      return DEFAULT_POLL_INTERVAL_MS;
    }
    return value;
  }

  function validateDefinitionsPayload(payload) {
    // 정의 응답도 null·배열이 아닌 JSON 객체여야 한다.
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new Error("정의 API 응답이 JSON 객체가 아닙니다.");
    }
    // HTTP 200이어도 명시적인 성공 상태가 아니면 등록 정의로 사용하지 않는다.
    if (payload.status !== "ok") {
      throw new Error("정의 API가 정상 상태가 아닙니다.");
    }
    // 상태 API와 독립된 정의 형식 버전 1만 현재 화면이 이해한다.
    const snapshot = payload.snapshot;
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)
      || snapshot.schema_version !== 1) {
      throw new Error("지원하지 않는 정의 API 버전입니다.");
    }
    // 웹 파일 스냅샷만 받아 Runner 실행 중 hot reload로 오해할 여지를 막는다.
    if (snapshot.snapshot_kind !== "web_file_snapshot"
      || snapshot.runner_hot_reload_applied !== false) {
      throw new Error("정의 스냅샷 경계를 확인할 수 없습니다.");
    }
    // 화면이 사용하는 여섯 정의 구역이 모두 배열인지 먼저 확인한다.
    const definitions = snapshot.definitions;
    const sections = ["classes", "items", "places", "lists", "skills", "tasks"];
    if (!definitions || typeof definitions !== "object" || Array.isArray(definitions)
      || !sections.every((name) => Array.isArray(definitions[name]))) {
      throw new Error("등록 정의 구역이 없거나 형식이 다릅니다.");
    }
    // 검증된 서버 시작 시점 스냅샷만 app.js에 전달한다.
    return snapshot;
  }

  async function loadDefinitions(fetchDefinitions) {
    // 브라우저 캐시를 사용하지 않고 현재 Flask 기동이 읽은 정의를 요청한다.
    const response = await fetchDefinitions(DEFINITIONS_API_PATH, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    // 설정·파일 오류의 503을 빈 정의로 처리하지 않고 호출자에게 전달한다.
    if (!response.ok) throw new Error(`정의 API HTTP ${response.status}`);
    // JSON 해석과 정의 전용 형식 검증을 한 뒤 스냅샷만 반환한다.
    return validateDefinitionsPayload(await response.json());
  }

  function createPoller(options) {
    // 응답 완료 뒤 다음 조회를 예약해 중첩 요청 없이 상태를 반복 수신한다.
    // 시험과 브라우저 실행이 fetch·시계·timer를 각각 주입할 수 있게 의존성을 받는다.
    const fetchStatus = options.fetchStatus;
    const onSuccess = options.onSuccess;
    const onFailure = options.onFailure;
    const now = options.now || (() => new Date());
    const schedule = options.schedule || window.setTimeout.bind(window);
    const cancelSchedule = options.cancelSchedule || window.clearTimeout.bind(window);

    let stopped = false;
    let started = false;
    let timerId = null;
    let lastSuccessAt = null;

    async function pollOnce() {
      // 한 번 조회하고 성공·실패 표시 후 다음 호출을 예약한다.
      let nextDelay = DEFAULT_POLL_INTERVAL_MS;
      try {
        // HTTP 캐시를 사용하지 않고 서버의 현재 StateCache 스냅샷을 요청한다.
        const response = await fetchStatus(STATUS_API_PATH, {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });
        // 4xx·5xx 응답을 JSON 정상 상태처럼 처리하지 않는다.
        if (!response.ok) throw new Error(`상태 API HTTP ${response.status}`);

        const payload = validatePayload(await response.json());
        lastSuccessAt = now().toISOString();
        nextDelay = normalizedPollInterval(payload.poll_interval_ms);
        onSuccess(payload, lastSuccessAt);
      } catch (error) {
        // 마지막 성공 시각은 보존하되 오류 뒤 이전 상태를 정상으로 표시하지 않게 알린다.
        onFailure(error, lastSuccessAt);
      } finally {
        // setInterval 대신 완료 후 예약해 느린 요청이 서로 겹치지 않게 한다.
        if (!stopped) timerId = schedule(pollOnce, nextDelay);
      }
    }

    return {
      start() {
        // 페이지 준비 직후 첫 REST 조회를 시작한다.
        if (stopped || started) return;
        started = true;
        // 첫 화면에서 1초를 기다리지 않고 연결 상태를 바로 확인한다.
        void pollOnce();
      },
      stop() {
        // 페이지 종료 시 예약된 다음 조회를 취소한다.
        stopped = true;
        if (timerId !== null) cancelSchedule(timerId);
        timerId = null;
      },
    };
  }

  // app.js는 이 한 객체만 사용하므로 REST 세부 구현을 렌더링 코드와 분리한다.
  window.ROKEY_STATUS_API = {
    createPoller,
    loadDefinitions,
  };
})();
