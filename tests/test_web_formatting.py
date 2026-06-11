import unittest

from app.web import format_post_date, publication_label


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


if __name__ == "__main__":
    unittest.main()
