async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return await response.json();
}

let mediaRecorder = null;
let mediaRecorderStream = null;
let mediaRecorderFormat = null;
let recordedChunks = [];
let recordedAudioFile = null;
let recordedPreviewUrl = null;

const RECORDING_FORMATS = [
  {mimeType: "audio/webm;codecs=opus", extension: "webm"},
  {mimeType: "audio/webm", extension: "webm"},
  {mimeType: "audio/mp4", extension: "m4a"},
  {mimeType: "audio/ogg;codecs=opus", extension: "ogg"},
  {mimeType: "audio/ogg", extension: "ogg"},
];

const STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  ok: "正常",
  degraded: "降级",
};

const PHASE_LABELS = {
  queued: "排队",
  ingest: "接收",
  preprocess: "预处理",
  asr: "识别",
  dialogue: "对话",
  tts: "合成",
  persist: "保存",
  completed: "完成",
  failed: "失败",
};

const PIPELINE_PHASES = [
  "queued",
  "ingest",
  "preprocess",
  "asr",
  "dialogue",
  "tts",
  "persist",
  "completed",
];

function appendChildren(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) {
      continue;
    }
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
}

function el(tagName, options = {}, children = []) {
  const node = document.createElement(tagName);
  const {
    className,
    text,
    attrs = {},
    dataset = {},
    href,
    target,
    rel,
    type,
    title,
  } = options;
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  if (href !== undefined) {
    node.href = href;
  }
  if (target !== undefined) {
    node.target = target;
  }
  if (rel !== undefined) {
    node.rel = rel;
  }
  if (type !== undefined) {
    node.type = type;
  }
  if (title !== undefined) {
    node.title = title;
  }
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) {
      node.setAttribute(key, value);
    }
  }
  for (const [key, value] of Object.entries(dataset)) {
    node.dataset[key] = value;
  }
  appendChildren(node, children);
  return node;
}

function clearNode(node) {
  if (node) {
    node.replaceChildren();
  }
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
}

function setRecordingStatus(message) {
  setText("record-status", message);
}

function labelFor(value, labels = STATUS_LABELS) {
  return labels[value] || value || "未知";
}

function statusTone(value) {
  if (value === true || value === "ok" || value === "completed" || value === "available") {
    return "success";
  }
  if (value === "running" || value === "queued") {
    return "accent";
  }
  if (value === "degraded" || value === false || value === "unconfigured") {
    return "warn";
  }
  if (value === "failed" || value === "error" || value === "unavailable") {
    return "danger";
  }
  return "neutral";
}

function badge(text, tone = "neutral") {
  return el("span", {className: `badge badge-${tone}`, text});
}

function formatDate(value) {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function compactId(value) {
  return value ? value.slice(0, 8) : "未创建";
}

function formatValue(value) {
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  if (value === null || value === undefined || value === "") {
    return "未设置";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function emptyState(title, detail = "") {
  return el("div", {className: "empty-state"}, [
    el("strong", {text: title}),
    detail ? el("span", {text: detail}) : null,
  ]);
}

function renderError(containerId, error, title = "加载失败") {
  const container = document.getElementById(containerId);
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(emptyState(title, String(error)));
}

function renderStatusMessage(message, tone = "accent") {
  const container = document.getElementById("job-status");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(
    el("div", {className: "status-message"}, [
      badge(labelFor(tone === "danger" ? "failed" : "running"), tone),
      el("span", {text: message}),
    ]),
  );
}

function providerBadge(provider) {
  if (!provider.configured) {
    return badge("未配置", "warn");
  }
  return provider.available ? badge("可用", "success") : badge("不可用", "danger");
}

function renderProviders(providers = {}) {
  const providerList = el("div", {className: "provider-list"});
  const entries = Object.entries(providers);
  if (!entries.length) {
    providerList.appendChild(emptyState("暂无 provider 状态"));
    return providerList;
  }
  for (const [key, provider] of entries) {
    providerList.appendChild(
      el("article", {className: "provider-card"}, [
        el("div", {className: "provider-card-header"}, [
          el("strong", {text: provider.name || key}),
          providerBadge(provider),
        ]),
        el("p", {text: provider.detail || "无状态说明"}),
        el("small", {text: key}),
      ]),
    );
  }
  return providerList;
}

function renderKeyValueGrid(payload = {}) {
  const grid = el("div", {className: "kv-grid"});
  for (const [key, value] of Object.entries(payload)) {
    grid.appendChild(
      el("div", {className: "kv-item"}, [
        el("span", {text: key}),
        el("strong", {text: formatValue(value)}),
      ]),
    );
  }
  if (!grid.children.length) {
    grid.appendChild(emptyState("暂无数据"));
  }
  return grid;
}

function renderJobStatus(snapshot) {
  const container = document.getElementById("job-status");
  if (!container) {
    return;
  }
  clearNode(container);

  const job = snapshot?.job;
  if (!job) {
    container.appendChild(emptyState("等待新任务", "提交后会显示实时流水线状态。"));
    return;
  }

  const status = job.status || "queued";
  const phase = job.phase || "queued";
  const currentIndex = PIPELINE_PHASES.indexOf(phase);
  const completeIndex = status === "completed" ? PIPELINE_PHASES.length - 1 : currentIndex;

  const phaseTrack = el("div", {className: "phase-track"});
  for (const [index, phaseName] of PIPELINE_PHASES.entries()) {
    const classes = ["phase-step"];
    if (index <= completeIndex && completeIndex >= 0) {
      classes.push("is-complete");
    }
    if (phaseName === phase && status !== "completed") {
      classes.push(status === "failed" ? "is-failed" : "is-active");
    }
    phaseTrack.appendChild(el("span", {className: classes.join(" "), text: labelFor(phaseName, PHASE_LABELS)}));
  }

  container.appendChild(
    el("div", {className: "status-stack"}, [
      el("div", {className: "status-header"}, [
        el("div", {}, [
          el("span", {className: "muted-label", text: `JOB ${compactId(job.id)}`}),
          el("strong", {text: snapshot.session?.title || "临时会话"}),
        ]),
        badge(labelFor(status), statusTone(status)),
      ]),
      phaseTrack,
      renderKeyValueGrid({
        当前阶段: labelFor(phase, PHASE_LABELS),
        会话: compactId(job.session_id),
        轮次: compactId(job.turn_id),
        更新时间: formatDate(job.updated_at),
      }),
      job.error ? el("p", {className: "error-banner", text: job.error}) : null,
    ]),
  );
}

function renderConversation(snapshot) {
  const output = document.getElementById("conversation-output");
  if (!output) {
    return;
  }
  clearNode(output);

  const turn = snapshot?.turn || {};
  const messages = [];
  if (turn.user_text) {
    messages.push({role: "用户", tone: "user", text: turn.user_text});
  }
  if (turn.transcript && turn.transcript !== turn.user_text) {
    messages.push({role: "转写", tone: "transcript", text: turn.transcript});
  }
  if (turn.assistant_text) {
    messages.push({role: "助手", tone: "assistant", text: turn.assistant_text});
  }

  if (!messages.length) {
    output.appendChild(emptyState("等待结果", "提交任务后会在这里显示转写和回复。"));
  } else {
    const stack = el("div", {className: "message-stack"});
    for (const message of messages) {
      stack.appendChild(
        el("article", {className: `message-card message-${message.tone}`}, [
          el("span", {text: message.role}),
          el("p", {text: message.text}),
        ]),
      );
    }
    output.appendChild(stack);
  }

  const audioPlayer = document.getElementById("assistant-audio");
  if (!audioPlayer) {
    return;
  }
  const audioArtifact = (snapshot?.artifacts || []).find(
    (artifact) => artifact.kind === "assistant_audio",
  );
  if (audioArtifact) {
    audioPlayer.src = `/api/v1/artifacts/${audioArtifact.id}/content`;
    audioPlayer.classList.remove("hidden");
  } else {
    audioPlayer.classList.add("hidden");
  }
}

function renderHistory(details) {
  const container = document.getElementById("history-output");
  if (!container) {
    return;
  }
  clearNode(container);
  if (!details.length) {
    container.appendChild(emptyState("暂无会话", "完成一次对话后会出现在这里。"));
    return;
  }

  for (const session of details) {
    const turns = session.turns || [];
    const timeline = el("div", {className: "turn-list"});
    for (const turn of turns.slice(0, 5)) {
      timeline.appendChild(
        el("article", {className: "turn-card"}, [
          el("div", {className: "turn-meta"}, [
            badge(labelFor(turn.status), statusTone(turn.status)),
            el("span", {text: formatDate(turn.updated_at)}),
          ]),
          el("p", {text: turn.user_text || turn.transcript || "无用户输入文本"}),
          turn.assistant_text ? el("small", {text: turn.assistant_text}) : null,
        ]),
      );
    }
    if (!timeline.children.length) {
      timeline.appendChild(emptyState("暂无轮次"));
    }

    container.appendChild(
      el("article", {className: "info-card"}, [
        el("div", {className: "info-card-header"}, [
          el("div", {}, [
            el("h3", {text: session.title}),
            el("span", {className: "muted-label", text: `更新于 ${formatDate(session.updated_at)}`}),
          ]),
          badge(`${session.turn_count || turns.length} 轮`, "accent"),
        ]),
        timeline,
      ]),
    );
  }
}

function artifactKindLabel(kind) {
  const labels = {
    uploaded_audio: "上传音频",
    input_audio: "输入音频",
    converted_audio: "转换音频",
    preprocess_summary: "预处理",
    asr_result: "识别结果",
    assistant_response: "回复 JSON",
    assistant_audio: "回复音频",
    feature_summary: "特征摘要",
  };
  return labels[kind] || kind;
}

function renderArtifacts(artifacts) {
  const container = document.getElementById("artifacts-output");
  if (!container) {
    return;
  }
  clearNode(container);
  if (!artifacts.length) {
    container.appendChild(emptyState("暂无产物", "上传音频或完成任务后会生成文件。"));
    return;
  }

  for (const artifact of artifacts) {
    container.appendChild(
      el("article", {className: "artifact-row"}, [
        el("div", {className: "artifact-main"}, [
          badge(artifactKindLabel(artifact.kind), "accent"),
          el("div", {}, [
            el("strong", {text: artifact.label}),
            el("span", {text: artifact.relative_path}),
          ]),
        ]),
        el("div", {className: "artifact-meta"}, [
          el("span", {text: artifact.media_type || "application/octet-stream"}),
          el("span", {text: formatDate(artifact.created_at)}),
          el("a", {
            className: "button button-small",
            text: "打开",
            href: `/api/v1/artifacts/${artifact.id}/content`,
          }),
        ]),
      ]),
    );
  }
}

function renderSettings(payload) {
  const container = document.getElementById("settings-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(
    el("section", {className: "settings-section"}, [
      el("h3", {text: "Provider 状态"}),
      renderProviders(payload.providers),
    ]),
  );
  container.appendChild(
    el("section", {className: "settings-section"}, [
      el("h3", {text: "运行配置"}),
      renderKeyValueGrid(payload.settings),
    ]),
  );
}

function renderHealth(payload) {
  const container = document.getElementById("health-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(
    el("div", {className: "metric-grid"}, [
      el("article", {className: "metric-card"}, [
        el("span", {text: "服务状态"}),
        badge(labelFor(payload.status), statusTone(payload.status)),
      ]),
      el("article", {className: "metric-card"}, [
        el("span", {text: "就绪"}),
        badge(payload.ready ? "已就绪" : "未就绪", statusTone(payload.ready)),
      ]),
      el("article", {className: "metric-card"}, [
        el("span", {text: "Worker"}),
        badge(payload.worker_running ? "运行中" : "未运行", statusTone(payload.worker_running)),
      ]),
      el("article", {className: "metric-card"}, [
        el("span", {text: "队列"}),
        el("strong", {text: `${payload.queue_size ?? 0}`}),
      ]),
      el("article", {className: "metric-card"}, [
        el("span", {text: "Profile"}),
        el("strong", {text: payload.profile || "unknown"}),
      ]),
    ]),
  );
  container.appendChild(renderProviders(payload.providers));
}

function setRecordingControls({isRecording, hasRecording}) {
  const startButton = document.getElementById("record-start");
  const stopButton = document.getElementById("record-stop");
  const clearButton = document.getElementById("record-clear");
  if (startButton) {
    startButton.disabled = isRecording;
  }
  if (stopButton) {
    stopButton.disabled = !isRecording;
  }
  if (clearButton) {
    clearButton.disabled = isRecording || !hasRecording;
  }
}

function clearRecordingPreview() {
  const preview = document.getElementById("recording-preview");
  if (recordedPreviewUrl) {
    URL.revokeObjectURL(recordedPreviewUrl);
    recordedPreviewUrl = null;
  }
  if (preview) {
    preview.pause();
    preview.removeAttribute("src");
    preview.classList.add("hidden");
  }
}

function resetRecordedAudio() {
  recordedAudioFile = null;
  recordedChunks = [];
  clearRecordingPreview();
  setRecordingStatus("点“Pi5 录音并提交”会调用树莓派 USB 麦克风；浏览器录音只用于本机麦克风。");
  setRecordingControls({isRecording: false, hasRecording: false});
}

function pickRecordingFormat() {
  if (!window.MediaRecorder) {
    return null;
  }
  for (const candidate of RECORDING_FORMATS) {
    if (!window.MediaRecorder.isTypeSupported || window.MediaRecorder.isTypeSupported(candidate.mimeType)) {
      return candidate;
    }
  }
  return {mimeType: "", extension: "webm"};
}

function recordingExtension(mimeType) {
  if (mimeType.includes("webm")) {
    return "webm";
  }
  if (mimeType.includes("ogg")) {
    return "ogg";
  }
  if (mimeType.includes("mp4")) {
    return "m4a";
  }
  return "webm";
}

function stopRecordingTracks() {
  if (mediaRecorderStream) {
    mediaRecorderStream.getTracks().forEach((track) => track.stop());
    mediaRecorderStream = null;
  }
}

async function startBrowserRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setRecordingStatus("当前浏览器不支持录音；树莓派实验请直接点“Pi5 录音并提交”。");
    return;
  }

  resetRecordedAudio();
  mediaRecorderFormat = pickRecordingFormat();
  if (!mediaRecorderFormat) {
    setRecordingStatus("当前浏览器无法选择可用的录音格式，请改用上传 WAV。");
    return;
  }

  try {
    mediaRecorderStream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = mediaRecorderFormat.mimeType
      ? new MediaRecorder(mediaRecorderStream, {mimeType: mediaRecorderFormat.mimeType})
      : new MediaRecorder(mediaRecorderStream);
  } catch (error) {
    setRecordingStatus(`浏览器麦克风不可用：${String(error)}。树莓派实验请直接点“Pi5 录音并提交”。`);
    stopRecordingTracks();
    return;
  }

  recordedChunks = [];
  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      recordedChunks.push(event.data);
    }
  };
  mediaRecorder.onstop = () => {
    const mimeType = mediaRecorder?.mimeType || mediaRecorderFormat?.mimeType || "audio/webm";
    const extension = recordingExtension(mimeType);
    const blob = new Blob(recordedChunks, {type: mimeType});
    recordedAudioFile = new File([blob], `browser-recording.${extension}`, {type: mimeType});

    const preview = document.getElementById("recording-preview");
    if (preview) {
      recordedPreviewUrl = URL.createObjectURL(blob);
      preview.src = recordedPreviewUrl;
      preview.classList.remove("hidden");
    }
    setRecordingStatus("浏览器录音已完成，提交任务时会优先使用这段录音。");
    setRecordingControls({isRecording: false, hasRecording: true});
    stopRecordingTracks();
  };
  mediaRecorder.onerror = (event) => {
    setRecordingStatus(`录音失败：${event.error?.message || "未知错误"}`);
    setRecordingControls({isRecording: false, hasRecording: false});
    stopRecordingTracks();
  };

  mediaRecorder.start();
  setRecordingStatus("录音中...再次点击“停止录音”后即可提交任务。");
  setRecordingControls({isRecording: true, hasRecording: false});
}

function stopBrowserRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}

async function loadSessions() {
  const select = document.getElementById("session-select");
  if (!select) {
    return;
  }
  const sessions = await fetchJson("/api/v1/sessions");
  select.replaceChildren(el("option", {text: "创建新会话", attrs: {value: ""}}));
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = `${session.title} (${session.turn_count})`;
    select.appendChild(option);
  }
}

function streamJob(jobId) {
  const eventSource = new EventSource(`/api/v1/jobs/${jobId}/events`);
  eventSource.onmessage = (event) => {
    const snapshot = JSON.parse(event.data);
    renderJobStatus(snapshot);
    renderConversation(snapshot);
    const status = snapshot.job?.status;
    if (status === "completed" || status === "failed") {
      eventSource.close();
      loadSessions().catch(() => {});
      loadHistory().catch(() => {});
      loadArtifacts().catch(() => {});
    }
  };
  eventSource.onerror = () => {
    eventSource.close();
  };
}

function buildAssistantPayload(uploadArtifactId = null) {
  const textInput = document.getElementById("text-input");
  const sessionSelect = document.getElementById("session-select");
  const sessionTitle = document.getElementById("session-title");
  const useTts = document.getElementById("use-tts");

  return {
    session_id: sessionSelect?.value || null,
    title: sessionTitle?.value || null,
    text_input: textInput?.value || null,
    upload_artifact_id: uploadArtifactId,
    use_tts: Boolean(useTts?.checked),
  };
}

async function uploadSelectedAudio() {
  const fileInput = document.getElementById("audio-input");
  const file = recordedAudioFile || fileInput?.files?.[0];
  if (!file) {
    return null;
  }

  renderStatusMessage("正在上传音频...");
  const formData = new FormData();
  formData.append("file", file);
  const uploadResult = await fetchJson("/api/v1/audio/upload", {
    method: "POST",
    body: formData,
  });
  return uploadResult.artifact.id;
}

async function submitAssistantPayload(payload) {
  const snapshot = await fetchJson("/api/v1/assistant/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  renderJobStatus(snapshot);
  renderConversation(snapshot);
  streamJob(snapshot.job.id);
}

async function submitAssistantForm(event) {
  event.preventDefault();
  renderStatusMessage("正在提交任务...");

  const uploadArtifactId = await uploadSelectedAudio();
  await submitAssistantPayload(buildAssistantPayload(uploadArtifactId));
}

function setPiRecordingControls(isRecording) {
  const piButton = document.getElementById("pi-record-submit");
  const submitButton = document.querySelector("#assistant-form button[type='submit']");
  if (piButton) {
    piButton.disabled = isRecording;
  }
  if (submitButton) {
    submitButton.disabled = isRecording;
  }
  setRecordingControls({isRecording: false, hasRecording: Boolean(recordedAudioFile)});
}

async function recordPiAndSubmit() {
  const durationSeconds = 6;
  setPiRecordingControls(true);
  renderStatusMessage(`Pi5 正在录音 ${durationSeconds} 秒...`);
  setRecordingStatus(`Pi5 USB 麦克风录音中，请现在讲话，${durationSeconds} 秒后会自动提交。`);
  try {
    const recordResult = await fetchJson("/api/v1/audio/record", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({duration_seconds: durationSeconds}),
    });
    setRecordingStatus("Pi5 录音已完成，正在识别并回复。");
    await submitAssistantPayload(buildAssistantPayload(recordResult.artifact.id));
  } finally {
    setPiRecordingControls(false);
  }
}

async function loadHistory() {
  const container = document.getElementById("history-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(emptyState("正在加载会话..."));
  const sessions = await fetchJson("/api/v1/sessions");
  const details = [];
  for (const session of sessions.slice(0, 10)) {
    const detail = await fetchJson(`/api/v1/sessions/${session.id}`);
    details.push(detail);
  }
  renderHistory(details);
}

async function loadArtifacts() {
  const container = document.getElementById("artifacts-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(emptyState("正在加载产物..."));
  const artifacts = await fetchJson("/api/v1/artifacts");
  renderArtifacts(artifacts);
}

async function loadSettings() {
  const container = document.getElementById("settings-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(emptyState("正在加载配置..."));
  const settings = await fetchJson("/api/v1/settings");
  renderSettings(settings);
}

async function loadHealth() {
  const container = document.getElementById("health-output");
  if (!container) {
    return;
  }
  clearNode(container);
  container.appendChild(emptyState("正在加载健康状态..."));
  const health = await fetchJson("/api/v1/health");
  renderHealth(health);
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  if (page === "assistant") {
    loadSessions().catch((error) => renderError("job-status", error));
    renderJobStatus(null);
    renderConversation(null);
    setRecordingControls({isRecording: false, hasRecording: false});
    document.getElementById("assistant-form")?.addEventListener("submit", (event) => {
      submitAssistantForm(event).catch((error) => {
        renderStatusMessage(String(error), "danger");
      });
    });
    document.getElementById("record-start")?.addEventListener("click", () => {
      startBrowserRecording().catch((error) => setRecordingStatus(`录音失败：${String(error)}`));
    });
    document.getElementById("pi-record-submit")?.addEventListener("click", () => {
      recordPiAndSubmit().catch((error) => {
        renderStatusMessage(String(error), "danger");
        setRecordingStatus(`Pi5 录音失败：${String(error)}`);
      });
    });
    document.getElementById("record-stop")?.addEventListener("click", () => {
      stopBrowserRecording();
    });
    document.getElementById("record-clear")?.addEventListener("click", () => {
      resetRecordedAudio();
    });
  }
  if (page === "history") {
    loadHistory().catch((error) => renderError("history-output", error));
  }
  if (page === "artifacts") {
    loadArtifacts().catch((error) => renderError("artifacts-output", error));
  }
  if (page === "settings") {
    loadSettings().catch((error) => renderError("settings-output", error));
  }
  if (page === "health") {
    loadHealth().catch((error) => renderError("health-output", error));
  }
});
