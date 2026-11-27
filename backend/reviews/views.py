import csv
import io

from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import ask, llm, pipeline, queries
from .importer import ImportError_, import_reviews
from .models import AnalysisJob, Review, ReviewLabel


def _job_json(job):
    if not job:
        return None
    return {"id": job.id, "status": job.status, "total_reviews": job.total_reviews,
            "labelled_reviews": job.labelled_reviews, "failed_reviews": job.failed_reviews,
            "error": job.error, "created_at": job.created_at, "finished_at": job.finished_at}


@api_view(["GET"])
def health(request):
    connection.ensure_connection()
    return Response({"status": "ok", "llm_configured": settings.LLM_CONFIGURED or llm.is_configured()})


@api_view(["GET"])
def status_view(request):
    """What the UI polls: is there data, is the LLM set up, how far is the analysis."""
    pipeline.ensure_running()
    return Response({"llm": llm.describe(), "review_count": Review.objects.count(),
                     "job": _job_json(AnalysisJob.latest())})


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def import_view(request):
    upload = request.FILES.get("file")
    if not upload:
        return Response({"error": "Upload a CSV file in a form field named 'file'."}, status=400)
    try:
        result = import_reviews(upload.read())
    except ImportError_ as e:
        return Response({"error": str(e)}, status=400)
    job = AnalysisJob.objects.create(total_reviews=Review.objects.count())
    pipeline.start_analysis(job.id)
    return Response({**result, "job": _job_json(job), "llm_configured": llm.is_configured()},
                    status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
@parser_classes([JSONParser, FormParser])
def rerun_view(request):
    """Re-run the analysis. {"reset": true} also forgets the current themes and starts fresh."""
    if not Review.objects.exists():
        return Response({"error": "Import reviews first."}, status=400)
    if request.data.get("reset"):
        pipeline.reset_analysis()
    job = AnalysisJob.objects.create(total_reviews=Review.objects.count())
    pipeline.start_analysis(job.id)
    return Response({"job": _job_json(job)}, status=202)


@api_view(["GET"])
def export_labels(request):
    """202 while themes are being worked out, then 200 + CSV: review_id,theme,sub_theme,sentiment."""
    pipeline.ensure_running()
    job = AnalysisJob.latest()
    if not job:
        return Response({"status": "no_data", "detail": "No reviews imported yet."}, status=404)
    if job.status != AnalysisJob.Status.DONE:
        code = 503 if job.status in (AnalysisJob.Status.FAILED, AnalysisJob.Status.WAITING_FOR_KEY) else 202
        return Response({"status": job.status, "detail": job.error or "Analysis in progress",
                         "job": _job_json(job)}, status=code)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["review_id", "theme", "sub_theme", "sentiment"])
    for row in (ReviewLabel.objects.order_by("review__review_id", "theme__name")
                .values_list("review__review_id", "theme__name", "sub_theme__name", "sentiment")):
        writer.writerow(row)
    response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="labels.csv"'
    return response


@api_view(["GET"])
def filters_view(request):
    return Response(queries.filter_options())


@api_view(["GET"])
def themes_view(request):
    return Response(queries.theme_summary(request.query_params))


@api_view(["GET"])
def reviews_view(request):
    return Response(queries.review_list(request.query_params))


@api_view(["GET"])
def trends_view(request):
    return Response(queries.trends(request.query_params))


@api_view(["POST"])
@parser_classes([JSONParser])
def ask_view(request):
    if not llm.is_configured():
        return Response({"answer": "No LLM key is configured, so questions can't be understood yet. "
                                   "Add a key to .env and restart.", "evidence_review_ids": []}, status=503)
    try:
        return Response(ask.answer_question(str(request.data.get("question", ""))))
    except llm.LLMError as e:
        return Response({"answer": f"The language model failed to read the question ({e}). Please try again.",
                         "evidence_review_ids": []}, status=502)
