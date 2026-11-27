# Zesto Review Insights

A dashboard that shows a product manager what customers talk about in app reviews, how they feel about each topic, and the reviews behind every number.

**Stack:** Django 5 + Django REST Framework · PostgreSQL 16 · React 18 + Vite · Docker Compose · LLM over plain HTTPS (no SDKs)

## Features

- **Themes found from the data**: the LLM proposes 5–12 themes with sub-themes. Nothing is hard-coded.
- **Per-topic sentiment**: each review is tagged with one (theme, sub-theme, sentiment) per topic it mentions.
- **Dashboard**: review count, share of reviews and a negative/positive bar for every theme and sub-theme. Sort by "most mentioned" or "most complaints".
- **Evidence**: click a theme or sub-theme to read the reviews behind the number, then filter by sentiment.
- **Filters**: city, platform, month and rating.
- **What changed**: share of each month's reviews that complain about each theme (previous month → latest), with a sparkline and "getting worse" / "improving" call-outs.
- **Ask**: ask a question in plain English (`POST /api/ask`). The LLM only turns it into a structured query; the database does the counting. Questions the data can't answer (e.g. revenue) get "can't answer".
- **Works without a key**: the app starts, imports reviews and shows "No LLM key configured". Add a key and restart, and the analysis resumes by itself.

## Quick start

Requirements: Docker and Docker Compose.

```bash
cp .env.example .env      # fill in ONE key (see below)
docker compose up --build
```

- UI: http://localhost:3000
- API health: http://localhost:8000/api/health

Then click **Choose CSV file** in the UI, or import from the terminal:

```bash
curl -F file=@data/reviews.csv localhost:8000/api/import
```

Run the tests:

```bash
docker compose exec backend python manage.py test
```

### Configuration

Set one key in `.env`. The first key found picks the provider, or force one with `LLM_PROVIDER`.

| Variable | Provider | Default model |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic | `claude-haiku-4-5` |
| `GEMINI_API_KEY` | Google Gemini | `gemini-2.5-flash` |
| `GROQ_API_KEY` | Groq | `llama-3.3-70b-versatile` |
| `OPENROUTER_API_KEY` | OpenRouter | `openai/gpt-4o-mini` |

Each provider has its own model variable (`OPENAI_MODEL`, `GEMINI_MODEL`, …). `LLM_MODEL` overrides all of them. Ports can be changed with `API_PORT` (default 8000) and `WEB_PORT` (default 3000).

### Input format

A CSV with these columns (see `data/reviews.csv`, 300 reviews):

```
review_id,date,city,platform,rating,review_text
```

## Architecture

```
React (Vite, :3000)  ──►  Django REST API (:8000)  ──►  PostgreSQL
                               │
                               └─ background thread ──► LLM provider (HTTPS)
```

**Data model:** `Review` (raw CSV row) · `Theme` · `SubTheme` (FK theme) · `ReviewLabel` (review, theme, sub_theme, sentiment; unique per review+theme, which is exactly one export row) · `AnalysisJob` (status, progress, error).

**Analysis runs in a background thread**, started by `POST /api/import`. The request returns `202` at once, because labelling hundreds of reviews takes about a minute. Progress is stored in `AnalysisJob`, and the UI polls `/api/status`. It works in two passes (`reviews/labelling.py`, `reviews/pipeline.py`):

1. **Discover:** the LLM reads the reviews and proposes themes with sub-themes.
2. **Label:** batches of 20 reviews, 4 in parallel. The LLM may add a new theme if nothing fits (shown as **new topic**). Names are matched loosely (case, typos). Reviews with no letters (`.`, `👍`) become `NONE` without an LLM call. Reviews the model skips are retried, then retried in smaller batches. Anything still missing is exported as `NONE` and counted in the UI.

Progress is saved, so the job is resumable: if the server restarts, the next `/api/status` or export call continues it.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | 200 when the DB is ready |
| `POST /api/import` | CSV upload (`file`), starts analysis, returns `202` |
| `GET /api/export/labels.csv` | `202` while running, `503` if no key / failed, then `200` with the CSV |
| `GET /api/status` | LLM config + job progress (the UI polls this) |
| `POST /api/analysis/run` | Re-run analysis; `{"reset": true}` rebuilds themes from scratch |
| `GET /api/themes` · `/api/reviews` · `/api/trends` · `/api/filters` | Dashboard data; all accept `city, platform, month, rating` |
| `POST /api/ask` | Question → answer + evidence review ids |

## Project structure

```
.
├── backend/
│   ├── config/            Django settings, urls, wsgi
│   └── reviews/
│       ├── llm.py         standard-library LLM client (5 providers)
│       ├── labelling.py   theme discovery + batch labelling
│       ├── pipeline.py    background job, progress, resume
│       ├── importer.py    CSV import
│       ├── queries.py     themes / trends / filters queries
│       ├── ask.py         question → structured query → answer
│       ├── models.py · views.py · urls.py
│       └── tests/
├── frontend/src/          App.jsx, api.js, components/ (ThemeList, Trends, ReviewPanel, AskBox, Filters, StatusBanner)
├── data/
│   ├── reviews.csv        sample reviews
│   └── labels.csv         reference labels for scoring
├── check_labels.py        compares your export with the reference labels
└── docker-compose.yml     db + backend + frontend
```

## How well it works

```bash
curl -s localhost:8000/api/export/labels.csv > my_labels.csv
python3 check_labels.py my_labels.csv
```

The script matches each of your themes to the reference theme with the most shared reviews, then reports theme precision / recall / F1 and sentiment accuracy.

Model used: `TODO`

```
TODO: paste the output here
```

Two cases it gets wrong:

1. TODO (review id, what we said vs. the reference label, why)
2. TODO

## AI tools

TODO: list each tool and what you used it for.

## Design decisions

- **User:** Priya, the PM. **Decision:** which customer problem to fix first, and whether a fix worked.
- **"What changed" uses shares, not counts**, because review volume changes month to month and raw counts would mislead.
- **No new packages:** the LLM is called over plain HTTPS with Python's standard library.
- **Left out on purpose:** login/users, editing labels by hand, multiple datasets/projects, charts beyond what helps the decision.

## Next steps

- Merge near-duplicate new themes with a final consolidation pass, and let the PM rename or merge themes in the UI.
- Move the background work to a task queue (Celery/RQ) for many users and large files.
- Measure accuracy per theme, tune prompts on the failure cases, and cache LLM answers.
- Alerts when a theme's complaint share jumps week over week.
