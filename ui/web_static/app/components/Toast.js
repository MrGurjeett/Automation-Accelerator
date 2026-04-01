export function Toasts({ toasts, onDismiss }) {
  const h = window.React.createElement;
  return h(
    "div",
    { className: "toastWrap" },
    (toasts || []).map((t) =>
      h(
        "div",
        { key: t.id, className: `toast ${t.kind === 'error' ? 'err' : ''}`, onClick: () => onDismiss(t.id) },
        t.message
      )
    )
  );
}
