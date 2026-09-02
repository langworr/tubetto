from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from videos.models import Channel
from .models import ScheduledTaskHistory
from .tasks import dispatch_async_task


def _is_admin(user):
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name__in=["admin"]).exists())


@login_required
def scheduled_task(request):
    if not _is_admin(request.user):
        raise PermissionDenied("Admin privileges required.")

    channels = Channel.objects.all().order_by('title', 'yt_channel_id')
    history_entries = ScheduledTaskHistory.objects.all()[:20]
    running_tasks = ScheduledTaskHistory.objects.filter(status='running')

    if request.method == 'POST':
        selected_channel_ids = None
        if 'scan_videos' in request.POST or 'scan_channel_tabs' in request.POST:
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

        task_type = None
        task_label = None

        if 'update_channels' in request.POST:
            task_type = 'update_channels'
            task_label = "Update Channels Metadata"
        elif 'scan_videos' in request.POST:
            task_type = 'scan_videos'
            task_label = "Scan Channel Videos"
        elif 'scan_channel_tabs' in request.POST:
            task_type = 'scan_channel_tabs'
            task_label = "Scan Channel Tabs"
        elif 'update_videos_metadata' in request.POST:
            task_type = 'update_videos_metadata'
            task_label = "Update Videos Metadata"
        elif 'update_music_tracks' in request.POST:
            task_type = 'update_music_tracks'
            task_label = "Update Music Tracks Metadata"
        elif 'run_all' in request.POST:
            task_type = 'run_all'
            task_label = "All Tasks"

        if task_type:
            dispatch_async_task(
                task_type=task_type,
                user=request.user,
                channel_ids=selected_channel_ids,
            )
            messages.success(request, f"Task '{task_label}' has been scheduled and is running in the background.")
            return redirect('scheduled_task')

    return render(request, "scheduled_task.html", {
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
