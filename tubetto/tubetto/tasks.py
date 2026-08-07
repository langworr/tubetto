"""
Django-Q2 task wrappers for the scheduled-task admin page.

These are the functions actually enqueued via `django_q.tasks.async_task()`
from `views.scheduled_task`. Each one runs in the `qcluster` worker process
(a separate process from the web server), so it can't receive or return
Django model instances directly through the queue's serialization — it takes
a plain `history_id` and re-fetches the ScheduledTaskHistory row itself, then
writes the outcome (status/result/ended_at) back to that same row when done.

The web view only creates the ScheduledTaskHistory row and enqueues the task;
it never blocks waiting for the result. The "Recent Task History" table and
the "N task(s) running" banner (already present in the template, driven by
`ended_at__isnull=True`) are what surface progress/results to the user.
"""
import json

from django.utils import timezone

from tubetto.services import (
    update_channels_metadata,
    scan_channel_videos,
    sync_channel_tabs,
    update_videos_metadata,
    update_music_tracks_metadata,
    run_scheduled_task,
)
from .models import ScheduledTaskHistory


def _finish_history(history_id, results=None, error=None):
    """
    Write the outcome of a background task run back to its history row.

    Args:
        history_id (int): PK of the ScheduledTaskHistory row to update.
        results (dict | None): Task result payload on success.
        error (Exception | None): The exception raised, if the task failed.
    """
    try:
        history = ScheduledTaskHistory.objects.get(pk=history_id)
    except ScheduledTaskHistory.DoesNotExist:
        return

    history.ended_at = timezone.now()
    if error is not None:
        history.status = 'failed'
        history.result = str(error)
    else:
        history.status = 'completed'
        history.result = json.dumps(results, indent=2, default=str)
    history.save(update_fields=['status', 'result', 'ended_at'])


def run_update_channels(history_id):
    try:
        _finish_history(history_id, results=update_channels_metadata())
    except Exception as exc:  # noqa: BLE001 - must not crash the worker
        _finish_history(history_id, error=exc)


def run_scan_videos(history_id, channel_ids=None):
    try:
        _finish_history(history_id, results=scan_channel_videos(channel_ids=channel_ids))
    except Exception as exc:  # noqa: BLE001
        _finish_history(history_id, error=exc)


def run_scan_channel_tabs(history_id, channel_ids=None):
    try:
        _finish_history(history_id, results=sync_channel_tabs(channel_ids=channel_ids))
    except Exception as exc:  # noqa: BLE001
        _finish_history(history_id, error=exc)


def run_update_videos_metadata(history_id):
    try:
        _finish_history(history_id, results=update_videos_metadata())
    except Exception as exc:  # noqa: BLE001
        _finish_history(history_id, error=exc)


def run_update_music_tracks(history_id):
    try:
        _finish_history(history_id, results=update_music_tracks_metadata())
    except Exception as exc:  # noqa: BLE001
        _finish_history(history_id, error=exc)


def run_all_tasks(history_id):
    try:
        _finish_history(history_id, results=run_scheduled_task())
    except Exception as exc:  # noqa: BLE001
        _finish_history(history_id, error=exc)