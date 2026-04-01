function normalizeStatus(status) {
  const s = String(status || "").toLowerCase();
  if (s === "done" || s === "completed" || s === "complete" || s === "success") return "success";
  if (s === "active" || s === "running" || s === "in_progress") return "running";
  if (s === "error" || s === "failed" || s === "fail") return "failed";
  return "pending";
}

export function PipelineStepper({ steps }) {
  const h = window.React.createElement;
  const icons = {
    upload: "📤",
    parse: "⚙️",
    dom: "🌐",
    rag: "🧠",
    generate: "🧩",
    execute: "▶️",
  };
  const items = steps && steps.length ? steps : [
    { key: "upload", label: "Upload", status: "pending" },
    { key: "parse", label: "Parse", status: "pending" },
    { key: "dom", label: "DOM", status: "pending" },
    { key: "rag", label: "RAG", status: "pending" },
    { key: "generate", label: "Generate", status: "pending" },
    { key: "execute", label: "Execute", status: "pending" },
  ];

  return h(
    "div",
    { className: "pipelineStepper" },
    items.map((step, idx) => {
      const ns = normalizeStatus(step.status);
      const isLast = idx === items.length - 1;
      return h(
        "div",
        { key: step.key, className: `pipeStep ${ns}` },
        h("div", { className: "pipeTop" },
          h(
            "div",
            { className: "pipeCircle", "aria-hidden": true },
            h("span", { className: "pipeIcon" }, icons[step.key] || "")
          ),
          !isLast ? h("div", { className: "pipeLine", "aria-hidden": true }) : null
        ),
        h("div", { className: "pipeLabel" }, step.label)
      );
    })
  );
}

// Backwards-compatible export
export function Stepper(props) {
  return PipelineStepper(props);
}
