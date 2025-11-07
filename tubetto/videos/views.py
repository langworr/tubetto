from django.http import HttpResponse, HttpResponseForbidden
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from .models import Video
from .services import resolve_stream_manifest, resolve_video_info, metadata_from_info
import requests
from urllib.parse import urljoin, urlencode

from django.shortcuts import render, get_object_or_404


def _is_video_allowed(video: Video) -> bool:
    # All videos present in DB are viewable regardless of whitelist.
    return True


def reconstruct_segment_url(video_id: str, name: str) -> str:
    """Best-effort reconstruction of upstream segment URL.
    This re-resolves the manifest and uses its base URL for the segment.
    """
    info = resolve_stream_manifest(video_id)
    base = info["manifest_url"].rsplit("/", 1)[0] + "/"
    return urljoin(base, name)


@login_required
def progressive_file(request, video_id):
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    info = resolve_stream_manifest(video_id)
    if info.get("stream_type") != "progressive":
        return HttpResponseForbidden("Not a progressive stream")
    file_url = info.get("stream_url")
    headers = {}
    if 'Range' in request.headers:
        headers['Range'] = request.headers['Range']
    upstream = requests.get(file_url, headers=headers, stream=True, timeout=8)
    content_type = upstream.headers.get('Content-Type', 'video/mp4')
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=64 * 1024),
                                 status=upstream.status_code,
                                 content_type=content_type)
    for h in ['Content-Length', 'Content-Range', 'Accept-Ranges', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp

@login_required
def video_list(request):
    videos = Video.objects.all().order_by('-upload_date', '-created_at')
    return render(request, "videos/video_list.html", {"videos": videos})

@login_required
def video_detail(request, video_id):
    video = Video.objects.filter(yt_video_id=video_id).first()
    if not video or not _is_video_allowed(video):
        return HttpResponseForbidden("Video non autorizzato")
    info = resolve_video_info(video_id)
    meta = metadata_from_info(info)
    changed = False
    for field, value in meta.items():
        if getattr(video, field) != value:
            setattr(video, field, value)
            changed = True
    if changed:
        video.save()
    stream = resolve_stream_manifest(video_id)
    return render(request, "videos/video_detail.html", {
        "video": video,
        "stream": stream,
    })


 # Removed: separate comments page. Comments now shown on video_detail for privileged users.


@login_required
def hls_segment(request, video_id):
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    segment_url = request.GET.get('u')
    if not segment_url:
        return HttpResponseForbidden("Missing segment URL")
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
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    info = resolve_stream_manifest(video_id)
    if info.get("stream_type") != "hls":
        return HttpResponseForbidden("HLS required")
    r = requests.get(info["manifest_url"], timeout=8)
    r.raise_for_status()
    text = r.text
    base = info["manifest_url"].rsplit("/", 1)[0] + "/"

    # If master playlist, pick the first variant and fetch it
    if "#EXT-X-STREAM-INF" in text:
        lines = text.splitlines()
        variant_url = None
        for i, line in enumerate(lines):
            if line.strip().startswith('#EXT-X-STREAM-INF'):
                for j in range(i + 1, len(lines)):
                    u = lines[j].strip()
                    if not u or u.startswith('#'):
                        continue
                    variant_url = urljoin(base, u)
                    break
                if variant_url:
                    break
        if variant_url:
            rv = requests.get(variant_url, timeout=8)
            rv.raise_for_status()
            text = rv.text
            base = variant_url.rsplit('/', 1)[0] + '/'

    rewritten = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('#EXT-X-KEY') and 'URI=' in s:
            try:
                prefix, rest = s.split('URI=', 1)
                if rest.startswith('"'):
                    uri_part = rest.split('"', 2)[1]
                else:
                    uri_part = rest.split(',', 1)[0]
                upstream_key = urljoin(base, uri_part)
                proxied = f"/stream/{video_id}/key?" + urlencode({"u": upstream_key})
                if '"' in rest:
                    newline = s.replace(f'URI="{uri_part}"', f'URI="{proxied}"')
                else:
                    newline = s.replace(f'URI={uri_part}', f'URI={proxied}')
                rewritten.append(newline)
            except Exception:
                rewritten.append(line)
            continue
        if s.startswith('#') or not s:
            rewritten.append(line)
            continue
        upstream_url = urljoin(base, s)
        proxied = f"/stream/{video_id}/seg?" + urlencode({"u": upstream_url})
        rewritten.append(proxied)

    content = "\n".join(rewritten)
    return HttpResponse(content, content_type="application/vnd.apple.mpegurl")


@login_required
def hls_key(request, video_id):
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    key_url = request.GET.get('u')
    if not key_url:
        return HttpResponseForbidden("Missing key URL")
    upstream = requests.get(key_url, stream=True, timeout=8)
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=32 * 1024),
                                 status=upstream.status_code,
                                 content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
    for h in ['Content-Length', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp
