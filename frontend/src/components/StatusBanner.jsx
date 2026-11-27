import { useRef, useState } from "react";
import { api, ACTIVE_STATUSES, pct } from "../api.js";

const STEP_TEXT = {
  pending: "Starting the analysis…",
  discovering: "Reading the reviews to find the themes…",
  labelling: "Tagging each review with its themes and sentiment…",
};

export function UploadCard({ onDone, compact = false }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function send(file) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.upload(file);
      setResult(r);
      onDone?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className={compact ? "upload compact" : "upload card"}>
      {!compact && (
        <>
          <h2>Import reviews to get started</h2>
          <p className="muted">
            A CSV with columns <code>review_id, date, city, platform, rating, review_text</code>.
          </p>
        </>
      )}
      <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => send(e.target.files[0])} />
      <button className={compact ? "btn ghost" : "btn primary"} disabled={busy} onClick={() => input.current.click()}>
        {busy ? "Uploading…" : compact ? "Import more reviews" : "Choose CSV file"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {result && !compact && (
        <p className="muted">
          Imported {result.created} reviews{result.skipped ? ` (${result.skipped} already existed)` : ""}.
        </p>
      )}
    </div>
  );
}

export default function StatusBanner({ status, onChange }) {
  const [busy, setBusy] = useState(false);
  const job = status?.job;
  if (!status || !job) return null;

  async function rerun(reset) {
    setBusy(true);
    try {
      await api.post("analysis/run", { reset });
      onChange?.();
    } finally {
      setBusy(false);
    }
  }

  if (job.status === "waiting_for_key" || !status.llm?.configured) {
    if (job.status === "done") return null; // results exist from an earlier run with a key
    return (
      <div className="banner warn">
        <strong>No LLM key configured.</strong> Your {status.review_count} reviews are imported, but themes can't be
        found without a language model. Add one key (for example <code>OPENAI_API_KEY</code> or{" "}
        <code>GEMINI_API_KEY</code>) to <code>.env</code> and restart with <code>docker compose up</code>. The
        analysis will then start by itself.
      </div>
    );
  }

  if (ACTIVE_STATUSES.includes(job.status)) {
    const total = job.total_reviews || status.review_count;
    const done = job.labelled_reviews;
    return (
      <div className="banner info">
        <div className="row-between">
          <span>
            <span className="spinner" /> {STEP_TEXT[job.status]}
          </span>
          {job.status === "labelling" && (
            <span className="muted">
              {done} / {total} reviews
            </span>
          )}
        </div>
        <div className="progress">
          <div style={{ width: `${job.status === "labelling" ? Math.max(5, pct(done, total)) : 5}%` }} />
        </div>
      </div>
    );
  }

  if (job.status === "failed") {
    return (
      <div className="banner error">
        <strong>The analysis stopped with an error.</strong> <span className="mono">{job.error}</span>
        <div style={{ marginTop: 8 }}>
          <button className="btn" disabled={busy} onClick={() => rerun(false)}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (job.status === "done" && job.failed_reviews > 0) {
    return (
      <div className="banner warn">
        {job.failed_reviews} review(s) could not be analysed after several tries and are counted as "no content".
      </div>
    );
  }
  return null;
}
