export function fmt(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export function safeJson(obj) {
  try {
    return JSON.stringify(obj || {}, null, 2);
  } catch {
    return "{}";
  }
}

export function statusBadge(state) {
  if (!state) return { cls: "idle", text: "Idle" };
  if (state.running) return { cls: "running", text: "Running" };
  if (state.exit_code === 0) return { cls: "ok", text: "Completed" };
  if (state.exit_code === null || state.exit_code === undefined) return { cls: "idle", text: "Idle" };
  return { cls: "fail", text: "Failed" };
}

export function highlightLogLine(line) {
  const upper = (line || "").toUpperCase();
  if (upper.includes("[ ERROR]") || upper.includes(" ERROR ") || upper.includes("TRACEBACK")) return "err";
  if (upper.includes("[ WARNING]") || upper.includes(" WARNING ")) return "warn";
  return "";
}

export function buildTree(paths) {
  const root = { name: "", path: "", children: new Map(), files: [] };
  for (const p of paths || []) {
    const parts = String(p).split("/");
    let node = root;
    let accum = "";
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      accum = accum ? `${accum}/${part}` : part;
      const isLast = i === parts.length - 1;
      if (isLast) {
        node.files.push({ name: part, path: accum });
      } else {
        if (!node.children.has(part)) {
          node.children.set(part, { name: part, path: accum, children: new Map(), files: [] });
        }
        node = node.children.get(part);
      }
    }
  }
  return root;
}
