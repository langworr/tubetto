"""
Django admin configuration for the music module.

This module registers the music app models with the Django admin interface,
enabling CRUD operations for audio tracks, playlists, and playlist entries
through the Django admin dashboard.
"""

from django.contrib import admin
from django.db.models import Count
from .models import MusicTrack, MusicPlaylist, MusicPlaylistTrack


@admin.register(MusicTrack)
class MusicTrackAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "album", "yt_video_id", "duration")
    search_fields = ("title", "artist", "album", "yt_video_id")
    list_filter = ("artist", "album")
    ordering = ("title",)

    fieldsets = (
        (None, {"fields": ("title", "artist", "album", "yt_video_id", "duration")}),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("created_at", "updated_at")


class MusicPlaylistTrackInline(admin.TabularInline):
    model = MusicPlaylistTrack
    extra = 1
    autocomplete_fields = ("track",)
    ordering = ("position",)


@admin.register(MusicPlaylist)
class MusicPlaylistAdmin(admin.ModelAdmin):
    list_display = ("title", "description", "track_count", "created_at")
    search_fields = ("title", "description")
    inlines = [MusicPlaylistTrackInline]
    readonly_fields = ("created_at", "updated_at")
    ordering = ("title",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_track_count=Count("entries"))

    def track_count(self, obj):
        if hasattr(obj, "_track_count"):
            return obj._track_count
        return obj.track_count()
    track_count.short_description = "Tracks"
    track_count.admin_order_field = "_track_count"
