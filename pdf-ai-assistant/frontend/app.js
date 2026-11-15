const $ = (id) => document.getElementById(id);
const state = { docId: null, docName: "", pages: 0, busy: false, hasSummary: false, summary: null };

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
  if (!res.ok) throw new Error((data && data.detail) || "Request failed (" + res.status + ")");
  return data;
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

async function poll(jobId, onProgress) {
  for (;;) {
    const j = await api("/jobs/" + jobId);
    onProgress(j);
    if (j.status === "done") return j.result;
    if (j.status === "error") throw new Error(j.error);
    await new Promise((r) => setTimeout(r, 900));
  }
}

function pageValue() {
  const v = parseInt($("page").value, 10);
  return Number.isFinite(v) && v > 0 ? v : null;
}

function setBusy(b) {
  state.busy = b;
  const ready = !!state.docId && !b;
  $("sum-btn").disabled = !ready;
  $("q").disabled = !ready;
  $("send").disabled = !ready;
  $("page").disabled = !state.docId || b;
  $("pick").disabled = b;
  $("download-pdf").disabled = !state.summary || b;
  $("download-docx").disabled = !state.summary || b;
}

function setProgress(f, msg) {
  $("progress").hidden = false;
  $("bar").style.width = Math.round(f * 100) + "%";
  $("progress-msg").textContent = msg + " (" + Math.round(f * 100) + "%)";
}

function updateSumButton() {
  const p = pageValue();
  $("sum-btn").textContent = p ? "Summarize page " + p : state.hasSummary ? "Summarize again" : "Summarize document";
}

/* page coverage strip: shows which pages the model actually read */
function drawCoverage(read, skipped, label) {
  const readSet = new Set(read || []);
  const skipSet = new Set([
    ...(skipped?.references || []),
    ...(skipped?.empty || []),
  ]);
  const cells = $("cells");
  cells.textContent = "";
  for (let n = 1; n <= state.pages; n++) {
    const c = document.createElement("button");
    c.type = "button";
    c.className = "cell" + (readSet.has(n) ? " read" : skipSet.has(n) ? " skip" : "");
    c.title = "Page " + n;
    c.setAttribute("aria-label", "Page " + n + (readSet.has(n) ? ", read" : skipSet.has(n) ? ", skipped" : ", not read"));
    c.onclick = () => { $("page").value = n; updateSumButton(); $("page").focus(); };
    cells.appendChild(c);
  }
  $("cov-text").textContent = label;
  $("coverage").hidden = false;
}

function renderSummary(r) {
  state.summary = r;
  $("sum-empty").hidden = true;
  const s = r.stats || {};
  const sk = { references: [], empty: [], ...(r.pages_skipped || {}) };
  const parts = ["Read " + r.pages_read.length + " of " + r.pages_total + " pages."];
  if (sk.references.length) parts.push(sk.references.length + " reference page(s) skipped.");
  if (sk.empty.length) parts.push(sk.empty.length + " empty or image-only page(s) skipped.");
  let textInfo;
  if (s.summary_source === "full_text") {
    textInfo = "Full text from all readable pages was sent to the model.";
  } else if (s.summary_source === "extractive_digest") {
    textInfo = "The text was condensed by " + s.reduction_percent + "% before sending; all readable pages are included.";
  } else {
    textInfo = "This is an older cached summary. Click Summarize again to use the updated full-text mode for small PDFs.";
  }
  parts.push(s.model_calls + " model call(s). " + textInfo);
  $("stats").textContent = parts.join(" ");
  const box = $("topics");
  box.textContent = "";
  for (const t of r.topics) {
    const div = document.createElement("div");
    div.className = "topic";
    const h = document.createElement("h3");
    const name = document.createElement("span");
    name.textContent = t.topic;
    h.appendChild(name);
    if (t.pages && t.pages.length) {
      const pg = document.createElement("span");
      pg.className = "pg";
      pg.textContent = "p. " + t.pages.join(", ");
      h.appendChild(pg);
    }
    const ul = document.createElement("ul");
    for (const p of t.points) {
      const li = document.createElement("li");
      li.textContent = p;
      ul.appendChild(li);
    }
    div.append(h, ul);
    box.appendChild(div);
  }
  drawCoverage(r.pages_read, sk, r.pages_read.length + " of " + r.pages_total + " pages went into this summary");
}

async function downloadSummary(format) {
  const button = $("download-" + format);
  button.disabled = true;
  try {
    const res = await fetch("/api/docs/" + encodeURIComponent(state.docId) +
      "/summary/export?format=" + format, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.summary),
      });
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
      throw new Error((data && data.detail) || "Download failed (" + res.status + ")");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const disposition = res.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    link.download = filename
      ? decodeURIComponent(filename[1])
      : state.docName.replace(/\.pdf$/i, "") + "-summary." + format;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    $("sum-status").textContent = e.message;
  } finally {
    button.disabled = !state.summary || state.busy;
  }
}

function showTab(name) {
  for (const t of ["summary", "ask"]) {
    $("tab-" + t).setAttribute("aria-selected", String(t === name));
    $("panel-" + t).hidden = t !== name;
  }
}
$("tab-summary").onclick = () => showTab("summary");
$("tab-ask").onclick = () => showTab("ask");
$("page").addEventListener("input", updateSumButton);
$("pick").onclick = () => $("file").click();

/* upload: the script behind the button runs on the server for every file */
$("file").addEventListener("change", async () => {
  const f = $("file").files[0];
  if (!f) return;
  state.docId = null;
  state.docName = "";
  state.hasSummary = false;
  state.summary = null;
  $("doc").hidden = true;
  $("page-filter").hidden = true;
  $("coverage").hidden = true;
  $("topics").textContent = "";
  $("stats").textContent = "";
  $("sum-empty").hidden = false;
  $("chat").innerHTML = '<p class="empty">Upload a PDF to start asking.</p>';
  setBusy(true);
  setProgress(0, "Uploading");
  try {
    const fd = new FormData();
    fd.append("file", f);
    const up = await api("/upload", { method: "POST", body: fd });
    const meta = up.job_id ? await poll(up.job_id, (j) => setProgress(j.progress, j.message)) : up;
    state.docId = meta.doc_id;
    state.docName = meta.name;
    state.pages = meta.pages;
    $("page-filter").hidden = false;
    $("doc-name").textContent = meta.name;
    $("doc-pages").textContent = meta.pages + " pages";
    $("doc").hidden = false;
    $("page").max = meta.pages;
    $("chat").textContent = "";
    if (meta.has_summary) {
      const d = await api("/docs/" + meta.doc_id);
      state.hasSummary = true;
      renderSummary(d.summary);
    }
    updateSumButton();
  } catch (e) {
    $("sum-status").textContent = e.message;
  } finally {
    $("progress").hidden = true;
    $("file").value = "";
    setBusy(false);
  }
});

async function runSummary() {
  const page = pageValue();
  setBusy(true);
  $("sum-status").textContent = "Starting";
  try {
    const r = await post("/docs/" + state.docId + "/summary", { page, refresh: state.hasSummary && !page });
    const result = r.job_id
      ? await poll(r.job_id, (j) => { $("sum-status").textContent = j.message + " (" + Math.round(j.progress * 100) + "%)"; })
      : r.result;
    if (!page) state.hasSummary = true;
    renderSummary(result);
    $("sum-status").textContent = "";
  } catch (e) {
    $("sum-status").textContent = e.message;
  } finally {
    setBusy(false);
    updateSumButton();
  }
}
$("sum-btn").onclick = runSummary;
$("download-pdf").onclick = () => downloadSummary("pdf");
$("download-docx").onclick = () => downloadSummary("docx");

/* chat */
function addMsg(cls, text) {
  if ($("chat").querySelector(".empty")) $("chat").textContent = "";
  const m = document.createElement("div");
  m.className = "msg " + cls;
  m.textContent = text;
  $("chat").appendChild(m);
  $("chat").scrollTop = $("chat").scrollHeight;
  return m;
}

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("q").value.trim();
  if (!q || !state.docId || state.busy) return;
  $("q").value = "";
  addMsg("user", q);
  const bot = addMsg("bot", "Thinking...");
  setBusy(true);
  try {
    const r = await post("/docs/" + state.docId + "/ask", { question: q, page: pageValue() });
    bot.textContent = r.answer;
    if (r.pages && r.pages.length) {
      const src = document.createElement("span");
      src.className = "src";
      src.textContent = "Pages read: " + r.pages.join(", ");
      bot.appendChild(src);
      drawCoverage(r.pages, null, r.pages.length + " of " + state.pages + " pages were read for this answer");
    }
    if (r.suggest_summary) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-black";
      b.textContent = "Summarize now";
      b.onclick = () => { showTab("summary"); runSummary(); };
      bot.appendChild(b);
    }
  } catch (e) {
    bot.className = "msg err";
    bot.textContent = e.message;
  } finally {
    setBusy(false);
    $("q").focus();
  }
});

api("/health").then((h) => {
  if (!h.llm_configured) {
    $("banner").textContent = "OPENROUTER_API_KEY is missing. Add it to .env and restart the server.";
    $("banner").hidden = false;
  }
}).catch(() => {});
