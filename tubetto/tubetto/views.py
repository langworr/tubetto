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

from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required, user_passes_test

from tubetto.services import (
    run_scheduled_task, update_channels_metadata, scan_channel_videos, update_videos_metadata,
    update_music_tracks_metadata
)


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
    task_name = None

    if request.method == 'POST':
        if 'update_channels' in request.POST:
            results = update_channels_metadata()
            task_name = "Update Channels Metadata"
        elif 'scan_videos' in request.POST:
            results = scan_channel_videos()
            task_name = "Scan Channel Videos"
        elif 'update_videos_metadata' in request.POST:
            results = update_videos_metadata()
            task_name = "Update Videos Metadata"
        elif 'update_music_tracks' in request.POST:
            results = update_music_tracks_metadata()
            task_name = "Update Music Tracks Metadata"
        elif 'run_all' in request.POST:
            results = run_scheduled_task()
            task_name = "All Tasks"

    return render(request, "scheduled_task.html", {
        "results": results,
        "task_name": task_name,
    })
