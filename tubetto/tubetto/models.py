from django.conf import settings
from django.db import models
from django.utils import timezone


class ScheduledTaskHistory(models.Model):
    TASK_TYPE_CHOICES = [
        ("update_channels", "Update Channels Metadata"),
        ("scan_videos", "Scan Channel Videos"),
        ("update_videos_metadata", "Update Videos Metadata"),
        ("update_music_tracks", "Update Music Tracks Metadata"),
        ("run_all", "All Tasks"),
    ]

    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    task_type = models.CharField(max_length=50, choices=TASK_TYPE_CHOICES)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    result = models.TextField(blank=True)
    channels = models.JSONField(null=True, blank=True, default=list)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self):
        return f"{self.get_task_type_display()} started at {self.started_at:%Y-%m-%d %H:%M:%S}"

    @property
    def duration(self):
        if self.ended_at:
            return self.ended_at - self.started_at
        return timezone.now() - self.started_at
