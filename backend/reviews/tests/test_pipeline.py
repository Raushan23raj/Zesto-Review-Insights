from django.test import SimpleTestCase, TestCase

from reviews import labelling, llm
from reviews.ask import execute_plan
from reviews.models import AnalysisJob, Review, ReviewLabel, Theme
from reviews.pipeline import run_job

from .fakes import TAXONOMY, FakeLLM

TAX = labelling.clean_taxonomy(TAXONOMY)


class NormaliseTests(SimpleTestCase):
    def test_matches_names_loosely_and_keeps_one_row_per_theme(self):
        rows, new = labelling.normalise_topics([
            {"theme": "delivery", "sub_theme": "delivery time", "sentiment": "Negative"},
            {"theme": "Delivery", "sub_theme": "Rider Behaviour", "sentiment": "negative"},
            {"theme": "Food Qualty", "sub_theme": "Taste", "sentiment": "positive"},  # typo
        ], TAX)
        self.assertEqual(rows, [("Delivery", "Delivery Time", "negative"), ("Food Quality", "Taste", "positive")])
        self.assertEqual(new, [])

    def test_none_is_dropped_when_there_are_real_topics(self):
        rows, _ = labelling.normalise_topics([
            {"theme": "NONE", "sub_theme": "NONE", "sentiment": "neutral"},
            {"theme": "Delivery", "sub_theme": "Delivery Time", "sentiment": "positive"}], TAX)
        self.assertEqual(rows, [("Delivery", "Delivery Time", "positive")])

    def test_empty_answer_becomes_none(self):
        self.assertEqual(labelling.normalise_topics([], TAX)[0], [("NONE", "NONE", "neutral")])

    def test_unknown_theme_is_reported_as_new(self):
        rows, new = labelling.normalise_topics([{"theme": "Grocery", "sub_theme": "Stock", "sentiment": "negative"}], TAX)
        self.assertEqual(rows, [("Grocery", "Stock", "negative")])
        self.assertEqual(new, [("Grocery", "Stock")])

    def test_content_free(self):
        for text in [".", "👍", "...", "", "😡😡"]:
            self.assertTrue(labelling.is_content_free(text), text)
        self.assertFalse(labelling.is_content_free("cold food"))

    def test_parse_json_tolerates_code_fences(self):
        self.assertEqual(llm.parse_json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})


class RunJobTests(TestCase):
    def setUp(self):
        Review.objects.bulk_create([
            Review(review_id="R1", text="Food was cold and the rider was late", rating=1),
            Review(review_id="R2", text="So tasty!", rating=5),
            Review(review_id="R3", text="👍", rating=4),
            Review(review_id="R4", text="Wallet cashback never came", rating=2),
        ])
        self.job = AnalysisJob.objects.create()

    def labels(self, rid):
        return sorted(ReviewLabel.objects.filter(review__review_id=rid).values_list("theme__name", "sentiment"))

    def test_full_run(self):
        fake = FakeLLM()
        job = run_job(self.job.id, chat=fake)
        self.assertEqual(job.status, AnalysisJob.Status.DONE)
        self.assertEqual(self.labels("R1"), [("Delivery", "negative"), ("Food Quality", "negative")])
        self.assertEqual(self.labels("R2"), [("Food Quality", "positive")])
        self.assertEqual(self.labels("R3"), [("NONE", "neutral")])  # never sent to the LLM
        self.assertTrue(Theme.objects.get(name="Loyalty Wallet").discovered_late)
        self.assertEqual(job.labelled_reviews, 4)
        self.assertNotIn("👍", "".join(fake.calls))

    def test_review_the_model_keeps_forgetting_is_exported_as_none_and_counted(self):
        job = run_job(self.job.id, chat=FakeLLM(drop_ids={"R2"}))
        self.assertEqual(job.status, AnalysisJob.Status.DONE)
        self.assertEqual(job.failed_reviews, 1)
        self.assertEqual(self.labels("R2"), [("NONE", "neutral")])

    def test_llm_failure_marks_job_failed(self):
        def broken(*a, **k):
            raise llm.LLMError("HTTP 401: bad key", fatal=True)
        job = run_job(self.job.id, chat=broken)
        self.assertEqual(job.status, AnalysisJob.Status.FAILED)
        self.assertIn("bad key", job.error)


class AskTests(TestCase):
    def setUp(self):
        Review.objects.bulk_create([
            Review(review_id="A1", text="late delivery", city="Pune"),
            Review(review_id="A2", text="late again", city="Pune"),
            Review(review_id="A3", text="tasty", city="Delhi"),
        ])
        run_job(AnalysisJob.objects.create().id, chat=FakeLLM())

    def test_counts_come_from_the_database(self):
        out = execute_plan({"answerable": True, "filters": {"theme": "Delivery", "sentiment": "negative"}})
        self.assertTrue(out["answer"].startswith("2 of 3 reviews (67%)"))
        self.assertEqual(sorted(out["evidence_review_ids"]), ["A1", "A2"])

    def test_group_by_city(self):
        out = execute_plan({"answerable": True, "filters": {"theme": "Delivery"}, "group_by": "city"})
        self.assertIn("Pune: 2", out["answer"])

    def test_unanswerable(self):
        out = execute_plan({"answerable": False, "reason": "revenue is not in the reviews"})
        self.assertIn("can't answer", out["answer"])
        self.assertEqual(out["evidence_review_ids"], [])
