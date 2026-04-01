import { App } from "./App.js";

function mount() {
  const rootEl = document.getElementById("root");
  if (!rootEl) return;

  if (!window.React || !window.ReactDOM) {
    rootEl.innerHTML = `<div style="padding:16px;font-family:system-ui">React failed to load (are you offline?).</div>`;
    return;
  }

  const root = window.ReactDOM.createRoot(rootEl);
  root.render(window.React.createElement(App));
}

mount();
