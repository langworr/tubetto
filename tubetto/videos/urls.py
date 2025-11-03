from django.urls import path
from . import views

urlpatterns = [
    path('', views.video_list, name='video_list'),
    path('watch/<str:video_id>/', views.video_detail, name='video_detail'),
    path('watch/<str:video_id>/comments/', views.comment_list, name='comment_list'),
    # path('watch/<str:video_id>/comment/add/', views.comment_add, name='comment_add'),

    # Streaming proxy
    path('stream/<str:video_id>/master.m3u8', views.hls_manifest, name='hls_manifest'),
    path('stream/<str:video_id>/seg/<str:name>', views.hls_segment, name='hls_segment'),
]
