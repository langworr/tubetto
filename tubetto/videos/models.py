from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

from tubetto.enums import YouTubeTab

User = get_user_model()


class Channel(models.Model):
    objects = models.Manager()
    title = models.CharField(max_length=255, blank=True)
    yt_channel_id = models.CharField(max_length=128, unique=True)
    yt_channel_url = models.CharField(max_length=256, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.URLField(max_length=500, blank=True)
    video_count = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.title or self.yt_channel_id)


class Video(models.Model):
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
    tabs = models.ManyToManyField('Tab', through='TabVideo', related_name='videos', blank=True)
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


class Tab(models.Model):
    GROUPED_TYPES = (YouTubeTab.PLAYLISTS, YouTubeTab.PODCASTS)

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="tabs")
    type = models.CharField(max_length=32, choices=YouTubeTab.choices)
    name = models.CharField(max_length=255)
    yt_id = models.CharField(max_length=128, blank=True)

    class Meta:
        unique_together = ("channel", "type", "yt_id")
        ordering = ["type", "name"]

    def __str__(self):
        return f"{self.channel}: {self.name} ({self.get_type_display()})"


class TabVideo(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="tab_links")
    tab = models.ForeignKey(Tab, on_delete=models.CASCADE, related_name="video_links")

    class Meta:
        unique_together = ("video", "tab")

    def __str__(self):
        return f"{self.video} <-> {self.tab}"


class ChannelVideo(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='discovered_videos')
    yt_video_id = models.CharField(max_length=64)
    title = models.CharField(max_length=255, blank=True)
    thumbnail_url = models.URLField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("channel", "yt_video_id")

    def __str__(self):
        return f"{self.channel}: {self.title or self.yt_video_id}"
