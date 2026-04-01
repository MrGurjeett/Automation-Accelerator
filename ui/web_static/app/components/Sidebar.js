export function Sidebar({ active, onSelect }) {
  const h = window.React.createElement;

  const items = [
    { key: "run", label: "Run Pipeline" },
    { key: "history", label: "Runs History" },
    { key: "analytics", label: "Analytics" },
    { key: "artifacts", label: "Artifacts" },
  ];

  return h(
    "div",
    { className: "sidebar" },
    h("div", { className: "brand" }, "Automation Accelerator"),
    h("div", { className: "subtle" }, "Local UI"),
    h(
      "div",
      { className: "nav" },
      items.map((it) =>
        h(
          "button",
          {
            key: it.key,
            className: `navBtn ${active === it.key ? "active" : ""}`,
            onClick: () => onSelect(it.key),
          },
          it.label
        )
      )
    ),
    h(
      "div",
      { className: "subtle", style: { marginTop: 14 } },
      "Tip: keep this tab open while runs execute."
    )
  );
}
