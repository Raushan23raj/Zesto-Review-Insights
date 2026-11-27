import { monthLabel } from "./Filters.jsx";

// "What changed" - Priya's Monday question: which problems got worse (or better) since last month?
// Uses the share of reviews that complain about a theme, so a busier month doesn't look worse by itself.

function Sparkline({ values, width = 90, height = 24 }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 0.01);
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`);
  return (
    <svg width={width} height={height} className="spark" aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" strokeWidth="1.5" />
      <circle cx={pts.at(-1).split(",")[0]} cy={pts.at(-1).split(",")[1]} r="2.5" />
    </svg>
  );
}

const fmt = (share) => `${Math.round(share * 100)}%`;

export default function Trends({ data, onSelect }) {
  if (!data) return null;
  const { months, themes, latest_month: latest, previous_month: previous } = data;

  if (months.length < 2) {
    return (
      <section className="card">
        <h2>What changed</h2>
        <p className="muted">Need reviews from at least two months to compare. Clear the month filter or import more data.</p>
      </section>
    );
  }

  const rows = themes.filter((t) => t.negative_change_pp !== null);
  const worst = rows.filter((t) => t.negative_change_pp > 0)[0];
  const best = [...rows].sort((a, b) => a.negative_change_pp - b.negative_change_pp).find((t) => t.negative_change_pp < 0);

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          What changed: {monthLabel(previous)} → {monthLabel(latest)}
        </h2>
        <p className="muted small">
          Share of each month's reviews that complain about a theme. Sorted by the biggest change. ({data.totals[previous]}{" "}
          reviews in {monthLabel(previous)}, {data.totals[latest]} in {monthLabel(latest)}.)
        </p>
      </div>

      <div className="callouts">
        {worst && (
          <div className="callout bad" onClick={() => onSelect({ theme: worst.id, themeName: worst.name, sentiment: "negative" })}>
            <span className="small">Getting worse</span>
            <strong>{worst.name}</strong>
            <span>
              complaints up {worst.negative_change_pp} pts ({fmt(worst.series.at(-2).negative_share)} →{" "}
              {fmt(worst.series.at(-1).negative_share)})
            </span>
          </div>
        )}
        {best && (
          <div className="callout good" onClick={() => onSelect({ theme: best.id, themeName: best.name, sentiment: "negative" })}>
            <span className="small">Improving</span>
            <strong>{best.name}</strong>
            <span>
              complaints down {Math.abs(best.negative_change_pp)} pts ({fmt(best.series.at(-2).negative_share)} →{" "}
              {fmt(best.series.at(-1).negative_share)})
            </span>
          </div>
        )}
      </div>

      <table className="themes trends">
        <thead>
          <tr>
            <th>Theme</th>
            <th>Complaints by month ({months.map(monthLabel).map((m) => m.slice(0, 3)).join(" · ")})</th>
            <th className="num">{monthLabel(previous)}</th>
            <th className="num">{monthLabel(latest)}</th>
            <th className="num">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const c = t.negative_change_pp;
            return (
              <tr key={t.id} className="theme-row" onClick={() => onSelect({ theme: t.id, themeName: t.name, sentiment: "negative" })}>
                <td>
                  <strong>{t.name}</strong>
                </td>
                <td>
                  <Sparkline values={t.series.map((s) => s.negative_share)} />
                </td>
                <td className="num">{fmt(t.series.at(-2).negative_share)}</td>
                <td className="num">{fmt(t.series.at(-1).negative_share)}</td>
                <td className={`num ${c > 0 ? "neg-text" : c < 0 ? "pos-text" : ""}`}>
                  {c > 0 ? "▲" : c < 0 ? "▼" : "–"} {Math.abs(c)} pts
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
