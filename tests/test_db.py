import tempfile
import unittest
from pathlib import Path

from app.db import Database


class WebDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir="/tmp")
        self.db = Database(str(Path(self.temp_dir.name) / "test.sqlite3"))
        self.db.open()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_parsed_post_and_comments_are_idempotent(self):
        run_id = self.db.create_parse_run(
            "https://t.me/example/42",
            "post",
            "example",
            1,
            download_media=True,
        )
        post = {
            "channel": "example",
            "channel_title": "Example",
            "post_id": 42,
            "publication_number": 9,
            "text": "first",
            "has_media": True,
            "media_type": "voice",
            "media": {
                "downloaded": True,
                "filename": "post_42.ogg",
                "type": "voice",
                "duration": 83,
            },
            "media_directory": "media",
        }
        self.db.upsert_parsed_post(post, run_id)
        post["text"] = "updated"
        self.db.upsert_parsed_post(post, run_id)
        self.db.replace_parsed_comments("example", 42, [{
            "id": 7,
            "text": "hello",
            "has_media": False,
            "media": {
                "downloaded": True,
                "path": "media/comment_7.ogg",
            },
        }], run_id)
        self.db.replace_parsed_comments("example", 42, [{
            "id": 7,
            "text": "edited",
            "has_media": False,
            "media": {
                "downloaded": True,
                "path": "media/comment_7.ogg",
            },
        }], run_id)

        result = self.db.get_parsed_post("example", 42)
        run = self.db.get_parse_run(run_id)
        self.assertEqual(result["text"], "updated")
        self.assertEqual(result["publication_number"], 9)
        self.assertEqual(result["comments_count"], 1)
        self.assertEqual(result["comments"][0]["text"], "edited")
        self.assertEqual(result["media_directory"], "media")
        self.assertTrue(result["comments"][0]["media"]["downloaded"])
        self.assertEqual(run["download_media"], 1)
        self.assertEqual(
            self.db.list_parsed_posts(limit=1)[0]["media"]["duration"],
            83,
        )


if __name__ == "__main__":
    unittest.main()
