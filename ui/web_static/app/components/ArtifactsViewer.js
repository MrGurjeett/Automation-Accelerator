import { listFiles, readFile } from "../api.js";
import { buildTree } from "../utils.js";

async function loadMonaco() {
  if (window.monaco) return window.monaco;
  if (window.__monacoLoading) return window.__monacoLoading;

  window.__monacoLoading = new Promise((resolve, reject) => {
    window.MonacoEnvironment = {
      getWorkerUrl: function () {
        const base = "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/";
        const code = `self.MonacoEnvironment={baseUrl:'${base}'};importScripts('${base}vs/base/worker/workerMain.js');`;
        return `data:text/javascript;charset=utf-8,${encodeURIComponent(code)}`;
      },
    };

    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js";
    s.async = true;
    s.onload = () => {
      const r = window.require;
      if (!r) {
        reject(new Error("Monaco loader missing"));
        return;
      }
      r.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" } });
      r(["vs/editor/editor.main"], () => resolve(window.monaco), (err) => reject(err));
    };
    s.onerror = () => reject(new Error("Failed to load Monaco from CDN"));
    document.head.appendChild(s);
  });

  return window.__monacoLoading;
}

function guessLanguage(path) {
  const p = (path || "").toLowerCase();
  if (p.endsWith(".json")) return "json";
  if (p.endsWith(".md")) return "markdown";
  if (p.endsWith(".yaml") || p.endsWith(".yml")) return "yaml";
  if (p.endsWith(".feature")) return "gherkin";
  if (p.endsWith(".py")) return "python";
  if (p.endsWith(".js") || p.endsWith(".mjs")) return "javascript";
  if (p.endsWith(".ts") || p.endsWith(".tsx")) return "typescript";
  if (p.endsWith(".css")) return "css";
  if (p.endsWith(".html")) return "html";
  if (p.endsWith(".log") || p.endsWith(".txt")) return "plaintext";
  return "plaintext";
}

function TreeNode({ node, onOpen, readableMap }) {
  const React = window.React;
  const h = React.createElement;
  const [open, setOpen] = React.useState(true);

  const dirs = Array.from(node.children.values()).sort((a, b) => a.name.localeCompare(b.name));
  const files = (node.files || []).sort((a, b) => a.name.localeCompare(b.name));

  return h(
    "div",
    null,
    node.name
      ? h(
          "div",
          { className: "fileItem", onClick: () => setOpen(!open) },
          `${open ? "▾" : "▸"} ${node.name}/`
        )
      : null,
    open
      ? h(
          "div",
          { style: { paddingLeft: node.name ? 12 : 0 } },
          dirs.map((d) => h(TreeNode, { key: d.path, node: d, onOpen, readableMap })),
          files.map((f) =>
            h(
              "div",
              {
                key: f.path,
                className: `fileItem ${(readableMap && readableMap[f.path] === false) ? "disabled" : ""}`,
                onClick: () => onOpen(f.path),
              },
              f.name
            )
          )
        )
      : null
  );
}

export function ArtifactsViewer({ toast }) {
  const React = window.React;
  const h = React.createElement;

  const [root, setRoot] = React.useState("workspace");
  const [tree, setTree] = React.useState(null);
  const [readableMap, setReadableMap] = React.useState({});
  const [activePath, setActivePath] = React.useState("");
  const [content, setContent] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [hasMonaco, setHasMonaco] = React.useState(false);
  const editorRef = React.useRef(null);
  const editorInstanceRef = React.useRef(null);

  async function refresh() {
    setLoading(true);
    try {
      const data = await listFiles(root);
      const files = data.files || [];
      const paths = files.map((f) => f.path);
      const rm = {};
      for (const f of files) rm[f.path] = !!f.readable;
      setReadableMap(rm);
      setTree(buildTree(paths));
    } catch (e) {
      toast("error", e.message);
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root]);

  async function openFile(path) {
    if (readableMap && readableMap[path] === false) {
      toast("error", "This file type is not viewable in the UI.");
      return;
    }
    setActivePath(path);
    try {
      const file = await readFile(path);
      const text = file.content || "";
      setContent(text);

      // Monaco if possible; otherwise fallback pre.
      if (!editorRef.current) return;
      const monaco = await loadMonaco().catch(() => null);
      if (!monaco) return;
      setHasMonaco(true);

      if (!editorInstanceRef.current) {
        editorInstanceRef.current = monaco.editor.create(editorRef.current, {
          value: text,
          language: guessLanguage(path),
          readOnly: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: "on",
        });
      } else {
        const model = editorInstanceRef.current.getModel();
        if (model) {
          monaco.editor.setModelLanguage(model, guessLanguage(path));
          model.setValue(text);
        }
      }
    } catch (e) {
      toast("error", e.message);
    }
  }

  React.useEffect(() => {
    return () => {
      try {
        if (editorInstanceRef.current) {
          editorInstanceRef.current.dispose();
          editorInstanceRef.current = null;
        }
      } catch {
        // ignore
      }
    };
  }, []);

  return h(
    "div",
    { className: "card" },
    h("div", { className: "cardTitle" }, "Artifacts"),
    h(
      "div",
      { className: "row" },
      h("label", null, "Root"),
      h(
        "select",
        { value: root, onChange: (e) => setRoot(e.target.value) },
        h("option", { value: "workspace" }, "workspace/"),
        h("option", { value: "generated" }, "generated/"),
        h("option", { value: "artifacts" }, "artifacts/"),
        h("option", { value: "docs" }, "docs/"),
        h("option", { value: "core" }, "core/"),
        h("option", { value: "framework" }, "framework/")
      ),
      h(
        "button",
        { className: "btn secondary", onClick: refresh, disabled: loading },
        loading ? "Loading…" : "Refresh"
      )
    ),
    h(
      "div",
      { className: "split" },
      h(
        "div",
        { className: "fileList" },
        tree
          ? h(TreeNode, { node: tree, onOpen: openFile, readableMap })
          : h("div", { className: "fileItem" }, loading ? "Loading files…" : "No files")
      ),
      h(
        "div",
        { className: "codeBox" },
        h("div", { className: "codeHeader" }, activePath || "Select a file"),
        h(
          "div",
          { style: { height: 560, position: "relative" } },
          h("div", { ref: editorRef, style: { position: "absolute", inset: 0 } }),
          h(
            "pre",
              { className: "codeFallback", style: { position: "absolute", inset: 0, margin: 0, display: (hasMonaco ? "none" : "block") } },
            content
          )
        )
      )
    )
  );
}

// Alias for requested component naming
export function ArtifactExplorer(props) {
  return ArtifactsViewer(props);
}
