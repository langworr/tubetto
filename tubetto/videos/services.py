# videos/services.py
import subprocess
import json
import time

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

def select_manifest(data: dict) -> dict:
    formats = data.get("formats", [])
    # Preferisci HLS (m3u8)
    hls = [f for f in formats if f.get("protocol") == "m3u8" or "m3u8" in (f.get("url") or "")]
    if hls:
        chosen = sorted(hls, key=lambda f: f.get("tbr") or 0, reverse=True)[0]  # bitrate più alto
        return {"type": "hls", "manifest_url": chosen.get("url")}
    # Fallback: DASH manifest
    dash = [f for f in formats if f.get("manifest_url") or (f.get("url") or "").endswith(".mpd")]
    if dash:
        chosen = dash[0]
        mu = chosen.get("manifest_url") or chosen.get("url")
        return {"type": "dash", "manifest_url": mu}
    raise RuntimeError("Nessun manifest HLS/DASH disponibile")

def resolve_stream_manifest(video_id: str) -> dict:
    info = resolve_video_info(video_id)
    sel = select_manifest(info)
    return {
        "video_id": video_id,
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "manifest_type": sel["type"],
        "manifest_url": sel["manifest_url"],
        "channel": (info.get("channel") or ""),
        "published_at": info.get("upload_date"),
    }
