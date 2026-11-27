from django.urls import path

from . import views

urlpatterns = [
    # fixed by the brief
    path("health", views.health),
    path("import", views.import_view),
    path("export/labels.csv", views.export_labels),
    path("ask", views.ask_view),
    # used by the dashboard
    path("status", views.status_view),
    path("analysis/run", views.rerun_view),
    path("filters", views.filters_view),
    path("themes", views.themes_view),
    path("reviews", views.reviews_view),
    path("trends", views.trends_view),
]
