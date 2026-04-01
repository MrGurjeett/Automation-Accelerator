export function Toggle({ checked, onChange, label, disabled }) {
  const h = window.React.createElement;
  return h(
    "div",
    { className: "togRow" },
    h("div", { className: "togLabel" }, label),
    h(
      "label",
      { className: "switch" },
      h("input", {
        type: "checkbox",
        role: "switch",
        checked: !!checked,
        disabled: !!disabled,
        onChange: (e) => onChange(!!e.target.checked),
      }),
      h("span", { className: "slider" })
    )
  );
}
