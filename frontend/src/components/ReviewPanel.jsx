import { useEffect, useState } from "react";
import { api } from "../api.js";

const PAGE = 30;

function Stars({ n }) {
  if (!n) return null;
  return (
    <span className={`stars r${n}`} title={`${n} of 5`}>
      {"★".repeat(n)}
      <span className="dim">{"★".repeat(5 - n)}</span>
    </span>
  );
}

function ReviewCard({ r, highlightTheme }) {
  return (
    <article className="review">
      <div className="review-meta">
        <Stars n={r.rating} />
        <span>{r.date}</span>
        <span>{r.city}</span>
        <span>{r.platform === "ios" ? "iOS" : r.platform}</span>
        <span className="mono dim">{r.review_id}</span>
      </div>
      <p>{r.text}</p>
      <div className="chips">
        {r.labels.map((l) => (
          <span
            key={l.theme + l.sub_theme}
            className={`chip ${l.sentiment} ${highlightTheme === l.theme_id ? "strong" : ""}`}
          >
            {l.theme === "NONE" ? "no content" : `${l.theme} › ${l.sub_theme}`}
          </span>
        ))}
      </div>
    </article>
  );
}

export default function ReviewPanel({ selection, filters, onClear }) {
  const [sentiment, setSentiment] = useState("");
  const [state, setState] = useState({ loading: false, error: null, data: null });
  const [limit, setLimit] = useState(PAGE);

  useEffect(() => {
    setLimit(PAGE);
    setSentiment(selection?.sentiment || "");
  }, [selection]);

  useEffect(() => {
    if (!selection) return;
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    // Evidence from "Ask" is a fixed list of reviews, so the dashboard filters don't apply to it.
    const params = selection.ids
      ? { ids: selection.ids.join(","), page_size: limit }
      : { ...filters, theme: selection.theme, sub_theme: selection.sub_theme, sentiment, page_size: limit };
    api
      .get("reviews", params)
      .then((data) => !cancelled && setState({ loading: false, error: null, data }))
      .catch((e) => !cancelled && setState({ loading: false, error: e.message, data: null }));
    return () => {
      cancelled = true;
    };
  }, [selection, filters, sentiment, limit]);

  if (!selection) {
    return (
      <section className="card reviews-panel placeholder">
        <h2>Reviews</h2>
        <p className="muted">Pick a theme or sub-theme on the left to read the reviews behind the numbers.</p>
      </section>
    );
  }

  const title = selection.title || [selection.themeName, selection.subName].filter(Boolean).join(" › ");
  const { loading, error, data } = state;

  return (
    <section className="card reviews-panel">
      <div className="row-between card-head">
        <div>
          <h2>{title}</h2>
          <p className="muted small">{data ? `${data.count} review(s)` : " "}</p>
        </div>
        <button className="btn ghost" onClick={onClear} aria-label="Close">
          ✕
        </button>
      </div>
      {!selection.ids && (
        <div className="seg">
          {[
            ["", "All"],
            ["negative", "Negative"],
            ["positive", "Positive"],
          ].map(([v, l]) => (
            <button key={v} className={sentiment === v ? "on" : ""} onClick={() => setSentiment(v)}>
              {l}
            </button>
          ))}
        </div>
      )}
      {error && <p className="error-text">Couldn't load reviews: {error}</p>}
      {loading && !data && <p className="muted">Loading…</p>}
      {data && data.count === 0 && <p className="empty">No reviews match.</p>}
      <div className="review-list">
        {data?.results.map((r) => (
          <ReviewCard key={r.review_id} r={r} highlightTheme={selection.theme} />
        ))}
      </div>
      {data && data.count > data.results.length && (
        <button className="btn ghost wide" disabled={loading} onClick={() => setLimit(limit + PAGE)}>
          {loading ? "Loading…" : `Show more (${data.count - data.results.length} left)`}
        </button>
      )}
    </section>
  );
}
