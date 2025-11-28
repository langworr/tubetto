"""
Models for the music section of Tubetto.

This module defines the data models used to represent audio tracks, playlists,
and the relationship between them in the database.

Classes:
- MusicTrack: Represents an audio track with metadata.
- MusicPlaylist: Represents a playlist containing multiple audio tracks.
- MusicPlaylistTrack: Represents the relationship between a playlist and its tracks.
"""

from django.db import models
from django.core.exceptions import ValidationError


class MusicTrack(models.Model):
    """
    Audio track metadata for the music section.

    Attributes:
        yt_video_id (str): Unique YouTube video ID to extract audio from.
        title (str): Title of the audio track.
        artist (str): Artist of the audio track.
        album (str): Album of the audio track.
        duration (int): Duration of the track in seconds.
        created_at (datetime): Timestamp when the track was created.
        updated_at (datetime): Timestamp when the track was last updated.
    """

    objects = models.Manager()

    yt_video_id = models.CharField(
        max_length=64,
        unique=True,
        default="",
        help_text="YouTube video id to extract audio from")
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
        """
        Meta options for the MusicTrack model.

        Attributes:
            ordering (tuple): Default ordering of MusicTrack instances by title,
                              artist, and YouTube video ID.
        """
        ordering = ("title", "artist", "yt_video_id")

    def __str__(self):
        """Return a string representation of the audio track."""
        label = self.title or self.yt_video_id or "Untitled track"
        if self.artist:
            return f"{label} — {self.artist}"
        return label

    def clean(self):
        """Validate the model instance before saving.

        Raises:
            ValidationError: If yt_video_id is not set.
        """
        super().clean()
        if not self.yt_video_id:
            raise ValidationError("You must set a YouTube video id for the audio track.")

    def duration_display(self):
        """Return a formatted string representation of the track's duration.

        Returns:
            str: Formatted duration in 'HH:MM:SS' or 'MM:SS' format.
        """
        if not self.duration:
            return None
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"


class MusicPlaylist(models.Model):
    """
    Represents a playlist containing multiple audio tracks.

    Attributes:
        title (str): Title of the playlist.
        description (str): Description of the playlist.
        created_at (datetime): Timestamp when the playlist was created.
        updated_at (datetime): Timestamp when the playlist was last updated.
        published_m3u_path (str): Path to the published M3U file.
    """

    title = models.CharField(max_length=255)
    objects = models.Manager()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_m3u_path = models.CharField(max_length=512, blank=True, help_text="Path to the published M3U file")

    class Meta:
        """
        Meta options for the MusicPlaylist model.

        Attributes:
            ordering (tuple): Default ordering of MusicPlaylist instances by title
                              and creation date.
        """
        ordering = ("title", "created_at")

    def __str__(self):
        """Return the title of the playlist."""
        return f"{self.title}"

    def track_count(self) -> int:
        """Return the number of tracks in the playlist.

        Returns:
            int: Count of tracks in the playlist.
        """
        return self.objects.count()


class MusicPlaylistTrack(models.Model):
    """
    Represents the relationship between a playlist and its tracks.

    Attributes:
        playlist (MusicPlaylist): The playlist to which the track belongs.
        track (MusicTrack): The audio track in the playlist.
        position (int): Playback order of the track in the playlist.
        added_at (datetime): Timestamp when the track was added to the playlist.
    """

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
        """
        Meta options for the MusicPlaylistTrack model.

        Attributes:
            ordering (tuple): Default ordering of MusicPlaylistTrack instances by
                              position and added timestamp.
            unique_together (tuple): Ensures that each track can only appear once
                                     in a playlist.
        """
        ordering = ("position", "added_at")
        unique_together = ("playlist", "track")

    def __str__(self):
        """Return a string representation of the playlist track entry."""
        return f"{self.playlist.title} — {self.track.title} ({self.position})"
