import { getStatus, getProgress } from "./api.js";
import { fmt, statusBadge } from "./utils.js";
import { Sidebar } from "./components/Sidebar.js";
import { PipelineStepper } from "./components/Stepper.js";
import { RunControls } from "./components/RunControls.js";
import { LogsViewer } from "./components/LogsPanel.js";
import { ArtifactsViewer } from "./components/ArtifactsViewer.js";
import { RunHistory } from "./components/RunHistory.js";
import { AnalyticsPage } from "./components/AnalyticsPage.js";
import { Toasts } from "./components/Toast.js";

export function App() {
  const React = window.React;
  const h = React.createElement;

  const [page, setPage] = React.useState("run");
  const [status, setStatus] = React.useState({ state: {}, latest_run: {}, latest_stats: null, cumulative_stats: {} });
  const [progress, setProgress] = React.useState({ steps: [] });
  const [toasts, setToasts] = React.useState([]);
  const [loadedOnce, setLoadedOnce] = React.useState(false);

  function toast(kind, message) {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [{ id, kind, message }, ...prev].slice(0, 4));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }

  function dismissToast(id) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  async function refresh() {
    const s = await getStatus();
    try {
      // eslint-disable-next-line no-console
      console.log("Stats API response:", s);
    } catch {
      // ignore
    }
    setStatus(s);
    setLoadedOnce(true);
    const p = await getProgress().catch(() => ({ steps: [] }));
    setProgress(p);
  }

  function pickLatestStats(payload) {
    const a = payload && payload.latest_stats;
    // Backend may return { updated_at, stats: {...} }.
    if (a && typeof a === "object") {
      const inner = a.stats;
      if (inner && typeof inner === "object" && Object.keys(inner).length > 0) return inner;
      if (Object.keys(a).length > 0) return a;
    }
    const b = payload && payload.latest_run && payload.latest_run.stats;
    if (b && typeof b === "object") return b;
    return {};
  }

  React.useEffect(() => {
    // Inspect the resolved stats object used by the UI.
    try {
      // eslint-disable-next-line no-console
      console.log("[ui] resolved stats", pickLatestStats(status));
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  React.useEffect(() => {
    refresh().catch((e) => toast("error", e.message));
    const id = setInterval(() => {
      refresh().catch(() => {});
    }, 1200);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Prefer live in-memory state when running; otherwise fall back to the
  // persisted ui_state (useful after server restarts).
  const apiState = (status && status.state) || {};
  const persistedState = (status && status.ui_state) || {};
  const st = apiState && apiState.running
    ? apiState
    : (apiState && Number(apiState.started_at || 0) > 0)
      ? apiState
      : (persistedState && Number(persistedState.started_at || 0) > 0)
        ? persistedState
        : apiState;
  const badge = statusBadge(st);

  const tests = (status && status.latest_run && status.latest_run.tests) || {};
  const latestStats = pickLatestStats(status) || {};

  const isRunning = !!st.running;
  const isFailed = !isRunning && st.exit_code !== null && st.exit_code !== undefined && Number(st.exit_code) !== 0;
  const statusText = isRunning ? "Running" : isFailed ? "Failed" : Number(st.exit_code) === 0 ? "Completed" : "Idle";

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined) return "-";
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    if (m <= 0) return `${r}s`;
    return `${m}m ${r}s`;
  }

  const startedAt = st.started_at;
  const finishedAt = st.finished_at;
  const durationSec =
    startedAt
      ? (isRunning ? Date.now() / 1000 : finishedAt || null)
        ? (Number((isRunning ? Date.now() / 1000 : finishedAt) || 0) - Number(startedAt || 0))
        : null
      : null;

  const pageTitle = page === "run" ? "Run Pipeline" : page === "history" ? "Runs History" : page === "analytics" ? "Analytics" : "Artifacts";

  return h(
    "div",
    { className: "layout bg-gray-100 min-h-screen" },

    // Top header (full-width)
    h(
      "div",
      { className: "ocTopbar" },
      h("div", { className: "ocTopbarTitle" }, "Automation Accelerator"),
      h(
        "div",
        { className: "flex items-center gap-3" },
        h("div", { className: `badge badgeDark ${badge.cls}` }, badge.text),
        h("div", { className: "userIcon", title: "Local" }, "\u{1F464}")
      )
    ),

    h(Sidebar, { active: page, onSelect: setPage }),
    h(
      "div",
      { className: "main" },
      h(
        React.Fragment,
        null,

        h(
          "div",
          { className: "max-w-6xl mx-auto px-6 py-4 space-y-4" },
        h(
          "div",
          { className: "headerBarCompact" },
          h(
            "div",
            null,
            h("div", { className: "text-base font-semibold text-gray-900" }, pageTitle)
          ),
          h("div", { className: "text-sm text-gray-500" }, statusText)
        ),

        page === "run"
          ? h(
              "div",
              { className: "space-y-4" },
              h(
                "div",
                { className: "sticky top-0 z-20 stickyStrip" },
                h(
                  "div",
                  {
                    className:
                      "card",
                  },
                  h("div", { className: "text-base font-semibold text-gray-900 text-center" }, "Pipeline"),
                  h(
                    "div",
                    { className: "mt-4 flex justify-center" },
                    h(PipelineStepper, { steps: progress.steps || [] })
                  )
                )
              ),
              h(
                "div",
                { className: "flex gap-4" },
                h(
                  "div",
                  { className: "flex-1" },
                  h(RunControls, {
                    running: !!st.running,
                    state: st,
                    toast,
                    onRunAction: () => refresh().catch(() => {}),
                  })
                ),
                h(
                  "div",
                  {
                    className:
                      "flex-1 card",
                  },
                  h("div", { className: "text-base font-semibold text-gray-900" }, "Status Summary"),
                  h(
                    "div",
                    { className: "mt-4 flex gap-4" },
                    h(
                      "div",
                      { className: "flex-1 border border-gray-200 bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition" },
                      h("div", { className: "flex items-center justify-between gap-4" },
                        h("div", { className: "text-sm text-gray-500" }, "Status"),
                        h("div", { className: "text-sm" }, "⚡")
                      ),
                      h("div", { className: "mt-2 text-lg font-medium text-gray-900" }, statusText)
                    ),
                    h(
                      "div",
                      { className: "flex-1 border border-gray-200 bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition" },
                      h("div", { className: "flex items-center justify-between gap-4" },
                        h("div", { className: "text-sm text-gray-500" }, "Duration"),
                        h("div", { className: "text-sm" }, "⏱️")
                      ),
                      h("div", { className: "mt-2 text-lg font-medium text-gray-900" }, fmtDuration(durationSec))
                    ),
                    h(
                      "div",
                      { className: "flex-1 border border-gray-200 bg-gray-50 rounded-lg p-4 hover:bg-gray-100 transition" },
                      h("div", { className: "flex items-center justify-between gap-4" },
                        h("div", { className: "text-sm text-gray-500" }, "Tokens"),
                        h("div", { className: "text-sm" }, "🧾")
                      ),
                      h("div", { className: "mt-2 text-lg font-medium text-gray-900" }, fmt(latestStats.tokens_total))
                    )
                  ),
                  h(
                    "div",
                    { className: "mt-4 flex items-center justify-between gap-4 text-sm text-gray-500" },
                    h("div", null, `Passed: ${fmt(tests.passed)} · Failed: ${fmt(tests.failed)}`),
                    st && st.exit_code !== null && st.exit_code !== undefined
                      ? h("div", null, `Exit: ${fmt(st.exit_code)}`)
                      : null
                  )
                )
              ),
              h(LogsViewer, { running: !!st.running, toast })
            )
          : null,

        page === "history" ? h(RunHistory, { toast }) : null,
        page === "analytics" ? h(AnalyticsPage, { status, loading: !loadedOnce }) : null,
        page === "artifacts" ? h(ArtifactsViewer, { toast }) : null,

        h(Toasts, { toasts, onDismiss: dismissToast })
        )
      )
    )
  );
}
