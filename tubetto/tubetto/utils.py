"""
Shared utility functions for Tubetto.

This module provides common utility functions used across multiple apps.
"""

from urllib.parse import urljoin
from tubetto.services import resolve_stream_manifest


def reconstruct_segment_url(video_id: str, name: str) -> str:
    """
    Reconstruct upstream segment URL by re-resolving the manifest.

    Best-effort reconstruction of the original segment URL using the manifest's
    base URL and the provided segment name.

    Args:
        video_id: YouTube video ID.
        name: Segment name or relative path.

    Returns:
        Reconstructed absolute URL for the segment.
    """
    info = resolve_stream_manifest(video_id)
    base = info["manifest_url"].rsplit("/", 1)[0] + "/"
    return urljoin(base, name)
