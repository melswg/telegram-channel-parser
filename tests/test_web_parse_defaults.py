import unittest
from pathlib import Path

from app.web import ParsePayload


class WebParseDefaultsTests(unittest.TestCase):
    def test_missing_limit_means_all_posts(self):
        payload = ParsePayload(url="https://t.me/example_channel")
        self.assertIsNone(payload.limit)

    def test_parser_form_starts_without_a_post_limit(self):
        template = (
            Path(__file__).parents[1] / "app" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('for="parse-limit">Количество постов</label>', template)
        self.assertIn('placeholder="Все доступные"', template)
        self.assertNotIn('id="parse-limit" name="limit" type="number" min="1" value=', template)

    def test_parser_form_offers_every_media_category(self):
        template = (
            Path(__file__).parents[1] / "app" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        for media_type in (
            "photo", "video", "video_note", "animation", "document",
            "audio", "voice", "sticker",
        ):
            self.assertIn(f'value="{media_type}"', template)


if __name__ == "__main__":
    unittest.main()
