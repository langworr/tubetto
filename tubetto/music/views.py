"""
Music views for Tubetto.

Provides Django views for managing and streaming music tracks and playlists.
Includes playlist publishing to M3U format and admin task scheduling.
"""
from pathlib import Path
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch
from django.conf import settings
from django.urls import reverse
from django.shortcuts import render, get_object_or_404
from django_ratelimit.decorators import ratelimit

from tubetto.services import resolve_audio_stream
from .models import MusicTrack, MusicPlaylist, MusicPlaylistTrack

STREAM_SESSION = requests.Session()
adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=Retry(total=2, backoff_factor=0.2))
STREAM_SESSION.mount('http://', adapter)
STREAM_SESSION.mount('https://', adapter)

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


@login_required
def music_list(request):
    tracks = MusicTrack.objects.all().order_by('title', 'artist')
    paginator = Paginator(tracks, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "music/music_list.html",
        {
            "page_obj": page_obj,
        },
    )


@login_required
def music_detail(_request, track_id):
    track = get_object_or_404(MusicTrack, pk=track_id)
    stream_url = reverse("music_stream", args=[track.id])
    content_type = "audio/mpeg"

    return render(
        _request,
        "music/music_detail.html",
        {
            "track": track,
            "stream_url": stream_url,
            "content_type": content_type,
        },
    )


@login_required
@ratelimit(key='user', rate='200/h')
def music_stream(_request, track_id):
    track = get_object_or_404(MusicTrack, pk=track_id)
    audio = resolve_audio_stream(track.yt_video_id)
    stream_url = audio.get("stream_url")
    if not stream_url or not _is_url_allowed(stream_url):
        return HttpResponseForbidden("Stream URL not allowed")
    upstream = STREAM_SESSION.get(stream_url, stream=True, timeout=8)
    resp = StreamingHttpResponse(
        upstream.iter_content(chunk_size=256 * 1024),
        content_type=upstream.headers.get("Content-Type", "audio/mpeg"),
    )
    for header in ["Content-Length", "Content-Range", "Accept-Ranges", "Cache-Control"]:
        if header in upstream.headers:
            resp[header] = upstream.headers[header]
    return resp


@login_required
def music_playlist_list(request):
    """Display all music playlists with track counts and pagination.

    Args:
        request: HTTP request object (login required).

    Returns:
        Rendered template with paginated list of playlists sorted by title and creation date.
    """
    playlists = (
        MusicPlaylist.objects.annotate(track_total=Count("entries"))
        .order_by("title", "created_at")
    )
    paginator = Paginator(playlists, 20)  # Show 20 playlists per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(
        request,
        "music/music_playlist_list.html",
        {
            "page_obj": page_obj,
        },
    )


@login_required
def music_playlist_detail(_request, playlist_id):
    """Display details for a single music playlist with all entries.

    Args:
        _request: HTTP request object (login required).
        playlist_id: Primary key of the MusicPlaylist.

    Returns:
        Rendered template with playlist details, entries, and stream URLs.

    Raises:
        Http404: If playlist not found.
    """
    playlist_qs = MusicPlaylist.objects.prefetch_related(
        Prefetch(
            "entries",
            queryset=MusicPlaylistTrack.objects.select_related("track").order_by("position", "added_at"),
        )
    )
    playlist = get_object_or_404(playlist_qs, pk=playlist_id)
    entries = list(playlist.entries.all())
    return render(
        _request,
        "music/music_playlist_detail.html",
        {
            "playlist": playlist,
            "entries": entries,
        },
    )


@login_required
@require_POST
def publish_playlist(request, playlist_id):
    """Publish a single playlist by writing its M3U file to disk.

    Generates an M3U playlist file with track metadata and stream URLs,
    saves it to the media directory, and updates the playlist model.

    Args:
        request: HTTP request object (login required).
        playlist_id: Primary key of the MusicPlaylist.

    Returns:
        HttpResponseRedirect to the playlist detail page.

    Raises:
        Http404: If playlist not found.
    """
    playlist = get_object_or_404(MusicPlaylist, pk=playlist_id)

    # Generate M3U content
    entries = playlist.entries.select_related("track").order_by("position", "added_at")
    m3u_lines = ["#EXTM3U"]
    base_url = request.build_absolute_uri("/").rstrip("/")

    for entry in entries:
        track = entry.track
        stream_url = base_url + reverse("music_stream", args=[track.id])
        duration = track.duration or -1
        title = track.title
        if track.artist:
            title = f"{track.artist} - {title}"
        m3u_lines.append(f"#EXTINF:{duration},{title}")
        m3u_lines.append(stream_url)

    m3u_content = "\n".join(m3u_lines) + "\n"

    # Create media/playlists directory if it doesn't exist
    playlists_dir = Path(settings.MEDIA_ROOT) / "playlists"
    playlists_dir.mkdir(parents=True, exist_ok=True)

    # Write M3U file
    filename = f"playlist_{playlist.id}.m3u"
    file_path = playlists_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    # Save relative path to model
    relative_path = f"playlists/{filename}"
    playlist.published_m3u_path = relative_path
    playlist.save()

    # Redirect back to playlist detail
    return HttpResponseRedirect(reverse("music_playlist_detail", args=[playlist.id]))
