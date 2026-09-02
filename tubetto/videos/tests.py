from django.test import SimpleTestCase, TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from unittest.mock import patch
from pathlib import Path
import tempfile

from tubetto.services import select_manifest, ydl_base_opts
from videos.models import Video


class StreamManifestSelectionTests(SimpleTestCase):
    def test_selects_hls_with_m3u8_native_protocol(self):
        data = {
            "formats": [
                {
                    "protocol": "m3u8_native",
                    "url": "https://googlevideo.com/video.m3u8",
                    "tbr": 1500,
                    "vcodec": "avc1.42c01e",
                    "acodec": "mp4a.40.2",
                }
            ]
        }
        sel = select_manifest(data)
        self.assertEqual(sel["type"], "hls")
        self.assertEqual(sel["manifest_url"], "https://googlevideo.com/video.m3u8")

    def test_selects_adaptive_dash_when_only_split_streams_exist(self):
        data = {
            "formats": [
                {
                    "protocol": "https",
                    "url": "https://googlevideo.com/video.mp4",
                    "ext": "mp4",
                    "vcodec": "avc1.640028",
                    "acodec": "none",
                    "height": 720,
                    "tbr": 2000,
                    "width": 1280,
                },
                {
                    "protocol": "https",
                    "url": "https://googlevideo.com/audio.m4a",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "tbr": 128,
                },
            ]
        }
        sel = select_manifest(data)
        self.assertEqual(sel["type"], "dash")
        self.assertEqual(sel["video_url"], "https://googlevideo.com/video.mp4")
        self.assertEqual(sel["audio_url"], "https://googlevideo.com/audio.m4a")

    def test_ydl_opts_include_cookiefile_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies = Path(tmp) / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with override_settings(DATA_DIR=Path(tmp), MEDIA_ROOT=Path(tmp)):
                opts = ydl_base_opts()
        self.assertEqual(opts["cookiefile"], str(cookies))
        self.assertIn("User-Agent", opts["http_headers"])


class VideoDetailStreamTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="viewer", password="secret123")
        self.video = Video.objects.create(yt_video_id="dQw4w9wgXcQ", title="Test video")
        self.client.login(username="viewer", password="secret123")

    @patch("videos.views.resolve_stream_manifest")
    @patch("videos.views.resolve_video_info")
    def test_video_detail_renders_dash_player(self, mock_info, mock_stream):
        mock_info.return_value = {"title": "Test video"}
        mock_stream.return_value = {
            "stream_type": "dash",
            "video_url": "https://googlevideo.com/video.mp4",
            "audio_url": "https://googlevideo.com/audio.m4a",
        }
        response = self.client.get(reverse("video_detail", args=[self.video.yt_video_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dashjs")
        self.assertContains(response, reverse("dash_manifest", args=[self.video.yt_video_id]))
