"""Theme-finding logic: prompts + cleaning up what the LLM returns.

Two passes:
  1. discover_taxonomy(): show the LLM the reviews, ask it to propose themes and sub-themes.
     Nothing is hard-coded, so new topics in new data get their own themes.
  2. label_batch(): for ~20 reviews at a time, ask which theme/sub-theme(s) each review is about
     and the sentiment for each. The LLM may add a new theme if nothing fits.

This module has no Django imports, so it can be tested with a fake LLM.
"""
import difflib
import re

NONE = "NONE"
SENTIMENTS = {"positive", "negative", "neutral"}
MAX_TEXT = 400  # characters of each review sent to the LLM


def is_content_free(text):
    """Reviews like '.', '👍', '...' have no letters at all -> NONE without asking the LLM."""
    return len(re.findall(r"[^\W\d_]", text or "")) < 2


def _clip(text):
    text = " ".join((text or "").split())
    return text[:MAX_TEXT]


# ---------------------------------------------------------------- pass 1: discover themes

DISCOVERY_SYSTEM = (
    "You are a customer-insights analyst. You build a clear taxonomy of what customers talk about "
    "in app-store reviews, for a product manager who has to act on it."
)

DISCOVERY_PROMPT = """Below are customer reviews of a food-delivery app (one per line: id | text).

Build a two-level taxonomy of the topics customers talk about:
- 5 to 12 THEMES: broad areas a product team would own (example format: "Delivery").
- Each theme has 1 to 5 SUB-THEMES: specific aspects (example format: "Delivery Time").
- Name things neutrally so that praise and complaints fit the same sub-theme
  (e.g. "Delivery Time", not "Late Delivery").
- Cover EVERY recurring topic, including smaller ones mentioned by only a few reviews.
- Sub-themes must not overlap: a given complaint should clearly belong to one sub-theme.
- No catch-all themes such as "General Feedback" or "Overall Experience".
- Ignore reviews with no real content (gibberish, emoji, "ok", "hmm").

Return JSON only:
{{"themes": [{{"name": "...", "description": "one sentence",
  "sub_themes": [{{"name": "...", "description": "one sentence"}}]}}]}}

Reviews:
{reviews}"""


def discovery_prompt(reviews):
    lines = "\n".join(f"{r['review_id']} | {_clip(r['text'])}" for r in reviews if not is_content_free(r["text"]))
    return DISCOVERY_PROMPT.format(reviews=lines)


def clean_taxonomy(data):
    """LLM output -> [{"name", "description", "sub_themes": [{"name", "description"}]}], deduplicated."""
    themes, seen = [], set()
    for t in (data or {}).get("themes", []) or []:
        name = _title(t.get("name"))
        if not name or name.upper() == NONE or name.lower() in seen:
            continue
        seen.add(name.lower())
        subs, sub_seen = [], set()
        for s in t.get("sub_themes", []) or []:
            sname = _title(s.get("name") if isinstance(s, dict) else s)
            if sname and sname.lower() not in sub_seen:
                sub_seen.add(sname.lower())
                subs.append({"name": sname, "description": (s.get("description") if isinstance(s, dict) else "") or ""})
        themes.append({"name": name, "description": t.get("description") or "", "sub_themes": subs or [{"name": "General", "description": ""}]})
    return themes


# ---------------------------------------------------------------- pass 2: label reviews

LABEL_SYSTEM = (
    "You label customer reviews of a food-delivery app against a fixed taxonomy of themes and "
    "sub-themes. You are precise: you tag every topic a review mentions and nothing it does not."
)

LABEL_PROMPT = """Taxonomy (THEME > sub-themes):
{taxonomy}

For each review below, list every topic it talks about.
Rules:
- One entry per THEME the review mentions. Pick the single best sub-theme inside that theme.
- A review can mention several themes ("food was cold and the rider was rude" = 2 entries).
  Tag a topic even if it is mentioned briefly or at the end.
- Filler phrases ("ordered late at night", "uninstalling", "happy customer", "sigh") are not topics
  by themselves; they only tell you the sentiment.
- sentiment is the customer's feeling about THAT topic: "positive" or "negative".
  Use "neutral" only if the topic is mentioned with no opinion at all.
- Reviews with no real content (gibberish, emoji, "ok", "hmm", "nice") get exactly one entry:
  {{"theme": "NONE", "sub_theme": "NONE", "sentiment": "neutral"}}
- Use the taxonomy names exactly. Only if a topic clearly fits NO theme, invent a new short
  theme and sub-theme name (neutral wording) and add "new": true.

Return JSON only:
{{"results": [{{"id": "<review id>", "topics": [{{"theme": "...", "sub_theme": "...", "sentiment": "..."}}]}}]}}

Reviews (id | rating | text):
{reviews}"""


def taxonomy_text(taxonomy):
    out = []
    for t in taxonomy:
        subs = "; ".join(s["name"] for s in t["sub_themes"])
        desc = f" ({t['description']})" if t.get("description") else ""
        out.append(f"- {t['name']}{desc} > {subs}")
    return "\n".join(out)


def label_prompt(taxonomy, reviews):
    lines = "\n".join(f"{r['review_id']} | {r.get('rating') or '-'}* | {_clip(r['text'])}" for r in reviews)
    return LABEL_PROMPT.format(taxonomy=taxonomy_text(taxonomy), reviews=lines)


def _title(name):
    name = " ".join(str(name or "").split()).strip(" .:-")
    return name[:100]


def _best_match(name, candidates, cutoff=0.82):
    """Case-insensitive exact match, else close fuzzy match, else None."""
    lower = {c.lower(): c for c in candidates}
    if name.lower() in lower:
        return lower[name.lower()]
    close = difflib.get_close_matches(name.lower(), list(lower), n=1, cutoff=cutoff)
    return lower[close[0]] if close else None


def normalise_topics(topics, taxonomy):
    """Clean one review's topics from the LLM.

    Returns (rows, new_items):
      rows      = [(theme, sub_theme, sentiment)], at most one per theme, NONE only if alone
      new_items = [(theme, sub_theme)] that are not in the taxonomy yet (caller adds them)
    """
    theme_names = [t["name"] for t in taxonomy]
    subs_by_theme = {t["name"]: [s["name"] for s in t["sub_themes"]] for t in taxonomy}
    sub_owner = {}
    for t in taxonomy:
        for s in t["sub_themes"]:
            sub_owner.setdefault(s["name"].lower(), t["name"])

    rows, seen_themes, new_items = [], set(), []
    for topic in topics or []:
        if not isinstance(topic, dict):
            continue
        theme = _title(topic.get("theme"))
        sub = _title(topic.get("sub_theme"))
        sentiment = str(topic.get("sentiment", "")).strip().lower()
        if sentiment not in SENTIMENTS:
            sentiment = "negative" if sentiment.startswith("neg") else "positive" if sentiment.startswith("pos") else "neutral"

        if not theme or theme.upper() == NONE:
            rows.append((NONE, NONE, "neutral"))
            continue

        matched = _best_match(theme, theme_names)
        if not matched and sub and sub.lower() in sub_owner:   # right sub-theme, garbled theme name
            matched = sub_owner[sub.lower()]
        if matched:
            theme = matched
            sub_match = _best_match(sub, subs_by_theme[theme]) if sub else None
            if sub_match:
                sub = sub_match
            else:
                sub = sub or "General"
                new_items.append((theme, sub))
                subs_by_theme[theme].append(sub)
        else:
            sub = sub or "General"
            new_items.append((theme, sub))
            theme_names.append(theme)
            subs_by_theme[theme] = [sub]

        if theme in seen_themes:
            continue
        seen_themes.add(theme)
        rows.append((theme, sub, sentiment))

    real = [r for r in rows if r[0] != NONE]
    if real:
        return real, new_items
    return [(NONE, NONE, "neutral")], new_items


def parse_label_response(data, batch_ids):
    """LLM JSON -> {review_id: topics list} for ids that were in this batch."""
    out = {}
    wanted = set(batch_ids)
    for item in (data or {}).get("results", []) or []:
        rid = str(item.get("id", "")).strip()
        if rid in wanted and rid not in out:
            out[rid] = item.get("topics") or []
    return out
