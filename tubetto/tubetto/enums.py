from django.db import models
from django.utils.translation import gettext_lazy as _


class YouTubeTab(models.TextChoices):
    HOME = "featured", _("Home")
    VIDEOS = "videos", _("Video")
    SHORTS = "shorts", _("Shorts")
    STREAMS = "streams", _("Live")
    PODCASTS = "podcasts", _("Podcast")
    COURSES = "courses", _("Corsi")
    PLAYLISTS = "playlists", _("Playlist")
