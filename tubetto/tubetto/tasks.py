"""
Asynchronous background tasks for Tubetto powered by Django Q.

This module provides background task wrappers for YouTube channel synchronization,
metadata extraction, tab syncing, and maintenance routines.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from django.utils import timezone
from django_q.tasks import async_task

from tubetto.models import ScheduledTaskHistory
from tubetto.services import (
    run_scheduled_task,
    scan_channel_videos,
    sync_channel_tabs,
    update_channels_metadata,
    update_music_tracks_metadata,
    update_videos_metadata,
)

logger = logging.getLogger(__name__)


TASK_DISPATCH_MAP = {
    "update_channels": ("Update Channels Metadata", lambda channel_ids: update_channels_metadata()),
    "scan_videos": ("Scan Channel Videos", lambda channel_ids: scan_channel_videos(channel_ids=channel_ids)),
    "scan_channel_tabs": ("Scan Channel Tabs", lambda channel_ids: sync_channel_tabs(channel_ids=channel_ids)),
    "update_videos_metadata": ("Update Videos Metadata", lambda channel_ids: update_videos_metadata()),
    "update_music_tracks": ("Update Music Tracks Metadata", lambda channel_ids: update_music_tracks_metadata()),
    "run_all": ("All Tasks", lambda channel_ids: run_scheduled_task()),
}


def execute_task(history_id: int, task_type: str, channel_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Execute a background task and update its ScheduledTaskHistory record.

    Args:
        history_id: The primary key of the ScheduledTaskHistory instance.
        task_type: The task identifier (e.g. 'update_channels', 'scan_videos').
        channel_ids: Optional list of channel IDs for channel-specific tasks.

    Returns:
        Dict[str, Any]: The task result dictionary.
    """
    try:
        history = ScheduledTaskHistory.objects.get(pk=history_id)
    except ScheduledTaskHistory.DoesNotExist:
        logger.error("ScheduledTaskHistory %s not found for task '%s'", history_id, task_type)
        return {"error": f"ScheduledTaskHistory {history_id} not found"}

    if task_type not in TASK_DISPATCH_MAP:
        error_msg = f"Unknown task type: {task_type}"
        logger.error("Task failed: %s [history_id=%s]", error_msg, history_id)
        history.status = "failed"
        history.result = error_msg
        history.ended_at = timezone.now()
        history.save(update_fields=["status", "result", "ended_at"])
        return {"error": error_msg}

    name, runner_fn = TASK_DISPATCH_MAP[task_type]
    logger.info("Starting task '%s' (%s) [history_id=%s, channel_ids=%s]", task_type, name, history_id, channel_ids)

    try:
        results = runner_fn(channel_ids)
        history.status = "completed"
        history.result = json.dumps(results, indent=2, default=str)
        logger.info(
            "Task '%s' [history_id=%s] completed successfully. Result: %s",
            task_type,
            history_id,
            history.result,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Task '%s' [history_id=%s] failed: %s", task_type, history_id, exc)
        results = {"error": str(exc)}
        history.status = "failed"
        history.result = str(exc)
    finally:
        history.ended_at = timezone.now()
        history.save(update_fields=["status", "result", "ended_at"])

    return results


def dispatch_async_task(
    task_type: str,
    user: Optional[Any] = None,
    channel_ids: Optional[List[int]] = None,
) -> ScheduledTaskHistory:
    """
    Create a ScheduledTaskHistory entry and enqueue the task to Django Q cluster.

    Args:
        task_type: The task type key.
        user: The requesting user (if authenticated).
        channel_ids: Optional list of channel IDs to filter the scan.

    Returns:
        ScheduledTaskHistory: The created history entry with status 'running'.
    """
    if channel_ids:
        channels_data = list(channel_ids)
    elif task_type in ("scan_videos", "scan_channel_tabs"):
        channels_data = ["all"]
    else:
        channels_data = []

    history = ScheduledTaskHistory.objects.create(
        task_type=task_type,
        user=user if getattr(user, "is_authenticated", False) else None,
        status="running",
        channels=channels_data,
    )

    q_task_id = async_task("tubetto.tasks.execute_task", history.id, task_type, channel_ids)
    if q_task_id:
        history.q_task_id = str(q_task_id)
        history.save(update_fields=["q_task_id"])

    logger.info(
        "Dispatched async task '%s' [history_id=%s, q_task_id=%s, user=%s, channel_ids=%s]",
        task_type,
        history.id,
        history.q_task_id,
        user,
        channels_data,
    )

    return history


def task_update_channels_metadata(history_id: int) -> Dict[str, Any]:
    return execute_task(history_id, "update_channels")


def task_scan_channel_videos(history_id: int, channel_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    return execute_task(history_id, "scan_videos", channel_ids=channel_ids)


def task_sync_channel_tabs(history_id: int, channel_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    return execute_task(history_id, "scan_channel_tabs", channel_ids=channel_ids)


def task_update_videos_metadata(history_id: int) -> Dict[str, Any]:
    return execute_task(history_id, "update_videos_metadata")


def task_update_music_tracks_metadata(history_id: int) -> Dict[str, Any]:
    return execute_task(history_id, "update_music_tracks")


def task_run_all(history_id: int) -> Dict[str, Any]:
    return execute_task(history_id, "run_all")
