import asyncio
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.parser import (
    _collect_messages,
    _prepare_media,
    _publication_numbers,
    _unprocessed_messages,
    _wait_until_resumed,
    build_parse_preview,
)
from app.targets import TelegramTarget
from app.telegram import TelegramBackend


class FakeDownloadClient:
    def __init__(self):
        self.calls = 0

    async def download_media(self, _message, file):
        self.calls += 1
        path = Path(f"{file}.jpg")
        path.write_bytes(b"image")
        return str(path)


class FakeCountClient:
    async def get_messages(self, _entity, limit):
        assert limit == 0
        return type("Messages", (), {"total": 5721})()


class FakeTelegramBackend:
    def __init__(self):
        self.client = FakeDownloadClient()

    async def iter_posts(self, _entity, reverse=False):
        assert reverse is True
        for message_id in (4, 8, 15, 16, 23, 42):
            yield type("Message", (), {"id": message_id})()


class ParserMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_count_uses_telegram_total_without_history_scan(self):
        tg = TelegramBackend(1, "hash", "session")
        tg.client = FakeCountClient()

        self.assertEqual(await tg.count_posts(object()), 5721)

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

    async def test_paused_parser_waits_until_run_is_resumed(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            db = Database(str(Path(root) / "test.sqlite3"))
            db.open()
            run_id = db.create_parse_run(
                "https://t.me/example",
                "channel",
                "example",
                3,
            )
            db.update_parse_run(run_id, status="paused")
            waiter = asyncio.create_task(_wait_until_resumed(db, run_id))
            await asyncio.sleep(0.05)
            self.assertFalse(waiter.done())

            db.update_parse_run(run_id, status="running")
            self.assertTrue(await asyncio.wait_for(waiter, timeout=1))
            db.close()

    async def test_message_collection_stops_immediately_on_external_pause(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            db_path = str(Path(root) / "test.sqlite3")
            worker_db = Database(db_path)
            worker_db.open()
            controller_db = Database(db_path)
            controller_db.open()
            run_id = worker_db.create_parse_run(
                "https://t.me/example",
                "channel",
                "example",
                3,
            )
            worker_db.update_parse_run(run_id, status="running")

            first_message_seen = asyncio.Event()

            class SlowBackend:
                async def iter_posts(self, _entity, limit=None):
                    for message_id in (3, 2, 1):
                        yield type("Message", (), {"id": message_id})()
                        if message_id == 3:
                            first_message_seen.set()
                        await asyncio.sleep(0.05)

            collection = asyncio.create_task(_collect_messages(
                SlowBackend(), object(), 3, worker_db, run_id
            ))
            await first_message_seen.wait()
            controller_db.update_parse_run(run_id, status="paused")
            await asyncio.sleep(0.12)
            self.assertFalse(collection.done())

            controller_db.update_parse_run(run_id, status="running")
            messages = await asyncio.wait_for(collection, timeout=1)
            self.assertEqual([message.id for message in messages], [3, 2, 1])
            controller_db.close()
            worker_db.close()

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
            "Будет загружено 843 публикации. Медиа включены. Вы согласны?",
        )

    def test_explicit_limit_is_not_capped_at_200(self):
        preview = build_parse_preview(
            TelegramTarget(kind="channel", channel="example"),
            total_posts=5000,
            requested_limit=1200,
            download_media=False,
        )
        self.assertEqual(preview["posts_count"], 1200)

    def test_resume_skips_already_processed_telegram_ids(self):
        messages = [
            type("Message", (), {"id": message_id})()
            for message_id in (50, 49, 48, 47)
        ]
        pending = _unprocessed_messages(messages, {50, 49})
        self.assertEqual([message.id for message in pending], [48, 47])


if __name__ == "__main__":
    unittest.main()
