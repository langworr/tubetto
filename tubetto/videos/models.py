from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()

class Channel(models.Model):
    """
    Rappresenta un canale YouTube con metadata.
    """
    objects = models.Manager()
    title = models.CharField(max_length=255, blank=True)
    yt_channel_id = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True)
    thumbnail = models.URLField(blank=True)
    subscriber_count = models.PositiveIntegerField(null=True, blank=True)
    video_count = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.title or self.yt_channel_id)


class Video(models.Model):
    """Metadata for a YouTube video tracked by the application."""
    objects = models.Manager()
    yt_video_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    duration = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds")
    upload_date = models.DateField(null=True, blank=True)
    thumbnail = models.URLField(blank=True)
    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.SET_NULL)
    channel_title = models.CharField(max_length=255, blank=True)
    channel_external_id = models.CharField(max_length=128, blank=True)
    uploader = models.CharField(max_length=255, blank=True)
    uploader_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.title or self.yt_video_id)

    def duration_display(self) -> str:
        if self.duration in (None, ""):
            return None
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"


class ChannelVideo(models.Model):
    """
    Video rilevati per un canale (snapshot dell'elenco del canale).
    """
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='discovered_videos')
    yt_video_id = models.CharField(max_length=64)
    title = models.CharField(max_length=255, blank=True)
    thumbnail_url = models.URLField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("channel", "yt_video_id")

    def __str__(self):
        return f"{self.channel}: {self.title or self.yt_video_id}"
