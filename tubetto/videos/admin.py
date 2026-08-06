import logging

from django.contrib import admin
from .models import Video, Channel, ChannelVideo, Tab, TabVideo

logger = logging.getLogger(__name__)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_channel_id")
    search_fields = ("title", "yt_channel_id")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_video_id", "channel", "created_at")
    list_filter = ("channel",)
    search_fields = ("title", "yt_video_id")
    ordering = ("-created_at",)


@admin.register(ChannelVideo)
class ChannelVideoAdmin(admin.ModelAdmin):
    list_display = ("channel", "yt_video_id", "title")
    list_filter = ("channel",)
    search_fields = ("yt_video_id", "title")
    ordering = ("-published_at",)


@admin.register(Tab)
class ChannelTabAdmin(admin.ModelAdmin):
    list_display = ("channel", "type", "name")
    list_filter = ("channel", "type")
    search_fields = ("name", "yt_id")


@admin.register(TabVideo)
class TabVideoAdmin(admin.ModelAdmin):
    list_display = ("video", "tab")
    list_filter = ("video", "tab")
    search_fields = ("video__title", "tab__name")
