const $ = (id) => document.getElementById(id);

function fmt(n) {
  if (n === null || n === undefined) return "";
  if (typeof n === "number") return n.toLocaleString();
  return String(n);
}

function renderKVs(el, obj, title) {
  const keys = Object.keys(obj || {}).sort();
  if (!keys.length) {
    el.innerHTML = `<div class="hint">${title}: (none)</div>`;
    return;
  }
  const rows = keys.map((k) => {
    const v = obj[k];
    return `<div class="kv"><div class="k">${k}</div><div class="v">${fmt(v)}</div></div>`;
  });
  el.innerHTML = rows.join("");
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

function collectEnv() {
  const keys = ["BASE_URL", "UI_USERNAME", "UI_PASSWORD", "DOM_BASE_URL", "DOM_USERNAME", "DOM_PASSWORD"];
  const env = {};
  for (const k of keys) {
    const v = $(k).value.trim();
    if (v) env[k] = v;
  }
  return env;
}

async function refreshStatus() {
  const status = await api("/api/status");
  const state = status.state || {};

  const running = !!state.running;
  $("runState").textContent = running ? `Running (${state.mode || ""})` : `Idle${state.exit_code !== null && state.exit_code !== undefined ? " (exit " + state.exit_code + ")" : ""}`;
  $("start").disabled = running;
  $("stop").disabled = !running;

  $("cmd").textContent = (state.command || []).join(" ");

  renderKVs($("stats"), status.latest_stats || {}, "Latest stats");
  renderKVs($("cumulative"), status.cumulative_stats || {}, "Cumulative");

  $("latestRun").textContent = JSON.stringify(status.latest_run || {}, null, 2);

  // Refresh logs (cheap tail)
  const lines = parseInt($("logLines").value || "200", 10);
  const logs = await api(`/api/logs?lines=${lines}`);
  $("logs").textContent = (logs.lines || []).join("\n");
}

async function startRun() {
  const body = {
    mode: $("mode").value,
    force: $("force").checked,
    scan: $("scan").checked,
    env: collectEnv(),
  };
  await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  await refreshStatus();
}

async function stopRun() {
  await api("/api/stop", { method: "POST" });
  await refreshStatus();
}

async function listFiles() {
  const root = $("fileRoot").value;
  const data = await api(`/api/files?root=${encodeURIComponent(root)}`);
  const list = $("fileList");
  list.innerHTML = "";
  for (const f of data.files || []) {
    const li = document.createElement("li");
    li.textContent = `${f.path} (${fmt(f.size)} bytes)`;
    li.dataset.path = f.path;
    li.onclick = async () => {
      const file = await api(`/api/file?path=${encodeURIComponent(f.path)}`);
      $("filePath").textContent = file.path;
      $("fileContent").textContent = file.content || "";
    };
    list.appendChild(li);
  }
}

$("start").onclick = () => startRun().catch((e) => alert(e.message));
$("stop").onclick = () => stopRun().catch((e) => alert(e.message));
$("refresh").onclick = () => refreshStatus().catch((e) => alert(e.message));
$("listFiles").onclick = () => listFiles().catch((e) => alert(e.message));

// Poll status (simple)
setInterval(() => {
  refreshStatus().catch(() => {});
}, 1500);

refreshStatus().catch(() => {});
