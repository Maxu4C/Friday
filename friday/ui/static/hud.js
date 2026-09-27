// FRIDAY HUD client: renders FRIDAY's state and sends the user's actions over a WebSocket.
// Every piece of text coming from FRIDAY or Claude is escaped before being displayed.
"use strict";

const token = new URLSearchParams(location.search).get("t") || "";
const $ = (id) => document.getElementById(id);
const STATE_LABELS = { idle: "En veille", listening: "À l'écoute", thinking: "Réflexion", speaking: "Parole" };
const DISPLAY_BLOCK = /\[AFFICHER\][\s\S]*?(\[\/AFFICHER\]|$)/g;

let socket = null;
let retryDelay = 500;
let current = null; // FRIDAY message being streamed: { el, raw }
let muted = false;

// -- helpers -----------------------------------------------------------------------

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function inline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

// Small markdown renderer for [AFFICHER] blocks: code fences, headings, lists, inline code, bold.
function renderMarkdown(text) {
  const parts = String(text).split(/```/);
  let html = "";
  parts.forEach((part, index) => {
    if (index % 2 === 1) {
      const code = part.replace(/^[\w+-]*\n/, "");
      html += `<pre><code>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`;
      return;
    }
    let inList = false;
    for (const line of part.split("\n")) {
      const heading = line.match(/^(#{1,4})\s+(.*)$/);
      const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (item) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${inline(item[1])}</li>`;
        continue;
      }
      if (inList) { html += "</ul>"; inList = false; }
      if (heading) {
        const level = heading[1].length > 2 ? 4 : 3;
        html += `<h${level}>${inline(heading[2])}</h${level}>`;
      } else if (line.trim()) {
        html += `<p>${inline(line)}</p>`;
      }
    }
    if (inList) html += "</ul>";
  });
  return html;
}

function visible(raw) {
  return raw.replace(DISPLAY_BLOCK, " ").replace(/\[MODE_CODE\]/g, "").replace(/[ \t]+\n/g, "\n").trim();
}

function scrollToEnd(el) { el.scrollTop = el.scrollHeight; }

function addMessage(kind, text, extra = "") {
  const conversation = $("conversation");
  const el = document.createElement("div");
  el.className = `msg msg-${kind} ${extra}`.trim();
  el.textContent = text;
  conversation.appendChild(el);
  while (conversation.children.length > 200) conversation.removeChild(conversation.firstChild);
  scrollToEnd(conversation);
  return el;
}

function addAction(html, cls = "") {
  const list = $("actions");
  const li = document.createElement("li");
  li.className = cls;
  li.innerHTML = html;
  list.appendChild(li);
  while (list.children.length > 80) list.removeChild(list.firstChild);
  scrollToEnd(list);
}

function send(type, value = "") {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type, value }));
}

function setIndicator(id, state) {
  const el = $(id);
  el.classList.toggle("off", state === "off");
  el.classList.toggle("bad", state === "bad");
}

function button(label, onClick) {
  const b = document.createElement("button");
  b.className = "btn btn-small";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function finishStream() { current = null; }
function hideConfirm() { $("confirm").hidden = true; }

// -- rendering FRIDAY's messages -----------------------------------------------------

function renderSessions(msg) {
  const list = $("sessions");
  list.innerHTML = "";
  for (const r of msg.sessions) {
    const isCurrent = r.key === msg.session.key;
    const li = document.createElement("li");
    li.className = isCurrent ? "current" : "";
    const mode = r.mode === "claude_code" ? "Claude Code" : "Claude";
    const when = r.last_used.replace("T", " ");
    const summary = r.summary ? ` · ${escapeHtml(r.summary)}` : "";
    li.innerHTML = `<span class="s-name">${escapeHtml(r.name)}</span>
      <span class="s-meta">${mode} · ${escapeHtml(r.model)} · ${escapeHtml(when)}${summary}</span>
      <span class="s-actions"></span>`;
    const actions = li.querySelector(".s-actions");
    if (!isCurrent) {
      actions.appendChild(button("Reprendre", () => send("session_resume", r.name)));
    } else {
      actions.appendChild(button("Renommer", () => {
        const name = prompt("Nouveau nom de la session :", r.name);
        if (name && name.trim()) send("session_rename", name.trim());
      }));
    }
    actions.appendChild(button("Oublier", () => send("session_forget", r.name)));
    list.appendChild(li);
  }
}

const handlers = {
  snapshot(msg) {
    const s = msg.session;
    $("session-name").textContent = s.name;
    $("mode-select").value = s.mode;
    const models = $("model-select");
    models.innerHTML = "";
    models.appendChild(new Option(`Automatique (${s.model_label})`, "auto"));
    for (const m of msg.models) models.appendChild(new Option(m.label, m.alias));
    models.value = s.locked || "auto";
    const badge = $("model-badge");
    badge.textContent = s.locked ? "verrouillé" : "auto";
    badge.classList.toggle("locked", Boolean(s.locked));
    $("workspace").textContent = s.workspace || "—";
    $("workspace").title = s.workspace || "";
    renderSessions(msg);

    const usage = Object.entries(msg.usage).map(([label, n]) => `${escapeHtml(label)} : ${n}`).join(" · ");
    const names = { five_hour: "5 h", seven_day: "7 j" };
    const quota = Object.entries(msg.quota).map(([w, p]) => `${names[w] || escapeHtml(w)} ${p} %`).join(" · ");
    $("usage").innerHTML = `Requêtes aujourd'hui : ${usage || "aucune"}${quota ? `<br>Quota utilisé : ${quota}` : ""}`;

    const ind = msg.indicators;
    muted = ind.mic_muted;
    setIndicator("ind-mic", ind.microphone ? "on" : "off");
    setIndicator("ind-whisper", ind.whisper ? "on" : "off");
    setIndicator("ind-voice", ind.voice ? "on" : "off");
    $("mute").classList.toggle("muted", muted);
    $("mute").textContent = muted ? "Micro coupé" : "Micro";
    const triggers = [];
    if (ind.wake_word && !muted) triggers.push(`dites « ${ind.wake_word} »`);
    if (ind.hotkey) triggers.push(ind.hotkey);
    triggers.push("bouton Parler");
    $("wake-hint").textContent = `Pour parler : ${triggers.join(", ")}`;
    handlers.state({ state: msg.state });
  },
  state(msg) {
    document.body.dataset.state = msg.state;
    $("state-label").textContent = STATE_LABELS[msg.state] || msg.state;
  },
  user(msg) {
    finishStream();
    const el = addMessage("user", "");
    el.innerHTML = `<span class="via">${msg.spoken ? "voix" : "clavier"}</span>${escapeHtml(msg.text)}`;
  },
  delta(msg) {
    if (!current) current = { el: addMessage("friday", ""), raw: "" };
    current.raw += msg.text;
    current.el.textContent = visible(current.raw);
    scrollToEnd($("conversation"));
  },
  turn_done(msg) {
    if (current && !visible(current.raw)) current.el.remove();
    finishStream();
    hideConfirm();
    setIndicator("ind-claude", msg.error && msg.error !== "interrupted" ? "bad" : "on");
    for (const tool of msg.denied || []) addAction(`<span class="tool">refusé</span>${escapeHtml(tool)}`, "denied");
  },
  say(msg) { finishStream(); addMessage("friday", msg.text); },
  ask(msg) { finishStream(); addMessage("friday", msg.text, "msg-question"); },
  confirm(msg) {
    finishStream();
    addMessage("friday", msg.question, "msg-question");
    const box = $("confirm");
    box.hidden = false;
    box.classList.toggle("dangerous", msg.dangerous);
    $("confirm-question").textContent = msg.question;
    $("confirm-detail").textContent = msg.detail;
    const yes = $("confirm-yes");
    yes.textContent = msg.step === 2 ? "Oui, confirme" : "Oui";
    yes.dataset.answer = msg.step === 2 ? "oui, confirme" : "oui";
    yes.focus();
  },
  tool(msg) { addAction(`<span class="tool">${escapeHtml(msg.name)}</span>${escapeHtml(msg.detail)}`); },
  tool_error(msg) { addAction(`<span class="tool">échec</span>${escapeHtml(msg.summary)}`, "error"); },
  block(msg) {
    const display = $("display");
    const empty = display.querySelector(".empty");
    if (empty) empty.remove();
    const block = document.createElement("div");
    block.className = "block";
    block.innerHTML = renderMarkdown(msg.text);
    display.appendChild(block);
    while (display.children.length > 30) display.removeChild(display.firstChild);
    scrollToEnd(display);
  },
  stopped() { finishStream(); hideConfirm(); },
};

// -- connection ---------------------------------------------------------------------------

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(token)}`);
  socket.addEventListener("open", () => { retryDelay = 500; setIndicator("ind-link", "on"); });
  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    const handler = handlers[msg.type];
    if (handler) handler(msg);
  });
  socket.addEventListener("close", () => {
    setIndicator("ind-link", "bad");
    current = null;
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, 5000);
  });
}

// -- controls -----------------------------------------------------------------------------

$("text-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("text-input");
  const text = input.value.trim();
  if (text) send("text", text);
  input.value = "";
});
$("ptt").addEventListener("click", () => send("ptt"));
$("stop").addEventListener("click", () => send("stop"));
$("mute").addEventListener("click", () => send(muted ? "unmute" : "mute"));
$("mode-select").addEventListener("change", (e) => send("mode", e.target.value));
$("model-select").addEventListener("change", (e) => send("model", e.target.value));
$("session-new").addEventListener("click", () => {
  const name = prompt("Nom de la nouvelle session (laisser vide pour un nom automatique) :", "");
  if (name !== null) send("session_new", name.trim());
});
$("confirm-yes").addEventListener("click", (e) => { send("text", e.target.dataset.answer || "oui"); hideConfirm(); });
$("confirm-no").addEventListener("click", () => { send("text", "non"); hideConfirm(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") send("stop"); });

connect();
