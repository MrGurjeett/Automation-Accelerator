import { fmt } from "../utils.js";

function StatCard({ label, value }) {
  const h = window.React.createElement;
  return h(
    "div",
    { className: "statCard" },
    h("div", { className: "statLabel" }, label),
    h("div", { className: "statValue" }, fmt(value))
  );
}

export function StatsPanel({ latestStats, cumulative, loading }) {
  const h = window.React.createElement;

  const s = latestStats || {};
  const c = (cumulative && cumulative.cumulative) ? cumulative.cumulative : (cumulative || {});
  const hasLatest = s && typeof s === "object" && Object.keys(s).length > 0;
  const hasCumulative = c && typeof c === "object" && Object.keys(c).length > 0;

  return h(
    "div",
    { className: "card" },
    h("div", { className: "cardTitle" }, "Stats"),
    h("div", { className: "subtle" }, "Latest run"),
    !hasLatest
      ? h(
          "div",
          { className: "emptyState" },
          loading ? "Loading stats…" : "No stats yet. Run the pipeline to generate metrics."
        )
      : null,
    h(
      "div",
      { className: "cards" },
      h(StatCard, { label: "DOM elements", value: s.dom_elements }),
      h(StatCard, { label: "Pages scanned", value: s.pages_scanned }),
      h(StatCard, { label: "Raw steps converted", value: s.raw_steps_converted }),
      h(StatCard, { label: "Normalized steps", value: s.normalized_steps }),
      h(StatCard, { label: "RAG resolutions", value: s.rag_resolutions }),
      h(StatCard, { label: "Locator healing", value: s.locator_healing }),
      h(StatCard, { label: "Chat calls", value: s.aoai_chat_calls }),
      h(StatCard, { label: "Embedding calls", value: s.aoai_embedding_calls }),
      h(StatCard, { label: "Cache hits", value: s.aoai_cache_hits }),
      h(StatCard, { label: "Tokens (prompt)", value: s.tokens_prompt }),
      h(StatCard, { label: "Tokens (completion)", value: s.tokens_completion }),
      h(StatCard, { label: "Tokens (total)", value: s.tokens_total }),
      h(StatCard, { label: "Tokens saved", value: s.tokens_saved_total })
    ),
    h("div", { className: "divider" }),
    h("div", { className: "subtle" }, "Cumulative"),
    !hasCumulative
      ? h(
          "div",
          { className: "emptyState" },
          loading ? "Loading cumulative stats…" : "No cumulative stats yet."
        )
      : null,
    h(
      "div",
      { className: "cards" },
      h(StatCard, { label: "Runs", value: c.runs }),
      h(StatCard, { label: "Tokens total", value: c.tokens_total }),
      h(StatCard, { label: "Tokens saved", value: c.tokens_saved_total }),
      h(StatCard, { label: "Chat calls", value: c.aoai_chat_calls }),
      h(StatCard, { label: "Embedding calls", value: c.aoai_embedding_calls }),
      h(StatCard, { label: "Cache hits", value: c.aoai_cache_hits }),
      h(StatCard, { label: "RAG resolutions", value: c.rag_resolutions }),
      h(StatCard, { label: "Locator healing", value: c.locator_healing })
    )
  );
}

// Alias for requested component naming
export function StatsCards(props) {
  return StatsPanel(props);
}
