from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
import logging
import re
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from django.conf import settings
import requests
import yt_dlp
from yt_dlp.utils import DownloadError

from music.models import MusicTrack
from videos.models import Channel, Video, ChannelVideo, Tab

from tubetto.constants import YT_USER_AGENT
from tubetto.enums import YouTubeTab

from django.core.cache import cache

logger = logging.getLogger(__name__)

YOUTUBE_HTTP_HEADERS = {
    "User-Agent": YT_USER_AGENT,
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "*/*",
    "Origin": "https://www.youtube.com",
    "Referer": "https://www.youtube.com/",
}


def cookies_file_path(cookies_file: str = "cookies.txt") -> Optional[Path]:
    data_dir = Path(getattr(settings, "DATA_DIR", settings.MEDIA_ROOT))
    candidates = [data_dir / cookies_file, Path(settings.MEDIA_ROOT) / cookies_file]
    for path in candidates:
        if path.exists():
            return path
    return None


def youtube_request_cookies():
    path = cookies_file_path()
    if not path:
        return None
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, LoadError) as e:
        logger.error("Error loading cookies from %s: %s", path, e)
        return None
    return jar


def ydl_base_opts() -> dict:
    opts = {
        "skip_download": True,
        "no_warnings": True,
        "quiet": True,
        "http_headers": dict(YOUTUBE_HTTP_HEADERS),
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "ios", "android"],
            }
        },
    }
    cookies_path = cookies_file_path()
    if cookies_path:
        opts["cookiefile"] = str(cookies_path)
    return opts


def _cache_get(key: str) -> Optional[Any]:
    return cache.get(key)


def _cache_set(key: str, data: Any, ttl: int = 90) -> None:
    cache.set(key, data, timeout=ttl)


def resolve_video_info(video_id: str) -> dict:
    cache_key = f"ytinfo:{video_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    ydl_opts = ydl_base_opts()
    ydl_opts["format"] = "bestvideo*+bestaudio/best"
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        raise RuntimeError(f"yt-dlp error: {e.args[0] if e.args else 'unknown error'}") from e

    _cache_set(cache_key, data)
    return data


def select_best_audio(formats: list[dict]) -> dict | None:
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
    return {
        "url": best.get("url"),
        "ext": best.get("ext"),
        "acodec": best.get("acodec"),
        "http_headers": _http_headers_from_format(best),
    }


def resolve_audio_stream(video_id: str) -> dict:
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
        "http_headers": audio.get("http_headers") or dict(YOUTUBE_HTTP_HEADERS),
    }


def update_music_tracks_metadata() -> Dict[str, Any]:
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


def _http_headers_from_format(fmt: dict | None) -> dict:
    headers = dict(YOUTUBE_HTTP_HEADERS)
    if not fmt:
        return headers
    extra = fmt.get("http_headers") or {}
    headers.update(extra)
    return headers


def _is_http_format(fmt: dict) -> bool:
    proto = (fmt.get("protocol") or "https").split("+", 1)[0]
    return proto in ("http", "https") and bool(fmt.get("url"))


def _select_progressive(formats: list[dict]) -> dict | None:
    progressive = []
    for f in formats:
        if not _is_http_format(f):
            continue
        if (f.get("vcodec") and f.get("vcodec") != "none") and (f.get("acodec") and f.get("acodec") != "none"):
            if (f.get("ext") or "").lower() in ("mp4", "m4v", "webm"):
                progressive.append(f)
    if not progressive:
        return None
    progressive = sorted(
        progressive,
        key=lambda f: ((f.get("ext") or "").lower() == "mp4", f.get("tbr") or 0),
        reverse=True,
    )
    chosen = progressive[0]
    return {
        "type": "progressive",
        "url": chosen.get("url"),
        "ext": chosen.get("ext"),
        "http_headers": _http_headers_from_format(chosen),
    }


def _is_hls_format(fmt: dict) -> bool:
    proto = (fmt.get("protocol") or "")
    ext = (fmt.get("ext") or "")
    url = fmt.get("manifest_url") or fmt.get("url") or ""
    return "m3u8" in proto or ext == "m3u8" or ".m3u8" in url


def _select_hls(formats: list[dict]) -> dict | None:
    hls = [f for f in formats if _is_hls_format(f) and (f.get("url") or f.get("manifest_url"))]
    if not hls:
        return None
    chosen = sorted(hls, key=lambda f: f.get("tbr") or f.get("height") or 0, reverse=True)[0]
    return {
        "type": "hls",
        "manifest_url": chosen.get("manifest_url") or chosen.get("url"),
        "http_headers": _http_headers_from_format(chosen),
    }


def _select_adaptive_pair(formats: list[dict]) -> dict | None:
    videos = []
    audios = []
    for f in formats:
        if not _is_http_format(f):
            continue
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        has_video = vcodec and vcodec != "none"
        has_audio = acodec and acodec != "none"
        if has_video and not has_audio:
            videos.append(f)
        elif has_audio and not has_video:
            audios.append(f)
    if not videos or not audios:
        return None

    def video_score(f: dict) -> tuple:
        ext = (f.get("ext") or "").lower()
        vcodec = (f.get("vcodec") or "").lower()
        mp4_like = 1 if ext in ("mp4", "m4v") or vcodec.startswith("avc") else 0
        return (mp4_like, f.get("height") or 0, f.get("tbr") or 0)

    def audio_score(f: dict) -> tuple:
        ext = (f.get("ext") or "").lower()
        m4a_like = 1 if ext in ("m4a", "mp4") else 0
        return (m4a_like, f.get("tbr") or f.get("abr") or 0)

    video = sorted(videos, key=video_score, reverse=True)[0]
    audio = sorted(audios, key=audio_score, reverse=True)[0]
    return {
        "type": "dash",
        "video_url": video.get("url"),
        "audio_url": audio.get("url"),
        "video_ext": video.get("ext") or "mp4",
        "audio_ext": audio.get("ext") or "m4a",
        "video_codec": video.get("vcodec") or "avc1.42c01e",
        "audio_codec": audio.get("acodec") or "mp4a.40.2",
        "width": video.get("width") or 0,
        "height": video.get("height") or 0,
        "video_bitrate": int((video.get("tbr") or video.get("vbr") or 1) * 1000),
        "audio_bitrate": int((audio.get("tbr") or audio.get("abr") or 1) * 1000),
        "http_headers": _http_headers_from_format(video),
    }


def select_manifest(data: dict) -> dict:
    formats = data.get("formats") or []
    # HLS first: browser-playable via hls.js, typical YouTube live/vod client output
    hls = _select_hls(formats)
    if hls:
        return hls
    prog = _select_progressive(formats)
    if prog:
        return prog
    adaptive = _select_adaptive_pair(formats)
    if adaptive:
        return adaptive
    dash = [
        f for f in formats
        if f.get("manifest_url") or (f.get("url") or "").endswith(".mpd")
    ]
    if dash:
        chosen = dash[0]
        mu = chosen.get("manifest_url") or chosen.get("url")
        return {
            "type": "dash",
            "manifest_url": mu,
            "http_headers": _http_headers_from_format(chosen),
        }
    raise RuntimeError("Nessun manifest disponibile (progressive/HLS/DASH)")


def resolve_stream_manifest(video_id: str) -> dict:
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
            "http_headers": sel.get("http_headers") or dict(YOUTUBE_HTTP_HEADERS),
        })
    elif sel["type"] == "hls":
        result.update({
            "stream_type": "hls",
            "manifest_url": sel.get("manifest_url"),
            "http_headers": sel.get("http_headers") or dict(YOUTUBE_HTTP_HEADERS),
        })
    else:
        result.update({
            "stream_type": "dash",
            "manifest_url": sel.get("manifest_url"),
            "video_url": sel.get("video_url"),
            "audio_url": sel.get("audio_url"),
            "video_ext": sel.get("video_ext"),
            "audio_ext": sel.get("audio_ext"),
            "video_codec": sel.get("video_codec"),
            "audio_codec": sel.get("audio_codec"),
            "width": sel.get("width"),
            "height": sel.get("height"),
            "video_bitrate": sel.get("video_bitrate"),
            "audio_bitrate": sel.get("audio_bitrate"),
            "http_headers": sel.get("http_headers") or dict(YOUTUBE_HTTP_HEADERS),
        })
    return result


def _channel_tab_url(channel_id: str, tab: str) -> str:
    if channel_id.startswith("@"):  # YouTube handle
        base = f"https://www.youtube.com/{channel_id}"
    elif channel_id.startswith("UC"):
        base = f"https://www.youtube.com/channel/{channel_id}"
    else:
        base = f"https://www.youtube.com/c/{channel_id}"
    return f"{base}/{tab}"


def _extract_flat_entries(url: str, limit: Optional[int] = None) -> List[Dict]:
    ydl_opts = ydl_base_opts()
    ydl_opts["extract_flat"] = True
    if limit:
        ydl_opts["playlistend"] = limit

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        logger.error("yt-dlp error listing %s: %s", url, e.args[0] if e.args else e)
        return []

    if not data:
        return []
    entries = data.get("entries") or []
    if limit:
        entries = entries[:limit]
    return entries


def list_channel_videos_flat(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    cache_key = f"chflat:{channel_id}:{limit if limit else 'all'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = _channel_tab_url(channel_id, YouTubeTab.VIDEOS)
    logger.debug("Fetching channel videos for %s from %s", channel_id, url)

    entries = _extract_flat_entries(url, limit=limit)
    results: List[Dict] = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        results.append({
            "yt_video_id": vid,
            "title": e.get("title") or "",
        })
        if limit and len(results) >= limit:
            break

    _cache_set(cache_key, results, ttl=300)
    logger.debug("Fetched %d videos for channel %s", len(results), channel_id)
    return results


def fetch_channel_playlists(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    url = _channel_tab_url(channel_id, YouTubeTab.PLAYLISTS)
    entries = _extract_flat_entries(url, limit=limit)
    playlists: List[Dict] = []
    for e in entries:
        pid = e.get("id")
        if not pid:
            continue
        playlists.append({"yt_id": pid, "title": e.get("title") or pid})
    return playlists


def fetch_channel_podcasts(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    url = _channel_tab_url(channel_id, YouTubeTab.PODCASTS)
    entries = _extract_flat_entries(url, limit=limit)
    podcasts: List[Dict] = []
    for e in entries:
        pid = e.get("id")
        if not pid:
            continue
        podcasts.append({"yt_id": pid, "title": e.get("title") or pid})
    return podcasts


def fetch_channel_shorts(channel_id: str, limit: Optional[int] = None) -> List[Dict]:
    url = _channel_tab_url(channel_id, YouTubeTab.SHORTS)
    entries = _extract_flat_entries(url, limit=limit)
    shorts: List[Dict] = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        shorts.append({"yt_video_id": vid, "title": e.get("title") or ""})
    return shorts


def sync_channel_tabs(
        channel_ids: Optional[List[int]] = None,
        videos_per_playlist: Optional[int] = None,
) -> Dict[str, any]:
    results: Dict[str, any] = {
        "channels_scanned": 0,
        "tabs_created": 0,
        "tabs_updated": 0,
        "videos_linked": 0,
        "errors": [],
    }

    channels = Channel.objects.all()
    if channel_ids is not None:
        channels = channels.filter(pk__in=channel_ids)

    for channel in channels:
        try:
            grouped_sources = [
                (YouTubeTab.PLAYLISTS, fetch_channel_playlists(channel.yt_channel_id)),
                (YouTubeTab.PODCASTS, fetch_channel_podcasts(channel.yt_channel_id)),
            ]
            for tab_type, items in grouped_sources:
                for item in items:
                    try:
                        tab_obj, created = Tab.objects.get_or_create(
                            channel=channel,
                            type=tab_type,
                            yt_id=item["yt_id"],
                            defaults={"name": item["title"]},
                        )
                        if created:
                            results["tabs_created"] += 1
                        elif tab_obj.name != item["title"]:
                            tab_obj.name = item["title"]
                            tab_obj.save(update_fields=["name"])
                            results["tabs_updated"] += 1

                        playlist_url = f"https://www.youtube.com/playlist?list={item['yt_id']}"
                        entries = _extract_flat_entries(playlist_url, limit=videos_per_playlist)
                        for e in entries:
                            vid = e.get("id")
                            if not vid:
                                continue
                            vid_obj, _ = Video.objects.get_or_create(
                                yt_video_id=vid,
                                defaults={
                                    "title": e.get("title") or vid,
                                    "channel": channel,
                                },
                            )
                            vid_obj.tabs.add(tab_obj)
                            results["videos_linked"] += 1
                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:
                        results["errors"].append(
                            f"{channel.yt_channel_id} {tab_type} {item.get('yt_id')}: {e}"
                        )

            # Shorts: a single tab per channel, not grouped by name.
            shorts = fetch_channel_shorts(channel.yt_channel_id, limit=videos_per_playlist)
            if shorts:
                tab_obj, created = Tab.objects.get_or_create(
                    channel=channel,
                    type=YouTubeTab.SHORTS,
                    yt_id="",
                    defaults={"name": "Shorts"},
                )
                if created:
                    results["tabs_created"] += 1
                for s in shorts:
                    try:
                        vid_obj, _ = Video.objects.get_or_create(
                            yt_video_id=s["yt_video_id"],
                            defaults={
                                "title": s.get("title") or s["yt_video_id"],
                                "channel": channel,
                            },
                        )
                        vid_obj.tabs.add(tab_obj)
                        results["videos_linked"] += 1
                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:
                        results["errors"].append(
                            f"{channel.yt_channel_id} shorts {s.get('yt_video_id')}: {e}"
                        )

            results["channels_scanned"] += 1
        except (RuntimeError, ValueError, AttributeError) as e:
            results["errors"].append(f"Channel {channel.yt_channel_id} tabs sync: {str(e)}")

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

    cookies_path = cookies_file_path(cookies_file)
    data_dir = Path(getattr(settings, "DATA_DIR", settings.MEDIA_ROOT))

    regex_path = data_dir / regex_file
    if not regex_path.exists():
        regex_path = settings.MEDIA_ROOT / regex_file

    if not cookies_path:
        return {}

    reg_ex = {}
    if regex_path.exists():
        reg_ex = json.loads(regex_path.read_text(encoding="utf-8"))
    else:
        return {}

    jar = MozillaCookieJar(str(cookies_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, LoadError) as e:
        logger.error("Error loading cookies from %s: %s", cookies_path, str(e))
        return {}

    session = requests.Session()
    session.cookies = jar
    session.headers.update({
        "User-Agent": YT_USER_AGENT,
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    try:
        response = session.get(url, allow_redirects=True, timeout=15)
    except (OSError, LoadError) as e:
        logger.error("Error fetching channel page for %s: %s", channel_id, str(e))
        return {}

    if "consent.youtube.com" in response.url or "consent.google.com" in response.url:
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

    return metadata


def update_channels_metadata() -> Dict[str, any]:
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
            cache.delete(cache_key)

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
    channel_results = update_channels_metadata()
    scan_results = scan_channel_videos()
    tabs_results = sync_channel_tabs()
    video_results = update_videos_metadata()
    music_results = update_music_tracks_metadata()

    return {
        "channels": channel_results,
        "scan": scan_results,
        "tabs": tabs_results,
        "videos": video_results,
        "music": music_results,
    }


def metadata_from_info(data: dict) -> Dict[str, Optional[str]]:
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
