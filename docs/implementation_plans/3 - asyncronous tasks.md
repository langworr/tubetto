# Implementation Plan - Asynchronous Tasks with Django-Q

Transform all Tubetto background and maintenance tasks into asynchronous jobs managed by **Django-Q** (`django-q2`). This eliminates synchronous HTTP request blocking and timeouts during heavy YouTube scraping and metadata updates.

## Summary of Changes

- **Dependency Integration**: Added `django-q2` and `django-picklefield` to project dependencies (`requirements_prod.txt` and `requirements_dev.txt`).
- **Settings & Broker Configuration**:
  - Added `'django_q'` to `INSTALLED_APPS` in `tubetto/settings.py`.
  - Configured `Q_CLUSTER` setting using Django ORM as the task broker (`'orm': 'default'`), requiring no external Redis/RabbitMQ infrastructure.
- **Model Updates (`tubetto/models.py`)**:
  - Added `"scan_channel_tabs"` choice to `ScheduledTaskHistory.TASK_TYPE_CHOICES`.
  - Added `q_task_id` field to `ScheduledTaskHistory` to track Django Q task execution IDs.
  - Generated and applied migration `0003_scheduledtaskhistory_q_task_id_and_more.py`.
- **Task Orchestration (`tubetto/tasks.py`)**:
  - Created asynchronous task runner functions and dispatcher for:
    - Update Channels Metadata (`update_channels_metadata`)
    - Scan Channel Videos (`scan_channel_videos`)
    - Scan Channel Tabs (`sync_channel_tabs`)
    - Update Videos Metadata (`update_videos_metadata`)
    - Update Music Tracks Metadata (`update_music_tracks_metadata`)
    - Run All Tasks (`run_scheduled_task`)
  - Implemented robust exception handling and automatic lifecycle updates (`running` -> `completed` / `failed`, recording start/end timestamps and output JSON).
- **View & UX Enhancements**:
  - Updated `scheduled_task` view in `tubetto/views.py` to enqueue tasks asynchronously via `dispatch_async_task()` and immediately redirect with a flash message (Post-Redirect-Get pattern).
  - Enhanced `tubetto/templates/scheduled_task.html` with status badges, auto-refresh when tasks are in progress, and expandable task result JSON viewers.
  - Added Django message alerts to `tubetto/templates/base.html`.
  - Registered `ScheduledTaskHistory` in Django admin (`tubetto/admin.py`).
- **Testing**:
  - Comprehensive unit and integration test coverage in `tubetto/tests.py`.
