import { useCallback, useEffect, useState } from "react";
import { api, ACTIVE_STATUSES, pct } from "./api.js";
import AskBox from "./components/AskBox.jsx";
import Filters from "./components/Filters.jsx";
import ReviewPanel from "./components/ReviewPanel.jsx";
import StatusBanner, { UploadCard } from "./components/StatusBanner.jsx";
import ThemeList from "./components/ThemeList.jsx";
import Trends from "./components/Trends.jsx";

function Kpis({ data }) {
  const mentions = data.themes.reduce((a, t) => a + t.count, 0);
  const negative = data.themes.reduce((a, t) => a + t.negative, 0);
  const top = [...data.themes].sort((a, b) => b.negative - a.negative)[0];
  return (
    <div className="kpis">
      <div className="kpi">
        <span>Reviews</span>
        <strong>{data.total_reviews}</strong>
      </div>
      <div className="kpi">
        <span>Themes found</span>
        <strong>{data.themes.length}</strong>
      </div>
      <div className="kpi">
        <span>Mentions that are negative</span>
        <strong className={pct(negative, mentions) >= 50 ? "neg-text" : ""}>{pct(negative, mentions)}%</strong>
      </div>
      <div className="kpi">
        <span>Biggest complaint</span>
        <strong>{top && top.negative ? top.name : "–"}</strong>
        {top && top.negative > 0 && <small>{top.negative} negative reviews</small>}
      </div>
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [options, setOptions] = useState(null);
  const [filters, setFilters] = useState({});
  const [themes, setThemes] = useState({ loading: false, error: null, data: null });
  const [trends, setTrends] = useState(null);
  const [selection, setSelection] = useState(null);

  const loadStatus = useCallback(() => {
    return api
      .get("status")
      .then((s) => {
        setStatus(s);
        setStatusError(null);
      })
      .catch((e) => setStatusError(e.message));
  }, []);

  // Used by "What changed" and "Ask": select, then scroll up to the review panel.
  const selectAndShow = (sel) => {
    setSelection(sel);
    setTimeout(() => document.querySelector(".reviews-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  const job = status?.job;
  const active = !status || ACTIVE_STATUSES.includes(job?.status);

  // Poll while the backend is starting or the analysis is running.
  useEffect(() => {
    loadStatus();
    if (!active) return;
    const id = setInterval(loadStatus, 2500);
    return () => clearInterval(id);
  }, [active, loadStatus]);

  // Reload the dashboard data whenever filters change or the analysis makes progress.
  const progressKey = job ? `${job.id}-${job.status}-${Math.floor(job.labelled_reviews / 40)}` : "none";
  useEffect(() => {
    if (!status?.review_count) return;
    let cancelled = false;
    setThemes((t) => ({ ...t, loading: true, error: null }));
    Promise.all([api.get("themes", filters), api.get("trends", filters), api.get("filters")])
      .then(([th, tr, opts]) => {
        if (cancelled) return;
        setThemes({ loading: false, error: null, data: th });
        setTrends(tr);
        setOptions(opts);
      })
      .catch((e) => !cancelled && setThemes({ loading: false, error: e.message, data: null }));
    return () => {
      cancelled = true;
    };
  }, [filters, progressKey, status?.review_count]);

  const header = (
    <header className="top">
      <div>
        <h1>Zesto · Review Insights</h1>
        <p className="muted small">What customers are saying in app-store reviews, and how they feel about it.</p>
      </div>
      <div className="top-right">
        {status && (
          <span className={`pill ${status.llm.configured ? "ok" : "warn"}`}>
            {status.llm.configured ? `AI: ${status.llm.provider} · ${status.llm.model}` : "No LLM key configured"}
          </span>
        )}
        {status?.review_count > 0 && <UploadCard compact onDone={loadStatus} />}
      </div>
    </header>
  );

  if (statusError && !status) {
    return (
      <main className="page">
        {header}
        <div className="banner error">
          Can't reach the backend ({statusError}). It may still be starting. Retrying…
        </div>
      </main>
    );
  }
  if (!status) {
    return (
      <main className="page">
        {header}
        <p className="muted">
          <span className="spinner" /> Connecting…
        </p>
      </main>
    );
  }

  const data = themes.data;
  const hasThemes = data && data.themes.length > 0;

  return (
    <main className="page">
      {header}
      {status.review_count === 0 ? (
        <UploadCard onDone={loadStatus} />
      ) : (
        <>
          <StatusBanner status={status} onChange={loadStatus} />
          <Filters options={options} filters={filters} setFilters={setFilters} />
          {themes.error && <div className="banner error">Couldn't load themes: {themes.error}</div>}
          {data && <Kpis data={data} />}
          {!hasThemes && data && !active && job?.status === "done" && (
            <p className="empty card">No reviews match these filters.</p>
          )}
          {!hasThemes && active && <p className="muted">Themes will appear here as reviews are analysed…</p>}
          {hasThemes && (
            <div className="grid">
              <ThemeList data={data} selection={selection} onSelect={setSelection} />
              <ReviewPanel selection={selection} filters={filters} onClear={() => setSelection(null)} />
            </div>
          )}
          {hasThemes && (
            <div className="grid">
              <Trends data={trends} onSelect={selectAndShow} />
              <AskBox llmConfigured={status.llm.configured} onShowReviews={selectAndShow} />
            </div>
          )}
        </>
      )}
    </main>
  );
}
