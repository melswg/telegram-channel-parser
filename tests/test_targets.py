import unittest

from app.targets import parse_telegram_target


class TelegramTargetTests(unittest.TestCase):
    def test_post_variants(self):
        for value in (
            "https://t.me/deployladeploy/1935",
            "t.me/deployladeploy/1935",
            "@deployladeploy/1935",
        ):
            target = parse_telegram_target(value)
            self.assertEqual(target.kind, "post")
            self.assertEqual(target.channel, "deployladeploy")
            self.assertEqual(target.post_id, 1935)

    def test_channel_variants(self):
        for value in ("https://t.me/deployladeploy", "@deployladeploy"):
            target = parse_telegram_target(value)
            self.assertEqual(target.kind, "channel")
            self.assertIsNone(target.post_id)

    def test_invite_link_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invite"):
            parse_telegram_target("https://t.me/+secret")

    def test_private_subscribed_channel_link(self):
        target = parse_telegram_target("https://t.me/c/123456789/42")
        self.assertEqual(target.kind, "post")
        self.assertEqual(target.channel, "private_123456789")
        self.assertEqual(target.private_channel_id, 123456789)
        self.assertEqual(target.telegram_identifier, "c:123456789")
        self.assertEqual(target.canonical_url, "https://t.me/c/123456789/42")


if __name__ == "__main__":
    unittest.main()
