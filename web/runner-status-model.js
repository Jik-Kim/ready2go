(function () {
  "use strict";

  // 파싱 결과는 정상 객체, 아직 없는 값, 계약과 다른 값의 세 상태로 구분한다.
  const VALID = "valid";
  const ABSENT = "absent";
  const INVALID = "invalid";
  // 요청과 결과의 연결 판정은 파싱 상태와 구분해 연결됨·분리됨으로 표현한다.
  const LINKED = "linked";
  const UNLINKED = "unlinked";
  // Runner 실행 결과와 재개 대기에서 실제로 사용하는 최상위 결과 상태만 허용한다.
  const OVERALL_STATUSES = Object.freeze([
    "COMPLETED",
    "FAILED",
    "ABORTED",
    "SUSPENDED",
  ]);

  function isRecord(value) {
    // JavaScript에서 배열과 null도 object로 분류되므로 Runner JSON 객체에서 제외한다.
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function hasOwn(record, key) {
    // prototype에서 상속된 이름을 Runner가 보낸 필드로 잘못 인정하지 않는다.
    return Object.prototype.hasOwnProperty.call(record, key);
  }

  function isNullableString(value) {
    // Runner의 선택 필드는 null 또는 비어 있지 않은 문자열만 허용한다.
    return value === null || (typeof value === "string" && value.trim().length > 0);
  }

  function isNullableStringArray(value) {
    // targets는 해석 실패 때 null일 수 있고 정상 해석에서는 문자열 배열이어야 한다.
    return value === null || (Array.isArray(value)
      && value.every((entry) => typeof entry === "string" && entry.trim().length > 0));
  }

  function invalidResult(fields) {
    // 화면 계층은 원본 일부를 재사용하지 않고 invalidFields를 진단 근거로만 사용한다.
    return Object.freeze({ status: INVALID, value: null, invalidFields: Object.freeze(fields) });
  }

  function absentResult() {
    // null은 아직 처리한 요청 또는 완료한 실행이 없는 정상 상태다.
    return Object.freeze({ status: ABSENT, value: null, invalidFields: Object.freeze([]) });
  }

  function validResult(value) {
    // 새 객체만 공개해 이후 화면 가공이 REST 원본 객체를 변경하지 않게 한다.
    return Object.freeze({ status: VALID, value: Object.freeze(value), invalidFields: Object.freeze([]) });
  }

  function connectionResult(status, reason, value = null) {
    // 화면은 연결 여부와 분리 이유를 사용하고 원본 레코드를 다시 비교하지 않는다.
    return Object.freeze({
      status,
      reason,
      value: value === null ? null : Object.freeze(value),
    });
  }

  function parseLastIntent(value) {
    // Runner는 처리한 인텐트가 아직 없을 때 last_intent를 null로 보낸다.
    if (value === null) return absentResult();
    // 키 누락과 잘못된 자료형을 실제 요청 정보로 부분 사용하지 않는다.
    if (!isRecord(value)) return invalidResult(["last_intent"]);

    // 현재 Runner summary가 항상 제공하는 필드만 이번 내부 모델의 입력으로 삼는다.
    const requiredFields = [
      "intent", "targets", "decision", "reason", "task_id", "request_id", "run_id",
    ];
    // 필드가 빠진 객체는 계약을 충족하지 않으므로 누락 이름을 모두 남긴다.
    const invalidFields = requiredFields.filter((field) => !hasOwn(value, field));

    // intent는 BAD_INTENT 같은 해석 실패에서 null일 수 있다.
    if (hasOwn(value, "intent") && !isNullableString(value.intent)) invalidFields.push("intent");
    // targets의 항목까지 검사해 객체·숫자를 물품 ID처럼 사용하지 않는다.
    if (hasOwn(value, "targets") && !isNullableStringArray(value.targets)) invalidFields.push("targets");
    // last_intent 객체가 존재하면 어떤 결정을 내렸는지는 비어 있지 않은 문자열이어야 한다.
    if (hasOwn(value, "decision")
      && !(typeof value.decision === "string" && value.decision.trim().length > 0)) {
      invalidFields.push("decision");
    }
    // 나머지 선택 필드는 null 또는 비어 있지 않은 문자열만 허용한다.
    ["reason", "task_id", "request_id", "run_id"].forEach((field) => {
      if (hasOwn(value, field) && !isNullableString(value[field])) invalidFields.push(field);
    });

    // 하나라도 잘못되면 정상 필드만 골라 사용하는 대신 전체 요청을 확인 전으로 둔다.
    if (invalidFields.length > 0) return invalidResult([...new Set(invalidFields)]);

    return validResult({
      // 화면 코드의 camelCase 규칙으로 복사하되 Runner 원본 이름은 변경하지 않는다.
      intent: value.intent,
      // 배열은 새 배열로 복사해 내부 모델 변경이 REST 원본 targets에 전달되지 않게 한다.
      targets: value.targets === null ? null : Object.freeze([...value.targets]),
      decision: value.decision,
      reason: value.reason,
      taskId: value.task_id,
      requestId: value.request_id,
      runId: value.run_id,
    });
  }

  function parseLastResult(value) {
    // 완료된 실행이 아직 없으면 Runner는 last를 null로 보낸다.
    if (value === null) return absentResult();
    // 배열·문자열 같은 값은 실행 결과의 일부로 해석하지 않는다.
    if (!isRecord(value)) return invalidResult(["last"]);

    // 결과 연결과 실패 설명에 필요한 현재 Runner 필드만 검사한다.
    const requiredFields = ["task_id", "run_id", "overall_status", "error_code", "failed_step"];
    // 현재 계약에 필요한 필드가 빠지면 누락된 이름을 진단에 보존한다.
    const invalidFields = requiredFields.filter((field) => !hasOwn(value, field));

    // 완료 결과에는 연결 기준인 run_id가 비어 있지 않은 문자열로 있어야 한다.
    if (hasOwn(value, "run_id")
      && !(typeof value.run_id === "string" && value.run_id.trim().length > 0)) {
      invalidFields.push("run_id");
    }
    // 임의 문자열을 완료 상태로 표시하지 않고 Runner가 정의한 결과 enum만 인정한다.
    if (hasOwn(value, "overall_status") && !OVERALL_STATUSES.includes(value.overall_status)) {
      invalidFields.push("overall_status");
    }
    // task와 실패 정보는 실행 종류·성공 여부에 따라 null일 수 있다.
    ["task_id", "error_code", "failed_step"].forEach((field) => {
      if (hasOwn(value, field) && !isNullableString(value[field])) invalidFields.push(field);
    });

    // 부분적으로 정상인 결과를 현재 실행 결과처럼 표시하지 않는다.
    if (invalidFields.length > 0) return invalidResult([...new Set(invalidFields)]);

    return validResult({
      taskId: value.task_id,
      runId: value.run_id,
      overallStatus: value.overall_status,
      errorCode: value.error_code,
      failedStep: value.failed_step,
    });
  }

  function linkRunnerRecords(lastIntent, lastResult) {
    // 형식 오류가 있는 요청·결과는 일부 정상 필드나 같은 문자열 ID가 있어도 연결하지 않는다.
    if (lastIntent.status === INVALID || lastResult.status === INVALID) {
      return connectionResult(INVALID, "invalid_record");
    }

    // 요청과 결과가 모두 null이면 아직 연결할 기록이 없는 정상 초기 상태다.
    if (lastIntent.status === ABSENT && lastResult.status === ABSENT) {
      return connectionResult(ABSENT, "records_absent");
    }

    // 결과만 남아 있는 경우 어느 요청의 결과인지 현재 last_intent만으로 추정하지 않는다.
    if (lastIntent.status === ABSENT) {
      return connectionResult(UNLINKED, "last_intent_absent");
    }

    // run 이외의 결정은 실행을 수락하지 않았으므로 과거 last와 ID를 비교하지 않는다.
    if (lastIntent.value.decision !== "run") {
      return connectionResult(UNLINKED, "non_run_decision");
    }

    // 수락 결정에 run_id가 없으면 결과가 있어도 동일 실행임을 확인할 수 없다.
    if (lastIntent.value.runId === null) {
      return connectionResult(UNLINKED, "run_id_missing");
    }

    // 실행 중처럼 아직 최종 결과가 없으면 요청만 유지하고 연결 완료로 표시하지 않는다.
    if (lastResult.status === ABSENT) {
      return connectionResult(UNLINKED, "last_result_absent");
    }

    // 서로 다른 실행 ID는 마지막 요청과 과거 또는 다른 실행 결과로 분리한다.
    if (lastIntent.value.runId !== lastResult.value.runId) {
      return connectionResult(UNLINKED, "run_id_mismatch");
    }

    // 파서가 선택 필드로 허용한 null task_id는 동일 태스크라는 근거가 될 수 없다.
    if (lastIntent.value.taskId === null || lastResult.value.taskId === null) {
      return connectionResult(UNLINKED, "task_id_missing");
    }

    // 같은 실행 ID라도 태스크가 다르면 모순된 요청·결과이므로 현재 요청의 결과로 쓰지 않는다.
    if (lastIntent.value.taskId !== lastResult.value.taskId) {
      return connectionResult(UNLINKED, "task_id_mismatch");
    }

    // decision=run이고 실행 ID와 태스크 ID가 모두 같을 때만 하나의 요청·결과로 묶는다.
    return connectionResult(LINKED, null, {
      runId: lastIntent.value.runId,
      request: lastIntent.value,
      result: lastResult.value,
    });
  }

  function parseRunnerRecords(data) {
    // source.data 자체가 없거나 객체가 아니면 두 하위 기록 모두 확인 전이다.
    if (!isRecord(data)) {
      // 같은 invalid 객체를 연결 판정에도 전달해 초기화 경로의 결과 모양을 일정하게 유지한다.
      const lastIntent = invalidResult(["runner"]);
      const lastResult = invalidResult(["runner"]);
      return Object.freeze({
        status: INVALID,
        lastIntent,
        lastResult,
        connection: linkRunnerRecords(lastIntent, lastResult),
      });
    }

    // 요청과 결과는 독립적으로 파싱해 한쪽 오류가 다른 쪽 원본을 오염시키지 않게 한다.
    const lastIntent = parseLastIntent(data.last_intent);
    const lastResult = parseLastResult(data.last);
    // 파싱된 내부 모델만 연결 함수에 전달해 REST 원본을 직접 비교하지 않는다.
    const connection = linkRunnerRecords(lastIntent, lastResult);
    // 둘 중 하나라도 형식 오류이면 상위 모델도 확인이 필요한 상태로 표시한다.
    const status = lastIntent.status === INVALID || lastResult.status === INVALID ? INVALID : VALID;
    return Object.freeze({ status, lastIntent, lastResult, connection });
  }

  function createStatusGuard() {
    // boot 간 seq는 비교하지 않는다. 떠난 기동은 기억해 늦게 온 응답의 역전도 막는다.
    let bootId = null;
    let seq = -1;
    let fingerprint = null;
    const retiredBoots = new Set();
    return {
      accept(data) {
        // 기동·순서를 검증할 수 없는 메시지는 과거 정상값으로 대체하지 않는다.
        if (!data || typeof data.boot_id !== "string" || !data.boot_id.trim()
          || !Number.isSafeInteger(data.seq) || data.seq < 0) return { status: "invalid" };
        if (retiredBoots.has(data.boot_id)
          || (bootId === data.boot_id && data.seq < seq)) return { status: "stale" };
        const nextFingerprint = JSON.stringify(data);
        // 변경 때만 seq가 증가하므로 같은 seq에 다른 내용은 계약 불일치다.
        if (bootId === data.boot_id && data.seq === seq && fingerprint !== nextFingerprint) {
          return { status: "invalid" };
        }
        const restarted = bootId !== null && bootId !== data.boot_id;
        if (restarted) retiredBoots.add(bootId);
        bootId = data.boot_id;
        seq = data.seq;
        fingerprint = nextFingerprint;
        return { status: "valid", restarted, bootId, seq };
      },
    };
  }

  function currentTaskView(data, taskDefinitions = []) {
    // 현재 물품·run·장소는 최신 요청에서 가져오지 않는다. 상태 토픽이 보장하는 필드만 사용한다.
    const unknown = { title: "현재 작업 확인 전", steps: [] };
    if (!data || !["idle", "running", "halted"].includes(data.phase)) return unknown;
    if (data.phase === "idle") return { title: "현재 실행 없음 · 대기", steps: [] };
    if (data.phase === "halted") return { title: "Runner 정지(잠김) · 현재 단계 확인 전", steps: [] };
    const task = typeof data.task_id === "string" && data.task_id.trim() ? data.task_id : null;
    const step = typeof data.current_step === "string" && data.current_step.trim() ? data.current_step : null;
    // 현재 task와 정확히 연결되는 파일 정의만 사용한다. group/동적 계획의 child는 추정하지 않는다.
    const definition = taskDefinitions.find(entry => entry?.id === task);
    const name = step && definition?.step_labels?.[step];
    const display = typeof name === "string" && name.trim() ? name : null;
    return {
      title: `실행 중 · 태스크: ${task || "확인 전"} · 단계: ${display || "단계명 확인 전"}`,
      // 현재 단계 하나만 표시한다. 앞 단계 성공·단계 자체 완료는 추론하지 않는다.
      steps: step ? [{ id: step, label: display || "작업 진행 중 · 단계명 확인 전", status: "current",
        reason: display ? `등록 태스크 정의 기준 · 단계 ID: ${step}` : `단계 정의 미확인 · 단계 ID: ${step}`,
        statusLabel: "현재 진행 중" }] : [],
    };
  }

  // 검증된 최신 요청과 연결된 결과만 PC·모바일 공통 명령 표시로 변환한다.
  function commandView(records, itemLabel = (id) => id) {
    const view = {
      understood: "확인 전",
      interpretation: { status: "waiting", label: "해석 정보 확인 전" },
      receipt: { status: "waiting", label: "접수 상태 확인 전" },
      processing: { status: "waiting", label: "처리 결과 확인 전" },
      confirmation: null,
    };
    if (records.lastIntent.status !== VALID) return view;
    const request = records.lastIntent.value;
    const targets = request.targets?.map(itemLabel).join(" · ");
    view.understood = `${request.intent ? `인텐트: ${request.intent}` : "인텐트 확인 전"} · ${targets || "대상 정보 없음"}`;
    view.interpretation = request.intent === null
      ? view.interpretation : { status: "confirmed", label: "Runner 해석 정보 수신" };
    // 미지의 결정은 수락으로 추정하지 않는다. 사유는 원본 코드를 보존한다.
    const decisions = {
      run: ["accepted", "수락"], hold: ["pending", "보류"], reject: ["error", "거절"],
      status: ["pending", "상태 조회 처리"], cancel: ["pending", "취소 요청 처리"],
      recover: ["pending", "복구 요청 처리"], resume: ["pending", "재개 요청 처리"],
      end: ["pending", "작업 종료 처리"],
      registered: ["pending", "재개 질문·요청 등록"], closed: ["pending", "재개 대기 종료"],
    };
    const decision = decisions[request.decision];
    view.receipt = {
      status: decision?.[0] || "waiting",
      label: `${decision?.[1] || "접수 상태 확인 전"}${request.reason ? ` · 사유 코드: ${request.reason}` : ""}`,
    };
    if (["hold", "reject"].includes(request.decision)) {
      view.processing = { status: "waiting", label: "이 요청의 실행은 수락되지 않음" };
    } else if (request.decision === "run") {
      view.processing.label = "수락된 요청의 실행 결과 확인 전";
    }
    // phase/current_step 또는 accepted를 최신 요청의 결과로 대신 사용하지 않는다.
    if (records.connection.status === LINKED) {
      const result = records.connection.value.result;
      const results = {
        COMPLETED: ["complete", "실행 완료"], FAILED: ["error", "실행 실패"],
        ABORTED: ["stopped", "실행 중단"], SUSPENDED: ["stopped", "실행 일시 중단"],
      };
      const [status, label] = results[result.overallStatus];
      const detail = [result.errorCode, result.failedStep].filter(Boolean).join(" · ");
      view.processing = { status, label: `${label}${detail ? ` · ${detail}` : ""}` };
    }
    return view;
  }

  // app.js와 브라우저 단위시험이 같은 공개 함수만 사용한다.
  window.ROKEY_RUNNER_STATUS_MODEL = Object.freeze({
    VALID,
    ABSENT,
    INVALID,
    LINKED,
    UNLINKED,
    parseLastIntent,
    parseLastResult,
    linkRunnerRecords,
    parseRunnerRecords,
    commandView,
    createStatusGuard,
    currentTaskView,
  });
})();
