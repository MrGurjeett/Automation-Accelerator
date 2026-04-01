import { fmt } from "../utils.js";

export function StatsCard({ label, value, icon }) {
  const h = window.React.createElement;

  return h(
    "div",
    { className: "statCard statCardModern" },
    h("div", { className: "statTop" },
      h("div", { className: "statIcon", "aria-hidden": true }, icon || ""),
      h("div", { className: "statLabel" }, label)
    ),
    h("div", { className: "statValue" }, fmt(value))
  );
}
