"""Django admin registration for inspecting jobs."""

from django.contrib import admin

from .models import SolveJob


@admin.register(SolveJob)
class SolveJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "language",
        "created_at",
        "finished_at",
    )
    list_filter = ("status", "language", "created_at")
    search_fields = ("id", "problem_statement")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "celery_task_id",
        "result",
        "progress",
    )
    ordering = ("-created_at",)
