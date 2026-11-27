"""Data model.

Review          one row per imported review (raw data, never changed by the analysis).
Theme           a top-level topic, e.g. "Delivery". Found from the data, not hard-coded.
SubTheme        a topic inside a theme, e.g. "Delivery Time".
ReviewLabel     "review X talks about sub-theme Y with sentiment Z".
                At most one label per (review, theme) - that is exactly one row of the export.
AnalysisJob     progress of the background theme-finding run, so the API/UI can show status.
"""
from django.db import models


class Review(models.Model):
    review_id = models.CharField(max_length=64, unique=True)
    date = models.DateField(null=True, blank=True, db_index=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    platform = models.CharField(max_length=50, blank=True, db_index=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    text = models.TextField(blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "review_id"]

    def __str__(self):
        return self.review_id


class Theme(models.Model):
    NONE_NAME = "NONE"  # reviews with no real content ("ok", "👍", "asdf")

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    # True when the theme was added while labelling (a topic the first pass did not see).
    discovered_late = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubTheme(models.Model):
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="sub_themes")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["theme__name", "name"]
        constraints = [models.UniqueConstraint(fields=["theme", "name"], name="uniq_subtheme_per_theme")]

    def __str__(self):
        return f"{self.theme.name} / {self.name}"


class ReviewLabel(models.Model):
    class Sentiment(models.TextChoices):
        POSITIVE = "positive"
        NEGATIVE = "negative"
        NEUTRAL = "neutral"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="labels")
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="labels")
    sub_theme = models.ForeignKey(SubTheme, on_delete=models.CASCADE, related_name="labels")
    sentiment = models.CharField(max_length=10, choices=Sentiment.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["review", "theme"], name="uniq_label_per_review_theme")]
        indexes = [models.Index(fields=["theme", "sentiment"], name="label_theme_sentiment_idx")]

    def __str__(self):
        return f"{self.review.review_id}: {self.sub_theme} ({self.sentiment})"


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"                  # created, not started yet
        WAITING_FOR_KEY = "waiting_for_key"  # no LLM key configured
        DISCOVERING = "discovering"          # pass 1: finding the list of themes
        LABELLING = "labelling"              # pass 2: tagging each review
        DONE = "done"
        FAILED = "failed"

    ACTIVE = [Status.PENDING, Status.DISCOVERING, Status.LABELLING]

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_reviews = models.PositiveIntegerField(default=0)
    labelled_reviews = models.PositiveIntegerField(default=0)
    failed_reviews = models.PositiveIntegerField(default=0)  # gave up after retries -> exported as NONE
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def latest(cls):
        return cls.objects.order_by("-created_at", "-id").first()
