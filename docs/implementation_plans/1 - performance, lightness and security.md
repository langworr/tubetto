# Implementation Plan - Optimize Tubetto for Speed, Lightness, and Security

Apply all proposed modifications across the codebase to maximize performance, reduce memory/storage footprint, and harden security.

## User Review Required

> [!IMPORTANT]
> - `publish_playlist` will now require a `POST` request (with CSRF token) instead of a `GET` request. The template [music_playlist_detail.html](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/templates/music/music_playlist_detail.html) will be updated with a POST button.
> - Private configuration files (like `cookies.txt` and `regex_list.json`) will be accessed via a secure `DATA_DIR` / private path rather than the public `MEDIA_ROOT`.
> - Database indexes will be added, requiring migrations to be generated and applied.

---

## Proposed Changes

### Configuration & Core (`tubetto`)

#### [MODIFY] [settings.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/settings.py)
- Enforce `SECRET_KEY` presence in production (`if not DEBUG and not SECRET_KEY: raise ImproperlyConfigured`).
- Sanitize `ALLOWED_HOSTS` splitting.
- Configure `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE = 'Lax'`, `CSRF_COOKIE_SAMESITE = 'Lax'`.
- Define `DATA_DIR` / `PRIVATE_DIR` for sensitive cookies and regex configurations.
- Configure `CACHES` backend with `LocMemCache` or default Django cache backend.

#### [MODIFY] [models.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/models.py)
- Add database indexes for `ScheduledTaskHistory` (`started_at`, `status`, `ended_at`).

#### [MODIFY] [services.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/services.py)
- Replace unbounded `_CACHE` dictionary with Django `cache` (`django.core.cache.cache`).
- Update cookie and regex file loading to use `DATA_DIR` or fallback.
- Streamline `scan_channel_videos()`: eliminate duplicate yt-dlp fetches and avoid duplicate `ChannelVideo` writes if not required.

#### [MODIFY] [views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/tubetto/views.py)
- Replace `@user_passes_test(_is_admin)` with explicit `PermissionDenied` check to prevent infinite OIDC redirect loop for non-admin authenticated users.
- Remove unused `HomeView`.

---

### Videos App (`videos`)

#### [MODIFY] [views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/views.py)
- Add `select_related('channel')` in `video_list` to eliminate N+1 SQL queries.
- Introduce reusable `requests.Session` with `HTTPAdapter` connection pooling for proxy endpoints (`progressive_file`, `hls_segment`, `hls_key`, `hls_manifest`).
- Harden `_is_url_allowed` against SSRF: validate `scheme in ('http', 'https')` and parse `parsed.hostname`.
- Apply SSRF check to `variant_url` in `hls_manifest`.
- Increase stream chunk size to `256 * 1024` for reduced CPU/memory overhead.

#### [MODIFY] [models.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/models.py)
- Add database indexes to `Video` (`title`, `upload_date`, `created_at`).

#### [MODIFY] [signals.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/videos/signals.py)
- Remove automatic duplicate yt-dlp metadata fetch on raw `post_save` or check flag to prevent slowing down bulk scanning.

---

### Music App (`music`)

#### [MODIFY] [views.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/views.py)
- Convert `publish_playlist` to `@require_POST` for CSRF protection.
- Introduce reusable `requests.Session` and validate `audio['stream_url']` with SSRF domain check in `music_stream`.
- Increase stream chunk size to `256 * 1024`.
- Remove uncalled `reconstruct_segment_url` import.

#### [MODIFY] [admin.py](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/admin.py)
- Annotate `track_count` in `MusicPlaylistAdmin.get_queryset` to eliminate N+1 queries in admin list view.

#### [MODIFY] [music_playlist_detail.html](file:///c:/Users/DY00080/Roby/svil/github/tubetto/tubetto/music/templates/music/music_playlist_detail.html)
- Update "Publish" link to a `POST` form with `{% csrf_token %}`.

---

### Dependencies

#### [MODIFY] [requirements_prod.txt](file:///c:/Users/DY00080/Roby/svil/github/tubetto/requirements_prod.txt)
- Remove `uv` and unnecessary non-runtime dependencies.

---

## Verification Plan

### Automated Tests
- Run `python manage.py makemigrations` and `python manage.py migrate` to ensure schema integrity with indexes.
- Run `python manage.py check` to verify Django system configuration and settings.
- Run `python manage.py test` to verify all tests pass without regressions.

### Manual Verification
- Verify `video_list` page loads properly with `select_related('channel')`.
- Verify playlist publish button triggers POST and generates the M3U file correctly.
- Verify streaming endpoints proxy properly with connection pool and chunk size.
