import unittest

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.web import (
    estimate_remaining_seconds,
    format_wait_time,
    format_media_duration,
    format_post_date,
    media_type_label,
    post_preview,
    publication_label,
    resolve_media_path,
)


class WebFormattingTests(unittest.TestCase):
    def test_formats_post_publication_date(self):
        self.assertEqual(
            format_post_date("2026-06-11T15:42:19+00:00"),
            "11.06.2026, 15:42",
        )

    def test_missing_date_has_readable_fallback(self):
        self.assertEqual(format_post_date(""), "дата неизвестна")

    def test_uses_real_publication_number_when_available(self):
        self.assertEqual(
            publication_label({"publication_number": 37, "post_id": 900}),
            "Публикация №37",
        )

    def test_does_not_invent_missing_publication_number(self):
        self.assertEqual(
            publication_label({"publication_number": None, "post_id": 900}),
            "Порядковый номер не рассчитан",
        )

    def test_voice_preview_includes_duration_and_caption(self):
        self.assertEqual(
            post_preview({
                "text": "Короткая подпись",
                "media_type": "voice",
                "media": {"type": "voice", "duration": 83},
            }),
            "Короткая подпись · Голосовое сообщение 01:23",
        )

    def test_media_duration_supports_hours(self):
        self.assertEqual(format_media_duration(3661), "1:01:01")

    def test_media_type_has_readable_label(self):
        self.assertEqual(media_type_label("video_note"), "Видеосообщение")

    def test_estimates_remaining_parse_time_from_current_rate(self):
        run = {
            "status": "running",
            "started_at": "2026-06-12T10:00:00+00:00",
            "processed_posts": 2,
            "total_posts": 10,
        }
        self.assertEqual(
            estimate_remaining_seconds(
                run,
                datetime(2026, 6, 12, 10, 2, tzinfo=timezone.utc),
            ),
            480,
        )
        self.assertEqual(format_wait_time(480), "Примерно 8 мин осталось")

    def test_wait_estimate_requires_processed_post(self):
        self.assertIsNone(estimate_remaining_seconds({
            "status": "running",
            "started_at": "2026-06-12T10:00:00+00:00",
            "processed_posts": 0,
            "total_posts": 10,
        }))

    def test_media_path_cannot_escape_post_directory(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            save_dir = Path(root)
            expected = (
                save_dir / "example" / "42" / "media" / "voice.ogg"
            ).resolve()
            self.assertEqual(
                resolve_media_path(save_dir, "example", 42, "voice.ogg"),
                expected,
            )
            with self.assertRaises(ValueError):
                resolve_media_path(save_dir, "example", 42, "../secret")


if __name__ == "__main__":
    unittest.main()
