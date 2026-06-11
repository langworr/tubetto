"""
URL configuration for the videos app.

This module maps HTTP paths to view callables in videos.views. Each entry below
documents the route purpose and the expected view behavior.

Routes:
- '' -> video_list: Render a paginated or filtered list of videos.
- 'channels/' -> channel_list: Render a list of channels.
- 'channels/<int:channel_id>/' -> channel_detail: Show channel details and its videos.
- 'watch/<str:video_id>/' -> video_detail: Show a video's detail page and stream info.
- 'stream/<str:video_id>/master.m3u8' -> hls_manifest: Fetch and rewrite HLS manifests so
  segments/keys are proxied through this application.
- 'stream/<str:video_id>/seg' -> hls_segment: Proxy individual HLS media segments (expects query param 'u').
- 'stream/<str:video_id>/key' -> hls_key: Proxy HLS encryption keys (expects query param 'u').
- 'stream/<str:video_id>/file' -> progressive_file: Proxy progressive MP4 streams with Range support.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.video_list, name='video_list'),
    path('channels/', views.channel_list, name='channel_list'),
    path('channels/<int:channel_id>/', views.channel_detail, name='channel_detail'),
    path('watch/<str:video_id>/', views.video_detail, name='video_detail'),

    # Streaming proxy
    path('stream/<str:video_id>/master.m3u8', views.hls_manifest, name='hls_manifest'),
    path('stream/<str:video_id>/seg', views.hls_segment, name='hls_segment'),
    path('stream/<str:video_id>/key', views.hls_key, name='hls_key'),
    path('stream/<str:video_id>/file', views.progressive_file, name='progressive_file'),
]
