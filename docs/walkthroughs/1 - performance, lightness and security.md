# Optimization Walkthrough: Speed, Lightness, and Security

All optimizations have been applied and verified against the Django system check and database migrations.

---

## Key Changes Summary

### 1. Performance ("Faster")
* **Eliminated N+1 Queries**:
  * [video_list](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/views.py#L112): Added `select_related('channel')` when querying videos.
  * [MusicPlaylistAdmin](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/admin.py#L78): Annotated `_track_count` in `get_queryset` to eliminate repetitive count queries per row in the Django admin list view.
* **Persistent HTTP Connection Pooling**:
  * Replaced repeated individual `requests.get()` calls in [videos/views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/views.py#L18) and [music/views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/views.py#L26) with a pooled `STREAM_SESSION` using `HTTPAdapter` and `Retry` configuration, removing TCP/TLS handshake latency for HLS segments and progressive streams.
* **Database Indexes**:
  * Added indexes for `Video` (`title`, `-upload_date, -created_at`, `channel, -upload_date`).
  * Added indexes for `ScheduledTaskHistory` (`-started_at`, `status, ended_at`).
* **Optimized Buffer Size**:
  * Increased streaming chunk sizes in `StreamingHttpResponse` from 64 KB to 256 KB to reduce context switches and Python runtime overhead during streaming.

### 2. Lightness & Resource Efficiency ("Lighter")
* **Bounded Caching**:
  * Replaced the unbounded in-process `_CACHE` dictionary in [services.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/services.py#L24) with Django's `LocMemCache` (bounded `MAX_ENTRIES=2000` with TTL eviction), eliminating potential memory leaks.
* **Removed Redundant Signals & Dead Imports**:
  * Removed unneeded signal handlers and clean apps configuration in [videos/apps.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/apps.py).
  * Removed unused `HomeView` and unused utility imports.
* **Trimmed Dependencies**:
  * Removed CLI-only package `uv` from [requirements_prod.txt](file:///c:/Users/DY00080/Roby/svil/github/tubetto/requirements_prod.txt).

### 3. Security Hardening ("More Secure")
* **SSRF Hardening**:
  * Rewrote `_is_url_allowed()` in [videos/views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/views.py#L32) and [music/views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/views.py#L43) to strictly validate URL schemes (`http`, `https`), parse `hostname`, and verify against `ALLOWED_PROXY_DOMAINS`.
  * Added URL validation for master HLS playlist variants in `hls_manifest` and stream URLs in `music_stream`.
* **State Change Protection (CSRF)**:
  * Converted [publish_playlist](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/views.py#L168) to require `POST` (`@require_POST`).
  * Updated [music_playlist_detail.html](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/templates/music/music_playlist_detail.html#L21) with a POST form and `{% csrf_token %}`.
* **Production Secret Key Enforcement**:
  * Added `ImproperlyConfigured` check in [settings.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/settings.py#L27) when `DEBUG=False` and `SECRET_KEY` is missing.
* **Access Control Redirect Loop Fix**:
  * In [scheduled_task](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/views.py#L21), replaced `user_passes_test` with explicit `PermissionDenied` to return HTTP 403 Forbidden instead of redirecting into an infinite OIDC login loop.
* **Cookie & Host Header Security**:
  * Set `SESSION_COOKIE_HTTPONLY = True`, `CSRF_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`, and `CSRF_COOKIE_SAMESITE = 'Lax'`.
  * Sanitized `ALLOWED_HOSTS` parsing to strip whitespace.
  * Added `DATA_DIR` support for sensitive session cookies and regex files.

---

## Verification Results

* `python manage.py check`: Passed with **0 issues**.
* `python manage.py makemigrations`: Generated migrations `tubetto.0002` and `videos.0009`.
* `python manage.py migrate`: Successfully applied all index migrations.
* `python manage.py test`: Passed.
