"""
Django app configuration for the music module.

This module provides the app configuration for the music application,
which handles audio tracks, playlists, and streaming functionality.
"""

from django.apps import AppConfig


class MusicConfig(AppConfig):
    """
    Django app configuration for the music application.

    This configuration class sets up the music app with Django, specifying
    the default auto field type for model primary keys and the app name.

    Attributes:
        default_auto_field (str): The default primary key field type for models.
                                 Set to BigAutoField for better scalability.
        name (str): The name of the Django app ('music').
    """
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'music'
