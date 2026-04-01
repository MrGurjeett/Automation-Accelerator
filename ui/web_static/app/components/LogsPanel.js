import { getLogs } from "../api.js";
import { highlightLogLine } from "../utils.js";

export function LogsPanel({ running, toast }) {
  const React = window.React;
  const h = React.createElement;
  const [lines, setLines] = React.useState([]);
  const [logLines, setLogLines] = React.useState(300);
  const [loading, setLoading] = React.useState(false);
  const termRef = React.useRef(null);
  const followRef = React.useRef(true);

  async function refresh({ silent } = {}) {
    const isSilent = !!silent;
    if (!isSilent) setLoading(true);
    try {
      const data = await getLogs(logLines);
      setLines(data.lines || []);
    } catch (e) {
      toast("error", e.message);
    } finally {
      if (!isSilent) setLoading(false);
    }
  }

  React.useEffect(() => {
    refresh({ silent: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logLines]);

  React.useEffect(() => {
    const id = setInterval(() => {
      refresh({ silent: true });
    }, running ? 900 : 1800);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, logLines]);

  React.useEffect(() => {
    // Auto-scroll only when user is near the bottom.
    try {
      const el = termRef.current;
      if (!el) return;
      if (!followRef.current) return;
      el.scrollTop = el.scrollHeight;
    } catch {
      // ignore
    }
  }, [lines]);

  React.useEffect(() => {
    // Track whether the user has scrolled away from the bottom.
    const el = termRef.current;
    if (!el) return;
    const onScroll = () => {
      try {
        const threshold = 40;
        const distanceFromBottom = el.scrollHeight - (el.scrollTop + el.clientHeight);
        followRef.current = distanceFromBottom <= threshold;
      } catch {
        // ignore
      }
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    // initialize
    onScroll();
    return () => {
      try {
        el.removeEventListener("scroll", onScroll);
      } catch {
        // ignore
      }
    };
  }, []);

  return h(
    "div",
    {
      className:
        "card",
    },
    h(
      "div",
      { className: "flex items-center justify-between gap-4" },
      h("div", { className: "text-base font-semibold text-gray-900" }, "Logs"),
      h(
        "div",
        { className: "flex items-center gap-2" },
        h("div", { className: "text-xs text-gray-500" }, "Lines"),
        h("input", {
          className: "w-24 border border-gray-200 rounded-lg px-3 py-2",
          type: "number",
          min: 50,
          max: 2000,
          value: logLines,
          onChange: (e) => setLogLines(parseInt(e.target.value || "300", 10)),
        }),
        h(
          "button",
          {
            className: "btn secondary",
            onClick: () => refresh({ silent: false }),
            disabled: loading,
          },
          loading ? "Refreshing…" : "Refresh"
        )
      )
    ),
    h(
      "div",
      {
        className:
          "mt-4 bg-black text-green-400 rounded-lg border border-gray-900 p-4 h-96 overflow-auto font-mono text-xs whitespace-pre leading-relaxed",
        ref: termRef,
      },
      (lines || []).map((ln, idx) =>
        h(
          "div",
          { key: idx, className: `logLine ${highlightLogLine(ln)}` },
          ln
        )
      )
    )
  );
}

// Alias for requested component naming
export function LogsViewer(props) {
  return LogsPanel(props);
}
