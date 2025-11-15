from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

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


class MusicTrack(models.Model):
    objects = models.Manager()
    """
    Audio track metadata for the music section.
    """

    yt_video_id = models.CharField(max_length=64, unique=True, default="", help_text="YouTube video id to extract audio from")
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255, blank=True)
    album = models.CharField(max_length=255, blank=True)
    duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration in seconds",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "artist", "yt_video_id")

    def __str__(self):
        label = self.title or self.yt_video_id or "Untitled track"
        if self.artist:
            return f"{label} — {self.artist}"
        return label

    def clean(self):
        super().clean()
        if not self.yt_video_id:
            raise ValidationError("You must set a YouTube video id for the audio track.")

    def duration_display(self):
        if not self.duration:
            return None
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    # File-based fields removed: only yt-dlp audio streams are supported


class MusicPlaylist(models.Model):
    title = models.CharField(max_length=255)
    objects = models.Manager()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_m3u_path = models.CharField(max_length=512, blank=True, help_text="Path to the published M3U file")

    class Meta:
        ordering = ("title", "created_at")

    def __str__(self):
        return self.title

    def track_count(self) -> int:
        return self.entries.count()


class MusicPlaylistTrack(models.Model):
    objects = models.Manager()
    playlist = models.ForeignKey(
        MusicPlaylist,
        related_name="entries",
        on_delete=models.CASCADE,
    )
    track = models.ForeignKey(
        MusicTrack,
        related_name="playlist_entries",
        on_delete=models.CASCADE,
    )
    position = models.PositiveIntegerField(default=1, help_text="Playback order (starting at 1)")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "added_at")
        unique_together = ("playlist", "track")

    def __str__(self):
        return f"{self.playlist.title} — {self.track.title} ({self.position})"


## Whitelist removed per requirements
