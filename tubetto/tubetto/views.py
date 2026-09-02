import json

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from tubetto.services import (
    run_scheduled_task, update_channels_metadata, scan_channel_videos, update_videos_metadata,
    update_music_tracks_metadata, sync_channel_tabs
)
from videos.models import Channel
from .models import ScheduledTaskHistory


def _is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["admin"]).exists())


@login_required
def scheduled_task(request):
    if not _is_admin(request.user):
        raise PermissionDenied("Admin privileges required.")
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
        elif 'scan_channel_tabs' in request.POST:
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
        elif 'scan_channel_tabs' in request.POST:
            task_name = "Scan Channel Tabs"
            history = _create_history('scan_channel_tabs', selected_channel_ids)
            try:
                results = sync_channel_tabs(channel_ids=selected_channel_ids)
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


class CustomLoginView(LoginView):
    """
    Login view supporting both internal Django authentication and OIDC/Keycloak SSO fallback.
    """
    template_name = "login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["oidc_error"] = bool(self.request.GET.get("oidc_error"))
        context["oidc_enabled"] = bool(getattr(settings, "OIDC_OP_AUTHORIZATION_ENDPOINT", None))
        return context


def logout_view(request):
    """
    Log out the user from the current session and redirect to LOGOUT_REDIRECT_URL.
    """
    auth_logout(request)
    return redirect(getattr(settings, "LOGOUT_REDIRECT_URL", "/"))

