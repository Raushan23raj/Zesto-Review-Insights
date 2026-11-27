const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function monthLabel(ym) {
  if (!ym) return "";
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES[Number(m) - 1]} ${y}`;
}

function Select({ label, value, options, onChange, format = (x) => x }) {
  return (
    <label className="filter">
      <span>{label}</span>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {format(o)}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function Filters({ options, filters, setFilters }) {
  if (!options) return null;
  const set = (key) => (value) => setFilters({ ...filters, [key]: value });
  const active = Object.values(filters).some(Boolean);
  return (
    <div className="filters">
      <Select label="City" value={filters.city} options={options.cities} onChange={set("city")} />
      <Select label="Platform" value={filters.platform} options={options.platforms} onChange={set("platform")}
        format={(p) => (p === "ios" ? "iOS" : p.charAt(0).toUpperCase() + p.slice(1))} />
      <Select label="Month" value={filters.month} options={options.months} onChange={set("month")} format={monthLabel} />
      <Select label="Rating" value={filters.rating} options={options.ratings.map(String)} onChange={set("rating")}
        format={(r) => `${r} ★`} />
      {active && (
        <button className="btn ghost" onClick={() => setFilters({})}>
          Clear filters
        </button>
      )}
    </div>
  );
}
