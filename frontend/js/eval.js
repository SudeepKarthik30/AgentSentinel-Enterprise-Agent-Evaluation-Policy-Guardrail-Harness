/**
 * Evaluation Dashboard Controller
 * Streams genuine live DeepEval metrics, model statuses, and builds live comparative leaderboards.
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

  const selectedModel = modelSelect ? modelSelect.value : "llama";
  const limit = countSelect ? parseInt(countSelect.value, 10) : 25;

  let modelsParam = "llama";
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
  updateStepperText("Connecting to evaluation stream and launching model benchmarks...");

  // Open SSE stream
  const streamUrl = `/api/eval/stream?models=${encodeURIComponent(modelsParam)}&limit=${limit}&start=0`;
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
      updateStepperText(`Benchmark started: ${event.total_cases} test cases queued across models.`);
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
      break;

    case "case_completed":
      currentResults.push({ ...event.result, model: event.model });
      appendTableRow(event.model, event.result);
      updateModelCardProgress(event.model, event.case_index, event.total_cases, event.current_pass_rate);
      updateMetricsGauges(event.result.metrics);
      updateDownloadBtnState();
      break;

    case "model_completed":
      updateModelCardStatus(event.model, "COMPLETED");
      finalizeModelCard(event.model, event.summary);
      unhighlightModelCard(event.model);
      break;

    case "run_completed":
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      setEvalRunningState(false);
      updateStepperText("Benchmark run successfully completed across all models.");
      renderLeaderboard(event.leaderboard);
      updateDownloadBtnState();
      break;

    case "run_cancelled":
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      setEvalRunningState(false);
      updateStepperText("Evaluation was cancelled.");
      break;

    case "run_error":
      updateStepperText(`Evaluation Error: ${event.error}`);
      setEvalRunningState(false);
      break;
  }
}

function setEvalRunningState(running) {
  const startBtn = document.getElementById("startEvalBtn");
  const cancelBtn = document.getElementById("cancelEvalBtn");
  const modelSelect = document.getElementById("evalModelSelect");
  const countSelect = document.getElementById("evalCountSelect");

  if (startBtn) startBtn.disabled = running;
  if (cancelBtn) cancelBtn.disabled = !running;
  if (modelSelect) modelSelect.disabled = running;
  if (countSelect) countSelect.disabled = running;

  updateDownloadBtnState(running);
}

function updateDownloadBtnState(forceRunning = false) {
  const downloadBtn = document.getElementById("downloadCsvBtn");
  if (downloadBtn) {
    downloadBtn.disabled = forceRunning || currentResults.length === 0;
  }
}

function updateStepperText(text) {
  const el = document.getElementById("activeCaseQuery");
  if (el) el.textContent = text;
}

function renderActiveCaseStepper(index, total, query, category, model) {
  const badge = document.getElementById("stepperCaseTag");
  const catBadge = document.getElementById("stepperCatBadge");
  const queryEl = document.getElementById("activeCaseQuery");

  if (badge) badge.textContent = `${model.toUpperCase()} · Case ${index} of ${total}`;
  if (catBadge) catBadge.textContent = category;
  if (queryEl) queryEl.textContent = query;
}

function updateMetricsGauges(metrics) {
  if (!metrics) return;

  const setGauge = (metricKey, title, idPrefix) => {
    const data = metrics[metricKey];
    const scoreEl = document.getElementById(`${idPrefix}Score`);
    const statusEl = document.getElementById(`${idPrefix}Status`);

    if (data && scoreEl && statusEl) {
      scoreEl.textContent = `${Math.round(data.score * 100)}%`;
      statusEl.textContent = data.passed ? "PASS" : "FAIL";
      statusEl.className = `metric-badge-status ${data.passed ? "pass" : "fail"}`;
    }
  };

  setGauge("tool_correctness", "Tool Correctness", "mTool");
  setGauge("answer_correctness", "Answer Correctness", "mAnswer");
  setGauge("argument_correctness", "Argument Correctness", "mArg");
  setGauge("task_completion", "Task Completion", "mTask");
}

function clearMetricsGauges() {
  ["mTool", "mAnswer", "mArg", "mTask"].forEach((idPrefix) => {
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
  const mTask = formatMetricPill(result.metrics?.task_completion);

  const resultIndex = currentResults.length - 1;

  tr.innerHTML = `
    <td style="font-family: var(--font-mono); font-size: 11px;">#${result.case_index}</td>
    <td style="font-weight: 600; text-transform: uppercase; font-size: 11px;">${model}</td>
    <td style="max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${result.input}">${result.input}</td>
    <td style="max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink);" title="${result.actual_output || 'None'}">${result.actual_output || '<span style="color:var(--ink-muted)">None</span>'}</td>
    <td style="max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-muted);" title="${result.expected_output}">${result.expected_output}</td>
    <td style="font-family: var(--font-mono); font-size: 11px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${toolsSummary}">${toolsSummary}</td>
    <td style="text-align: center;">${mTool}</td>
    <td style="text-align: center;">${mAns}</td>
    <td style="text-align: center;">${mArg}</td>
    <td style="text-align: center;">${mTask}</td>
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

function resetModelCards() {
  ["llama"].forEach((key) => {
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

function highlightModelCard(modelKey) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (card) card.classList.add("running");
}

function unhighlightModelCard(modelKey) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (card) card.classList.remove("running");
}

function updateModelCardStatus(modelKey, status) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (!card) return;

  const badge = card.querySelector(".status-badge");
  if (!badge) return;

  badge.textContent = status;
  badge.className = `status-badge ${status.toLowerCase()}`;
}

function updateModelCardProgress(modelKey, current, total, passRate) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (!card) return;

  const countEl = card.querySelector(".card-case-count");
  if (countEl) countEl.textContent = `${current}/${total}`;

  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) passRateEl.textContent = `${passRate}%`;

  const bar = card.querySelector(".model-progress-bar-fill");
  if (bar && total > 0) {
    bar.style.width = `${Math.round((current / total) * 100)}%`;
  }
}

function updateModelCardError(modelKey, errorMsg) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (!card) return;
  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) passRateEl.textContent = "N/A";
  const countEl = card.querySelector(".card-case-count");
  if (countEl) countEl.textContent = "Skipped";
}

function finalizeModelCard(modelKey, summary) {
  const card = document.getElementById(`modelCard_${modelKey}`);
  if (!card) return;

  const passRateEl = card.querySelector(".card-pass-rate");
  if (passRateEl) passRateEl.textContent = `${summary.pass_rate}%`;

  const countEl = card.querySelector(".card-case-count");
  if (countEl) countEl.textContent = `${summary.passed}/${summary.total}`;

  const latencyEl = card.querySelector(".card-latency");
  if (latencyEl) latencyEl.textContent = `${summary.avg_latency_ms}ms`;

  const bar = card.querySelector(".model-progress-bar-fill");
  if (bar) bar.style.width = "100%";
}

function renderLeaderboard(leaderboard) {
  const section = document.getElementById("leaderboardSection");
  const tbody = document.getElementById("leaderboardTableBody");
  if (!section || !tbody) return;

  tbody.innerHTML = "";
  section.style.display = "block";

  // Sort by pass rate descending
  const sorted = [...leaderboard].sort((a, b) => b.pass_rate - a.pass_rate);

  sorted.forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-family: var(--font-mono); font-size: 12px; font-weight: 700;">#${idx + 1}</td>
      <td style="font-weight: 600; text-transform: uppercase;">${item.model} <span style="font-size: 11px; color: var(--ink-muted); font-weight: 400;">(${item.model_name})</span></td>
      <td><span style="font-size: 11px; color: var(--ink-muted);">${item.provider}</span></td>
      <td style="font-family: var(--font-mono); font-weight: 600;">${item.passed} / ${item.total}</td>
      <td><span class="test-pass-pill ${item.pass_rate >= 80 ? "pass" : "fail"}">${item.pass_rate}%</span></td>
      <td style="font-family: var(--font-mono);">${item.avg_score.toFixed(2)}</td>
      <td style="font-family: var(--font-mono);">${item.avg_latency_ms}ms</td>
    `;
    tbody.appendChild(tr);
  });

  // Scroll into view smoothly
  section.scrollIntoView({ behavior: "smooth" });
}

function hideLeaderboard() {
  const section = document.getElementById("leaderboardSection");
  if (section) section.style.display = "none";
}

/* Modal Inspection Logic */
function initModal() {
  const modal = document.getElementById("caseModal");
  const closeBtn = document.getElementById("closeModalBtn");

  if (closeBtn && modal) {
    closeBtn.addEventListener("click", () => {
      modal.classList.remove("active");
    });

    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        modal.classList.remove("active");
      }
    });
  }
}

window.openCaseModal = function (index) {
  const item = currentResults[index];
  if (!item) return;

  const modal = document.getElementById("caseModal");
  if (!modal) return;

  document.getElementById("modalCaseTitle").textContent = `Case #${item.case_index} Details (${item.model.toUpperCase()})`;
  document.getElementById("modalInput").textContent = item.input;
  document.getElementById("modalExpectedOutput").textContent = item.expected_output || "N/A";
  document.getElementById("modalActualOutput").textContent = item.actual_output || "N/A";

  const errorSection = document.getElementById("modalErrorSection");
  const errorContent = document.getElementById("modalErrorContent");
  if (errorSection && errorContent) {
    if (item.error) {
      errorSection.style.display = "block";
      errorContent.textContent = item.error;
    } else {
      errorSection.style.display = "none";
    }
  }

  const toolsCalledEl = document.getElementById("modalToolsCalled");
  if (toolsCalledEl) {
    toolsCalledEl.textContent = JSON.stringify(item.tools_called, null, 2);
  }

  const expectedToolsEl = document.getElementById("modalExpectedTools");
  if (expectedToolsEl) {
    expectedToolsEl.textContent = JSON.stringify(item.expected_tools, null, 2);
  }

  const metricsBox = document.getElementById("modalMetricsJson");
  if (metricsBox) {
    metricsBox.textContent = JSON.stringify(item.metrics, null, 2);
  }

  modal.classList.add("active");
};

/**
 * Export completed test case results into standard CSV format.
 * Includes UTF-8 BOM so Excel opens all symbols and text with perfect formatting.
 */
function downloadBenchmarkCsv() {
  if (!currentResults || currentResults.length === 0) {
    alert("No evaluation test case results available to download.");
    return;
  }

  const headers = [
    "Case Index",
    "Model",
    "Category",
    "Input Query",
    "Given Output (Model)",
    "Expected Output",
    "Tools Called",
    "Tool Correctness (%)",
    "Tool Status",
    "Answer Correctness (%)",
    "Answer Status",
    "Argument Correctness (%)",
    "Argument Status",
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
    const mTask = r.metrics?.task_completion;

    return [
      r.case_index !== undefined ? r.case_index : "",
      r.model || "",
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
      mTask && mTask.score !== undefined ? Math.round(mTask.score * 100) + "%" : "-",
      mTask ? (mTask.passed ? "PASS" : "FAIL") : "-",
      r.passed ? "PASS" : "FAIL",
      r.latency_ms || 0,
      r.error || "",
    ]
      .map(escapeCsv)
      .join(",");
  });

  // Prepend UTF-8 BOM (\uFEFF)
  const csvContent = "\uFEFF" + [headers.map(escapeCsv).join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const modelName = currentResults[0]?.model || "models";
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, "-");
  a.href = url;
  a.download = `agent_eval_benchmark_${modelName}_${dateStr}_${timeStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
