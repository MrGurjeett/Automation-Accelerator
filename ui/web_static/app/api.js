export async function apiJson(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = (data && data.error) ? data.error : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export function getStatus() {
  return apiJson("/api/status");
}

export function getProgress() {
  return apiJson("/api/progress");
}

export function getLogs(lines = 200) {
  return apiJson(`/api/logs?lines=${encodeURIComponent(String(lines))}`);
}

export function startRun(body) {
  return apiJson("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

export function stopRun() {
  return apiJson("/api/stop", { method: "POST" });
}

export function listFiles(root) {
  return apiJson(`/api/files?root=${encodeURIComponent(root)}`);
}

export function readFile(path) {
  return apiJson(`/api/file?path=${encodeURIComponent(path)}`);
}

export function listRuns() {
  return apiJson("/api/runs");
}

export function getInputs() {
  return apiJson("/api/inputs");
}

export function clearOutput() {
  return apiJson("/api/clear_output", { method: "POST" });
}

export function uploadExcel({ filename, content_base64 }) {
  return apiJson("/api/upload_excel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content_base64 }),
  });
}
