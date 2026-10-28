"""URL routing for the API v1."""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("solve/", views.create_solve_job, name="create-solve"),
    path("solve/list/", views.list_solve_jobs, name="list-solve"),
    path("solve/<uuid:job_id>/", views.get_solve_job, name="get-solve"),
    path("health/", views.health, name="health"),
]
