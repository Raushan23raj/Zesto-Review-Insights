"""Background theme-finding run.

Why a background thread: labelling 300-1000 reviews with an LLM takes a minute or more, far too
long for one HTTP request. POST /api/import returns at once; a thread does the work and writes
progress to AnalysisJob. GET /api/export/labels.csv answers 202 until the job is done.

The run is restartable: discovered themes and finished labels are stored as it goes, so if the
server restarts (or a key is added later), ensure_running() picks up where it stopped.
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from . import labelling, llm
from .models import AnalysisJob, Review, ReviewLabel, SubTheme, Theme

log = logging.getLogger(__name__)

BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE") or 20)
CONCURRENCY = int(os.environ.get("LLM_CONCURRENCY") or 4)
DISCOVERY_SAMPLE = int(os.environ.get("LLM_DISCOVERY_SAMPLE") or 350)

_running = set()
_lock = threading.Lock()


# ------------------------------------------------------------------ starting / resuming

def start_analysis(job_id):
    """Run the job in a background thread (no-op if this process is already running it)."""
    with _lock:
        if job_id in _running:
            return
        _running.add(job_id)
    threading.Thread(target=_thread_main, args=(job_id,), daemon=True, name=f"analysis-{job_id}").start()


def ensure_running():
    """Resume the latest job if it is unfinished and nobody is working on it (e.g. after a restart)."""
    job = AnalysisJob.latest()
    if not job:
        return
    resumable = job.status in AnalysisJob.ACTIVE or (
        job.status == AnalysisJob.Status.WAITING_FOR_KEY and llm.is_configured())
    if resumable and job.id not in _running:
        start_analysis(job.id)


def _thread_main(job_id):
    close_old_connections()
    try:
        run_job(job_id)
    finally:
        with _lock:
            _running.discard(job_id)
        connection.close()


# ------------------------------------------------------------------ the run itself

def _set(job, **fields):
    for k, v in fields.items():
        setattr(job, k, v)
    job.save()


def run_job(job_id, chat=None):
    """Discover themes (if not yet done), then label every unlabelled review.

    `chat` is the LLM call (system, user) -> dict; tests pass a fake.
    """
    chat = chat or llm.chat_json
    job = AnalysisJob.objects.get(pk=job_id)
    if chat is llm.chat_json and not llm.is_configured():
        _set(job, status=AnalysisJob.Status.WAITING_FOR_KEY, error="No LLM key configured")
        return job
    try:
        _set(job, total_reviews=Review.objects.count(), error="")
        _label_content_free()

        if not Theme.objects.exclude(name=labelling.NONE).exists():
            _set(job, status=AnalysisJob.Status.DISCOVERING)
            _discover(chat)

        _set(job, status=AnalysisJob.Status.LABELLING)
        failed = _label_all(job, chat)

        _prune_empty()
        _set(job, status=AnalysisJob.Status.DONE, failed_reviews=failed,
             labelled_reviews=_labelled_count(), finished_at=timezone.now())
    except llm.LLMNotConfigured:
        _set(job, status=AnalysisJob.Status.WAITING_FOR_KEY, error="No LLM key configured")
    except Exception as e:  # keep the error visible in the UI instead of dying silently
        log.exception("analysis job %s failed", job_id)
        _set(job, status=AnalysisJob.Status.FAILED, error=str(e)[:1000])
    return job


def _labelled_count():
    return Review.objects.filter(labels__isnull=False).distinct().count()


def _none_sub():
    theme, _ = Theme.objects.get_or_create(name=labelling.NONE, defaults={"description": "No real content"})
    sub, _ = SubTheme.objects.get_or_create(theme=theme, name=labelling.NONE)
    return sub


def _label_content_free():
    sub = _none_sub()
    empty = [r for r in Review.objects.filter(labels__isnull=True) if labelling.is_content_free(r.text)]
    ReviewLabel.objects.bulk_create(
        [ReviewLabel(review=r, theme=sub.theme, sub_theme=sub, sentiment="neutral") for r in empty],
        ignore_conflicts=True)


def _discover(chat):
    qs = Review.objects.order_by("?")[:DISCOVERY_SAMPLE]
    sample = [{"review_id": r.review_id, "text": r.text} for r in qs]
    data = chat(labelling.DISCOVERY_SYSTEM, labelling.discovery_prompt(sample))
    taxonomy = labelling.clean_taxonomy(data)
    if not taxonomy:
        raise RuntimeError("The LLM did not return any themes")
    with transaction.atomic():
        for t in taxonomy:
            theme, _ = Theme.objects.get_or_create(name=t["name"], defaults={"description": t["description"]})
            for s in t["sub_themes"]:
                SubTheme.objects.get_or_create(theme=theme, name=s["name"], defaults={"description": s["description"]})


def current_taxonomy():
    return [
        {"name": t.name, "description": t.description,
         "sub_themes": [{"name": s.name, "description": s.description} for s in t.sub_themes.all()]}
        for t in Theme.objects.exclude(name=labelling.NONE).prefetch_related("sub_themes")
    ]


def _ask_batch(chat, taxonomy, batch):
    """One LLM call for one batch. Returns ({review_id: topics}, error_or_None)."""
    try:
        data = chat(labelling.LABEL_SYSTEM, labelling.label_prompt(taxonomy, batch))
        return labelling.parse_label_response(data, [r["review_id"] for r in batch]), None
    except Exception as e:
        if getattr(e, "fatal", False) or isinstance(e, llm.LLMNotConfigured):
            raise
        return {}, e


def _label_all(job, chat):
    """Label unlabelled reviews in waves of parallel batches. Returns how many we gave up on."""
    todo = [{"review_id": r.review_id, "rating": r.rating, "text": r.text}
            for r in Review.objects.filter(labels__isnull=True).order_by("review_id")]
    batch_size = BATCH_SIZE
    for attempt in range(3):  # 3rd attempt uses small batches for whatever is still missing
        if not todo:
            break
        if attempt == 2:
            batch_size = 5
        batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
        missing = []
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            for w in range(0, len(batches), CONCURRENCY):
                if AnalysisJob.latest().id != job.id:  # a newer import/re-run took over
                    return 0
                wave = batches[w:w + CONCURRENCY]
                taxonomy = current_taxonomy()  # refreshed each wave so new themes are reused
                for batch, (answers, _err) in zip(wave, pool.map(lambda b: _ask_batch(chat, taxonomy, b), wave)):
                    _save_answers(answers)
                    missing += [r for r in batch if r["review_id"] not in answers]
                _set(job, labelled_reviews=_labelled_count())
        todo = missing

    # Anything still missing after 3 tries is stored as NONE so the export is complete;
    # the count is shown in the UI so nobody mistakes it for a real "no content" review.
    if todo:
        sub = _none_sub()
        ReviewLabel.objects.bulk_create(
            [ReviewLabel(review=Review.objects.get(review_id=r["review_id"]), theme=sub.theme, sub_theme=sub,
                         sentiment="neutral") for r in todo], ignore_conflicts=True)
    return len(todo)


@transaction.atomic
def _save_answers(answers):
    taxonomy = current_taxonomy()
    for rid, topics in answers.items():
        rows, new_items = labelling.normalise_topics(topics, taxonomy)
        for theme_name, sub_name in new_items:
            theme, created = Theme.objects.get_or_create(name=theme_name, defaults={"discovered_late": True})
            SubTheme.objects.get_or_create(theme=theme, name=sub_name)
            if created:
                taxonomy.append({"name": theme_name, "description": "", "sub_themes": []})
            for t in taxonomy:
                if t["name"] == theme_name and sub_name not in [s["name"] for s in t["sub_themes"]]:
                    t["sub_themes"].append({"name": sub_name, "description": ""})
        review = Review.objects.get(review_id=rid)
        labels = []
        for theme_name, sub_name, sentiment in rows:
            if theme_name == labelling.NONE:
                sub = _none_sub()
            else:
                sub = SubTheme.objects.select_related("theme").get(theme__name=theme_name, name=sub_name)
            labels.append(ReviewLabel(review=review, theme=sub.theme, sub_theme=sub, sentiment=sentiment))
        ReviewLabel.objects.bulk_create(labels, ignore_conflicts=True)


def _prune_empty():
    """Drop sub-themes/themes that ended up with no reviews (keeps the dashboard clean)."""
    SubTheme.objects.filter(labels__isnull=True).delete()
    Theme.objects.filter(sub_themes__isnull=True).delete()


def reset_analysis():
    """Forget all themes and labels (reviews stay). Used by 'Re-analyse from scratch'."""
    ReviewLabel.objects.all().delete()
    SubTheme.objects.all().delete()
    Theme.objects.all().delete()
