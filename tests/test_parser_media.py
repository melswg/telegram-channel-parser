import tempfile
import unittest
from pathlib import Path

from app.parser import (
    _prepare_media,
    _publication_numbers,
    build_parse_preview,
)
from app.targets import TelegramTarget


class FakeDownloadClient:
    def __init__(self):
        self.calls = 0

    async def download_media(self, _message, file):
        self.calls += 1
        path = Path(f"{file}.jpg")
        path.write_bytes(b"image")
        return str(path)


class FakeTelegramBackend:
    def __init__(self):
        self.client = FakeDownloadClient()

    async def iter_posts(self, _entity, reverse=False):
        assert reverse is True
        for message_id in (4, 8, 15, 16, 23, 42):
            yield type("Message", (), {"id": message_id})()


class ParserMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_is_downloaded_into_post_media_directory(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            media_dir = Path(root) / "media"
            tg = FakeTelegramBackend()

            info, warning = await _prepare_media(
                tg,
                object(),
                media_dir,
                "post_42",
                "photo",
                True,
            )

            self.assertIsNone(warning)
            self.assertTrue(info["downloaded"])
            self.assertEqual(info["path"], "media/post_42.jpg")
            self.assertEqual(tg.client.calls, 1)

    async def test_existing_media_is_reused_without_new_download(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            media_dir = Path(root) / "media"
            media_dir.mkdir()
            (media_dir / "comment_7.ogg").write_bytes(b"voice")
            tg = FakeTelegramBackend()

            info, warning = await _prepare_media(
                tg,
                object(),
                media_dir,
                "comment_7",
                "voice",
                False,
            )

            self.assertIsNone(warning)
            self.assertTrue(info["downloaded"])
            self.assertEqual(tg.client.calls, 0)

    async def test_media_metadata_keeps_voice_duration(self):
        attribute = type("AudioAttribute", (), {"duration": 83})()
        document = type("Document", (), {"attributes": [attribute]})()
        media = type("Media", (), {"document": document})()
        message = type("Message", (), {"media": media})()

        info, warning = await _prepare_media(
            FakeTelegramBackend(),
            message,
            Path("/tmp/unused-media-test"),
            "voice_1",
            "voice",
            False,
        )

        self.assertIsNone(warning)
        self.assertEqual(info["duration"], 83.0)

    async def test_publication_numbers_are_counted_from_first_real_post(self):
        numbers = await _publication_numbers(
            FakeTelegramBackend(),
            object(),
            {8, 23, 42},
        )
        self.assertEqual(numbers, {8: 2, 23: 5, 42: 6})

    def test_empty_limit_previews_all_available_posts(self):
        preview = build_parse_preview(
            TelegramTarget(kind="channel", channel="example"),
            total_posts=843,
            requested_limit=None,
            download_media=True,
        )
        self.assertEqual(preview["posts_count"], 843)
        self.assertTrue(preview["all_posts"])
        self.assertEqual(
            preview["confirmation"],
            "Будет загружено 843 публикации. Media включены. Вы согласны?",
        )

    def test_explicit_limit_is_not_capped_at_200(self):
        preview = build_parse_preview(
            TelegramTarget(kind="channel", channel="example"),
            total_posts=5000,
            requested_limit=1200,
            download_media=False,
        )
        self.assertEqual(preview["posts_count"], 1200)


if __name__ == "__main__":
    unittest.main()
