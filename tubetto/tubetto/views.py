"""
Main views for the Tubetto application.

This module provides view functions and class-based views for the core pages
of the Tubetto application, and admin task handling.

Contents
- _is_admin(user): Utility function that returns True when the given user has
  administrative privileges (superuser or member of the "admin" group).
- home(request): Function-based view that renders the public home page
  (home.html) with basic application context.
- HomeView(TemplateView): Class-based alternative for the home page. Supplies
  the same context as home() and renders home.html.
  - get_context_data(**kwargs): Builds context for the template with app name
    and description.
- scheduled_task(request): Admin-only view (login required and requires admin
  check) that exposes POST actions to run maintenance tasks such as updating
  channels, scanning videos, updating metadata, publishing playlists, or
  running all scheduled tasks.

Notes
- The scheduled_task view relies on helper functions imported from tubetto.services:
  run_scheduled_task, update_channels_metadata, scan_channel_videos,
  update_videos_metadata, update_music_tracks_metadata.
"""

import json

from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils import timezone

from tubetto.services import (
    run_scheduled_task, update_channels_metadata, scan_channel_videos, update_videos_metadata,
    update_music_tracks_metadata
)
from videos.models import Channel
from .models import ScheduledTaskHistory


def _is_admin(user):
    """
    Check whether the provided user has admin privileges.

    The function considers a user admin if they are a superuser or belong to
    a Django group named "admin".

    Args:
        user (User): Django user instance.

    Returns:
        bool: True if the user is an admin, False otherwise.
    """
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["admin"]).exists())


def home(request):
    """
    Display the home page of Tubetto.

    Renders the home.html template with basic context information.
    Accessible to both authenticated and unauthenticated users.

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        HttpResponse: Rendered home.html template.
    """
    context = {
        'app_name': 'Tubetto',
        'app_description': 'Your personal audio streaming platform powered by YouTube',
    }
    return render(request, 'home.html', context)


class HomeView(TemplateView):
    """
    Class-based view for the home page of Tubetto.

    Alternative to the function-based home view. Can be used if you prefer
    class-based views or need more advanced functionality like mixins.

    Attributes:
        template_name (str): The template file to render ('home.html').
    """
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        """
        Build context data for the home page template.

        Args:
            **kwargs: Additional keyword arguments.

        Returns:
            dict: Context dictionary with app information.
        """
        context = super().get_context_data(**kwargs)
        context['app_name'] = 'Tubetto'
        context['app_description'] = 'Your personal audio streaming platform powered by YouTube'
        return context


@login_required
@user_passes_test(_is_admin)
def scheduled_task(request):
    """Admin-only page to run scheduled tasks."""
    results = None
    results_text = None
    task_name = None
    selected_channel_ids = None

    channels = Channel.objects.all().order_by('title', 'yt_channel_id')
    history_entries = ScheduledTaskHistory.objects.all()[:10]
    running_tasks = ScheduledTaskHistory.objects.filter(ended_at__isnull=True)

    def _create_history(task_type, channel_ids=None):
        return ScheduledTaskHistory.objects.create(
            task_type=task_type,
            user=request.user,
            status='running',
            channels=list(channel_ids) if channel_ids else ['all'] if task_type == 'scan_videos' else [],
        )

    if request.method == 'POST':
        if 'scan_videos' in request.POST:
            selected_channel_ids = request.POST.getlist('scan_channels_selected')
            if 'all' in selected_channel_ids or not selected_channel_ids:
                selected_channel_ids = None
            else:
                parsed_ids = []
                for channel_id in selected_channel_ids:
                    try:
                        parsed_ids.append(int(channel_id))
                    except (ValueError, TypeError):
                        continue
                selected_channel_ids = parsed_ids or None

        if 'update_channels' in request.POST:
            task_name = "Update Channels Metadata"
            history = _create_history('update_channels')
            try:
                results = update_channels_metadata()
                history.status = 'completed'
                history.result = json.dumps(results, indent=2, default=str)
            except Exception as exc:
                results = {'error': str(exc)}
                history.status = 'failed'
                history.result = str(exc)
            finally:
                history.ended_at = timezone.now()
                history.save(update_fields=['status', 'result', 'ended_at'])
        elif 'scan_videos' in request.POST:
            task_name = "Scan Channel Videos"
            history = _create_history('scan_videos', selected_channel_ids)
            try:
                results = scan_channel_videos(channel_ids=selected_channel_ids)
                history.status = 'completed'
                history.result = json.dumps(results, indent=2, default=str)
            except Exception as exc:
                results = {'error': str(exc)}
                history.status = 'failed'
                history.result = str(exc)
            finally:
                history.ended_at = timezone.now()
                history.save(update_fields=['status', 'result', 'ended_at'])
        elif 'update_videos_metadata' in request.POST:
            task_name = "Update Videos Metadata"
            history = _create_history('update_videos_metadata')
            try:
                results = update_videos_metadata()
                history.status = 'completed'
                history.result = json.dumps(results, indent=2, default=str)
            except Exception as exc:
                results = {'error': str(exc)}
                history.status = 'failed'
                history.result = str(exc)
            finally:
                history.ended_at = timezone.now()
                history.save(update_fields=['status', 'result', 'ended_at'])
        elif 'update_music_tracks' in request.POST:
            task_name = "Update Music Tracks Metadata"
            history = _create_history('update_music_tracks')
            try:
                results = update_music_tracks_metadata()
                history.status = 'completed'
                history.result = json.dumps(results, indent=2, default=str)
            except Exception as exc:
                results = {'error': str(exc)}
                history.status = 'failed'
                history.result = str(exc)
            finally:
                history.ended_at = timezone.now()
                history.save(update_fields=['status', 'result', 'ended_at'])
        elif 'run_all' in request.POST:
            task_name = "All Tasks"
            history = _create_history('run_all')
            try:
                results = run_scheduled_task()
                history.status = 'completed'
                history.result = json.dumps(results, indent=2, default=str)
            except Exception as exc:
                results = {'error': str(exc)}
                history.status = 'failed'
                history.result = str(exc)
            finally:
                history.ended_at = timezone.now()
                history.save(update_fields=['status', 'result', 'ended_at'])

        if results is not None:
            results_text = json.dumps(results, indent=2, default=str)

    return render(request, "scheduled_task.html", {
        "results": results,
        "results_text": results_text,
        "task_name": task_name,
        "channels": channels,
        "history_entries": history_entries,
        "running_tasks": running_tasks,
    })
