import tempfile
import unittest
from pathlib import Path

from app.parser import _prepare_media


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


if __name__ == "__main__":
    unittest.main()
