from django.contrib import admin
from .models import Video, Channel, Comment, WhitelistEntry

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_channel_id")
    search_fields = ("title", "yt_channel_id")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_video_id", "is_whitelisted", "channel", "created_at")
    list_filter = ("is_whitelisted", "channel")
    search_fields = ("title", "yt_video_id")
    list_editable = ("is_whitelisted",)  # toggle rapido dalla lista
    ordering = ("-created_at",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("video", "author", "is_approved", "created_at")
    list_filter = ("is_approved", "created_at")
    search_fields = ("body", "author__username", "video__title")
    list_editable = ("is_approved",)  # approvazione rapida
    ordering = ("-created_at",)


@admin.register(WhitelistEntry)
class WhitelistEntryAdmin(admin.ModelAdmin):
    list_display = ("video", "added_by", "added_at")
    search_fields = ("video__title", "added_by__username")
    ordering = ("-added_at",)
