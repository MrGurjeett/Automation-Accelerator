import { listRuns, readFile } from "../api.js";
import { safeJson, fmt } from "../utils.js";

export function RunHistory({ toast }) {
  const React = window.React;
  const h = React.createElement;

  const [runs, setRuns] = React.useState([]);
  const [active, setActive] = React.useState(null);
  const [activeContent, setActiveContent] = React.useState("");
  const [loading, setLoading] = React.useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const data = await listRuns();
      setRuns(data.runs || []);
    } catch (e) {
      toast("error", e.message);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openRun(r) {
    setActive(r);
    setActiveContent("Loading…");
    try {
      const p = `${r.version_folder}/run_summary.json`;
      const file = await readFile(p);
      setActiveContent(file.content || "");
    } catch (e) {
      setActiveContent("");
      toast("error", e.message);
    }
  }

  function runStatus(tests) {
    if (!tests) return "—";
    if (tests.skipped) return "skipped";
    if (tests.exit_code === 0) return "passed";
    if (tests.exit_code !== null && tests.exit_code !== undefined) return "failed";
    return "—";
  }

  return h(
    "div",
    { className: "card" },
    h("div", { className: "cardTitle" }, "Run History"),
    h(
      "div",
      { className: "actions" },
      h(
        "button",
        { className: "btn secondary", onClick: refresh, disabled: loading },
        loading ? "Refreshing…" : "Refresh"
      )
    ),
    h(
      "div",
      { className: "split" },
      h(
        "div",
        { className: "fileList" },
        (runs || []).map((r) =>
          h(
            "div",
            {
              key: r.version_folder,
              className: "fileItem",
              onClick: () => openRun(r),
            },
            `${fmt(r.completed_at)} · ${r.mode || ""} · ${runStatus(r.tests)} · ${r.version_folder.split('/').pop()}`
          )
        )
      ),
      h(
        "div",
        { className: "codeBox" },
        h("div", { className: "codeHeader" }, active ? active.version_folder : "Select a run"),
        h("pre", { className: "codeFallback", style: { margin: 0 } }, activeContent || "")
      )
    )
  );
}
