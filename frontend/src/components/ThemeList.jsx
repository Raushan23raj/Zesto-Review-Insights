import { useState } from "react";
import { pct } from "../api.js";

export function SentimentBar({ positive, negative, neutral = 0 }) {
  const total = positive + negative + neutral || 1;
  return (
    <div className="sbar" title={`${negative} negative · ${positive} positive${neutral ? ` · ${neutral} neutral` : ""}`}>
      <div className="neg" style={{ width: `${(100 * negative) / total}%` }} />
      <div className="neu" style={{ width: `${(100 * neutral) / total}%` }} />
      <div className="pos" style={{ width: `${(100 * positive) / total}%` }} />
    </div>
  );
}

const SORTS = {
  count: { label: "Most mentioned", fn: (a, b) => b.count - a.count },
  negative: { label: "Most complaints", fn: (a, b) => b.negative - a.negative },
};

export default function ThemeList({ data, selection, onSelect }) {
  const [sort, setSort] = useState("count");
  const [open, setOpen] = useState({});
  const themes = [...data.themes].sort(SORTS[sort].fn);
  const max = Math.max(1, ...themes.map((t) => t.count));

  function clickTheme(t) {
    setOpen({ ...open, [t.id]: true });
    onSelect({ theme: t.id, themeName: t.name });
  }

  return (
    <section className="card">
      <div className="row-between card-head">
        <div>
          <h2>What customers talk about</h2>
          <p className="muted small">
            Click a theme to read its reviews. Bars show negative (red) vs positive (green) mentions.
          </p>
        </div>
        <div className="seg">
          {Object.entries(SORTS).map(([k, v]) => (
            <button key={k} className={sort === k ? "on" : ""} onClick={() => setSort(k)}>
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {themes.length === 0 && <p className="empty">No themes for these filters.</p>}

      <table className="themes">
        <thead>
          <tr>
            <th>Theme</th>
            <th className="num">Reviews</th>
            <th>Sentiment</th>
            <th className="num">Negative</th>
          </tr>
        </thead>
        <tbody>
          {themes.map((t) => {
            const isOpen = open[t.id];
            const selected = selection?.theme === t.id && !selection?.sub_theme;
            return [
              <tr key={t.id} className={`theme-row ${selected ? "selected" : ""}`} onClick={() => clickTheme(t)}>
                <td>
                  <button
                    className="chev"
                    aria-label={isOpen ? "Collapse" : "Expand"}
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpen({ ...open, [t.id]: !isOpen });
                    }}
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                  <strong>{t.name}</strong>
                  {t.new_topic && <span className="badge" title="Found while tagging, not in the first list of themes">new topic</span>}
                  <div className="volume" style={{ width: `${(100 * t.count) / max}%` }} />
                </td>
                <td className="num">
                  {t.count}
                  <span className="muted small"> · {pct(t.count, data.analysed_reviews)}%</span>
                </td>
                <td className="bar-cell">
                  <SentimentBar {...t} />
                </td>
                <td className={`num ${pct(t.negative, t.count) >= 60 ? "neg-text" : ""}`}>{pct(t.negative, t.count)}%</td>
              </tr>,
              ...(isOpen
                ? t.sub_themes.map((s) => (
                    <tr
                      key={`${t.id}-${s.id}`}
                      className={`sub-row ${selection?.sub_theme === s.id ? "selected" : ""}`}
                      onClick={() => onSelect({ theme: t.id, themeName: t.name, sub_theme: s.id, subName: s.name })}
                    >
                      <td className="sub-name">{s.name}</td>
                      <td className="num">{s.count}</td>
                      <td className="bar-cell">
                        <SentimentBar {...s} />
                      </td>
                      <td className="num">{pct(s.negative, s.count)}%</td>
                    </tr>
                  ))
                : []),
            ];
          })}
        </tbody>
      </table>
      {data.none_count > 0 && (
        <p className="muted small foot">
          {data.none_count} review(s) had no real content (e.g. "ok", "👍") and are not counted in any theme.
        </p>
      )}
    </section>
  );
}
