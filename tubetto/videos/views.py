"""
Views for the videos app.

This module provides view functions used by the videos application, including:
- serving and proxying video streams (progressive and HLS),
- listing and showing videos and channels,
- rewriting HLS manifests and proxying HLS segments/keys,
- utility helpers for URL reconstruction and authorization checks.

Functions:
- _is_video_allowed: Determine whether a video is viewable by the current policy.
- reconstruct_segment_url: Rebuild an upstream HLS segment URL from a video manifest.
- progressive_file: Proxy progressive MP4 stream requests with range support.
- video_list: Render a list of videos.
- channel_list: Render a list of channels.
- channel_detail: Render a single channel with its videos.
- video_detail: Show detailed info for a video and its resolved stream.
- hls_segment: Proxy HLS media segments to clients.
- hls_manifest: Fetch and rewrite HLS manifests to proxy segments/keys through the app.
- hls_key: Proxy HLS encryption keys to clients.
"""

from urllib.parse import urlencode, urlparse
import requests

from django.http import HttpResponse, HttpResponseForbidden
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django_ratelimit.decorators import ratelimit
from tubetto.services import (
    resolve_stream_manifest, resolve_video_info, metadata_from_info,
)
from tubetto.utils import reconstruct_segment_url
from .models import Video, Channel


# Allowed domains for proxy requests to prevent SSRF
ALLOWED_PROXY_DOMAINS = {
    'googlevideo.com',
    'googleusercontent.com',
    'ytimg.com',
    'youtube.com',
    'youtu.be',
}


def _is_url_allowed(url: str) -> bool:
    """
    Validate that a URL belongs to an allowed domain to prevent SSRF attacks.

    Args:
        url (str): URL to validate.

    Returns:
        bool: True if URL is from an allowed domain, False otherwise.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Check if domain or any parent domain is in allowed list
        return any(
            domain == allowed or domain.endswith('.' + allowed)
            for allowed in ALLOWED_PROXY_DOMAINS
        )
    except Exception:
        return False


def _is_video_allowed(_video: Video) -> bool:
    """
    Determine whether the given video is allowed to be viewed.

    Current policy: all videos present in the database are allowed.
    Replace or extend this function to implement whitelist/blacklist checks.

    Args:
        _video (Video): Video instance to evaluate.

    Returns:
        bool: True if the video may be served to the requester.
    """
    # All videos present in DB are viewable regardless of whitelist.
    return True


@login_required
@ratelimit(key='user', rate='100/h')
def progressive_file(request, video_id):
    """
    Proxy a progressive MP4 file stream for the given video.

    Supports Range requests by forwarding the Range header upstream and
    streaming the response to the client while preserving relevant headers.

    Args:
        request (HttpRequest): Incoming request, may include Range header.
        video_id (str): YouTube video identifier (yt_video_id).

    Returns:
        StreamingHttpResponse: Streaming response that proxies the upstream file,
        or HttpResponseForbidden when the video is not allowed or not progressive.
    """
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
    """
    Render the video list page with pagination.

    Lists videos that do not belong to a channel (or adjust the queryset as needed).

    Args:
        request (HttpRequest): Incoming request.

    Returns:
        HttpResponse: Rendered template with paginated videos queryset in context.
    """
    videos = Video.objects.filter(channel__isnull=True).order_by('-upload_date', '-created_at')
    paginator = Paginator(videos, 50)  # Show 50 videos per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, "videos/video_list.html", {"page_obj": page_obj})


@login_required
def channel_list(request):
    """
    Render the channel list page with pagination.

    Shows all channels ordered by title and YouTube channel id.

    Args:
        request (HttpRequest): Incoming request.

    Returns:
        HttpResponse: Rendered template with paginated channels queryset in context.
    """
    channels = Channel.objects.all().order_by('title', 'yt_channel_id')
    paginator = Paginator(channels, 50)  # Show 50 channels per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, "videos/channel_list.html", {"page_obj": page_obj})


@login_required
def channel_detail(request, channel_id):
    """
    Show details for a single channel and its videos.

    Args:
        request (HttpRequest): Incoming request.
        channel_id (int): Primary key of the Channel to display.

    Returns:
        HttpResponse: Rendered template containing the channel and its videos,
        or Http404 if the channel does not exist.
    """
    channel = get_object_or_404(Channel, pk=channel_id)
    videos = (
        Video.objects.filter(channel=channel)
        .order_by('-upload_date', '-created_at')
    )
    return render(
        request,
        "videos/channel_detail.html",
        {
            "channel": channel,
            "videos": videos,
        },
    )


@login_required
def video_detail(request, video_id):
    """
    Display detailed information for a video and its resolved stream manifest.

    The view attempts to refresh local metadata from the resolved video info
    and saves changes if any fields are updated.

    Args:
        request (HttpRequest): Incoming request.
        video_id (str): YouTube video identifier (yt_video_id).

    Returns:
        HttpResponse: Rendered template with video metadata and stream info,
        or HttpResponseForbidden when the video is not allowed.
    """
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


@login_required
@ratelimit(key='user', rate='500/h')
def hls_segment(request, video_id):
    """
    Proxy an individual HLS media segment to the client.

    The upstream segment URL is provided via the 'u' query parameter. Range
    requests are forwarded to the upstream server.

    Args:
        request (HttpRequest): Incoming request containing query parameter 'u'.
        video_id (str): YouTube video identifier (yt_video_id).

    Returns:
        StreamingHttpResponse: Proxied segment content or HttpResponseForbidden on error.
    """
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    segment_url = request.GET.get('u')
    if not segment_url:
        return HttpResponseForbidden("Missing segment URL")
    if not _is_url_allowed(segment_url):
        return HttpResponseForbidden("URL not allowed")
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
def hls_manifest(_request, video_id):
    """
    Fetch, optionally resolve, and rewrite an HLS manifest so segments and keys
    are proxied through this application.

    - If a master playlist is returned, the first variant is fetched and used.
    - All segment URLs are rewritten to point at the hls_segment endpoint.
    - #EXT-X-KEY URIs are rewritten to point at the hls_key endpoint.

    Args:
        _request (HttpRequest): Incoming request (unused).
        video_id (str): YouTube video identifier (yt_video_id).

    Returns:
        HttpResponse: The rewritten manifest with content_type 'application/vnd.apple.mpegurl',
        or HttpResponseForbidden if the video is not allowed or not HLS.
    """
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
                _prefix, rest = s.split('URI=', 1)
                if rest.startswith('"'):
                    uri_part = rest.split('"', 2)[1]
                else:
                    uri_part = rest.split(',', 1)[0]
                upstream_key = urljoin(base, uri_part)
                proxied = reverse("hls_key", args=[video_id]) + "?" + urlencode({"u": upstream_key})
                if '"' in rest:
                    newline = s.replace(f'URI="{uri_part}"', f'URI="{proxied}"')
                else:
                    newline = s.replace(f'URI={uri_part}', f'URI={proxied}')
                rewritten.append(newline)
            except (ValueError, IndexError, KeyError):
                rewritten.append(line)
            continue
        if s.startswith('#') or not s:
            rewritten.append(line)
            continue
        upstream_url = urljoin(base, s)
        proxied = reverse("hls_segment", args=[video_id]) + "?" + urlencode({"u": upstream_url})
        rewritten.append(proxied)

    content = "\n".join(rewritten)
    return HttpResponse(content, content_type="application/vnd.apple.mpegurl")


@login_required
@ratelimit(key='user', rate='500/h')
def hls_key(request, video_id):
    """
    Proxy an HLS encryption key to the client.

    The upstream key URL is supplied via the 'u' query parameter. The view
    streams the key bytes and preserves Content-Length where provided.

    Args:
        request (HttpRequest): Incoming request containing query parameter 'u'.
        video_id (str): YouTube video identifier (yt_video_id).

    Returns:
        StreamingHttpResponse: Proxied key bytes or HttpResponseForbidden on error.
    """
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    key_url = request.GET.get('u')
    if not key_url:
        return HttpResponseForbidden("Missing key URL")
    if not _is_url_allowed(key_url):
        return HttpResponseForbidden("URL not allowed")
    upstream = requests.get(key_url, stream=True, timeout=8)
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=32 * 1024),
                                 status=upstream.status_code,
                                 content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
    for h in ['Content-Length', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp
