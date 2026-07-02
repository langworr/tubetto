from django.test import SimpleTestCase

from tubetto.services import _extract_player_response, _select_audio_format_from_streaming_data


class CrawleeServiceTests(SimpleTestCase):
    def test_extract_player_response_from_watch_page(self):
        html = (
            '<html><head><script>var ytInitialPlayerResponse = '
            '{"videoDetails":{"title":"Example Title"}};</script></head></html>'
        )

        data = _extract_player_response(html)

        self.assertEqual(data["videoDetails"]["title"], "Example Title")

    def test_select_best_audio_prefers_high_quality_audio(self):
        formats = [
            {
                "mimeType": "audio/webm; codecs=\"opus\"",
                "url": "https://example.test/audio.webm",
                "bitrate": 64000,
            },
            {
                "mimeType": "audio/mp4; codecs=\"mp4a.40.2\"",
                "url": "https://example.test/audio.m4a",
                "bitrate": 128000,
            },
        ]

        best = _select_audio_format_from_streaming_data({"adaptiveFormats": formats})

        self.assertEqual(best["url"], "https://example.test/audio.m4a")
