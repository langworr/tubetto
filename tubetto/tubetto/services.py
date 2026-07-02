"""
Services module for Tubetto.

This module provides utility functions for interacting with YouTube via yt-dlp,
extracting and caching video/audio metadata, resolving stream manifests, and
performing batch metadata updates for videos, channels, and music tracks.

Key functionality:
- Caching: In-memory TTL-based cache for yt-dlp queries to reduce API calls.
- Video Info: Resolve video metadata, comments, and related videos using yt-dlp.
- Audio Extraction: Select and return the best audio-only stream for a video.
- Stream Selection: Choose between progressive (single-file), HLS, or DASH manifests.
- Channel Management: Scan channels for videos and update channel/video metadata.
- Music Metadata: Update music track metadata from YouTube sources.

Functions:
- _cache_get(video_id): Retrieve cached data if not expired.
- _cache_set(video_id, data, ttl): Store data in cache with TTL.
- resolve_video_info(video_id): Fetch complete video metadata via yt-dlp.
- select_best_audio(formats): Pick the best audio-only format from available formats.
- resolve_audio_stream(video_id): Return a direct audio stream URL for a video.
- update_music_tracks_metadata(): Update metadata for all music tracks in the database.
- _select_progressive(formats): Choose the best progressive (single-file) stream.
- select_manifest(data): Determine the best stream manifest type (progressive/HLS/DASH).
- resolve_stream_manifest(video_id): Resolve and return stream manifest info for a video.
- resolve_video_comments(video_id, max_comments): Fetch YouTube comments for a video.
- resolve_related_videos(video_id, limit): Get suggested/related videos.
- list_channel_videos_flat(channel_id, limit): Fetch a flat list of videos from a channel.
- resolve_channel_metadata(channel_id): Fetch channel metadata using yt-dlp.
- update_channels_metadata(): Update metadata for all channels in the database.
- scan_channel_videos(): Scan and index all videos from all channels.
- update_videos_metadata(): Update metadata for all videos in the database.
- run_scheduled_task(): Run all scheduled tasks (channels, scan, videos, music) in sequence.
- metadata_from_info(data): Extract persistent metadata fields from yt-dlp info dict.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from crawlee.http_clients import ImpitHttpClient

from music.models import MusicTrack
from videos.models import Channel, Video, ChannelVideo

logger = logging.getLogger(__name__)

_CACHE = {}  # {video_id: (expires_epoch, data)}


def _cache_get(video_id: str) -> Optional[dict]:
    """
    Retrieve cached data for a video if it exists and has not expired.

    Args:
        video_id (str): YouTube video identifier.

    Returns:
        dict or None: The cached data if valid, None if not cached or expired.
    """
    item = _CACHE.get(video_id)
    if item and item[0] > time.time():
        return item[1]
    return None


def _cache_set(video_id: str, data: dict, ttl: int = 90) -> None:
    """
    Store data in cache with a time-to-live (TTL).

    Args:
        video_id (str): YouTube video identifier.
        data (dict): Data to cache.
        ttl (int): Time to live in seconds (default 90).

    Returns:
        None
    """
    _CACHE[video_id] = (time.time() + ttl, data)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _fetch_page(url: str, timeout: int = 25) -> str:
    async def _request() -> str:
        client = ImpitHttpClient(browser="firefox")
        async with client:
            response = await client.send_request(url, timeout=timedelta(seconds=timeout))
            return (await response.read()).decode("utf-8", "ignore")

    return _run_async(_request())


def _extract_json_object(text: str, marker: str) -> dict:
    marker_pos = text.find(marker)
    if marker_pos == -1:
        return {}

    start = text.find("{", marker_pos)
    if start == -1:
        return {}

    depth = 0
    quote = False
    escape = False
    snippet = ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quote = False
            continue

        if char == '"':
            quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start:index + 1]
                break

    if not snippet:
        return {}

    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return {}


def _extract_player_response(html: str) -> dict:
    player_response = _extract_json_object(html, "ytInitialPlayerResponse")
    if player_response:
        return player_response
    return {}


def _extract_initial_data(html: str) -> dict:
    return _extract_json_object(html, "ytInitialData")


def _normalize_format(format_data: dict) -> dict:
    mime_type = format_data.get("mimeType") or format_data.get("mime_type") or ""
    ext = format_data.get("ext")
    if not ext and mime_type:
        if "mp4" in mime_type:
            ext = "mp4"
        elif "webm" in mime_type:
            ext = "webm"
        elif "m4a" in mime_type:
            ext = "m4a"

    acodec = format_data.get("audioCodec") or format_data.get("audio_sample_rate") or None
    vcodec = format_data.get("videoCodec") or format_data.get("vcodec") or None
    if mime_type.startswith("audio/") and not acodec:
        acodec = "audio"
    elif mime_type.startswith("video/") and not vcodec:
        vcodec = "video"

    return {
        "url": format_data.get("url") or "",
        "ext": ext,
        "mime_type": mime_type,
        "acodec": acodec,
        "vcodec": vcodec,
        "tbr": format_data.get("bitrate") or format_data.get("averageBitrate") or None,
    }


def _select_audio_format_from_streaming_data(streaming_data: dict) -> dict | None:
    formats = streaming_data.get("adaptiveFormats") or streaming_data.get("formats") or []
    audio_only: List[dict] = []
    for item in formats:
        normalized = _normalize_format(item)
        if normalized.get("url") and (normalized.get("vcodec") in (None, "none")) and normalized.get("acodec"):
            audio_only.append(normalized)
    if not audio_only:
        return None

    def score(item: dict) -> tuple:
        ext = (item.get("ext") or "").lower()
        is_preferred = 1 if ext in ("m4a", "mp4", "mp4a") else 0
        return is_preferred, item.get("tbr") or 0

    audio_only = sorted(audio_only, key=score, reverse=True)
    return audio_only[0]


def resolve_video_info(video_id: str) -> dict:
    """
    Fetch video metadata from YouTube using Crawlee.

    The implementation retrieves the watch page through Crawlee and parses the
    embedded player payload, which is sufficient for metadata and stream
    selection within this application.
    """
    cached = _cache_get(video_id)
    if cached:
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    html = _fetch_page(url)
    player_response = _extract_player_response(html)
    if not player_response:
        raise RuntimeError("Unable to resolve video metadata via Crawlee")

    video_details = player_response.get("videoDetails", {})
    streaming_data = player_response.get("streamingData", {})
    formats = [_normalize_format(format_data) for format_data in (streaming_data.get("formats") or []) + (streaming_data.get("adaptiveFormats") or [])]
    thumbnails = video_details.get("thumbnail", {}).get("thumbnails", [])
    thumbnail_url = thumbnails[-1].get("url") if thumbnails else ""
    duration = video_details.get("lengthSeconds")
    try:
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None

    data = {
        "id": video_details.get("videoId") or video_id,
        "title": video_details.get("title"),
        "description": video_details.get("shortDescription"),
        "duration": duration,
        "thumbnail": thumbnail_url,
        "channel": video_details.get("author"),
        "uploader": video_details.get("author"),
        "channel_id": video_details.get("channelId"),
        "view_count": video_details.get("viewCount"),
        "formats": formats,
        "adaptiveFormats": [format_item for format_item in formats if format_item.get("url")],
        "streamingData": streaming_data,
        "player_response": player_response,
    }

    _cache_set(video_id, data)
    return data


def select_best_audio(formats: list[dict] | dict) -> dict | None:
    """Pick the best audio-only format from Crawlee-derived stream data."""
    if isinstance(formats, dict):
        return _select_audio_format_from_streaming_data(formats)
    audio_only: List[dict] = []
    for item in formats:
        normalized = item if isinstance(item, dict) else _normalize_format(item)
        if normalized.get("url") and (normalized.get("vcodec") in (None, "none")) and normalized.get("acodec"):
            audio_only.append(normalized)
    if not audio_only:
        return None

    def score(item: dict) -> tuple:
        ext = (item.get("ext") or "").lower()
        is_preferred = 1 if ext in ("m4a", "mp4", "mp4a") else 0
        return is_preferred, item.get("tbr") or 0

    audio_only = sorted(audio_only, key=score, reverse=True)
    return audio_only[0]


def resolve_audio_stream(video_id: str) -> dict:
    """Return a direct audio stream URL and metadata for a given YouTube video."""
    info = resolve_video_info(video_id)
    audio = select_best_audio(info.get("streamingData", {})) or select_best_audio(info.get("formats", []))
    if not audio:
        raise RuntimeError("No audio-only stream available")
    return {
        "video_id": video_id,
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "stream_url": audio.get("url"),
        "ext": audio.get("ext"),
        "acodec": audio.get("acodec"),
    }


def update_music_tracks_metadata() -> Dict[str, Any]:
    """
    Update metadata for all music tracks in the database using yt-dlp.

    Iterates over all MusicTrack objects, fetches metadata from YouTube,
    and updates title, artist, album, and duration if they differ from
    the YouTube source.

    Returns:
        dict: Result summary with keys 'tracks_processed', 'tracks_updated', 'errors'.
    """
    results: Dict[str, Any] = {
        "tracks_processed": 0,
        "tracks_updated": 0,
        "errors": [],
    }

    tracks = MusicTrack.objects.all()
    for track in tracks:
        try:
            info = resolve_video_info(track.yt_video_id)
            duration = info.get("duration")
            if isinstance(duration, float):
                duration = int(duration)
            elif isinstance(duration, str):
                try:
                    duration = int(float(duration))
                except ValueError:
                    duration = None

            metadata_updates = {
                "title": info.get("title") or track.title,
                "artist": info.get("artist") or info.get("uploader") or track.artist,
                "album": info.get("album") or track.album,
                "duration": duration if duration is not None else track.duration,
            }

            changed = False
            for field, value in metadata_updates.items():
                current = getattr(track, field)
                if value is not None and value != current:
                    setattr(track, field, value)
                    changed = True

            if changed:
                track.save()
                results["tracks_updated"] += 1
            results["tracks_processed"] += 1

        except (RuntimeError, ValueError, TypeError) as exc:
            results["errors"].append(f"{track.yt_video_id}: {exc}")

    return results


def _select_progressive(formats: list[dict]) -> dict | None:
    """
    Select the best progressive (single-file) video format.

    Filters formats that contain both video and audio codecs, prefer HTTP/HTTPS,
    and selects the highest quality (preferring MP4, then by bitrate).

    Args:
        formats (list[dict): List of format dicts from yt-dlp.

    Returns:
        dict or None: Best progressive format with keys 'type', 'url', 'ext', or None if none available.
    """
    progressive = []
    for f in formats:
        if (f.get("vcodec") and f.get("vcodec") != "none") and (f.get("acodec") and f.get("acodec") != "none"):
            if (f.get("protocol") in ("https", "http")) and f.get("url"):
                progressive.append(f)
    if not progressive:
        return None
    # Prefer MP4, then highest bitrate
    progressive = sorted(progressive, key=lambda f: (f.get("ext") == "mp4", f.get("tbr") or 0), reverse=True)
    chosen = progressive[0]
    return {"type": "progressive", "url": chosen.get("url"), "ext": chosen.get("ext")}


def select_manifest(data: dict) -> dict:
    """
    Determine and select the best available stream manifest type.

    Prioritizes: progressive (single-file) > HLS (m3u8) > DASH (mpd).
    Returns the selected manifest info with type and URL(s).

    Args:
        data (dict): Full yt-dlp info dictionary.

    Returns:
        dict: Selected manifest with keys 'type' and either 'url' (progressive) or 'manifest_url' (HLS/DASH).

    Raises:
        RuntimeError: If no suitable manifest is found.
    """
    formats = data.get("formats", [])
    # 1) Prefer progressive (single-file) for simpler proxying/playback
    prog = _select_progressive(formats)
    if prog:
        return prog
    # 2) HLS (m3u8)
    hls = [f for f in formats if f.get("protocol") == "m3u8" or "m3u8" in (f.get("url") or "")]
    if hls:
        chosen = sorted(hls, key=lambda f: f.get("tbr") or 0, reverse=True)[0]
        return {"type": "hls", "manifest_url": chosen.get("url")}
    # 3) DASH manifest
    dash = [f for f in formats if f.get("manifest_url") or (f.get("url") or "").endswith(".mpd")]
    if dash:
        chosen = dash[0]
        mu = chosen.get("manifest_url") or chosen.get("url")
        return {"type": "dash", "manifest_url": mu}
    raise RuntimeError("Nessun manifest disponibile (progressive/HLS/DASH)")


def resolve_stream_manifest(video_id: str) -> dict:
    """
    Resolve and return stream manifest information for a video.

    Fetches video info, selects the best manifest type (progressive/HLS/DASH),
    and returns comprehensive metadata including title, duration, thumbnail,
    and stream details.

    Args:
        video_id (str): YouTube video identifier.

    Returns:
        dict: Stream info with keys 'video_id', 'title', 'thumbnail', 'duration',
              'channel', 'upload_date', 'stream_type', and stream-specific keys.
    """
    info = resolve_video_info(video_id)
    sel = select_manifest(info)
    result = {
        "video_id": video_id,
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "channel": (info.get("channel") or ""),
        "upload_date": info.get("upload_date"),
    }
    if sel["type"] == "progressive":
        result.update({
            "stream_type": "progressive",
            "stream_url": sel.get("url"),
            "ext": sel.get("ext"),
        })
    elif sel["type"] == "hls":
        result.update({
            "stream_type": "hls",
            "manifest_url": sel.get("manifest_url"),
        })
    else:
        result.update({
            "stream_type": "dash",
            "manifest_url": sel.get("manifest_url"),
        })
    return result


def resolve_video_comments(video_id: str, max_comments: int = 50) -> list[dict]:
    """Fetch YouTube comments for a video using Crawlee-derived page data."""
    cached = _cache_get(f"comments:{video_id}:{max_comments}")
    if cached is not None:
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        html = _fetch_page(url)
    except Exception:
        return []

    player_response = _extract_player_response(html)
    comments = player_response.get("contents", {}).get("twoColumnWatchNextResults", {}).get("results", {}).get("results", {}).get("comments", [])
    normalized = []
    for comment in comments[:max_comments]:
        comment_text = comment.get("commentText", {})
        normalized.append({
            "author": comment.get("authorText", {}).get("simpleText") or "",
            "text": comment_text.get("simpleText") or "",
            "like_count": comment.get("likes", 0),
            "timestamp": 0,
            "published": "",
        })

    _cache_set(f"comments:{video_id}:{max_comments}", normalized, ttl=120)
    return normalized


def resolve_related_videos(video_id: str, limit: int = 12) -> list[dict]:
    """Get suggested videos by parsing the watch page with Crawlee."""
    cached = _cache_get(f"related:{video_id}:{limit}")
    if cached is not None:
        return cached

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        html = _fetch_page(url)
    except Exception:
        return []

    matches = re.findall(r"(?:/watch\?v=|/shorts/)([A-Za-z0-9_-]{11})", html)
    results = []
    for video_id_match in matches:
        if video_id_match == video_id:
            continue
        results.append({
            "yt_video_id": video_id_match,
            "title": "",
            "thumbnail_url": "",
            "channel": "",
        })
        if len(results) >= limit:
            break

    _cache_set(f"related:{video_id}:{limit}", results, ttl=180)
    return results


def list_channel_videos_flat(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    """Fetch a flat list of videos from a YouTube channel using Crawlee."""
    cache_key = f"chflat:{channel_id}:{limit if limit else 'all'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}/videos"
    elif channel_id.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
    else:
        url = f"https://www.youtube.com/c/{channel_id}/videos"

    logger.debug("Fetching channel videos for %s from %s", channel_id, url)
    try:
        html = _fetch_page(url)
    except Exception:
        return []

    matches = re.findall(r"(?:/watch\?v=|/shorts/)([A-Za-z0-9_-]{11})", html)
    results: List[Dict] = []
    seen = set()
    for video_id_match in matches:
        if video_id_match in seen or video_id_match == channel_id:
            continue
        seen.add(video_id_match)
        results.append({
            "yt_video_id": video_id_match,
            "title": "",
        })
        if limit and len(results) >= limit:
            break

    _cache_set(cache_key, results, ttl=300)
    logger.debug("Fetched %d videos for channel %s", len(results), channel_id)
    return results


def resolve_channel_metadata(channel_id: str) -> Dict[str, Optional[str]]:
    """Fetch channel metadata from YouTube using Crawlee."""
    url = f"https://www.youtube.com/channel/{channel_id}"
    try:
        html = _fetch_page(url)
    except Exception:
        return {}

    title_match = re.search(r"<meta property=\"og:title\" content=\"([^\"]+)\">", html)
    thumbnail_match = re.search(r"<meta property=\"og:image\" content=\"([^\"]+)\">", html)
    description_match = re.search(r"<meta name=\"description\" content=\"([^\"]+)\">", html)

    return {
        "title": title_match.group(1) if title_match else "",
        "description": description_match.group(1) if description_match else "",
        "thumbnail": thumbnail_match.group(1) if thumbnail_match else "",
        "subscriber_count": None,
        "video_count": None,
    }


def update_channels_metadata() -> Dict[str, any]:
    """
    Update metadata for all channels in the database.

    Iterates over all Channel objects, fetches metadata from YouTube,
    and updates fields if they differ from the YouTube source.

    Returns:
        dict: Result summary with keys 'channels_processed', 'channels_updated', 'channels_errors'.
    """
    results = {
        "channels_processed": 0,
        "channels_updated": 0,
        "channels_errors": [],
    }

    channels = Channel.objects.all()
    for channel in channels:
        try:
            meta = resolve_channel_metadata(channel.yt_channel_id)
            changed = False
            for field, value in meta.items():
                if value is not None:
                    current = getattr(channel, field, None)
                    if current != value:
                        setattr(channel, field, value)
                        changed = True
            if changed:
                channel.save()
                results["channels_updated"] += 1
            results["channels_processed"] += 1
        except (RuntimeError, ValueError, AttributeError) as e:
            results["channels_errors"].append(f"{channel.yt_channel_id}: {str(e)}")

    return results


def scan_channel_videos(channel_ids: Optional[List[int]] = None) -> Dict[str, any]:
    """
    Scan videos for a set of channels and insert/update them in the database.

    If channel_ids is None, scans all channels. Otherwise, scans only the
    supplied Channel primary keys.

    Returns:
        dict: Result summary with keys 'channels_scanned', 'videos_scanned',
              'videos_created', 'videos_updated', 'errors'.
    """
    results = {
        "channels_scanned": 0,
        "videos_scanned": 0,
        "videos_created": 0,
        "videos_updated": 0,
        "errors": [],
    }

    channels = Channel.objects.all()
    if channel_ids is not None:
        channels = channels.filter(pk__in=channel_ids)

    for channel in channels:
        try:
            # Clear cache for this channel to ensure fresh data
            cache_key = f"chflat:{channel.yt_channel_id}:all"
            if cache_key in _CACHE:
                del _CACHE[cache_key]

            # Fetch all videos from the channel (no limit)
            vids = list_channel_videos_flat(channel.yt_channel_id, limit=None)
            if not vids:
                results["errors"].append(f"Channel {channel.yt_channel_id}: No videos found or error fetching videos")
                continue
            results["videos_scanned"] += len(vids)

            for v in vids:
                try:
                    # Create/update ChannelVideo entry
                    chv, _ = ChannelVideo.objects.get_or_create(
                        channel=channel,
                        yt_video_id=v["yt_video_id"],
                        defaults={"title": v.get("title", "")},
                    )
                    if v.get("title") and chv.title != v["title"]:
                        chv.title = v["title"]
                        chv.save(update_fields=["title"])

                    # Create/update Video entry with full metadata
                    vid_obj, created = Video.objects.get_or_create(
                        yt_video_id=v["yt_video_id"],
                        defaults={
                            "title": v.get("title", v["yt_video_id"]),
                            "channel": channel,
                        },
                    )

                    if created:
                        results["videos_created"] += 1

                    # Fetch and update full metadata for the video
                    try:
                        info = resolve_video_info(v["yt_video_id"])
                        meta = metadata_from_info(info)
                        changed = False
                        for field, value in meta.items():
                            if value is None:
                                continue
                            if getattr(vid_obj, field) != value:
                                setattr(vid_obj, field, value)
                                changed = True
                        if not vid_obj.channel:
                            vid_obj.channel = channel
                            changed = True
                        if v.get("title") and vid_obj.title != v["title"]:
                            vid_obj.title = v["title"]
                            changed = True
                        if changed:
                            vid_obj.save()
                            if not created:
                                results["videos_updated"] += 1
                    except (RuntimeError, ValueError, AttributeError) as e:
                        results["errors"].append(f"Video {v.get('yt_video_id')} metadata: {str(e)}")
                except (RuntimeError, ValueError, AttributeError, KeyError) as e:
                    results["errors"].append(f"Video {v.get('yt_video_id')}: {str(e)}")
            results["channels_scanned"] += 1
        except (RuntimeError, ValueError, AttributeError) as e:
            results["errors"].append(f"Channel {channel.yt_channel_id} scan: {str(e)}")

    return results


def update_videos_metadata() -> Dict[str, any]:
    """
    Update metadata for all videos in the database.

    Iterates over all Video objects, fetches metadata from YouTube,
    and updates fields if they differ from the YouTube source.

    Returns:
        dict: Result summary with keys 'videos_processed', 'videos_updated', 'errors'.
    """
    results = {
        "videos_processed": 0,
        "videos_updated": 0,
        "errors": [],
    }

    all_videos = Video.objects.all()
    for video in all_videos:
        try:
            info = resolve_video_info(video.yt_video_id)
            meta = metadata_from_info(info)
            changed = False
            for field, value in meta.items():
                if value is not None:
                    current = getattr(video, field, None)
                    if current != value:
                        setattr(video, field, value)
                        changed = True
            if changed:
                video.save()
                results["videos_updated"] += 1
            results["videos_processed"] += 1
        except (RuntimeError, ValueError, AttributeError) as e:
            results["errors"].append(f"Video {video.yt_video_id}: {str(e)}")

    return results


def run_scheduled_task() -> Dict[str, any]:
    """
    Run all scheduled maintenance tasks in sequence.

    Executes: update_channels_metadata → scan_channel_videos →
    update_videos_metadata → update_music_tracks_metadata.

    Returns:
        dict: Nested result summary with keys 'channels', 'scan', 'videos', 'music',
              each containing task-specific results.
    """
    channel_results = update_channels_metadata()
    scan_results = scan_channel_videos()
    video_results = update_videos_metadata()
    music_results = update_music_tracks_metadata()

    return {
        "channels": channel_results,
        "scan": scan_results,
        "videos": video_results,
        "music": music_results,
    }


def metadata_from_info(data: dict) -> Dict[str, Optional[str]]:
    """
    Extract persistent metadata fields from a yt-dlp info dictionary.

    Normalizes date strings to date objects, parses duration as integer,
    and extracts common video metadata fields.

    Args:
        data (dict): Full yt-dlp info dictionary.

    Returns:
        dict: Normalized metadata with keys 'title', 'description', 'duration',
              'upload_date', 'thumbnail', 'channel_title', 'channel_external_id',
              'uploader', 'uploader_id'.
    """
    upload_date = data.get("upload_date")
    upload_date_obj: Optional[datetime.date] = None
    if upload_date:
        try:
            upload_date_obj = datetime.strptime(upload_date, "%Y%m%d").date()
        except ValueError:
            upload_date_obj = None
    duration = data.get("duration")
    if isinstance(duration, float):
        duration = int(duration)
    elif isinstance(duration, str):
        try:
            duration = int(float(duration))
        except ValueError:
            duration = None
    return {
        "title": data.get("title") or "",
        "description": data.get("description") or "",
        "duration": duration,
        "upload_date": upload_date_obj,
        "thumbnail": data.get("thumbnail") or "",
        "channel_title": data.get("channel") or "",
        "channel_external_id": data.get("channel_id") or data.get("channel_url") or "",
        "uploader": data.get("uploader") or "",
        "uploader_id": data.get("uploader_id") or "",
    }
