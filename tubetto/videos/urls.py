from django.urls import path
from . import views

urlpatterns = [
    path('', views.video_list, name='video_list'),
    path('channels/', views.channel_list, name='channel_list'),
    path('channels/<int:channel_id>/', views.channel_detail, name='channel_detail'),
    path('music/', views.music_list, name='music_list'),
    path('music/<int:track_id>/', views.music_detail, name='music_detail'),
    path('music/<int:track_id>/stream/', views.music_stream, name='music_stream'),
    path('watch/<str:video_id>/', views.video_detail, name='video_detail'),
    path('scheduled-task/', views.scheduled_task, name='scheduled_task'),

    # Streaming proxy
    path('stream/<str:video_id>/master.m3u8', views.hls_manifest, name='hls_manifest'),
    path('stream/<str:video_id>/seg', views.hls_segment, name='hls_segment'),
    path('stream/<str:video_id>/key', views.hls_key, name='hls_key'),
    path('stream/<str:video_id>/file', views.progressive_file, name='progressive_file'),
]
