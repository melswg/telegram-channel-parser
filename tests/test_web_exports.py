import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from app.web_exports import (
    render_export,
    render_export_archive,
    write_export_archive,
)


class WebExportTests(unittest.TestCase):
    def setUp(self):
        self.posts = [{
            "channel": "example",
            "post_id": 42,
            "text": "post",
            "has_media": 0,
            "comments": [{
                "comment_id": 7,
                "text": "comment",
                "sender_username": "reader",
                "has_media": 0,
            }],
        }]

    def test_json_export_is_nested(self):
        content, media_type = render_export(self.posts, "json")
        data = json.loads(content)
        self.assertEqual(data["comments"][0]["text"], "comment")
        self.assertIn("application/json", media_type)

    def test_jsonl_export_has_analysis_text(self):
        content, _ = render_export(self.posts, "jsonl")
        row = json.loads(content.decode().strip())
        self.assertEqual(row["analysis_text"], "comment")

    def test_media_archive_contains_data_and_media_folder(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            save_dir = Path(root)
            media_dir = save_dir / "example" / "42" / "media"
            media_dir.mkdir(parents=True)
            media_file = media_dir / "comment_7.ogg"
            media_file.write_bytes(b"voice")
            self.posts[0]["comments"][0]["media"] = {
                "downloaded": True,
                "path": "media/comment_7.ogg",
                "type": "voice",
            }

            content, media_type, count = render_export_archive(
                self.posts, "json", save_dir
            )

        self.assertEqual(media_type, "application/zip")
        self.assertEqual(count, 1)
        with zipfile.ZipFile(BytesIO(content)) as archive:
            self.assertIn("data.json", archive.namelist())
            self.assertIn(
                "media/example/42/comment_7.ogg",
                archive.namelist(),
            )
            self.assertIn("media_manifest.json", archive.namelist())

    def test_media_archive_can_be_written_directly_to_disk(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            save_dir = Path(root)
            media_dir = save_dir / "example" / "42" / "media"
            media_dir.mkdir(parents=True)
            (media_dir / "post_42.mp4").write_bytes(b"video")
            self.posts[0]["media"] = {
                "downloaded": True,
                "path": "media/post_42.mp4",
                "type": "video",
            }
            destination = save_dir / "exports" / "result.zip"
            destination.parent.mkdir()

            media_type, count, size = write_export_archive(
                self.posts,
                "json",
                save_dir,
                destination,
            )

            self.assertEqual(media_type, "application/zip")
            self.assertEqual(count, 1)
            self.assertEqual(size, destination.stat().st_size)
            with zipfile.ZipFile(destination) as archive:
                info = archive.getinfo("media/example/42/post_42.mp4")
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_media_archive_explains_when_files_were_not_downloaded(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            with self.assertRaisesRegex(ValueError, "повторите парсинг"):
                render_export_archive(self.posts, "json", Path(root))


if __name__ == "__main__":
    unittest.main()
