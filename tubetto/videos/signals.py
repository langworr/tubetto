from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Video
from tubetto.services import resolve_video_info, metadata_from_info
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Video)
def fetch_video_metadata(sender, instance, created, **kwargs):
    """Automatically fetch and save metadata when a Video is created."""
    if created:
        try:
            info = resolve_video_info(instance.yt_video_id)
            meta = metadata_from_info(info)
            changed = False
            update_fields = {}
            for field, value in meta.items():
                if value is not None:
                    current_value = getattr(instance, field)
                    if current_value != value:
                        update_fields[field] = value
                        changed = True
            if changed:
                # Use update to avoid triggering the signal again
                Video.objects.filter(pk=instance.pk).update(**update_fields)
                logger.info("Metadata fetched and saved for video %s", instance.yt_video_id)
        except Exception as e:
            logger.error("Error fetching metadata for video %s: %s", instance.yt_video_id, e)

