from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from reviews.models import AnalysisJob, Review
from reviews.pipeline import run_job

from .fakes import FakeLLM

CSV = (
    "review_id,date,city,platform,rating,review_text\n"
    'T-1,2026-07-20,Pune,Android,1,"Rider was late and rude"\n'
    'T-2,2026-08-02,Delhi,ios,5,"Really tasty biryani"\n'
    'T-3,2026-08-03,Delhi,ios,3,"."\n'
    'T-3,2026-08-03,Delhi,ios,3,"duplicate id in the same file"\n'
)


def upload(client, content, name="reviews.csv"):
    return client.post("/api/import", {"file": SimpleUploadedFile(name, content.encode(), "text/csv")})


@mock.patch("reviews.views.pipeline.start_analysis")  # don't start a real background thread
class ImportTests(TestCase):
    def test_import_stores_reviews_and_starts_analysis(self, start):
        r = upload(self.client, CSV)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["created"], 3)
        self.assertEqual(Review.objects.count(), 3)
        rev = Review.objects.get(review_id="T-1")
        self.assertEqual((str(rev.date), rev.city, rev.platform, rev.rating), ("2026-07-20", "Pune", "android", 1))
        start.assert_called_once_with(AnalysisJob.latest().id)

    def test_reimport_skips_existing_ids(self, start):
        upload(self.client, CSV)
        r = upload(self.client, CSV)
        self.assertEqual((r.json()["created"], r.json()["skipped"]), (0, 3))
        self.assertEqual(Review.objects.count(), 3)

    def test_rejects_missing_columns(self, start):
        r = upload(self.client, "id,text\n1,hello\n")
        self.assertEqual(r.status_code, 400)
        self.assertIn("review_id", r.json()["error"])
        start.assert_not_called()

    def test_rejects_request_without_file(self, start):
        self.assertEqual(self.client.post("/api/import").status_code, 400)

    def test_bad_rating_and_date_become_empty(self, start):
        upload(self.client, "review_id,date,rating,review_text\nX,not-a-date,9,hi there\n")
        rev = Review.objects.get(review_id="X")
        self.assertIsNone(rev.date)
        self.assertIsNone(rev.rating)


@mock.patch("reviews.views.pipeline.ensure_running")
class ExportTests(TestCase):
    def setUp(self):
        with mock.patch("reviews.views.pipeline.start_analysis"):
            upload(self.client, CSV + 'T-4,2026-08-05,Pune,android,2,"My wallet balance vanished"\n')

    def test_not_200_while_running(self, _):
        r = self.client.get("/api/export/labels.csv")
        self.assertEqual(r.status_code, 202)

    def test_export_shape_after_analysis(self, _):
        run_job(AnalysisJob.latest().id, chat=FakeLLM())
        r = self.client.get("/api/export/labels.csv")
        self.assertEqual(r.status_code, 200)
        lines = r.content.decode().strip().splitlines()
        self.assertEqual(lines[0], "review_id,theme,sub_theme,sentiment")
        self.assertEqual(lines[1:], [
            "T-1,Delivery,Delivery Time,negative",  # one row per (review, theme): "late" wins, "rude" is same theme
            "T-2,Food Quality,Taste,positive",
            "T-3,NONE,NONE,neutral",
            "T-4,Loyalty Wallet,Wallet Balance,negative",  # topic not in the first-pass taxonomy
        ])

    def test_no_data_is_not_200(self, _):
        AnalysisJob.objects.all().delete()
        self.assertNotEqual(self.client.get("/api/export/labels.csv").status_code, 200)
