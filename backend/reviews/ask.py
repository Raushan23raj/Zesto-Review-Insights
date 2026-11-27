"""POST /api/ask - answer a question about the reviews.

The LLM is used ONLY to turn the question into a structured query (filters + grouping).
The numbers are counted by the database and the answer sentence is built from them here,
so the LLM can never invent a number. If the question can't be answered from this data,
we say so.
"""
from django.db.models import Count
from django.db.models.functions import TruncMonth

from . import llm
from .labelling import NONE, _best_match
from .models import Review, ReviewLabel, SubTheme, Theme
from .queries import filter_options, filter_reviews

GROUPS = {"theme": "theme__name", "sub_theme": "sub_theme__name", "sentiment": "sentiment",
          "city": "review__city", "platform": "review__platform", "rating": "review__rating"}

PLAN_SYSTEM = "You translate a product manager's question about app reviews into a JSON database query."

PLAN_PROMPT = """Data available: app-store reviews, each with date, city, platform, rating (1-5), text,
and labels (theme, sub_theme, sentiment positive/negative/neutral).

Known values:
themes and sub-themes: {taxonomy}
cities: {cities}
platforms: {platforms}
months: {months}

Question: {question}

Return JSON only:
{{"answerable": true/false,
  "reason": "if not answerable: why, in one sentence",
  "interpretation": "the question restated as what will be counted, one short sentence",
  "filters": {{"theme": null, "sub_theme": null, "sentiment": null, "city": null, "platform": null,
              "month": null, "rating_min": null, "rating_max": null}},
  "group_by": null}}

Rules:
- Use only the known values above (exact spelling). month is "YYYY-MM".
- group_by is one of: null, "theme", "sub_theme", "sentiment", "city", "platform", "rating", "month".
  Use it for "which/what is the most/top/compare" questions.
- "complaints"/"problems"/"unhappy" means sentiment "negative"; "praise"/"liked" means "positive".
- answerable is false if the question needs data we don't have (e.g. revenue, order volumes,
  customer age, competitors) or is not about these reviews."""


def _taxonomy_text():
    parts = []
    for t in Theme.objects.exclude(name=NONE).prefetch_related("sub_themes"):
        parts.append(f"{t.name} [{', '.join(s.name for s in t.sub_themes.all())}]")
    return "; ".join(parts) or "(none yet)"


def plan_question(question, chat=None):
    chat = chat or llm.chat_json
    opts = filter_options()
    prompt = PLAN_PROMPT.format(taxonomy=_taxonomy_text(), cities=", ".join(opts["cities"]),
                                platforms=", ".join(opts["platforms"]), months=", ".join(opts["months"]),
                                question=question.strip()[:500])
    return chat(PLAN_SYSTEM, prompt, max_tokens=600)


def _pct(a, b):
    return f"{round(100 * a / b)}%" if b else "0%"


def execute_plan(plan):
    """Run the structured query against the DB and build the answer text from real counts."""
    if not plan.get("answerable", True):
        reason = plan.get("reason") or "it needs data that isn't in the reviews"
        return {"answer": f"The review data can't answer that: {reason}", "evidence_review_ids": [], "data": None}

    f = plan.get("filters") or {}
    params = {k: f.get(k) for k in ("city", "platform", "month") if f.get(k)}
    reviews = filter_reviews(params)
    for key, lookup in (("rating_min", "rating__gte"), ("rating_max", "rating__lte")):
        try:
            if f.get(key):
                reviews = reviews.filter(**{lookup: int(f[key])})
        except (TypeError, ValueError):
            pass
    base_total = reviews.count()

    labels = ReviewLabel.objects.filter(review__in=reviews).exclude(theme__name=NONE)
    described = []
    if f.get("theme"):
        name = _best_match(str(f["theme"]), list(Theme.objects.values_list("name", flat=True)))
        if not name:
            return {"answer": f"There is no theme called '{f['theme']}' in the data.", "evidence_review_ids": [], "data": None}
        labels = labels.filter(theme__name=name)
        described.append(f"theme {name}")
    if f.get("sub_theme"):
        name = _best_match(str(f["sub_theme"]), list(SubTheme.objects.values_list("name", flat=True)))
        if not name:
            return {"answer": f"There is no sub-theme called '{f['sub_theme']}' in the data.", "evidence_review_ids": [], "data": None}
        labels = labels.filter(sub_theme__name=name)
        described.append(f"sub-theme {name}")
    if f.get("sentiment") in ("positive", "negative", "neutral"):
        labels = labels.filter(sentiment=f["sentiment"])
        described.append(f"{f['sentiment']} sentiment")
    for key in ("city", "platform", "month"):
        if f.get(key):
            described.append(f"{key} {f[key]}")
    if f.get("rating_min") or f.get("rating_max"):
        described.append(f"rating {f.get('rating_min') or 1}-{f.get('rating_max') or 5}")
    label_filtered = bool(f.get("theme") or f.get("sub_theme") or f.get("sentiment"))
    matched = reviews.filter(id__in=labels.values("review_id")) if label_filtered else reviews
    matched_count = matched.distinct().count()
    scope = ", ".join(described) or "all reviews"

    group_by = plan.get("group_by")
    if group_by in GROUPS or group_by == "month":
        groups, evidence = _group(group_by, labels, matched)
        if not groups:
            return {"answer": f"No reviews match ({scope}).", "evidence_review_ids": [], "data": {"groups": []}}
        top_name, top_n = max(groups, key=lambda g: g[1])
        listing = ", ".join(f"{g}: {n}" for g, n in groups[:8])
        answer = (f"By {group_by.replace('_', '-')} ({scope}, out of {base_total} reviews): {listing}. "
                  f"Highest is {top_name} with {top_n} reviews ({_pct(top_n, base_total)}).")
        ids = list(evidence(top_name).order_by("-date").values_list("review_id", flat=True)[:10])
        return {"answer": answer, "evidence_review_ids": ids,
                "data": {"group_by": group_by, "groups": [{"name": g, "reviews": n} for g, n in groups]}}

    answer = (f"{matched_count} of {base_total} reviews ({_pct(matched_count, base_total)}) match: {scope}."
              if label_filtered else f"There are {matched_count} reviews ({scope}).")
    ids = list(matched.order_by("-date").values_list("review_id", flat=True)[:10])
    return {"answer": answer, "evidence_review_ids": ids,
            "data": {"matched_reviews": matched_count, "out_of": base_total}}


def _group(group_by, labels, matched):
    """Count reviews per group. Returns ([(group, n)], evidence(group) -> Review queryset)."""
    if group_by in ("theme", "sub_theme", "sentiment"):
        field = GROUPS[group_by]
        rows = labels.values(field).annotate(n=Count("review_id", distinct=True)).order_by("-n")
        groups = [(str(r[field]), r["n"]) for r in rows]
        return groups, lambda g: Review.objects.filter(id__in=labels.filter(**{field: g}).values("review_id"))

    # review-level fields: count the matched reviews themselves
    base = matched.distinct()
    if group_by == "month":
        rows = base.exclude(date=None).annotate(g=TruncMonth("date")).values("g").annotate(n=Count("id")).order_by("g")
        groups = [(r["g"].strftime("%Y-%m"), r["n"]) for r in rows]

        def evidence(g):
            y, m = g.split("-")
            return base.filter(date__year=int(y), date__month=int(m))
        return groups, evidence
    field = group_by  # city / platform / rating
    rows = base.values(field).annotate(n=Count("id")).order_by("-n")
    groups = [(str(r[field]), r["n"]) for r in rows if r[field] not in (None, "")]
    return groups, lambda g: base.filter(**{field: int(g) if field == "rating" else g})


def answer_question(question, chat=None):
    if not question or not question.strip():
        return {"answer": "Please type a question.", "evidence_review_ids": []}
    if not Review.objects.exists():
        return {"answer": "There are no reviews yet. Import a CSV first.", "evidence_review_ids": []}
    plan = plan_question(question, chat)
    result = execute_plan(plan)
    result["interpretation"] = plan.get("interpretation", "")
    return result
