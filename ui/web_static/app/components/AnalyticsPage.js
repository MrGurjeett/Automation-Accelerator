import { StatsCard } from "./StatsCard.js";

function unwrapLatest(latestStats) {
  if (!latestStats || typeof latestStats !== "object") return null;
  if (latestStats.stats && typeof latestStats.stats === "object") return latestStats.stats;
  return latestStats;
}

function unwrapCumulative(cumulative) {
  if (!cumulative || typeof cumulative !== "object") return null;
  if (cumulative.cumulative && typeof cumulative.cumulative === "object") return cumulative.cumulative;
  return cumulative;
}

export function AnalyticsPage({ status, loading }) {
  const h = window.React.createElement;

  const latest = unwrapLatest(status && status.latest_stats) || (status && status.latest_run && status.latest_run.stats) || null;
  const cumulative = unwrapCumulative(status && status.cumulative_stats) || null;

  return h(
    "div",
    { className: "stack gap6" },
    h(
      "div",
      { className: "card" },
      h("div", { className: "sectionTitle" }, "Latest Run Stats"),
      h(
        "div",
        { className: "cards cards2" },
        h(StatsCard, { icon: "🌐", label: "DOM Elements", value: latest ? latest.dom_elements : null }),
        h(StatsCard, { icon: "📄", label: "Pages Scanned", value: latest ? latest.pages_scanned : null }),
        h(StatsCard, { icon: "🔁", label: "Steps Converted", value: latest ? latest.raw_steps_converted : null }),
        h(StatsCard, { icon: "🧾", label: "Tokens Used", value: latest ? latest.tokens_total : null }),
        h(StatsCard, { icon: "⚡", label: "Cache Hits", value: latest ? latest.aoai_cache_hits : null }),
        h(StatsCard, { icon: "🧠", label: "RAG Resolutions", value: latest ? latest.rag_resolutions : null })
      ),
      !latest
        ? h("div", { className: "emptyState" }, loading ? "Loading…" : "No latest stats yet.")
        : null
    ),

    h(
      "div",
      { className: "card" },
      h("div", { className: "sectionTitle" }, "Cumulative Stats"),
      h(
        "div",
        { className: "cards cards2" },
        h(StatsCard, { icon: "▶️", label: "Runs", value: cumulative ? cumulative.runs : null }),
        h(StatsCard, { icon: "🧾", label: "Tokens Used", value: cumulative ? cumulative.tokens_total : null }),
        h(StatsCard, { icon: "💾", label: "Tokens Saved", value: cumulative ? cumulative.tokens_saved_total : null }),
        h(StatsCard, { icon: "⚡", label: "Cache Hits", value: cumulative ? cumulative.aoai_cache_hits : null }),
        h(StatsCard, { icon: "🧠", label: "RAG Resolutions", value: cumulative ? cumulative.rag_resolutions : null }),
        h(StatsCard, { icon: "🧩", label: "Chat Calls", value: cumulative ? cumulative.aoai_chat_calls : null })
      ),
      !cumulative
        ? h("div", { className: "emptyState" }, loading ? "Loading…" : "No cumulative stats yet.")
        : null
    )
  );
}
