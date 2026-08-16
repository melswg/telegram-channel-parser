from pathlib import Path

from app.db import Database
from app.demo import demo_status, seed_demo_data


def test_demo_status_looks_authorized_without_real_credentials():
    status = demo_status()

    assert status["configured"] is True
    assert status["authenticated"] is True
    assert status["user"]["username"] == "demo_designer"


def test_seed_demo_data_is_repeatable(tmp_path: Path):
    db = Database(str(tmp_path / "demo.sqlite3"))
    db.open()
    try:
        seed_demo_data(db, tmp_path / "data")
        seed_demo_data(db, tmp_path / "data")

        runs = db.list_parse_runs()
        posts = db.list_parsed_posts()
        detail = db.get_parsed_post("design_digest", 1042)
    finally:
        db.close()

    assert len(runs) == 3
    assert len(posts) == 6
    assert detail is not None
    assert detail["comments_count"] == 3
    assert detail["media"]["filename"] == "calm-interface.svg"
    assert (
        tmp_path / "data" / "design_digest" / "1042" / "media"
        / "calm-interface.svg"
    ).is_file()
