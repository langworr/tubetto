from django.urls import path
from . import views

urlpatterns = [
    path('', views.video_list, name='video_list'),
    path('watch/<str:video_id>/', views.video_detail, name='video_detail'),

    # Streaming proxy
    path('stream/<str:video_id>/master.m3u8', views.hls_manifest, name='hls_manifest'),
    path('stream/<str:video_id>/seg', views.hls_segment, name='hls_segment'),
    path('stream/<str:video_id>/key', views.hls_key, name='hls_key'),
    path('stream/<str:video_id>/file', views.progressive_file, name='progressive_file'),
]
