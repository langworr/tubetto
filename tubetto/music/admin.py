"""
Django admin configuration for the music module.

This module registers the music app models with the Django admin interface,
enabling CRUD operations for audio tracks, playlists, and playlist entries
through the Django admin dashboard.
"""

from django.contrib import admin
from .models import MusicTrack, MusicPlaylist, MusicPlaylistTrack


@admin.register(MusicTrack)
class MusicTrackAdmin(admin.ModelAdmin):
    """
    Admin interface for the MusicTrack model.

    Provides a customized Django admin interface for managing audio tracks,
    including list display, search, filtering, and fieldset organization.

    Attributes:
        list_display (tuple): Fields to display in the list view.
        search_fields (tuple): Fields to search across in the admin search.
        list_filter (tuple): Fields available for filtering in the list view.
        ordering (tuple): Default ordering of tracks in the list view.
        fieldsets (tuple): Organization of fields in the detail view.
        readonly_fields (tuple): Fields that cannot be edited in the admin.
    """
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
    """
    Inline admin interface for MusicPlaylistTrack model.

    Allows editing of playlist tracks directly within the MusicPlaylist admin page
    using a tabular layout for easy management of multiple tracks per playlist.

    Attributes:
        model (MusicPlaylistTrack): The model to manage inline.
        extra (int): Number of empty rows to display for adding new tracks.
        autocomplete_fields (tuple): Fields that use autocomplete search.
        ordering (tuple): Default ordering of tracks by position.
    """
    model = MusicPlaylistTrack
    extra = 1
    autocomplete_fields = ("track",)
    ordering = ("position",)


@admin.register(MusicPlaylist)
class MusicPlaylistAdmin(admin.ModelAdmin):
    """
    Admin interface for the MusicPlaylist model.

    Provides a customized Django admin interface for managing music playlists,
    including inline editing of playlist tracks, search, and custom display columns.

    Attributes:
        list_display (tuple): Fields to display in the list view.
        search_fields (tuple): Fields to search across in the admin search.
        inlines (list): Inline admin classes for related models.
        readonly_fields (tuple): Fields that cannot be edited in the admin.
        ordering (tuple): Default ordering of playlists in the list view.
    """
    list_display = ("title", "description", "track_count", "created_at")
    search_fields = ("title", "description")
    inlines = [MusicPlaylistTrackInline]
    readonly_fields = ("created_at", "updated_at")
    ordering = ("title",)

    def track_count(self, obj):
        """
        Display the number of tracks in a playlist.

        Args:
            obj (MusicPlaylist): The playlist instance.

        Returns:
            int: The count of tracks in the playlist.
        """
        return obj.track_count()
    track_count.short_description = "Tracks"
