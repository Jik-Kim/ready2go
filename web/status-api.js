(function () {
  "use strict";

  // Flask와 같은 origin에서 제공하는 읽기 전용 상태 API다.
  const STATUS_API_PATH = "/api/status";

  // 서버 응답이 간격을 제공하지 못한 오류 상황에도 약 1초 조회를 유지한다.
  const DEFAULT_POLL_INTERVAL_MS = 1000;

  // API가 제공할 수 있는 지나치게 짧거나 긴 값으로 브라우저가 폭주·정지하지 않게 제한한다.
  const MIN_POLL_INTERVAL_MS = 250;
  const MAX_POLL_INTERVAL_MS = 10000;

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
    // 이번 단계의 유일한 실데이터 source인 runner가 반드시 객체여야 한다.
    if (!payload.sources || typeof payload.sources.runner !== "object" || payload.sources.runner === null) {
      throw new Error("Runner 상태가 응답에 없습니다.");
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
  };
})();
