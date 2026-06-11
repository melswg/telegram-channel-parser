import asyncio
import tempfile
import unittest
from pathlib import Path

from app import web
from app.db import Database


class WebRunControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir="/tmp")
        self.old_db_path = web.DB_PATH
        web.DB_PATH = str(Path(self.temp_dir.name) / "test.sqlite3")
        db = Database(web.DB_PATH)
        db.open()
        self.run_id = db.create_parse_run(
            "https://t.me/example",
            "channel",
            "example",
            10,
        )
        db.update_parse_run(self.run_id, status="running")
        db.close()

    async def asyncTearDown(self):
        task = web.running_tasks.pop(self.run_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        web.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    async def test_pause_and_resume_update_persisted_status(self):
        paused = await web.pause_run(self.run_id)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["estimated_wait_text"], "Парсинг на паузе")

        blocker = asyncio.create_task(asyncio.Event().wait())
        web._track_task(self.run_id, blocker)
        resumed = await web.resume_run(self.run_id)

        self.assertEqual(resumed["status"], "running")
        self.assertIs(web.running_tasks[self.run_id], blocker)


if __name__ == "__main__":
    unittest.main()
