from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Channel(models.Model):
    """
    Rappresenta un canale YouTube.
    """
    title = models.CharField(max_length=255, blank=True)
    yt_channel_id = models.CharField(max_length=128, unique=True)

    def __str__(self):
        return self.title or self.yt_channel_id


class Video(models.Model):
    """
    Rappresenta un video YouTube whitelisted.
    """
    yt_video_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    thumbnail_url = models.URLField(blank=True)
    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.SET_NULL)
    is_whitelisted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title


class Comment(models.Model):
    """
    Commenti interni al sistema (non quelli di YouTube).
    """
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Commento di {self.author} su {self.video}"


class WhitelistEntry(models.Model):
    """
    Traccia chi ha aggiunto un video alla whitelist e quando.
    """
    video = models.OneToOneField(Video, on_delete=models.CASCADE)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.video.title} whitelisted"
