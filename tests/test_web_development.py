import unittest

from starlette.requests import Request

from app.web import app, templates


class DevelopmentPlaceholderTests(unittest.TestCase):
    def render_media(self, media):
        request = Request({
            "type": "http", "method": "GET", "path": "/",
            "root_path": "", "scheme": "http", "server": ("testserver", 80),
            "headers": [], "router": app.router,
        })
        template = templates.env.from_string(
            '{% from "_media.html" import viewer with context %}'
            '{{ viewer(media, "demo", 42) }}'
        )
        return template.render(request=request, media=media)

    def test_paid_media_uses_the_supplied_image_placeholder(self):
        html = self.render_media({"type": "paid_media", "downloaded": False})
        self.assertIn("Медиа за Stars — В разработке", html)
        self.assertIn("/assets/in-development.png", html)
        self.assertNotIn("медиа не скачано", html)

    def test_regular_media_keeps_its_existing_view(self):
        html = self.render_media({"type": "photo", "downloaded": False})
        self.assertIn("медиа не скачано", html)
        self.assertNotIn("В разработке", html)

    def test_missing_media_does_not_show_a_placeholder(self):
        self.assertNotIn("В разработке", self.render_media(None))


if __name__ == "__main__":
    unittest.main()
