"""
URL configuration for the music app in Tubetto.

This module defines the URL patterns for the music section of the application,
mapping URLs to their corresponding view functions.

Available URL patterns:
- '' : List all music tracks (music_list).
- '<int:track_id>/' : Display details for a specific music track (music_detail).
- '<int:track_id>/stream/' : Stream audio for a specific music track (music_stream).
- 'playlists/' : List all music playlists (music_playlist_list).
- 'playlists/<int:playlist_id>/' : Display details for a specific music playlist (music_playlist_detail).
- 'playlists/<int:playlist_id>/publish/' : Publish a specific music playlist (publish_playlist).
"""

from django.urls import path
from . import views

urlpatterns = [
    path('', views.music_list, name='music_list'),
    path('<int:track_id>/', views.music_detail, name='music_detail'),
    path('<int:track_id>/stream/', views.music_stream, name='music_stream'),
    path('playlists/', views.music_playlist_list, name='music_playlist_list'),
    path('playlists/<int:playlist_id>/', views.music_playlist_detail, name='music_playlist_detail'),
    path('playlists/<int:playlist_id>/publish/', views.publish_playlist, name='publish_playlist'),
]
