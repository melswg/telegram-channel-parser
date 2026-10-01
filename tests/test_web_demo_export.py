import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import web
from app.db import Database
from app.demo import seed_demo_data


class DemoExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_archive_uses_demo_media_without_private_settings(self):
        with tempfile.TemporaryDirectory() as root:
            demo_dir = Path(root) / "demo"
            (Path(root) / "exports").mkdir()
            db = Database(str(Path(root) / "demo.sqlite3"))
            db.open()
            try:
                seed_demo_data(db, demo_dir)
                posts = [db.get_parsed_post("design_digest", 1042)]
            finally:
                db.close()
            with (
                patch.object(web, "DEMO_MODE", True),
                patch.object(web, "DEMO_SAVE_DIR", demo_dir),
                patch.object(web, "EXPORT_DIR", Path(root) / "exports"),
                patch.object(web, "export_lock", asyncio.Lock()),
                patch.object(web.LocalSettings, "load_effective", side_effect=AssertionError("Demo must not read private settings")),
            ):
                path, filename, count, size = await web.build_export_file(posts, "json", "demo")
            self.assertEqual(filename, "demo.zip")
            self.assertEqual(count, 1)
            self.assertGreater(size, 0)
            with zipfile.ZipFile(path) as archive:
                self.assertIn("media/design_digest/1042/calm-interface.png", archive.namelist())
                self.assertIn("data.json", archive.namelist())
