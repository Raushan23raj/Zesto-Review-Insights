"""Read-side queries shared by the dashboard endpoints and /api/ask. All numbers come from the DB."""
from collections import defaultdict

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from .labelling import NONE
from .models import Review, ReviewLabel, SubTheme, Theme

REVIEW_FILTERS = ("city", "platform", "month", "rating")


def filter_reviews(params, skip=()):
    """Apply the dashboard filters (city, platform, month=YYYY-MM, rating) to Review."""
    qs = Review.objects.all()
    city, platform = params.get("city"), params.get("platform")
    month, rating = params.get("month"), params.get("rating")
    if city and "city" not in skip:
        qs = qs.filter(city__iexact=city)
    if platform and "platform" not in skip:
        qs = qs.filter(platform__iexact=platform)
    if month and "month" not in skip:
        try:
            y, m = (int(x) for x in str(month).split("-")[:2])
            qs = qs.filter(date__year=y, date__month=m)
        except ValueError:
            pass
    if rating and "rating" not in skip:
        try:
            qs = qs.filter(rating=int(rating))
        except ValueError:
            pass
    return qs


def filter_options():
    months = (Review.objects.exclude(date=None).annotate(m=TruncMonth("date"))
              .values_list("m", flat=True).distinct().order_by("m"))
    return {
        "cities": sorted(set(Review.objects.exclude(city="").values_list("city", flat=True))),
        "platforms": sorted(set(Review.objects.exclude(platform="").values_list("platform", flat=True))),
        "months": [m.strftime("%Y-%m") for m in months],
        "ratings": sorted(set(Review.objects.exclude(rating=None).values_list("rating", flat=True))),
    }


def theme_summary(params):
    """Themes -> sub-themes with review counts and sentiment split, for the filtered reviews."""
    reviews = filter_reviews(params)
    total = reviews.count()
    labels = ReviewLabel.objects.filter(review__in=reviews)
    analysed = reviews.filter(labels__isnull=False).distinct().count()

    themes = {t.id: {"id": t.id, "name": t.name, "description": t.description, "new_topic": t.discovered_late,
                     "count": 0, "positive": 0, "negative": 0, "neutral": 0, "sub_themes": {}}
              for t in Theme.objects.all()}
    subs = {s.id: s for s in SubTheme.objects.all()}
    for row in labels.values("theme_id", "sub_theme_id", "sentiment").annotate(n=Count("id")):
        t = themes.get(row["theme_id"])
        if not t:
            continue
        t["count"] += row["n"]
        t[row["sentiment"]] += row["n"]
        s = t["sub_themes"].setdefault(row["sub_theme_id"], {
            "id": row["sub_theme_id"], "name": subs[row["sub_theme_id"]].name,
            "description": subs[row["sub_theme_id"]].description,
            "count": 0, "positive": 0, "negative": 0, "neutral": 0})
        s["count"] += row["n"]
        s[row["sentiment"]] += row["n"]

    none_count = 0
    out = []
    for t in themes.values():
        if t["name"] == NONE:
            none_count = t["count"]
            continue
        if not t["count"]:
            continue
        t["sub_themes"] = sorted(t["sub_themes"].values(), key=lambda s: -s["count"])
        out.append(t)
    out.sort(key=lambda t: -t["count"])
    return {"total_reviews": total, "analysed_reviews": analysed, "none_count": none_count, "themes": out}


def label_filter(params):
    """Q on ReviewLabel for theme / sub_theme / sentiment params."""
    q = Q()
    if params.get("theme"):
        q &= Q(theme_id=params["theme"])
    if params.get("sub_theme"):
        q &= Q(sub_theme_id=params["sub_theme"])
    if params.get("sentiment"):
        q &= Q(sentiment=params["sentiment"])
    return q


def review_list(params):
    reviews = filter_reviews(params)
    if params.get("ids"):
        reviews = reviews.filter(review_id__in=[i.strip() for i in str(params["ids"]).split(",") if i.strip()])
    lq = label_filter(params)
    if lq:
        reviews = reviews.filter(id__in=ReviewLabel.objects.filter(lq).values("review_id"))
    if params.get("q"):
        reviews = reviews.filter(text__icontains=params["q"])
    try:
        page = max(1, int(params.get("page", 1)))
        size = min(200, max(1, int(params.get("page_size", 50))))
    except ValueError:
        page, size = 1, 50
    count = reviews.count()
    rows = reviews.prefetch_related("labels__theme", "labels__sub_theme")[(page - 1) * size: page * size]
    return {"count": count, "page": page, "page_size": size, "results": [serialize_review(r) for r in rows]}


def serialize_review(r):
    return {
        "review_id": r.review_id, "date": r.date.isoformat() if r.date else None, "city": r.city,
        "platform": r.platform, "rating": r.rating, "text": r.text,
        "labels": [{"theme": lb.theme.name, "theme_id": lb.theme_id, "sub_theme": lb.sub_theme.name,
                    "sentiment": lb.sentiment} for lb in r.labels.all()],
    }


def trends(params):
    """Per month: share of reviews mentioning each theme, and share that are negative about it.

    Shares (not raw counts) because review volume changes month to month.
    The month filter is ignored here: the point is to compare months.
    """
    reviews = filter_reviews(params, skip=("month",)).exclude(date=None)
    totals = {row["m"].strftime("%Y-%m"): row["n"] for row in
              reviews.annotate(m=TruncMonth("date")).values("m").annotate(n=Count("id")).order_by("m")}
    months = list(totals)
    data = defaultdict(lambda: defaultdict(lambda: {"mentions": 0, "negative": 0}))
    names = {}
    rows = (ReviewLabel.objects.filter(review__in=reviews).exclude(theme__name=NONE)
            .annotate(m=TruncMonth("review__date"))
            .values("theme_id", "theme__name", "m", "sentiment").annotate(n=Count("id")))
    for row in rows:
        month = row["m"].strftime("%Y-%m")
        names[row["theme_id"]] = row["theme__name"]
        cell = data[row["theme_id"]][month]
        cell["mentions"] += row["n"]
        if row["sentiment"] == "negative":
            cell["negative"] += row["n"]

    themes = []
    for tid, by_month in data.items():
        series = []
        for m in months:
            c = by_month.get(m, {"mentions": 0, "negative": 0})
            n = totals[m] or 1
            series.append({"month": m, "mentions": c["mentions"], "negative": c["negative"],
                           "mention_share": round(c["mentions"] / n, 4),
                           "negative_share": round(c["negative"] / n, 4)})
        change = None
        if len(series) >= 2:
            change = round((series[-1]["negative_share"] - series[-2]["negative_share"]) * 100, 1)
        themes.append({"id": tid, "name": names[tid], "series": series, "negative_change_pp": change})
    themes.sort(key=lambda t: -(abs(t["negative_change_pp"]) if t["negative_change_pp"] is not None else 0))
    return {"months": months, "totals": totals, "themes": themes,
            "latest_month": months[-1] if months else None, "previous_month": months[-2] if len(months) > 1 else None}
