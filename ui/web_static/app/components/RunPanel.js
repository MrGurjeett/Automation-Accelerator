import { startRun, stopRun } from "../api.js";
import { Toggle } from "./Toggle.js";
import { PipelineStepper } from "./Stepper.js";

const ENV_KEYS = [
  "BASE_URL",
  "UI_USERNAME",
  "UI_PASSWORD",
  "DOM_BASE_URL",
  "DOM_USERNAME",
  "DOM_PASSWORD",
];

export function RunPanel({ running, state, steps, toast, onRunAction }) {
  const React = window.React;
  const h = React.createElement;

  const [mode, setMode] = React.useState("pipeline");
  const [force, setForce] = React.useState(false);
  const [scan, setScan] = React.useState(false);
  const [showEnv, setShowEnv] = React.useState(false);
  const [env, setEnv] = React.useState({});
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (state && state.mode && running) {
      setMode(state.mode);
    }
  }, [state, running]);

  async function onStart() {
    setBusy(true);
    try {
      const cleanedEnv = {};
      for (const k of ENV_KEYS) {
        const v = (env[k] || "").trim();
        if (v) cleanedEnv[k] = v;
      }

      await startRun({ mode, force, scan, env: cleanedEnv });
      toast("info", "Pipeline started");
      onRunAction();
    } catch (e) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    setBusy(true);
    try {
      await stopRun();
      toast("info", "Stop requested");
      onRunAction();
    } catch (e) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  function setEnvKey(k, v) {
    setEnv((prev) => ({ ...prev, [k]: v }));
  }

  return h(
    "div",
    { className: "card" },
    h("div", { className: "cardTitle" }, "Run Pipeline"),

    h("div", { className: "subtle" }, "Progress"),
    h(PipelineStepper, { steps }),

    h("div", { className: "divider" }),

    h(
      "div",
      { className: "row" },
      h("label", null, "Mode"),
      h(
        "select",
        {
          value: mode,
          onChange: (e) => setMode(e.target.value),
          disabled: running || busy,
        },
        h("option", { value: "pipeline" }, "Full pipeline (generate + tests)"),
        h("option", { value: "generate-only" }, "Generate only"),
        h("option", { value: "run-e2e" }, "Run generated E2E only")
      )
    ),

    h("div", { className: "togStack" },
      h(Toggle, { checked: force, onChange: setForce, label: "Force regenerate", disabled: running || busy }),
      h(Toggle, { checked: scan, onChange: setScan, label: "Force DOM scan", disabled: running || busy })
    ),

    h(
      "div",
      { className: "row" },
      h(
        "button",
        {
          className: "btn secondary",
          onClick: () => setShowEnv(!showEnv),
          disabled: running || busy,
        },
        showEnv ? "Hide env overrides" : "Env overrides"
      )
    ),

    showEnv
      ? h(
          "div",
          null,
          ENV_KEYS.map((k) =>
            h(
              "div",
              { className: "row", key: k },
              h("label", null, k),
              h("input", {
                className: "input",
                type: k.toUpperCase().includes("PASSWORD") ? "password" : "text",
                value: env[k] || "",
                placeholder: k.includes("URL") ? "https://..." : "",
                onChange: (e) => setEnvKey(k, e.target.value),
                disabled: running || busy,
              })
            )
          ),
          h(
            "div",
            { className: "subtle" },
            "Only these keys are passed to the run process."
          )
        )
      : null,

    h(
      "div",
      { className: "actions" },
      h(
        "button",
        { className: "btn", onClick: onStart, disabled: running || busy },
        busy ? "Starting…" : "Start Pipeline"
      ),
      h(
        "button",
        { className: "btn secondary", onClick: onStop, disabled: !running || busy },
        busy ? "Stopping…" : "Stop"
      )
    ),

    state && state.command
      ? h(
          "div",
          { className: "subtle", style: { marginTop: 10 } },
          (state.command || []).join(" ")
        )
      : null
  );
}
