"""Compare your labels with ours on data/reviews.csv. Standard library only.

    curl -s http://localhost:8000/api/export/labels.csv > my_labels.csv
    python3 check_labels.py my_labels.csv

Your theme names don't have to match ours. Each of your themes is matched to the one of ours
that shares the most reviews (that's how we score too), then we report:
  - theme F1: did you put the right reviews under the right themes?
  - sentiment accuracy, on the (review, theme) pairs we both found
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

GOLD = Path(__file__).resolve().parent / "data" / "labels.csv"


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return [{k.strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def f1(a, b):
    tp = len(a & b)
    return 2 * tp / (len(a) + len(b)) if tp else 0.0


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    gold, mine = load(GOLD), load(sys.argv[1])
    g_by_theme, m_by_theme = defaultdict(set), defaultdict(set)
    for r in gold:
        g_by_theme[r["theme"]].add(r["review_id"])
    for r in mine:
        m_by_theme[r["theme"]].add(r["review_id"])

    mapping = {}
    print(f"{'your theme':30} {'reviews':>7}  ->  {'our theme':25} overlap F1")
    for t, ids in sorted(m_by_theme.items(), key=lambda x: -len(x[1])):
        best, score = max(((g, f1(ids, gids)) for g, gids in g_by_theme.items()), key=lambda x: x[1])
        mapping[t] = best if score >= 0.3 else "(no match)"
        print(f"{t[:30]:30} {len(ids):7}  ->  {mapping[t][:25]:25} {score:.2f}")

    gold_pairs = {(r["review_id"], r["theme"]) for r in gold}
    my_pairs = {(r["review_id"], mapping[r["theme"]]) for r in mine}
    tp = len(gold_pairs & my_pairs)
    p, rec = tp / max(len(my_pairs), 1), tp / max(len(gold_pairs), 1)
    print(f"\ntheme precision {p:.2f}  recall {rec:.2f}  F1 {2 * p * rec / (p + rec) if tp else 0:.2f}")

    g_sent = {(r["review_id"], r["theme"]): r["sentiment"] for r in gold}
    both = [((r["review_id"], mapping[r["theme"]]), r["sentiment"].lower()) for r in mine
            if (r["review_id"], mapping[r["theme"]]) in g_sent and mapping[r["theme"]] != "NONE"]
    if both:
        acc = sum(g_sent[k] == s for k, s in both) / len(both)
        print(f"sentiment accuracy {acc:.2f} on {len(both)} shared (review, theme) pairs")
    missing = {r["review_id"] for r in gold} - {r["review_id"] for r in mine}
    if missing:
        print(f"\n{len(missing)} reviews have no row in your file, e.g. {sorted(missing)[:3]}")


if __name__ == "__main__":
    main()
