/**
 * Evaluation Dashboard Controller: AgentSentinel + EffectGuard
 * Streams live state-level evaluation telemetry, runs C0-C4 Scientific Matrix benchmarks,
 * and tracks real-world database mutations and claim audit diffs.
 */

let eventSource = null;
let currentResults = []; // Stores all completed cases for modal inspection

document.addEventListener("DOMContentLoaded", () => {
  initEvalDashboard();
  initModal();
});

function initEvalDashboard() {
  const startBtn = document.getElementById("startEvalBtn");
  const cancelBtn = document.getElementById("cancelEvalBtn");
  const downloadBtn = document.getElementById("downloadCsvBtn");

  if (startBtn) {
    startBtn.addEventListener("click", () => {
      startLiveEvaluation();
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      downloadBenchmarkCsv();
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/eval/cancel", { method: "POST" });
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        setEvalRunningState(false);
        updateStepperText("Evaluation stopped by user.");
      } catch (e) {
        console.error("Cancel failed", e);
      }
    });
  }
}

function startLiveEvaluation() {
  const modelSelect = document.getElementById("evalModelSelect");
  const countSelect = document.getElementById("evalCountSelect");
  const conditionSelect = document.getElementById("evalConditionSelect");
  const faultRateSelect = document.getElementById("evalFaultRateSelect");

  const selectedModel = modelSelect ? modelSelect.value : "openai";
  const limit = countSelect ? parseInt(countSelect.value, 10) : 25;
  const condition = conditionSelect ? conditionSelect.value : "c4";
  const faultRate = faultRateSelect ? parseFloat(faultRateSelect.value) : 0.0;

  let modelsParam = "openai";
  if (selectedModel !== "all") {
    modelsParam = selectedModel;
  }

  // Clear previous runs
  currentResults = [];
  clearTable();
  clearMetricsGauges();
  resetModelCards();
  hideLeaderboard();

  setEvalRunningState(true);
  updateStepperText(`Connecting to evaluation stream [Condition: ${condition.toUpperCase()}, Chaos: ${Math.round(faultRate * 100)}%]...`);

  // Open SSE stream with Condition and Fault Rate parameters
  const streamUrl = `/api/eval/stream?models=${encodeURIComponent(modelsParam)}&limit=${limit}&start=0&condition=${condition}&fault_rate=${faultRate}`;
  eventSource = new EventSource(streamUrl);

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      handleEvalEvent(data);
    } catch (err) {
      console.error("Error parsing SSE event", err, e.data);
    }
  };

  eventSource.onerror = (err) => {
    console.warn("SSE connection closed or errored", err);
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setEvalRunningState(false);
  };
}

function handleEvalEvent(event) {
  switch (event.type) {
    case "run_started":
      updateStepperText(`Benchmark started: ${event.total_cases} test cases queued [Condition: ${event.condition || 'C4'}, Fault Rate: ${Math.round((event.fault_rate || 0) * 100)}%].`);
      break;

    case "model_started":
      updateModelCardStatus(event.model, "RUNNING");
      highlightModelCard(event.model);
      updateStepperText(`Active benchmark: ${event.model.toUpperCase()} (${event.model_name})`);
      break;

    case "model_skipped":
      updateModelCardStatus(event.model, "SKIPPED");
      updateModelCardError(event.model, event.reason);
      break;

    case "case_started":
      renderActiveCaseStepper(event.case_index, event.total_cases, event.input, event.category, event.model);
      updateModelProgress(event.model, event.case_index, event.total_cases);
      break;

    case "case_completed":
      currentResults.push({
        ...event.result,
        model: event.model,
      });
      appendTableRow(event.model, event.result);
      updateMetricsGauges(event.result.metrics);
      updateModelCardMetrics(event.model, event.current_passed, event.case_index, event.current_pass_rate);
      break;

    case "model_completed":
      updateModelCardStatus(event.model, "COMPLETED");
      updateModelCardFinal(event.model, event.summary);
      break;

    case "run_completed":
      setEvalRunningState(false);
      updateStepperText("Evaluation run complete. Benchmark telemetry finalized.");
      renderLeaderboard(event.leaderboard);
      enableDownloadCsvButton();
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      break;

    case "run_cancelled":
      setEvalRunningState(false);
      updateStepperText(`Evaluation cancelled: ${event.message}`);
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      break;

    case "run_error":
      setEvalRunningState(false);
      updateStepperText(`Evaluation failed with error: ${event.error}`);
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      break;

    default:
      console.log("Unhandled SSE event", event);
  }
}

// =============================================================================
// UI Update Functions
// =============================================================================

function setEvalRunningState(isRunning) {
  const startBtn = document.getElementById("startEvalBtn");
  const cancelBtn = document.getElementById("cancelEvalBtn");
  const modelSelect = document.getElementById("evalModelSelect");
  const countSelect = document.getElementById("evalCountSelect");
  const conditionSelect = document.getElementById("evalConditionSelect");
  const faultRateSelect = document.getElementById("evalFaultRateSelect");

  if (startBtn) startBtn.disabled = isRunning;
  if (cancelBtn) cancelBtn.disabled = !isRunning;
  if (modelSelect) modelSelect.disabled = isRunning;
  if (countSelect) countSelect.disabled = isRunning;
  if (conditionSelect) conditionSelect.disabled = isRunning;
  if (faultRateSelect) faultRateSelect.disabled = isRunning;
}

function updateStepperText(text) {
  const queryEl = document.getElementById("activeCaseQuery");
  if (queryEl) queryEl.textContent = text;
}

function renderActiveCaseStepper(index, total, query, category, model) {
  const badge = document.getElementById("stepperCaseTag");
  const catBadge = document.getElementById("stepperCatBadge");
  const queryEl = document.getElementById("activeCaseQuery");

  const displayModel = (model === "llama" || model === "openai") ? "OpenAI OSS (20B)" : model.toUpperCase();
  if (badge) badge.textContent = `${displayModel} · Case ${index} of ${total}`;
  if (catBadge) catBadge.textContent = category;
  if (queryEl) queryEl.textContent = query;
}

function updateMetricsGauges(metrics) {
  if (!metrics) return;

  const setGauge = (metricKey, idPrefix) => {
    const data = metrics[metricKey];
    const scoreEl = document.getElementById(`${idPrefix}Score`);
    const statusEl = document.getElementById(`${idPrefix}Status`);

    if (data && scoreEl && statusEl) {
      if (data.score !== undefined && data.score !== null) {
        scoreEl.textContent = `${Math.round(data.score * 100)}%`;
      } else {
        scoreEl.textContent = data.passed ? "100%" : "0%";
      }
      statusEl.textContent = data.passed ? "PASS" : "FAIL";
      statusEl.className = `metric-badge-status ${data.passed ? "pass" : "fail"}`;
    }
  };

  setGauge("tool_correctness", "mTool");
  setGauge("answer_correctness", "mAnswer");
  setGauge("argument_correctness", "mArg");
  setGauge("financial_hallucination", "mFin");
  setGauge("claim_audit", "mClaim");
  setGauge("task_completion", "mTask");
}

function clearMetricsGauges() {
  ["mTool", "mAnswer", "mArg", "mFin", "mClaim", "mTask"].forEach((idPrefix) => {
    const scoreEl = document.getElementById(`${idPrefix}Score`);
    const statusEl = document.getElementById(`${idPrefix}Status`);
    if (scoreEl) scoreEl.textContent = "-";
    if (statusEl) {
      statusEl.textContent = "WAITING";
      statusEl.className = "metric-badge-status";
    }
  });
}

function formatMetricPill(metric) {
  if (!metric) return '<span style="color: var(--ink-muted); font-size: 11px;">-</span>';
  const score = Math.round((metric.score !== undefined ? metric.score : 0) * 100);
  const pillClass = metric.passed ? "pass" : "fail";
  return `<span class="test-pass-pill ${pillClass}" style="font-size: 10px; padding: 2px 5px;">${score}%</span>`;
}

function appendTableRow(model, result) {
  const tbody = document.getElementById("resultsTableBody");
  if (!tbody) return;

  const tr = document.createElement("tr");

  const toolsSummary = (result.tools_called || []).map((t) => t.name).join(", ") || "None";
  const passClass = result.passed ? "pass" : "fail";
  const passLabel = result.passed ? "PASS" : "FAIL";

  const mTool = formatMetricPill(result.metrics?.tool_correctness);
  const mAns = formatMetricPill(result.metrics?.answer_correctness);
  const mArg = formatMetricPill(result.metrics?.argument_correctness);
  
  // Format Claim Audit pill
  const claimData = result.metrics?.claim_audit;
  const mClaim = claimData
    ? `<span class="test-pass-pill ${claimData.passed ? 'pass' : 'fail'}" style="font-size: 10px; padding: 2px 5px;" title="${claimData.details || ''}">${claimData.discrepancy_type === 'NONE' ? 'AUDIT OK' : claimData.discrepancy_type}</span>`
    : `<span style="color:var(--ink-muted); font-size: 11px;">-</span>`;

  const resultIndex = currentResults.length - 1;

  tr.innerHTML = `
    <td style="font-family: var(--font-mono); font-size: 11px;">#${result.case_index}</td>
    <td style="font-size: 11px; font-weight: 500; color: var(--ink-muted);">${result.category || 'General'}</td>
    <td style="max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${result.input}">${result.input}</td>
    <td style="max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink);" title="${result.actual_output || 'None'}">${result.actual_output || '<span style="color:var(--ink-muted)">None</span>'}</td>
    <td style="max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-muted);" title="${result.expected_output}">${result.expected_output}</td>
    <td style="font-family: var(--font-mono); font-size: 11px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${toolsSummary}">${toolsSummary}</td>
    <td style="text-align: center;">${mTool}</td>
    <td style="text-align: center;">${mAns}</td>
    <td style="text-align: center;">${mArg}</td>
    <td style="text-align: center;">${mClaim}</td>
    <td><span class="test-pass-pill ${passClass}">${passLabel}</span></td>
    <td style="font-family: var(--font-mono); font-size: 11px;">${result.latency_ms}ms</td>
    <td><button type="button" class="btn-inspect-case" onclick="openCaseModal(${resultIndex})">Inspect</button></td>
  `;

  tbody.insertBefore(tr, tbody.firstChild);
}

function clearTable() {
  const tbody = document.getElementById("resultsTableBody");
  if (tbody) tbody.innerHTML = "";
}

function getModelCard(key) {
  return (
    document.getElementById(`modelCard_${key}`) ||
    document.getElementById("modelCard_openai") ||
    document.getElementById("modelCard_llama")
  );
}

function resetModelCards() {
  ["openai", "llama"].forEach((key) => {
    const card = document.getElementById(`modelCard_${key}`);
    if (card) {
      card.className = "model-card";
      const statusBadge = card.querySelector(".status-badge");
      if (statusBadge) {
        statusBadge.textContent = "IDLE";
        statusBadge.className = "status-badge idle";
      }
      const passRateEl = card.querySelector(".card-pass-rate");
      if (passRateEl) passRateEl.textContent = "-";
      const countEl = card.querySelector(".card-case-count");
      if (countEl) countEl.textContent = "0/0";
      const latencyEl = card.querySelector(".card-latency");
      if (latencyEl) latencyEl.textContent = "-";
      const bar = card.querySelector(".model-progress-bar-fill");
      if (bar) bar.style.width = "0%";
    }
  });
}

function updateModelCardStatus(modelKey, status) {
  const card = getModelCard(modelKey);
  if (!card) return;
  const badge = card.querySelector(".status-badge");
  if (badge) {
    badge.textContent = status;
    badge.className = `status-badge ${status.toLowerCase()}`;
  }
}

function highlightModelCard(modelKey) {
  ["openai", "llama"].forEach((key) => {
    const card = document.getElementById(`modelCard_${key}`);
    if (card) {
      if (key === modelKey || (modelKey === "openai" && key === "llama") || (modelKey === "llama" && key === "openai")) {
        card.classList.add("active-running");
      } else {
        card.classList.remove("active-running");
      }
    }
  });
}

function updateModelProgress(modelKey, current, total) {
  const card = getModelCard(modelKey);
  if (!card) return;
  const bar = card.querySelector(".model-progress-bar-fill");
  const countEl = card.querySelector(".card-case-count");
  if (bar && total > 0) {
    const pct = Math.round((current / total) * 100);
    bar.style.width = `${pct}%`;
  }
  if (countEl) {
    countEl.textContent = `${current}/${total}`;
  }
}

function updateModelCardMetrics(modelKey, passed, totalRan, passRate) {
  const card = getModelCard(modelKey);
  if (!card) return;
  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) {
    passRateEl.textContent = `${passRate}%`;
  }
}

function updateModelCardFinal(modelKey, summary) {
  const card = getModelCard(modelKey);
  if (!card) return;
  card.classList.remove("active-running");
  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) passRateEl.textContent = `${summary.pass_rate}%`;
  const latencyEl = card.querySelector(".card-latency");
  if (latencyEl) latencyEl.textContent = `${summary.avg_latency_ms}ms`;
}

function updateModelCardError(modelKey, reason) {
  const card = getModelCard(modelKey);
  if (!card) return;
  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) passRateEl.textContent = "SKIPPED";
}

function renderLeaderboard(leaderboard) {
  const section = document.getElementById("leaderboardSection");
  const tbody = document.getElementById("leaderboardTableBody");
  if (!section || !tbody) return;

  tbody.innerHTML = "";
  leaderboard.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-weight: 700;">#${index + 1}</td>
      <td style="font-weight: 600;">${item.model_name || item.model}</td>
      <td style="color: var(--ink-muted);">${item.provider}</td>
      <td style="font-weight: 700; color: ${item.pass_rate >= 80 ? 'var(--semantic-success)' : 'var(--semantic-error)'}">${item.pass_rate}% (${item.passed}/${item.total})</td>
      <td><span class="status-badge ${item.status.toLowerCase()}">${item.status}</span></td>
      <td style="font-family: var(--font-mono);">${item.avg_score}</td>
      <td style="font-family: var(--font-mono);">${item.avg_latency_ms}ms</td>
    `;
    tbody.appendChild(tr);
  });

  section.style.display = "block";
}

function hideLeaderboard() {
  const section = document.getElementById("leaderboardSection");
  if (section) section.style.display = "none";
}

function enableDownloadCsvButton() {
  const downloadBtn = document.getElementById("downloadCsvBtn");
  if (downloadBtn) {
    downloadBtn.disabled = currentResults.length === 0;
  }
}

function openCaseModal(index) {
  const modal = document.getElementById("caseModal");
  if (!modal || index < 0 || index >= currentResults.length) return;

  const data = currentResults[index];

  const titleEl = document.getElementById("modalCaseTitle");
  const inputEl = document.getElementById("modalInput");
  const actualEl = document.getElementById("modalActualOutput");
  const expectedEl = document.getElementById("modalExpectedOutput");
  const toolsEl = document.getElementById("modalToolsCalled");
  const expToolsEl = document.getElementById("modalExpectedTools");
  const metricsEl = document.getElementById("modalMetricsJson");
  const errorSec = document.getElementById("modalErrorSection");
  const errorEl = document.getElementById("modalErrorContent");

  const displayModel = (data.model === "llama" || data.model === "openai") ? "OpenAI OSS (20B)" : data.model.toUpperCase();
  if (titleEl) titleEl.textContent = `Case #${data.case_index} · ${data.category || 'General'} (${displayModel})`;
  if (inputEl) inputEl.textContent = data.input;
  if (actualEl) actualEl.textContent = data.actual_output || "No output generated";
  if (expectedEl) expectedEl.textContent = data.expected_output;

  if (toolsEl) {
    toolsEl.textContent = JSON.stringify(data.tools_called, null, 2);
  }
  if (expToolsEl) {
    expToolsEl.textContent = JSON.stringify(data.expected_tools, null, 2);
  }
  if (metricsEl) {
    metricsEl.textContent = JSON.stringify(data.metrics, null, 2);
  }

  if (data.error) {
    if (errorSec) errorSec.style.display = "block";
    if (errorEl) errorEl.textContent = data.error;
  } else if (errorSec) {
    errorSec.style.display = "none";
  }

  modal.classList.add("active");
}

// =============================================================================
// CSV Export Generator
// =============================================================================

function downloadBenchmarkCsv() {
  if (currentResults.length === 0) return;

  const headers = [
    "Case Index",
    "Model",
    "Category",
    "Input Query",
    "Actual Output",
    "Expected Output",
    "Tools Called",
    "Tool Correctness (%)",
    "Tool Status",
    "Answer Correctness (%)",
    "Answer Status",
    "Argument Correctness (%)",
    "Argument Status",
    "Claim Audit Status",
    "Claim Discrepancy",
    "Financial Hallucination",
    "Task Completion (%)",
    "Task Status",
    "Overall Result",
    "Latency (ms)",
    "Error",
  ];

  const escapeCsv = (val) => {
    if (val === null || val === undefined) return '""';
    const str = String(val).replace(/"/g, '""');
    return `"${str}"`;
  };

  const rows = currentResults.map((r) => {
    const toolsStr = (r.tools_called || []).map((t) => t.name).join("; ");
    const mTool = r.metrics?.tool_correctness;
    const mAns = r.metrics?.answer_correctness;
    const mArg = r.metrics?.argument_correctness;
    const mClaim = r.metrics?.claim_audit;
    const mFin = r.metrics?.financial_hallucination;
    const mTask = r.metrics?.task_completion;
    const modelCol = (r.model === "llama" || r.model === "openai") ? "OpenAI OSS (20B)" : r.model;

    return [
      r.case_index !== undefined ? r.case_index : "",
      modelCol,
      r.category || "",
      r.input || "",
      r.actual_output || "",
      r.expected_output || "",
      toolsStr || "None",
      mTool && mTool.score !== undefined ? Math.round(mTool.score * 100) + "%" : "-",
      mTool ? (mTool.passed ? "PASS" : "FAIL") : "-",
      mAns && mAns.score !== undefined ? Math.round(mAns.score * 100) + "%" : "-",
      mAns ? (mAns.passed ? "PASS" : "FAIL") : "-",
      mArg && mArg.score !== undefined ? Math.round(mArg.score * 100) + "%" : "-",
      mArg ? (mArg.passed ? "PASS" : "FAIL") : "-",
      mClaim ? (mClaim.passed ? "PASS" : "FAIL") : "-",
      mClaim ? (mClaim.discrepancy_type || "NONE") : "NONE",
      mFin ? (mFin.detected ? "DETECTED" : "ZERO") : "ZERO",
      mTask && mTask.score !== undefined ? Math.round(mTask.score * 100) + "%" : "-",
      mTask ? (mTask.passed ? "PASS" : "FAIL") : "-",
      r.passed ? "PASS" : "FAIL",
      r.latency_ms || 0,
      r.error || "",
    ]
      .map(escapeCsv)
      .join(",");
  });

  const csvContent = "\uFEFF" + [headers.map(escapeCsv).join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, "-");
  a.href = url;
  a.download = `agent_eval_benchmark_openai_${dateStr}_${timeStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
