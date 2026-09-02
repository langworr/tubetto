"""
Django admin configuration for Tubetto core app.
"""
from django.contrib import admin
from .models import ScheduledTaskHistory


@admin.register(ScheduledTaskHistory)
class ScheduledTaskHistoryAdmin(admin.ModelAdmin):
    list_display = ("task_type", "status", "started_at", "ended_at", "user", "duration_display", "q_task_id")
    list_filter = ("status", "task_type", "started_at")
    search_fields = ("task_type", "result", "q_task_id", "user__username")
    readonly_fields = ("task_type", "started_at", "ended_at", "user", "status", "result", "channels", "q_task_id")

    def duration_display(self, obj):
        dur = obj.duration
        if dur:
            total_seconds = int(dur.total_seconds())
            mins, secs = divmod(total_seconds, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                return f"{hours}h {mins}m {secs}s"
            if mins > 0:
                return f"{mins}m {secs}s"
            return f"{secs}s"
        return "-"
    duration_display.short_description = "Duration"

