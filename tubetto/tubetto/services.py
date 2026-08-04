from http.cookiejar import LoadError, MozillaCookieJar
import logging
import re
import subprocess
import json
import time
from datetime import datetime
from typing import List, Dict, Optional, Any
from django.conf import settings
import requests
import yt_dlp
from yt_dlp.utils import DownloadError

from music.models import MusicTrack
from videos.models import Channel, Video, ChannelVideo

logger = logging.getLogger(__name__)

_CACHE = {}  # {video_id: (expires_epoch, data)}

YT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


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


def resolve_video_info(video_id: str) -> dict:
    """
    Fetch complete video metadata from YouTube using yt-dlp.

    Uses yt-dlp to extract video information including title, description,
    formats, duration, and more. Results are cached for the TTL period.

    Args:
        video_id (str): YouTube video identifier.

    Returns:
        dict: Full yt-dlp info dictionary with video metadata.

    Raises:
        RuntimeError: If yt-dlp returns a non-zero exit code.
    """
    cached = _cache_get(video_id)
    if cached:
        return cached
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'skip_download': True,
        'no_warnings': True,
        'quiet': True,
    }
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        raise RuntimeError(f"yt-dlp error: {e.args[0] if e.args else 'unknown error'}") from e

    _cache_set(video_id, data)
    return data


def select_best_audio(formats: list[dict]) -> dict | None:
    """
    Pick the best audio-only format from a list of available formats.

    Filters formats with no video codec but valid audio codec, then selects
    the highest quality, preferring m4a/mp4 over webm.

    Args:
        formats (list[dict]): List of format dicts from yt-dlp.

    Returns:
        dict or None: Best audio format with keys 'url', 'ext', 'acodec', or None if none available.
    """
    audio_only = []
    for f in formats:
        if (f.get("vcodec") in (None, "none")) and (f.get("acodec") and f.get("acodec") != "none") and f.get("url"):
            audio_only.append(f)
    if not audio_only:
        return None
    # Prefer m4a/mp4 over webm when bitrates are comparable

    def score(f: dict) -> tuple:
        ext = (f.get("ext") or "").lower()
        is_m4a = 1 if ext in ("m4a", "mp4", "mp4a") else 0
        return (is_m4a, f.get("tbr") or f.get("abr") or 0)
    audio_only = sorted(audio_only, key=score, reverse=True)
    best = audio_only[0]
    return {"url": best.get("url"), "ext": best.get("ext"), "acodec": best.get("acodec")}


def resolve_audio_stream(video_id: str) -> dict:
    """
    Return a direct audio stream URL and metadata for a given YouTube video.

    Resolves video info, selects the best audio-only format, and returns
    stream details including URL, codec, and video metadata.

    Args:
        video_id (str): YouTube video identifier.

    Returns:
        dict: Dictionary with keys 'video_id', 'title', 'duration', 'thumbnail',
              'stream_url', 'ext', 'acodec'.

    Raises:
        RuntimeError: If no audio-only stream is available.
    """
    info = resolve_video_info(video_id)
    audio = select_best_audio(info.get("formats", []))
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
    """
    Fetch YouTube comments for a video using yt-dlp.

    Extracts up to max_comments top-level comments and normalizes them.
    Results are cached. On errors, returns an empty list.

    Args:
        video_id (str): YouTube video identifier.
        max_comments (int): Maximum number of comments to fetch (default 50).

    Returns:
        list[dict]: List of normalized comment dicts with keys 'author', 'text',
                   'like_count', 'timestamp', 'published'.
    """
    cached = _cache_get(f"comments:{video_id}:{max_comments}")
    if cached is not None:
        return cached
    ydl_opts = {
        'skip_download': True,
        'no_warnings': True,
        'quiet': True,
        'extractor_args': {
            'youtube': {
                'comments': 'all',
                'comment_sort': 'top',
                'max_comments': max_comments,
            }
        },
    }

    url = f"https://www.youtube.com/watch?v={video_id}"
    data = {}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)

    except DownloadError:
        return []

    comments = data.get("comments") or []
    normalized = []
    for c in comments:
        normalized.append({
            "author": c.get("author") or "",
            "text": c.get("text") or "",
            "like_count": c.get("like_count") or 0,
            "timestamp": c.get("timestamp") or 0,
            "published": c.get("published") or "",
        })

    _cache_set(f"comments:{video_id}:{max_comments}", normalized, ttl=120)
    return normalized


def resolve_related_videos(video_id: str, limit: int = 12) -> list[dict]:
    """
    Get suggested/related videos for a video using yt-dlp metadata.

    Parses related_videos or related data from yt-dlp info and extracts
    video IDs, titles, thumbnails, and channels. Results are cached.

    Args:
        video_id (str): YouTube video identifier.
        limit (int): Maximum number of related videos to return (default 12).

    Returns:
        list[dict]: List of related video dicts with keys 'yt_video_id', 'title',
                   'thumbnail_url', 'channel'.
    """
    cached = _cache_get(f"related:{video_id}:{limit}")
    if cached is not None:
        return cached
    info = resolve_video_info(video_id)
    related = info.get("related_videos") or info.get("related") or []
    # Some formats:
    # - list of dicts with 'id' or 'url', 'title', 'thumbnails'
    results = []
    for r in related:
        vid = r.get("id") or (r.get("url") or "").split("v=")[-1]
        if not vid:
            continue
        thumb = None
        thumbs = r.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url") or thumbs[0].get("url")
        results.append({
            "yt_video_id": vid,
            "title": r.get("title") or "",
            "thumbnail_url": thumb or "",
            "channel": r.get("uploader") or r.get("channel") or "",
        })
        if len(results) >= limit:
            break
    _cache_set(f"related:{video_id}:{limit}", results, ttl=180)
    return results


def list_channel_videos_flat(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    """
    Fetch a flat list of videos from a YouTube channel using yt-dlp.

    Retrieves videos from a channel's videos page with optional limit.
    Results are cached. Returns empty list on error.

    Args:
        channel_id (str): YouTube channel identifier (e.g., UCxxxx...).
        limit (int or None): Maximum videos to fetch; None fetches all available.

    Returns:
        list[dict]: List of video dicts with keys 'yt_video_id' and 'title'.
    """
    cache_key = f"chflat:{channel_id}:{limit if limit else 'all'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    # Use the channel's videos page - yt-dlp will handle pagination
    if channel_id.startswith("@"):  # YouTube handle
        url = f"https://www.youtube.com/{channel_id}/videos"
    elif channel_id.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel_id}/videos"
    else:
        url = f"https://www.youtube.com/c/{channel_id}/videos"

    logger.debug("Fetching channel videos for %s from %s", channel_id, url)
    cmd = [
        "yt-dlp", "-J", "--no-warnings", "--flat-playlist",
    ]
    # If limit is None, fetch all videos by setting playlist-end to -1
    # This tells yt-dlp to fetch all available videos
    if limit is None:
        cmd.extend(["--playlist-end", "-1"])
    else:
        cmd.extend(["--playlist-end", str(limit)])
    cmd.append(url)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except subprocess.TimeoutExpired as e:
        logger.error("yt-dlp timeout for channel %s after %s seconds", channel_id, e.timeout)
        return []
    if proc.returncode != 0:
        logger.error(
            "yt-dlp returned non-zero code for channel %s: %s; stderr=%s",
            channel_id,
            proc.returncode,
            proc.stderr.strip(),
        )
        # Return empty list on error - errors are handled by the caller
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    entries = data.get("entries") or []
    results: List[Dict] = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        results.append({
            "yt_video_id": vid,
            "title": e.get("title") or "",
        })
        # Only break if we have a limit and reached it
        if limit and len(results) >= limit:
            break
    _cache_set(cache_key, results, ttl=300)
    logger.debug("Fetched %d videos for channel %s", len(results), channel_id)
    return results


def resolve_channel_metadata(
        channel_id: str,
        cookies_file: Optional[str] = "cookies.txt",
        regex_file: Optional[str] = "regex_list.json",
) -> Dict[str, Optional[str]]:
    if channel_id.startswith("@"):
        url = f"https://www.youtube.com/{channel_id}"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}"

    cookies_path = settings.MEDIA_ROOT / cookies_file
    regex_path = settings.MEDIA_ROOT / regex_file

    if not cookies_path.exists():
        logger.warning("Cookies file %s not found", cookies_path)
        return {}

    reg_ex = {}
    if regex_path.exists():
        reg_ex = json.loads(regex_path.read_text(encoding="utf-8"))
    else:
        logger.warning("Regex file %s not found", regex_path)
        return {}

    jar = MozillaCookieJar(str(cookies_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, LoadError) as e:
        logger.error("Errore nel caricare i cookie da %s: %s", cookies_path, str(e))
        return {}

    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": YT_USER_AGENT,
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    logger.warning("Fetching channel page for %s", channel_id)
    try:
        response = session.get(url, allow_redirects=True, timeout=15)
    except (OSError, LoadError) as e:
        logger.error("Error fetching channel page for %s: %s", channel_id, str(e))
        return {}

    logger.warning(
        "Status %s, Final URL %s, len=%d",
        response.status_code, response.url, len(response.text),
    )

    if "consent.youtube.com" in response.url or "consent.google.com" in response.url:
        logger.error(
            "Redirect alla pagina di consenso per %s: i cookie non sono "
            "stati accettati da questo IP/contesto (Final URL=%s)",
            channel_id, response.url,
        )
        return {}

    html = response.text

    standard_keys = [
        "channel_id",
        "channel_url",
        "title",
        "description",
        "thumbnail",
    ]

    metadata = {}
    for key in standard_keys:
        pattern = reg_ex.get(key)
        if pattern:
            match = re.search(pattern, html)
            metadata[key] = match.group(1) if match else None
        else:
            metadata[key] = None

    logger.warning("Resolved metadata for channel %s: %s", channel_id, metadata)
    return metadata


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
