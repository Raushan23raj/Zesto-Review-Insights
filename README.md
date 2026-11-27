# Zesto Review Insights

A dashboard that shows a product manager what customers talk about in app reviews, how they feel about each topic, and the reviews behind every number.

## How to run
```bash
cp .env.example .env      # fill in ONE key: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY
docker compose up --build # UI http://localhost:3000 · API http://localhost:8000/api/health
```
Then click **Choose CSV file** in the UI (or `curl -F file=@data/reviews.csv localhost:8000/api/import`).
Tests: `docker compose exec backend python manage.py test`

What's different from the starter:
- No new packages. The LLM is called over plain HTTPS with Python's standard library (`backend/reviews/llm.py`).
- The first key that is set picks the provider. I developed with OpenRouter (`OPENROUTER_API_KEY`), but any of the standard keys works. Each provider has its own model variable (`OPENAI_MODEL`, `GEMINI_MODEL`, …) so the app works whichever key you fill in. `LLM_MODEL` overrides all of them.
- No key? The app still starts, imports reviews and shows "No LLM key configured". Add a key and restart, and the analysis then resumes by itself.

## Product
- **User:** Priya, the PM. **Decision:** which customer problem to fix first, and whether a fix worked.
- **Dashboard:** themes → sub-themes with review counts, share of reviews, and a negative/positive bar. You can sort by "most mentioned" or "most complaints". Click a theme or sub-theme to read its reviews, then filter them by sentiment. You can filter by city, platform, month and rating. Topics found during tagging that weren't in the first list are marked **new topic**.
- **My feature: "What changed"** (previous month → latest month). It shows the share of each month's reviews that complain about each theme, sorted by the biggest change, with a sparkline and "getting worse" / "improving" call-outs. **Why:** a PM opens this weekly, and the first question is "what got worse since last time?" A total count can't answer that, and raw counts would mislead because review volume changes month to month.
- **Bonus:** `POST /api/ask`. The LLM only turns the question into a structured query. The database does the counting, and the answer sentence is built from those counts. Questions the data can't answer (for example revenue) get "can't answer".
- **Left out on purpose:** login/users, editing labels by hand, multiple datasets/projects, charts beyond what helps the decision.

## Architecture
**Data model:** `Review` (raw CSV row) · `Theme` · `SubTheme` (FK theme) · `ReviewLabel` (review, theme, sub_theme, sentiment, **unique per review+theme**, which is exactly one export row) · `AnalysisJob` (status, progress, error).

**Theme-finding runs in a background thread**, started by `POST /api/import`. The request returns `202` at once, because labelling hundreds of reviews takes about a minute. Progress is stored in `AnalysisJob`, and the UI polls `/api/status`. It works in two passes (`reviews/labelling.py`, `reviews/pipeline.py`):
1. **Discover:** the LLM reads the reviews and proposes 5–12 themes with sub-themes. Nothing is hard-coded, so new topics in new data get their own themes.
2. **Label:** batches of 20 reviews, 4 in parallel. For each review the LLM returns one (theme, sub-theme, sentiment) per topic it mentions. It may add a new theme if nothing fits. Names are matched loosely (case, typos). Reviews with no letters (`.`, `👍`) become `NONE` without an LLM call. Reviews the model skips are retried, then in smaller batches. Anything still missing after that is exported as `NONE` and counted in the UI.

Saved progress makes the job resumable: if the server restarts, the next `/api/status` or export call continues it.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | 200 when DB is ready |
| `POST /api/import` | CSV upload (`file`), starts analysis, `202` |
| `GET /api/export/labels.csv` | `202` while running, `503` if no key / failed, then `200` CSV |
| `GET /api/status` | LLM config + job progress (UI polls this) |
| `POST /api/analysis/run` | re-run; `{"reset": true}` rebuilds themes from scratch |
| `GET /api/themes` · `/api/reviews` · `/api/trends` · `/api/filters` | dashboard data; all accept `city, platform, month, rating` |
| `POST /api/ask` | question → answer + evidence review ids |

## How well it works
`curl -s localhost:8000/api/export/labels.csv > my_labels.csv && python3 check_labels.py my_labels.csv` (model: `TODO`)
```
TODO: paste the output here
```
Two cases it gets wrong:
1. TODO (review id, what we said vs. the gold label, why)
2. TODO

## AI tools
TODO: list each tool and what you used it for.

## Next steps (with another day)
- Merge near-duplicate new themes with a final consolidation pass, and let Priya rename or merge themes in the UI.
- Move the background work to a proper task queue (Celery/RQ) for many users and large files.
- Measure accuracy per theme and tune the prompts on the cases it gets wrong; cache LLM answers.
- Alerts when a theme's complaint share jumps week over week.
