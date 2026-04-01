import { clearOutput, getInputs, startRun, stopRun, uploadExcel } from "../api.js";

const ENV_KEYS = [
  "BASE_URL",
  "UI_USERNAME",
  "UI_PASSWORD",
  "DOM_BASE_URL",
  "DOM_USERNAME",
  "DOM_PASSWORD",
];

export function RunControls({ running, state, toast, onRunAction }) {
  const React = window.React;
  const h = React.createElement;

  function Switch({ checked, disabled, onChange }) {
    return h(
      "button",
      {
        type: "button",
        role: "switch",
        "aria-checked": !!checked,
        disabled: !!disabled,
        onClick: () => {
          if (disabled) return;
          onChange(!checked);
        },
        className: `w-10 h-6 rounded-full border border-gray-200 ${
          checked ? "bg-teal-500" : "bg-gray-300"
        } flex items-center ${checked ? "justify-end" : "justify-start"} p-1 transition`,
      },
      h("span", { className: "w-4 h-4 rounded-full bg-white" })
    );
  }

  function ToggleRow({ label, checked, disabled, onChange }) {
    return h(
      "div",
      { className: "flex items-center justify-between gap-4" },
      h("div", { className: "text-sm text-gray-500" }, label),
      h(Switch, { checked, disabled, onChange })
    );
  }

  const [mode, setMode] = React.useState("pipeline");
  const [force, setForce] = React.useState(false);
  const [scan, setScan] = React.useState(false);
  const [showEnv, setShowEnv] = React.useState(false);
  const [env, setEnv] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [inputs, setInputs] = React.useState(null);
  const fileRef = React.useRef(null);

  React.useEffect(() => {
    if (state && state.mode && running) setMode(state.mode);
  }, [state, running]);

  async function refreshInputs() {
    try {
      const data = await getInputs();
      setInputs(data);
    } catch {
      // ignore
    }
  }

  React.useEffect(() => {
    refreshInputs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  async function onClearOutput() {
    setBusy(true);
    try {
      const res = await clearOutput();
      const n = (res.cleared || []).length;
      toast("info", n ? `Cleared ${n} file(s)` : "Nothing to clear");
      await refreshInputs();
      onRunAction();
    } catch (e) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onUploadFile(file) {
    if (!file) return;
    setBusy(true);
    try {
      const content_base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Failed to read file"));
        reader.onload = () => resolve(String(reader.result || ""));
        reader.readAsDataURL(file);
      });
      const res = await uploadExcel({ filename: file.name, content_base64 });
      toast("info", `Uploaded (${res.kind}) → ${res.saved_as}`);
      await refreshInputs();
    } catch (e) {
      toast("error", e.message);
    } finally {
      setBusy(false);
      try {
        if (fileRef.current) fileRef.current.value = "";
      } catch {
        // ignore
      }
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

  const disabled = running || busy;

  return h(
    "div",
    {
      className:
        "card",
    },
    h(
      "div",
      { className: "flex items-center justify-between gap-4" },
      h("div", { className: "text-base font-semibold text-gray-900" }, "Run Controls"),
      h(
        "div",
        { className: "flex items-center gap-2" },
        h(
          "button",
          {
            className: "btn secondary",
            onClick: onClearOutput,
            disabled: disabled,
            title: "Clears generated feature/output artifacts",
          },
          busy ? "Clearing…" : "Clear Output"
        ),
        h(
          "button",
          {
            className: "btn",
            onClick: onStart,
            disabled,
          },
          busy ? "Starting…" : "Start"
        ),
        h(
          "button",
          {
            className: "btn secondary",
            onClick: onStop,
            disabled: !running || busy,
          },
          busy ? "Stopping…" : "Stop"
        )
      )
    ),

    h(
      "div",
      { className: "mt-3 text-xs text-gray-500" },
      inputs && inputs.selected
        ? `Input: ${inputs.selected}${inputs.raw ? ` (raw: ${inputs.raw})` : ""}`
        : "Input: (auto-detect from input/*.xlsx)"
    ),

    h(
      "div",
      { className: "mt-3 flex items-center gap-3" },
      h("input", {
        ref: fileRef,
        className: "w-full border border-gray-200 rounded-lg px-3 py-2 bg-white",
        type: "file",
        accept: ".xlsx",
        disabled: disabled,
        onChange: (e) => onUploadFile((e.target.files || [])[0]),
      })
    ),

    h(
      "div",
      { className: "mt-4 flex flex-col gap-4" },
      h(
        "div",
        null,
        h("div", { className: "text-sm text-gray-500 mb-2" }, "Mode"),
        h(
          "select",
          {
            className: "w-full border border-gray-200 rounded-lg px-3 py-2 bg-white",
            value: mode,
            onChange: (e) => setMode(e.target.value),
            disabled,
          },
          h("option", { value: "pipeline" }, "Full pipeline (generate + tests)"),
          h("option", { value: "generate-only" }, "Generate only"),
          h("option", { value: "run-e2e" }, "Run generated E2E only")
        )
      ),
      h(
        "div",
        null,
        h("div", { className: "text-sm text-gray-500 mb-2" }, "Options"),
        h(
          "div",
          { className: "flex flex-col gap-3" },
          h(ToggleRow, { label: "Force regenerate", checked: !!force, disabled, onChange: setForce }),
          h(ToggleRow, { label: "Force DOM scan", checked: !!scan, disabled, onChange: setScan }),
          h(ToggleRow, { label: "Env overrides", checked: !!showEnv, disabled, onChange: setShowEnv })
        )
      )
    ),

    showEnv
      ? h(
          "div",
          { className: "mt-4 border-t border-gray-200 pt-4" },
          h("div", { className: "text-sm text-gray-500 mb-3" }, "Env overrides"),
          h(
            "div",
            { className: "grid grid-cols-12 gap-3" },
            ENV_KEYS.map((k) =>
              h(
                "div",
                { key: k, className: "col-span-12" },
                h(
                  "div",
                  { className: "flex items-center gap-3" },
                  h("div", { className: "w-40 text-xs text-gray-500" }, k),
                  h("input", {
                    className: "w-full border border-gray-200 rounded-lg px-3 py-2",
                    type: k.toUpperCase().includes("PASSWORD") ? "password" : "text",
                    value: env[k] || "",
                    placeholder: k.includes("URL") ? "https://..." : "",
                    onChange: (e) => setEnvKey(k, e.target.value),
                    disabled,
                  })
                )
              )
            )
          ),
          h(
            "div",
            { className: "mt-2 text-xs text-gray-500" },
            "Only these keys are passed to the run process."
          )
        )
      : null,

    state && state.command
      ? h(
          "div",
          { className: "mt-4 text-xs text-gray-500" },
          (state.command || []).join(" ")
        )
      : null
  );
}
