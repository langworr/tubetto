# Walkthrough - Asynchronous Tasks with Django-Q

This document provides a walkthrough of the asynchronous task architecture and verification results for Tubetto.

## Overview

All background tasks (channel metadata extraction, video scraping, tab sync, video metadata refresh, music track metadata refresh, and the master scheduled runner) now execute asynchronously in the background via **Django-Q** (`django-q2`) using the Django ORM broker.

## Key Components

### 1. Configuration (`tubetto/settings.py`)
- Registered `'django_q'` in `INSTALLED_APPS`.
- Configured `Q_CLUSTER`:
  ```python
  Q_CLUSTER = {
      'name': 'tubetto_tasks',
      'workers': int(os.environ.get('Q_CLUSTER_WORKERS', 4)),
      'recycle': 500,
      'timeout': int(os.environ.get('Q_CLUSTER_TIMEOUT', 1800)),
      'retry': int(os.environ.get('Q_CLUSTER_RETRY', 2000)),
      'queue_limit': 50,
      'bulk': 10,
      'orm': 'default',
      'catch_up': False,
      'sync': False,
  }
  ```

### 2. Task Runner & Tracking (`tubetto/tasks.py`)
- Central execution function `execute_task(history_id, task_type, channel_ids)` executes service tasks safely, capturing exceptions and recording output in `ScheduledTaskHistory`.
- `dispatch_async_task(task_type, user, channel_ids)` creates the history record and enqueues the job to Django Q.
- Task wrappers available:
  - `task_update_channels_metadata`
  - `task_scan_channel_videos`
  - `task_sync_channel_tabs`
  - `task_update_videos_metadata`
  - `task_update_music_tracks_metadata`
  - `task_run_all`

### 3. Non-blocking Views & UI (`tubetto/views.py` & `tubetto/templates/scheduled_task.html`)
- Triggering any task via the UI dispatches the background task instantly and redirects with a success flash message.
- The UI displays live status badges (`Running`, `Completed`, `Failed`).
- Auto-refreshes every 6 seconds when background tasks are running.
- Includes expandable JSON result viewers for each task history entry.

### 4. Admin Integration (`tubetto/admin.py`)
- `ScheduledTaskHistory` is registered in Django admin with duration formatting, status filters, and search capabilities.

## Running Worker Cluster in Production / Development

To start the Django Q worker cluster:
```powershell
python manage.py qcluster
```

## Verification Results

### Automated Tests
Executed full Django test suite (`22` tests):
```powershell
..\env\dev\Scripts\python.exe manage.py test
```
Result: **22 tests passed (OK)**.
- Authentication & login tests passed.
- OIDC backend role mapping tests passed.
- Asynchronous dispatch, task execution, error capturing, permission enforcement, and view tests passed.

