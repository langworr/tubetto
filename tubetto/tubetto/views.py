from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required, user_passes_test

from django_q.tasks import async_task

from tubetto.services import (
    run_update_channels,
    run_scan_videos,
    run_scan_channel_tabs,
    run_update_videos_metadata,
    run_update_music_tracks,
    run_all_tasks,
)
from videos.models import Channel
from .models import ScheduledTaskHistory


def _is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["admin"]).exists())


def home(request):
    context = {
        'app_name': 'Tubetto',
        'app_description': 'Your personal audio streaming platform powered by YouTube',
    }
    return render(request, 'home.html', context)


class HomeView(TemplateView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['app_name'] = 'Tubetto'
        context['app_description'] = 'Your personal audio streaming platform powered by YouTube'
        return context


def _parse_selected_channel_ids(request):
    """
    Read the 'scan_channels_selected' checkboxes from the POST body.

    Returns:
        list[int] | None: Channel PKs to scope the task to, or None to mean
        "all channels" (either the 'all' checkbox was ticked, nothing was
        selected, or every value failed to parse as an int).
    """
    selected = request.POST.getlist('scan_channels_selected')
    if 'all' in selected or not selected:
        return None
    parsed_ids = []
    for channel_id in selected:
        try:
            parsed_ids.append(int(channel_id))
        except (ValueError, TypeError):
            continue
    return parsed_ids or None


@login_required
@user_passes_test(_is_admin)
def scheduled_task(request):
    task_name = None
    task_started_message = None

    channels = Channel.objects.all().order_by('title', 'yt_channel_id')
    history_entries = ScheduledTaskHistory.objects.all()[:10]
    running_tasks = ScheduledTaskHistory.objects.filter(ended_at__isnull=True)

    _channel_scoped_tasks = {'scan_videos', 'scan_channel_tabs'}

    def _create_history(task_type, channel_ids=None):
        if channel_ids:
            channels_value = list(channel_ids)
        elif task_type in _channel_scoped_tasks:
            channels_value = ['all']
        else:
            channels_value = []
        return ScheduledTaskHistory.objects.create(
            task_type=task_type,
            user=request.user,
            status='running',
            channels=channels_value,
        )

    if request.method == 'POST':
        selected_channel_ids = None
        if 'scan_videos' in request.POST or 'scan_channel_tabs' in request.POST:
            selected_channel_ids = _parse_selected_channel_ids(request)

        if 'update_channels' in request.POST:
            task_name = "Update Channels Metadata"
            history = _create_history('update_channels')
            async_task(run_update_channels, history.id)

        elif 'scan_videos' in request.POST:
            task_name = "Scan Channel Videos"
            history = _create_history('scan_videos', selected_channel_ids)
            async_task(run_scan_videos, history.id, channel_ids=selected_channel_ids)

        elif 'scan_channel_tabs' in request.POST:
            task_name = "Scan Channel Tabs"
            history = _create_history('scan_channel_tabs', selected_channel_ids)
            async_task(run_scan_channel_tabs, history.id, channel_ids=selected_channel_ids)

        elif 'update_videos_metadata' in request.POST:
            task_name = "Update Videos Metadata"
            history = _create_history('update_videos_metadata')
            async_task(run_update_videos_metadata, history.id)

        elif 'update_music_tracks' in request.POST:
            task_name = "Update Music Tracks Metadata"
            history = _create_history('update_music_tracks')
            async_task(run_update_music_tracks, history.id)

        elif 'run_all' in request.POST:
            task_name = "All Tasks"
            history = _create_history('run_all')
            async_task(run_all_tasks, history.id)

        else:
            history = None

        if task_name:
            task_started_message = f"'{task_name}' avviato in background (task #{history.id})."
            # Refresh so the just-created row shows up immediately as running.
            history_entries = ScheduledTaskHistory.objects.all()[:10]
            running_tasks = ScheduledTaskHistory.objects.filter(ended_at__isnull=True)

    return render(request, "scheduled_task.html", {
        "task_name": task_name,
        "task_started_message": task_started_message,
        "channels": channels,
        "history_entries": history_entries,
        "running_tasks": running_tasks,
    })
