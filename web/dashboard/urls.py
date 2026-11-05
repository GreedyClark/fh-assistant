from django.urls import path

from . import views

urlpatterns = [
    path("", views.entry, name="entry"),
    path("auth/", views.auth, name="auth"),
    path("projects/", views.projects, name="projects"),
    path("p/<int:project_id>/", views.card, name="card"),
    path("p/<int:project_id>/analyze/", views.analyze, name="analyze"),
    path("p/<int:project_id>/skip/", views.skip, name="skip"),
    path("p/<int:project_id>/block/", views.block, name="block"),
    path("p/<int:project_id>/bid/", views.bid, name="bid"),
    path("p/<int:project_id>/bid/status/", views.bid_status, name="bid_status"),
    path("p/<int:project_id>/send/", views.send_bid, name="send_bid"),
    path("stats/", views.stats_view, name="stats"),
    path("settings/", views.settings_view, name="settings"),
]
