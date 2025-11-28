from django.contrib import admin
from .models import Video, Channel, ChannelVideo
from django.db import transaction
from django.contrib import messages
from tubetto.services import list_channel_videos_flat, resolve_video_info, metadata_from_info

@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_channel_id")
    search_fields = ("title", "yt_channel_id")
    actions = ["scan_channels"]

    def scan_channels(self, request, queryset):
        count = 0
        for ch in queryset:
            c = self._scan_channel(ch)
            count += c
        self.message_user(request, f"Scansione completata. Video creati/aggiornati: {count}", level=messages.INFO)
    scan_channels.short_description = "Scan selected channels for videos"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # On create or update, run a scan
        try:
            self._scan_channel(obj)
        except Exception as e:
            self.message_user(request, f"Error scanning channel: {e}", level=messages.ERROR)

    @staticmethod
    @transaction.atomic
    def _scan_channel(channel: Channel) -> int:
        vids = list_channel_videos_flat(channel.yt_channel_id, limit=200)
        created_or_updated = 0
        for v in vids:
            chv, _ = ChannelVideo.objects.get_or_create(
                channel=channel,
                yt_video_id=v["yt_video_id"],
                defaults={"title": v.get("title", "")},
            )
            if v.get("title") and chv.title != v["title"]:
                chv.title = v["title"]
                chv.save(update_fields=["title"])
            # Ensure Video exists and is tied to this channel
            vid_obj, created = Video.objects.get_or_create(
                yt_video_id=v["yt_video_id"],
                defaults={
                    "title": v.get("title", v["yt_video_id"]),
                    "channel": channel,
                },
            )
            info = resolve_video_info(v["yt_video_id"])
            meta = metadata_from_info(info)
            changed = False
            for field, value in meta.items():
                if value is None:
                    continue
                if getattr(vid_obj, field) != value:
                    setattr(vid_obj, field, value)
                    changed = True
            if not vid_obj.channel:
                vid_obj.channel = channel
                changed = True
            if v.get("title") and vid_obj.title != v["title"]:
                vid_obj.title = v["title"]
                changed = True
            if changed:
                vid_obj.save()
            created_or_updated += 1
        return created_or_updated


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "yt_video_id", "channel", "created_at")
    list_filter = ("channel",)
    search_fields = ("title", "yt_video_id")
    ordering = ("-created_at",)
    actions = ["refresh_metadata"]

    def refresh_metadata(self, request, queryset):
        count = 0
        for vid in queryset:
            try:
                info = resolve_video_info(vid.yt_video_id)
                meta = metadata_from_info(info)
                changed = False
                for field, value in meta.items():
                    if value is None:
                        continue
                    if getattr(vid, field) != value:
                        setattr(vid, field, value)
                        changed = True
                if changed:
                    vid.save()
                    count += 1
            except Exception as e:
                self.message_user(request, f"Error refreshing {vid.yt_video_id}: {e}", level=messages.ERROR)
        self.message_user(request, f"Metadata refreshed for {count} video(s)", level=messages.INFO)
    refresh_metadata.short_description = "Refresh metadata for selected videos"

    def save_model(self, request, obj, form, change):
        # Save first, then signal will fetch metadata if created
        super().save_model(request, obj, form, change)
        # Signal handles metadata fetching on creation, but we can also do it here as backup
        if not change:  # New video created
            try:
                info = resolve_video_info(obj.yt_video_id)
                meta = metadata_from_info(info)
                changed = False
                for field, value in meta.items():
                    if value is not None:
                        current = getattr(obj, field)
                        if current != value:
                            setattr(obj, field, value)
                            changed = True
                if changed:
                    obj.save()
            except Exception as e:
                self.message_user(request, f"Warning: Could not fetch metadata: {e}", level=messages.WARNING)
