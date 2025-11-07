# videos/services.py
import subprocess
import json
import time
from datetime import datetime
from typing import List, Dict, Optional

_CACHE = {}  # {video_id: (expires_epoch, data)}

def _cache_get(video_id: str):
    item = _CACHE.get(video_id)
    if item and item[0] > time.time():
        return item[1]
    return None

def _cache_set(video_id: str, data: dict, ttl: int = 90):
    _CACHE[video_id] = (time.time() + ttl, data)

def resolve_video_info(video_id: str) -> dict:
    cached = _cache_get(video_id)
    if cached:
        return cached
    cmd = [
        "yt-dlp",
        "-J",  # JSON
        "--no-warnings",
        "--skip-download",
        "-f", "bestvideo+bestaudio/best",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp error: {proc.stderr.strip() or 'unknown error'}")
    data = json.loads(proc.stdout)
    _cache_set(video_id, data)
    return data

def _select_progressive(formats: list[dict]) -> dict | None:
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
    """Return a list of YouTube comments for a video using yt-dlp.
    Uses yt-dlp's extractor-args to fetch up to max_comments top comments.
    """
    cached = _cache_get(f"comments:{video_id}:{max_comments}")
    if cached is not None:
        return cached
    cmd = [
        "yt-dlp",
        "-J",
        "--no-warnings",
        "--skip-download",
        "--extractor-args",
        f"youtube:comments=all;comment_sort=top;max_comments={max_comments}",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # On errors, return empty list to avoid breaking the page
        return []
    data = json.loads(proc.stdout)
    comments = data.get("comments") or []
    # Normalize a subset of fields expected by templates
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
    """Return a list of suggested/related videos using yt-dlp metadata.
    This parses keys yt-dlp may expose such as 'related_videos' or 'related'.
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


def list_channel_videos_flat(channel_id: str, limit: int = 200) -> List[Dict]:
    """Return a flat list of videos for a YouTube channel using yt-dlp --flat-playlist.
    channel_id is the YouTube channel id (e.g., UCxxxx...).
    """
    cached = _cache_get(f"chflat:{channel_id}:{limit}")
    if cached is not None:
        return cached
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    cmd = [
        "yt-dlp", "-J", "--no-warnings", "--flat-playlist",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    data = json.loads(proc.stdout)
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
        if len(results) >= limit:
            break
    _cache_set(f"chflat:{channel_id}:{limit}", results, ttl=300)
    return results


def metadata_from_info(data: dict) -> Dict[str, Optional[str]]:
    """Extracts persistent metadata fields from a yt-dlp info dict."""
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
