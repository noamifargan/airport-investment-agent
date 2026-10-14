"use strict";

const $ = (sel) => document.querySelector(sel);
const thread = $("#thread"), composer = $("#composer"), input = $("#composer-input"), askBtn = $("#ask-btn");
const heroCopy = $(".hero-copy"), main = $("#main");
let sessionId = null, busy = false;

const TOOL_NAMES = {
  rank_airports: "Rank airports", compare_airports: "Compare airports", airport_profile: "Airport profile",
  route_mix: "Route mix", unmet_demand: "Unmet demand", live_status: "FAA live status", methodology: "Scoring method",
};

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/* ---------- small, safe markdown renderer (input is escaped first) ---------- */
function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*(?!\s)([^*]+?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(https?:\/\/[^\s)<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function md(src) {
  let html = "";
  esc(src).split("```").forEach((part, i) => {
    if (i % 2) { html += `<pre><code>${part.replace(/^[a-z]*\n/, "")}</code></pre>`; return; }
    let para = [], list = null, table = [];
    const flushPara = () => { if (para.length) { html += `<p>${inline(para.join(" "))}</p>`; para = []; } };
    const flushList = () => {
      if (!list) return;
      html += `<${list.tag}>` + list.items.map((it) =>
        `<li>${inline(it.text)}${it.sub.length ? `<ul>${it.sub.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>` : ""}</li>`
      ).join("") + `</${list.tag}>`;
      list = null;
    };
    const flushTable = () => {
      if (!table.length) return;
      const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r))
        .map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
      html += '<div class="table"><table>' + rows.map((r, k) =>
        `<tr>${r.map((c) => (k ? `<td>${c}</td>` : `<th>${c}</th>`)).join("")}</tr>`).join("") + "</table></div>";
      table = [];
    };
    for (const raw of part.split("\n")) {
      const line = raw.replace(/\s+$/, "");
      let m;
      if (!line.trim()) { flushPara(); flushTable(); continue; }
      if (/^\s*\|/.test(line)) { flushPara(); flushList(); table.push(line.trim()); continue; }
      flushTable();
      if (/^-{3,}$/.test(line.trim())) { flushPara(); flushList(); html += "<hr>"; continue; }
      if ((m = line.match(/^#{1,4}\s+(.*)/))) { flushPara(); flushList(); html += `<h4>${inline(m[1])}</h4>`; continue; }
      if ((m = line.match(/^(\s*)([-*•]|\d+[.)])\s+(.*)/))) {
        flushPara();
        const indent = m[1].replace(/\t/g, "    ").length, tag = /\d/.test(m[2]) ? "ol" : "ul";
        if (indent >= 2 && list && list.items.length) { list.items[list.items.length - 1].sub.push(m[3]); continue; }
        if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
        list.items.push({ text: m[3], sub: [] });
        continue;
      }
      if (list && /^\s{2,}/.test(raw)) { list.items[list.items.length - 1].text += " " + line.trim(); continue; }
      flushList();
      para.push(line.trim());
    }
    flushPara(); flushList(); flushTable();
  });
  return html;
}

/* ---------- conversation ---------- */
function startChatting() {
  if (document.body.classList.contains("chatting")) return;
  document.body.classList.add("chatting");
  main.appendChild(composer);           // dock the composer under the thread
  $("#new-chat").hidden = false;
}

function resetChat() {
  if (busy) return;
  fetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ message: "", session_id: sessionId }) }).catch(() => {});
  sessionId = null;
  thread.innerHTML = "";
  document.body.classList.remove("chatting");
  heroCopy.appendChild(composer);
  $("#new-chat").hidden = true;
  window.scrollTo({ top: 0 });
  input.focus();
}

function argText(args) {
  return Object.entries(args || {}).map(([k, v]) => `${k.replace(/_/g, " ")} ${Array.isArray(v) ? v.join(", ") : v}`).join("; ") || "no inputs";
}

function evidenceHtml(ev, seconds) {
  const list = (items) => `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const n = (ev.sources || []).length;
  return `<summary><span class="label">Sources and assumptions${n ? ` (${n} datasets)` : ""}</span>` +
         `<span class="time">Answered in ${seconds} s</span></summary>` +
         (n ? `<h5>Data sources</h5>${list(ev.sources)}` : "") +
         ((ev.assumptions || []).length ? `<h5>Assumptions and uncertainty</h5>${list(ev.assumptions)}` : "");
}

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true; askBtn.disabled = true;
  startChatting();

  const turn = document.createElement("article");
  turn.className = "turn";
  turn.innerHTML = `<h3 class="q">${esc(question)}</h3><p class="understood" hidden></p><div class="strips"></div>` +
                   `<div class="progress">Reading the question…</div><div class="answer"></div>`;
  thread.appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "start" });
  const understood = turn.querySelector(".understood"), strips = turn.querySelector(".strips");
  const progress = turn.querySelector(".progress"), answerEl = turn.querySelector(".answer");
  const started = performance.now();
  let answer = "";

  try {
    const resp = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
                                            body: JSON.stringify({ message: question, session_id: sessionId }) });
    if (!resp.ok) throw new Error(`server answered ${resp.status}`);
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === "session") sessionId = ev.id;
        else if (ev.type === "status") {
          if (ev.text.startsWith("Resolved:")) {
            understood.hidden = false;
            understood.textContent = "Understood as " + ev.text.replace(/^Resolved:\s*/, "")
              .replace(/^airports\s+/, "").replace(/;\s*airports\s+/g, "; ");
            progress.textContent = "Choosing the analysis…";
          } else {
            understood.hidden = false;
            understood.textContent += (understood.textContent ? " " : "") + ev.text;
          }
        } else if (ev.type === "tool") {
          const strip = document.createElement("div");
          strip.className = "strip" + (ev.chosen_by === "router" ? " router" : "");
          strip.innerHTML = `<span title="${esc(ev.name || "")}">${esc(TOOL_NAMES[ev.name] || ev.name || "Analysis")}</span>` +
                            `<span>${esc(argText(ev.args))}</span>` +
                            `<span class="by">${ev.chosen_by === "router" ? "Chosen by the fallback router" : "Chosen by the model"}</span>`;
          strips.appendChild(strip);
          progress.textContent = "Pulling the data and writing the answer…";
        } else if (ev.type === "token") {
          progress.hidden = true;
          answer += ev.text;
          answerEl.innerHTML = md(answer);
        } else if (ev.type === "footer") {
          const details = document.createElement("details");
          details.className = "evidence";
          details.innerHTML = evidenceHtml(ev, Math.round((performance.now() - started) / 1000));
          turn.appendChild(details);
        } else if (ev.type === "error") {
          answerEl.insertAdjacentHTML("beforeend", `<p class="error">The agent stopped with an error: ${esc(ev.text)}</p>`);
        }
      }
    }
  } catch (err) {
    answerEl.insertAdjacentHTML("beforeend",
      `<p class="error">Couldn't reach the agent (${esc(err.message)}). Check that the server and Ollama are running, then ask again.</p>`);
  } finally {
    progress.hidden = true;
    busy = false; askBtn.disabled = false;
    input.focus();
  }
}

/* ---------- voice input: record in the browser, transcribe with local Whisper, then ask ---------- */
const micBtn = $("#mic-btn"), micTime = $("#mic-time"), voiceStatus = $("#voice-status");
const MAX_RECORDING_MS = 60000;
let recorder = null, recStream = null, recChunks = [], recStart = 0, recTimer = null, recCancelled = false;

function setVoice(state, message) {
  micBtn.dataset.state = state;
  const label = state === "recording" ? "Stop recording and ask" : "Ask by voice";
  micBtn.setAttribute("aria-label", label);
  micBtn.title = label;
  micTime.hidden = state !== "recording";
  voiceStatus.hidden = !message;
  voiceStatus.textContent = message || "";
}

async function startRecording() {
  if (busy) { setVoice("idle", "Wait for the current answer to finish, then ask your next question."); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setVoice("idle", "Voice input needs microphone access, which browsers only allow on localhost or https pages.");
    return;
  }
  try {
    recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    setVoice("idle", err.name === "NotAllowedError"
      ? "Microphone access is blocked. Allow it in the browser's site settings, or type your question."
      : "No microphone was found. Type your question instead.");
    return;
  }
  recChunks = [];
  recCancelled = false;
  recorder = new MediaRecorder(recStream);
  recorder.ondataavailable = (e) => { if (e.data.size) recChunks.push(e.data); };
  recorder.onstop = sendRecording;
  recorder.start();
  recStart = Date.now();
  micTime.textContent = "0:00";
  recTimer = setInterval(() => {
    const secs = Math.floor((Date.now() - recStart) / 1000);
    micTime.textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
    if (Date.now() - recStart > MAX_RECORDING_MS) stopRecording();
  }, 250);
  setVoice("recording", "Listening. Click the microphone again when you've finished, or press Esc to cancel.");
}

function stopRecording(cancel = false) {
  recCancelled = cancel;
  clearInterval(recTimer);
  if (recorder && recorder.state !== "inactive") recorder.stop();
  recStream?.getTracks().forEach((t) => t.stop());
}

async function sendRecording() {
  const type = recorder?.mimeType || "audio/webm";
  const blob = new Blob(recChunks, { type });
  recorder = null;
  if (recCancelled) { setVoice("idle", ""); return; }
  if (blob.size < 2000) { setVoice("idle", "That recording was too short. Click the microphone and ask your question."); return; }
  setVoice("working", "Turning your question into text…");
  try {
    const resp = await fetch("/api/transcribe", { method: "POST", headers: { "Content-Type": type }, body: blob });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `server answered ${resp.status}`);
    const text = (data.text || "").trim();
    if (!text) { setVoice("idle", "No speech was detected. Try again a little closer to the microphone."); return; }
    setVoice("idle", "");
    ask(text);
  } catch (err) {
    setVoice("idle", `The recording couldn't be transcribed (${err.message}). Try again or type your question.`);
  }
}

micBtn.addEventListener("click", () => {
  if (micBtn.dataset.state === "recording") stopRecording();
  else if (micBtn.dataset.state === "idle") startRecording();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && micBtn.dataset.state === "recording") stopRecording(true);
});

/* ---------- side panels ---------- */
async function loadMethod() {
  try {
    const m = await (await fetch("/api/methodology")).json();
    const render = (rows) => {
      const max = Math.max(...rows.map((r) => r.weight));
      return rows.map((r) => `<li title="${esc(r.scale)}"><span>${esc(r.kpi)}</span><span class="w">${Math.round(r.weight * 100)}%</span>` +
                             `<span class="bar"><i style="width:${(r.weight / max) * 100}%"></i></span></li>`).join("");
    };
    $("#weights-te").innerHTML = render(m.terminal_expansion);
    $("#weights-cg").innerHTML = render(m.congestion);
  } catch { /* the panel simply stays empty */ }
}

async function loadInfo() {
  try { $("#model-name").textContent = (await (await fetch("/api/info")).json()).model; } catch { /* keep default */ }
}

/* ---------- wiring ---------- */
composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (q && !busy) { input.value = ""; autosize(); ask(q); }
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); composer.requestSubmit(); }
});
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight + 2, 200) + "px"; }
input.addEventListener("input", autosize);
document.querySelectorAll(".ask-example").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q || b.textContent)));
$("#new-chat").addEventListener("click", resetChat);

// The full placeholder doesn't fit the narrow question bar on phones.
const narrow = window.matchMedia("(max-width: 640px)");
const setPlaceholder = () => { input.placeholder = narrow.matches ? "Ask about an airport…" : "Ask about an airport, a city or a region"; };
narrow.addEventListener("change", setPlaceholder);
setPlaceholder();

loadInfo(); loadMethod();
