from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AnalysisJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "Pending"), ("waiting_for_key", "Waiting For Key"), ("discovering", "Discovering"), ("labelling", "Labelling"), ("done", "Done"), ("failed", "Failed")], default="pending", max_length=20)),
                ("total_reviews", models.PositiveIntegerField(default=0)),
                ("labelled_reviews", models.PositiveIntegerField(default=0)),
                ("failed_reviews", models.PositiveIntegerField(default=0)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Review",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("review_id", models.CharField(max_length=64, unique=True)),
                ("date", models.DateField(blank=True, db_index=True, null=True)),
                ("city", models.CharField(blank=True, db_index=True, max_length=100)),
                ("platform", models.CharField(blank=True, db_index=True, max_length=50)),
                ("rating", models.PositiveSmallIntegerField(blank=True, db_index=True, null=True)),
                ("text", models.TextField(blank=True)),
                ("imported_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-date", "review_id"]},
        ),
        migrations.CreateModel(
            name="Theme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.TextField(blank=True)),
                ("discovered_late", models.BooleanField(default=False)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="SubTheme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("theme", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sub_themes", to="reviews.theme")),
            ],
            options={"ordering": ["theme__name", "name"]},
        ),
        migrations.CreateModel(
            name="ReviewLabel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sentiment", models.CharField(choices=[("positive", "Positive"), ("negative", "Negative"), ("neutral", "Neutral")], max_length=10)),
                ("review", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="labels", to="reviews.review")),
                ("sub_theme", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="labels", to="reviews.subtheme")),
                ("theme", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="labels", to="reviews.theme")),
            ],
        ),
        migrations.AddConstraint(
            model_name="subtheme",
            constraint=models.UniqueConstraint(fields=("theme", "name"), name="uniq_subtheme_per_theme"),
        ),
        migrations.AddConstraint(
            model_name="reviewlabel",
            constraint=models.UniqueConstraint(fields=("review", "theme"), name="uniq_label_per_review_theme"),
        ),
        migrations.AddIndex(
            model_name="reviewlabel",
            index=models.Index(fields=["theme", "sentiment"], name="label_theme_sentiment_idx"),
        ),
    ]
