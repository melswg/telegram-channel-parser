import unittest

from app.web import post_back_target


class WebNavigationTests(unittest.TestCase):
    def test_channel_post_returns_to_its_parse_run(self):
        url, label = post_back_target(
            {"last_run_id": 17},
            {"id": 17, "target_type": "channel"},
        )
        self.assertEqual(url, "/runs/17")
        self.assertEqual(label, "← К постам канала")

    def test_single_post_returns_to_parser(self):
        url, label = post_back_target(
            {"last_run_id": 18},
            {"id": 18, "target_type": "post"},
        )
        self.assertEqual(url, "/")
        self.assertEqual(label, "← Назад к парсингу")


if __name__ == "__main__":
    unittest.main()
