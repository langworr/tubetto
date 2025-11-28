"""
Music views for Tubetto.

Provides Django views for managing and streaming music tracks and playlists.
Includes playlist publishing to M3U format and admin task scheduling.
"""
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.exceptions import RequestException
from django.db import DatabaseError

from django.http import HttpResponseRedirect
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Prefetch
from django.conf import settings
from django.urls import reverse
from django.shortcuts import render, get_object_or_404

from tubetto.services import (
    resolve_stream_manifest,
    run_scheduled_task, update_channels_metadata, scan_channel_videos, update_videos_metadata,
    resolve_audio_stream, update_music_tracks_metadata
)

from .models import MusicTrack, MusicPlaylist, MusicPlaylistTrack


def reconstruct_segment_url(video_id: str, name: str) -> str:
    """Reconstruct upstream segment URL by re-resolving the manifest.

    Best-effort reconstruction of the original segment URL using the manifest's
    base URL and the provided segment name.

    Args:
        video_id: YouTube video ID.
        name: Segment name or relative path.

    Returns:
        Reconstructed absolute URL for the segment.
    """
    info = resolve_stream_manifest(video_id)
    base = info["manifest_url"].rsplit("/", 1)[0] + "/"
    return urljoin(base, name)


@login_required
def music_list(_request):
    """Display all music tracks sorted by title and artist.

    Args:
        _request: HTTP request object (login required).

    Returns:
        Rendered template with list of all music tracks.
    """
    tracks = MusicTrack.objects.all().order_by('title', 'artist')
    return render(
        _request,
        "videos/music_list.html",
        {
            "tracks": tracks,
        },
    )


@login_required
def music_detail(_request, track_id):
    """Display details for a single music track.

    Args:
        _request: HTTP request object (login required).
        track_id: Primary key of the MusicTrack.

    Returns:
        Rendered template with track details and streaming URL.

    Raises:
        Http404: If track not found.
    """
    track = get_object_or_404(MusicTrack, pk=track_id)
    stream_url = reverse("music_stream", args=[track.id])
    content_type = "audio/mpeg"

    return render(
        _request,
        "videos/music_detail.html",
        {
            "track": track,
            "stream_url": stream_url,
            "content_type": content_type,
        },
    )


@login_required
def music_stream(_request, track_id):
    """Stream audio content for a music track.

    Resolves a fresh audio-only stream via yt-dlp and proxies it to the client.
    Forwards relevant headers for content negotiation and range requests.

    Args:
        _request: HTTP request object (login required).
        track_id: Primary key of the MusicTrack.

    Returns:
        StreamingHttpResponse with audio content.

    Raises:
        Http404: If track not found.
    """
    track = get_object_or_404(MusicTrack, pk=track_id)
    # Resolve fresh audio-only stream via yt-dlp and proxy it
    audio = resolve_audio_stream(track.yt_video_id)
    upstream = requests.get(audio["stream_url"], stream=True, timeout=8)
    resp = StreamingHttpResponse(
        upstream.iter_content(chunk_size=64 * 1024),
        content_type=upstream.headers.get("Content-Type", "audio/mpeg"),
    )
    for header in ["Content-Length", "Content-Range", "Accept-Ranges", "Cache-Control"]:
        if header in upstream.headers:
            resp[header] = upstream.headers[header]
    return resp


@login_required
def music_playlist_list(_request):
    """Display all music playlists with track counts.

    Args:
        _request: HTTP request object (login required).

    Returns:
        Rendered template with list of all playlists sorted by title and creation date.
    """
    playlists = (
        MusicPlaylist.objects.annotate(track_total=Count("entries"))
        .order_by("title", "created_at")
    )
    return render(
        _request,
        "videos/music_playlist_list.html",
        {
            "playlists": playlists,
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
    stream_url = reverse("music_playlist_stream", args=[playlist.id])
    shuffle_stream_url = f"{stream_url}?shuffle=1"
    return render(
        _request,
        "videos/music_playlist_detail.html",
        {
            "playlist": playlist,
            "entries": entries,
            "playlist_stream_url": stream_url,
            "playlist_shuffle_stream_url": shuffle_stream_url,
        },
    )


def _is_admin(user):
    """Check if user has admin privileges.

    Args:
        user: Django User object.

    Returns:
        True if user is authenticated and is superuser or in 'admin' group.
    """
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["admin"]).exists())


@login_required
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
    # entries = playlist.entries.select_related("track").order_by("position", "added_at")
    entries = playlist.objects.select_related("track").order_by("position", "added_at")
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


@login_required
@user_passes_test(_is_admin)
def scheduled_task(request):
    """Admin-only page to run scheduled maintenance tasks.

    Handles POST requests to trigger various tasks: update channels metadata,
    scan videos, update video/music metadata, publish playlists, or run all tasks.

    Args:
        request: HTTP request object (login and admin privileges required).

    Returns:
        Rendered template with task results and status.
    """
    results = None
    task_name = None

    if request.method == 'POST':
        if 'update_channels' in request.POST:
            results = update_channels_metadata()
            task_name = "Update Channels Metadata"
        elif 'scan_videos' in request.POST:
            results = scan_channel_videos()
            task_name = "Scan Channel Videos"
        elif 'update_videos_metadata' in request.POST:
            results = update_videos_metadata()
            task_name = "Update Videos Metadata"
        elif 'update_music_tracks' in request.POST:
            results = update_music_tracks_metadata()
            task_name = "Update Music Tracks Metadata"
        elif 'publish_playlists' in request.POST:
            results = publish_all_playlists(request)
            task_name = "Publish Playlists"
        elif 'run_all' in request.POST:
            results = run_scheduled_task()
            task_name = "All Tasks"

    return render(request, "videos/scheduled_task.html", {
        "results": results,
        "task_name": task_name,
    })


def publish_all_playlists(request):
    """Publish all playlists by writing their M3U files to disk.

    Iterates over all playlists and generates M3U files with track metadata
    and stream URLs. Handles errors gracefully and logs failures.

    Args:
        request: HTTP request object (used to build absolute URLs).

    Returns:
        Dictionary with keys:
            - playlists_processed: Total number of playlists.
            - playlists_published: Number of successfully published playlists.
            - errors: List of error messages for failed playlists.
    """
    playlists = MusicPlaylist.objects.all()
    published_count = 0
    errors = []

    for playlist in playlists:
        try:
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

            published_count += 1
        except (OSError, RequestException, DatabaseError) as e:
            # Catch file I/O, upstream request and DB errors explicitly to avoid
            # broad-exception Pylint warning and to be explicit about expected failure modes.
            errors.append(f"Error publishing playlist '{playlist.title}': {e}")

    return {
        "playlists_processed": playlists.count(),
        "playlists_published": published_count,
        "errors": errors,
    }
