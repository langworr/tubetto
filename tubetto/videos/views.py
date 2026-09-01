from urllib.parse import urlencode, urlparse, urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

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
from .models import Tab, Video, Channel

STREAM_SESSION = requests.Session()
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=Retry(total=2, backoff_factor=0.2))
STREAM_SESSION.mount('http://', adapter)
STREAM_SESSION.mount('https://', adapter)

# Allowed domains for proxy requests to prevent SSRF
ALLOWED_PROXY_DOMAINS = {
    'googlevideo.com',
    'googleusercontent.com',
    'ytimg.com',
    'youtube.com',
    'youtu.be',
}


def _is_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        return any(
            hostname == allowed or hostname.endswith('.' + allowed)
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
    upstream = STREAM_SESSION.get(file_url, headers=headers, stream=True, timeout=8)
    content_type = upstream.headers.get('Content-Type', 'video/mp4')
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=256 * 1024),
                                 status=upstream.status_code,
                                 content_type=content_type)
    for h in ['Content-Length', 'Content-Range', 'Accept-Ranges', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp


@login_required
def video_list(request, channel_id=None):
    channel = None
    tabs_simple = []
    tabs_grouped = []
    selected_tab = None

    videos = Video.objects.select_related('channel').all().order_by('title')

    if channel_id:
        channel = get_object_or_404(Channel, yt_channel_id=channel_id)
        videos = videos.filter(channel=channel)
        channel_tabs = list(Tab.objects.filter(channel=channel))
        tabs_simple = [t for t in channel_tabs if t.type not in Tab.GROUPED_TYPES]
        tabs_grouped = {}
        for t in channel_tabs:
            if t.type in Tab.GROUPED_TYPES:
                tabs_grouped.setdefault(t.type, []).append(t)

        tab_id = request.GET.get('tab')
        if tab_id:
            selected_tab = next((t for t in channel_tabs if str(t.pk) == tab_id), None)
            if selected_tab:
                videos = videos.filter(tabs=selected_tab)

    videos = videos.order_by('title')

    search_query = request.GET.get('search', '')
    if search_query:
        videos = videos.filter(title__icontains=search_query)

    view_mode = request.GET.get('view', 'tile')
    if view_mode not in ['list', 'tile']:
        view_mode = 'tile'

    paginator = Paginator(videos, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "videos/video_list.html", {
        'channel': channel,
        'page_obj': page_obj,
        'videos': page_obj,
        'search_query': search_query,
        'view_mode': view_mode,
        'tabs_simple': tabs_simple,
        'tabs_grouped': tabs_grouped,
        'has_tabs': bool(tabs_simple or tabs_grouped),
        'selected_tab': selected_tab,
    })


@login_required
def channel_list(request):
    """
    Render the channel list page with pagination, search, and view modes.

    Lists all channels with optional search by title and view mode switching
    between list (table) and tile (thumbnail grid) views.

    Args:
        request (HttpRequest): Incoming request.

    Returns:
        HttpResponse: Rendered template with paginated channels queryset,
        search query, and view mode in context.
    """
    channels = Channel.objects.all().order_by('title')

    # Search by title
    search_query = request.GET.get('search', '')
    if search_query:
        channels = channels.filter(title__icontains=search_query)

    # View mode (list or tile, default: tile)
    view_mode = request.GET.get('view', 'tile')
    if view_mode not in ['list', 'tile']:
        view_mode = 'tile'

    paginator = Paginator(channels, 50)  # Show 50 channels per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, "videos/channel_list.html", {
        "page_obj": page_obj,
        "channels": page_obj,
        "search_query": search_query,
        "view_mode": view_mode,
    })


@login_required
def channel_detail(request, channel_id):
    """
    Show details for a single channel and its videos with pagination, search, and view modes.

    Args:
        request (HttpRequest): Incoming request.
        channel_id (str): YouTube channel ID of the Channel to display.

    Returns:
        HttpResponse: Rendered template containing the channel and its videos,
        or Http404 if the channel does not exist.
    """
    channel = get_object_or_404(Channel, yt_channel_id=channel_id)
    videos = Video.objects.select_related('channel').filter(channel=channel).order_by('-upload_date', '-created_at')

    # Search by title
    search_query = request.GET.get('search', '')
    if search_query:
        videos = videos.filter(title__icontains=search_query)

    # View mode (list or tile, default: tile)
    view_mode = request.GET.get('view', 'tile')
    if view_mode not in ['list', 'tile']:
        view_mode = 'tile'

    paginator = Paginator(videos, 50)  # Show 50 videos per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "videos/channel_detail.html",
        {
            "channel": channel,
            "videos": page_obj,
            "page_obj": page_obj,
            "search_query": search_query,
            "view_mode": view_mode,
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
    video = Video.objects.select_related('channel').filter(yt_video_id=video_id).first()
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
    upstream = STREAM_SESSION.get(segment_url, headers=headers, stream=True, timeout=8)
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=256 * 1024),
                                 status=upstream.status_code,
                                 content_type=upstream.headers.get('Content-Type', 'video/MP2T'))
    for h in ['Content-Length', 'Content-Range', 'Accept-Ranges', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp


@login_required
def hls_manifest(_request, video_id):
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    info = resolve_stream_manifest(video_id)
    if info.get("stream_type") != "hls":
        return HttpResponseForbidden("HLS required")
    manifest_url = info.get("manifest_url")
    if not manifest_url or not _is_url_allowed(manifest_url):
        return HttpResponseForbidden("Invalid manifest URL")
    r = STREAM_SESSION.get(manifest_url, timeout=8)
    r.raise_for_status()
    text = r.text
    base = manifest_url.rsplit("/", 1)[0] + "/"

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
        if variant_url and _is_url_allowed(variant_url):
            rv = STREAM_SESSION.get(variant_url, timeout=8)
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
    v = Video.objects.filter(yt_video_id=video_id).first()
    if not v or not _is_video_allowed(v):
        return HttpResponseForbidden("Not allowed")
    key_url = request.GET.get('u')
    if not key_url:
        return HttpResponseForbidden("Missing key URL")
    if not _is_url_allowed(key_url):
        return HttpResponseForbidden("URL not allowed")
    upstream = STREAM_SESSION.get(key_url, stream=True, timeout=8)
    resp = StreamingHttpResponse(upstream.iter_content(chunk_size=64 * 1024),
                                 status=upstream.status_code,
                                 content_type=upstream.headers.get('Content-Type', 'application/octet-stream'))
    for h in ['Content-Length', 'Cache-Control']:
        if h in upstream.headers:
            resp[h] = upstream.headers[h]
    return resp
