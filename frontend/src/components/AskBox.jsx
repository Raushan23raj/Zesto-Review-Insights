import { useState } from "react";
import { api } from "../api.js";

const EXAMPLES = [
  "What do customers complain about most?",
  "How many negative reviews about refunds?",
  "Which city has the most delivery complaints?",
];

export default function AskBox({ llmConfigured, onShowReviews }) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState({ loading: false, result: null, error: null });

  async function ask(q) {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    setState({ loading: true, result: null, error: null });
    try {
      setState({ loading: false, result: await api.post("ask", { question: text }), error: null });
    } catch (e) {
      setState({ loading: false, result: null, error: e.message });
    }
  }

  const { loading, result, error } = state;
  return (
    <section className="card">
      <h2>Ask the reviews</h2>
      <p className="muted small">Numbers are counted from the database, not guessed by the AI.</p>
      {!llmConfigured ? (
        <p className="muted">Needs an LLM key to understand questions.</p>
      ) : (
        <>
          <form
            className="ask-form"
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How many 1-star reviews mention late delivery in Pune?"
            />
            <button className="btn primary" disabled={loading}>
              {loading ? "Thinking…" : "Ask"}
            </button>
          </form>
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="link" onClick={() => ask(ex)}>
                {ex}
              </button>
            ))}
          </div>
        </>
      )}
      {error && <p className="error-text">{error}</p>}
      {result && (
        <div className="answer">
          {result.interpretation && <p className="muted small">Counted: {result.interpretation}</p>}
          <p>{result.answer}</p>
          {result.evidence_review_ids?.length > 0 && (
            <button
              className="btn ghost"
              onClick={() => onShowReviews({ ids: result.evidence_review_ids, title: `Evidence for: "${question}"` })}
            >
              Read {result.evidence_review_ids.length} example review(s)
            </button>
          )}
        </div>
      )}
    </section>
  );
}
