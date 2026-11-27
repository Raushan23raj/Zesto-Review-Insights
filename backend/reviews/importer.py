"""CSV import: review_id, date, city, platform, rating, review_text."""
import csv
import io
from datetime import datetime

from django.db import transaction

from .models import Review

REQUIRED = {"review_id", "review_text"}
MAX_ROWS = 5000
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d")


class ImportError_(ValueError):
    """Raised for a file we cannot import at all (wrong columns, not a CSV, too big)."""


def _date(value):
    value = (value or "").strip()[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _rating(value):
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 5 else None


def parse_csv(raw_bytes):
    """Bytes -> list of clean dicts. Raises ImportError_ for unusable files."""
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportError_("The file is empty.")
    reader.fieldnames = [(f or "").strip().lower() for f in reader.fieldnames]
    missing = REQUIRED - set(reader.fieldnames)
    if missing:
        raise ImportError_(f"Missing column(s): {', '.join(sorted(missing))}")

    rows, seen = [], set()
    for line_no, row in enumerate(reader, start=2):
        if line_no - 1 > MAX_ROWS:
            raise ImportError_(f"Too many rows (max {MAX_ROWS}).")
        rid = (row.get("review_id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        rows.append({
            "review_id": rid[:64],
            "date": _date(row.get("date")),
            "city": (row.get("city") or "").strip()[:100],
            "platform": (row.get("platform") or "").strip().lower()[:50],
            "rating": _rating(row.get("rating")),
            "text": (row.get("review_text") or "").strip(),
        })
    if not rows:
        raise ImportError_("No reviews found in the file.")
    return rows


@transaction.atomic
def import_reviews(raw_bytes):
    """Store new reviews. Existing review_ids are skipped. Returns {"created", "skipped"}."""
    rows = parse_csv(raw_bytes)
    existing = set(Review.objects.filter(review_id__in=[r["review_id"] for r in rows])
                   .values_list("review_id", flat=True))
    new = [Review(**r) for r in rows if r["review_id"] not in existing]
    Review.objects.bulk_create(new, batch_size=500)
    return {"created": len(new), "skipped": len(rows) - len(new)}
