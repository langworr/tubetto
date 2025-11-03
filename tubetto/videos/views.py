from django.http import HttpResponse, HttpResponseForbidden
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from .models import Video, Comment
from .services import resolve_stream_manifest
import requests
from urllib.parse import urljoin

from django.shortcuts import render, get_object_or_404

@login_required
def comment_list(request, video_id):
    video = get_object_or_404(Video, yt_video_id=video_id, is_whitelisted=True)
    comments = Comment.objects.filter(video=video, is_approved=True).order_by("-created_at")
    return render(request, "videos/comment_list.html", {
        "video": video,
        "comments": comments,
    })

@login_required
def video_list(request):
    videos = Video.objects.filter(is_whitelisted=True)
    return render(request, "videos/video_list.html", {"videos": videos})

@login_required
def video_detail(request, video_id):
    video = Video.objects.filter(yt_video_id=video_id, is_whitelisted=True).first()
    if not video:
        return HttpResponseForbidden("Video non autorizzato")
    return render(request, "videos/video_detail.html", {"video": video})


@login_required
def hls_segment(request, video_id, name):
    v = Video.objects.filter(yt_video_id=video_id, is_whitelisted=True).first()
    if not v:
        return HttpResponseForbidden("Not allowed")
    # Recupera URL upstream dalla cache (qui placeholder)
    segment_url = reconstruct_segment_url(video_id, name)
    headers = {}
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']
    upstream = requests.get(segment_url, headers=headers, stream=True, timeout=8)
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=64 * 1024),
                                 status=upstream.status_code,
                                 content_type=upstream.headers.get('Content-Type', 'video/MP2T'))
    for h in ['Content-Length', 'Content-Range', 'Accept-Ranges', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp


@login_required
def hls_manifest(request, video_id):
    v = Video.objects.filter(yt_video_id=video_id, is_whitelisted=True).first()
    if not v:
        return HttpResponseForbidden("Not allowed")
    info = resolve_stream_manifest(video_id)
    if info["manifest_type"] != "hls":
        return HttpResponseForbidden("HLS required")
    r = requests.get(info["manifest_url"], timeout=8)
    r.raise_for_status()
    original = r.text.splitlines()
    base = info["manifest_url"].rsplit("/", 1)[0] + "/"

    rewritten = []
    for line in original:
        if line.strip().startswith("#"):
            rewritten.append(line)
            continue
        if not line.strip():
            rewritten.append(line)
            continue
        upstream_url = urljoin(base, line.strip())
        name = upstream_url.rsplit("/", 1)[-1]
        # Salva mapping (idealmente in Redis) per segmenti e eventuali key URIs
        # cache_segment_url(video_id, name, upstream_url)
        rewritten.append(f"/stream/{video_id}/seg/{name}")
    content = "\n".join(rewritten)
    return HttpResponse(content, content_type="application/vnd.apple.mpegurl")
