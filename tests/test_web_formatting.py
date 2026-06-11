import unittest

from app.web import format_post_date


class WebFormattingTests(unittest.TestCase):
    def test_formats_post_publication_date(self):
        self.assertEqual(
            format_post_date("2026-06-11T15:42:19+00:00"),
            "11.06.2026, 15:42",
        )

    def test_missing_date_has_readable_fallback(self):
        self.assertEqual(format_post_date(""), "дата неизвестна")


if __name__ == "__main__":
    unittest.main()
