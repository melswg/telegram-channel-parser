"""Deterministic sample content for frontend work without Telegram access."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .db import Database
from .local_settings import PROJECT_ROOT


DEMO_MODE = os.getenv("TELEGRAM_IMPORTER_DEMO", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEMO_DB_PATH = PROJECT_ROOT / ".local" / "demo.sqlite3"
DEMO_SAVE_DIR = PROJECT_ROOT / ".local" / "demo-data"


def demo_status() -> dict:
    """Return a harmless authorized-looking state for the frontend."""
    return {
        "configured": True,
        "authenticated": True,
        "api_id_masked": "1234…5678",
        "api_hash_masked": "demo…mode",
        "session_name": "demo_session",
        "session_exists": True,
        "save_dir": str(DEMO_SAVE_DIR),
        "user": {
            "id": 9_001_001,
            "username": "demo_designer",
            "phone": "+7 ••• •••-••-••",
            "first_name": "Demo",
        },
        "state": "authorized",
        "reason": "Демонстрационный режим: Telegram не подключён.",
    }


def demo_private_settings() -> dict:
    """Fake values used by the settings screen's reveal action."""
    return {
        "api_id": "12345678",
        "api_hash": "demo_api_hash_not_connected_to_telegram",
        "session_name": "demo_session",
        "session_path": str(PROJECT_ROOT / ".local" / "demo_session.session"),
        "save_dir": str(DEMO_SAVE_DIR),
        "user": demo_status()["user"],
    }


def _media(filename: str, color_a: str, color_b: str, title: str) -> dict:
    return {
        "type": "photo",
        "mime_type": "image/svg+xml",
        "downloaded": True,
        "filename": filename,
        "demo_colors": [color_a, color_b],
        "demo_title": title,
    }


POSTS = [
    {
        "channel": "design_digest",
        "channel_title": "Design Digest",
        "post_id": 1042,
        "publication_number": 318,
        "date": "2026-08-15T17:40:00+03:00",
        "text": "Разбираем пять приёмов, которые делают сложный интерфейс спокойнее: ритм, контраст, воздух, понятные состояния и один главный акцент.",
        "views": 18_420,
        "forwards": 137,
        "has_media": True,
        "media_type": "photo",
        "media": _media("calm-interface.svg", "#7c6cff", "#35d6ae", "CALM INTERFACE"),
        "comments": [
            {
                "id": 701,
                "date": "2026-08-15T17:48:00+03:00",
                "text": "Очень вовремя. Особенно полезна мысль про один главный акцент.",
                "sender_id": 301,
                "sender_username": "anna_ui",
                "sender_name": "Анна",
            },
            {
                "id": 702,
                "date": "2026-08-15T18:03:00+03:00",
                "text": "А можно следующим постом показать это на мобильном экране?",
                "sender_id": 302,
                "sender_username": "max_product",
                "sender_name": "Максим",
                "reply_to": 701,
            },
            {
                "id": 703,
                "date": "2026-08-15T18:12:00+03:00",
                "text": "Добавила небольшой визуальный пример.",
                "sender_id": 303,
                "sender_username": "lena_frames",
                "sender_name": "Елена",
                "has_media": True,
                "media_type": "photo",
                "media": _media("comment-example.svg", "#ff7897", "#856dff", "UI EXAMPLE"),
            },
        ],
    },
    {
        "channel": "product_notes",
        "channel_title": "Product Notes",
        "post_id": 876,
        "publication_number": 94,
        "date": "2026-08-14T12:15:00+03:00",
        "text": "Чек-лист перед передачей макета разработчику: состояния, пустые экраны, длинный текст, ошибки и адаптив.",
        "views": 9_830,
        "forwards": 82,
        "has_media": False,
        "comments": [
            {
                "id": 610,
                "date": "2026-08-14T12:31:00+03:00",
                "text": "Сохраняю в рабочие заметки. Про длинные названия обычно вспоминаем слишком поздно.",
                "sender_id": 401,
                "sender_username": "dasha_frontend",
                "sender_name": "Дарья",
            }
        ],
    },
    {
        "channel": "design_digest",
        "channel_title": "Design Digest",
        "post_id": 1038,
        "publication_number": 317,
        "date": "2026-08-12T19:05:00+03:00",
        "text": "Новая подборка: тёмные дашборды, где данные остаются читаемыми, а декоративные эффекты не мешают работе.",
        "views": 21_560,
        "forwards": 204,
        "has_media": True,
        "media_type": "photo",
        "media": _media("dark-dashboard.svg", "#171923", "#7c6cff", "DARK DASHBOARD"),
        "comments": [
            {
                "id": 681,
                "date": "2026-08-12T20:11:00+03:00",
                "text": "Третий пример отлично работает за счёт типографики.",
                "sender_id": 501,
                "sender_username": "igor_type",
                "sender_name": "Игорь",
            },
            {
                "id": 682,
                "date": "2026-08-12T20:20:00+03:00",
                "text": "Оставлю голосовое с замечаниями позже.",
                "sender_id": 502,
                "sender_username": "olga_research",
                "sender_name": "Ольга",
                "has_media": True,
                "media_type": "voice",
                "media": {
                    "type": "voice",
                    "mime_type": "audio/ogg",
                    "downloaded": False,
                    "reason": "Голосовые не были выбраны при демо-импорте.",
                    "duration": 24,
                },
            },
        ],
    },
    {
        "channel": "frontend_weekly_ru",
        "channel_title": "Frontend Weekly RU",
        "post_id": 529,
        "publication_number": 152,
        "date": "2026-08-10T10:00:00+03:00",
        "text": "CSS Container Queries на практике: карточка адаптируется к своему контейнеру, а не ко всему окну браузера.",
        "views": 14_072,
        "forwards": 111,
        "has_media": False,
        "comments": [],
    },
    {
        "channel": "product_notes",
        "channel_title": "Product Notes",
        "post_id": 869,
        "publication_number": 93,
        "date": "2026-08-08T14:25:00+03:00",
        "text": "Хороший empty state не просто сообщает, что данных нет, а объясняет следующий полезный шаг.",
        "views": 7_615,
        "forwards": 59,
        "has_media": False,
        "comments": [
            {
                "id": 594,
                "date": "2026-08-08T15:02:00+03:00",
                "text": "И это как раз тот случай, когда одна строка текста экономит обращение в поддержку.",
                "sender_id": 601,
                "sender_username": "maria_pm",
                "sender_name": "Мария",
            }
        ],
    },
    {
        "channel": "design_digest",
        "channel_title": "Design Digest",
        "post_id": 1027,
        "publication_number": 316,
        "date": "2026-08-05T18:30:00+03:00",
        "text": "Мини-гайд по цветовым токенам: как назвать переменные так, чтобы светлая и тёмная темы не превратились в два разных проекта.",
        "views": 16_390,
        "forwards": 146,
        "has_media": True,
        "media_type": "photo",
        "media": _media("color-tokens.svg", "#35d6ae", "#ffce6a", "COLOR TOKENS"),
        "comments": [],
    },
]


def _write_demo_svg(path: Path, color_a: str, color_b: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{color_a}"/><stop offset="1" stop-color="{color_b}"/></linearGradient></defs>
<rect width="1280" height="720" rx="36" fill="#111319"/><circle cx="1070" cy="130" r="260" fill="url(#g)" opacity=".75"/>
<rect x="92" y="108" width="760" height="504" rx="30" fill="#1b1e27" stroke="#ffffff" stroke-opacity=".12"/>
<rect x="140" y="164" width="170" height="18" rx="9" fill="url(#g)"/><rect x="140" y="222" width="540" height="38" rx="12" fill="#f5f6f8"/>
<rect x="140" y="282" width="430" height="16" rx="8" fill="#747987"/><rect x="140" y="320" width="500" height="16" rx="8" fill="#555a67"/>
<rect x="140" y="402" width="196" height="128" rx="18" fill="url(#g)" opacity=".78"/><rect x="360" y="402" width="196" height="128" rx="18" fill="#252a36"/>
<text x="92" y="674" fill="#ffffff" font-family="Arial, sans-serif" font-size="30" font-weight="700" letter-spacing="8">{title}</text>
</svg>""",
        encoding="utf-8",
    )


def seed_demo_data(db: Database, save_dir: Path = DEMO_SAVE_DIR) -> None:
    """Reset and seed only the dedicated demo database."""
    if db.conn is None:
        raise RuntimeError("Database must be opened before seeding demo data.")

    for table in (
        "parse_run_queue",
        "parse_run_posts",
        "parsed_comments",
        "parsed_posts",
        "parse_runs",
    ):
        db.conn.execute(f"DELETE FROM {table}")
    db.conn.execute(
        "DELETE FROM sqlite_sequence WHERE name IN ('parse_runs', 'parsed_posts', 'parsed_comments')"
    )
    db.conn.commit()

    runs = [
        db.create_parse_run(
            "https://t.me/design_digest", "channel", "design_digest", 4,
            download_media=False, media_types=("photo",),
        ),
        db.create_parse_run(
            "https://t.me/product_notes", "channel", "product_notes", 2,
        ),
        db.create_parse_run(
            "https://t.me/frontend_weekly_ru/529", "post", "frontend_weekly_ru", 1,
        ),
    ]
    db.conn.executemany(
        "UPDATE parse_runs SET started_at = ? WHERE id = ?",
        [
            ("2026-08-15T17:39:12+03:00", runs[0]),
            ("2026-08-14T12:14:08+03:00", runs[1]),
            ("2026-08-10T09:59:31+03:00", runs[2]),
        ],
    )
    db.conn.commit()

    run_for_channel = {
        "design_digest": runs[0],
        "product_notes": runs[1],
        "frontend_weekly_ru": runs[2],
    }
    for post in POSTS:
        payload = {key: value for key, value in post.items() if key != "comments"}
        media = payload.get("media")
        if media and media.get("downloaded"):
            media_path = (
                save_dir / payload["channel"] / str(payload["post_id"])
                / "media" / media["filename"]
            )
            _write_demo_svg(
                media_path,
                media["demo_colors"][0],
                media["demo_colors"][1],
                media["demo_title"],
            )
            payload["media_directory"] = str(media_path.parent)
        payload["url"] = f"https://t.me/{payload['channel']}/{payload['post_id']}"
        payload["media_download_requested"] = bool(media)
        payload["media_download_types"] = ["photo"] if media else []
        run_id = run_for_channel[payload["channel"]]
        db.upsert_parsed_post(payload, run_id)

        comments = []
        for comment in post["comments"]:
            item = dict(comment)
            comment_media = item.get("media")
            if comment_media and comment_media.get("downloaded"):
                media_path = (
                    save_dir / payload["channel"] / str(payload["post_id"])
                    / "media" / comment_media["filename"]
                )
                _write_demo_svg(
                    media_path,
                    comment_media["demo_colors"][0],
                    comment_media["demo_colors"][1],
                    comment_media["demo_title"],
                )
            comments.append(item)
        db.replace_parsed_comments(payload["channel"], payload["post_id"], comments, run_id)

    first_comments = sum(
        len(post["comments"]) for post in POSTS if post["channel"] == "design_digest"
    )
    second_comments = sum(
        len(post["comments"]) for post in POSTS if post["channel"] == "product_notes"
    )
    db.update_parse_run(
        runs[0], status="success", finished_at="2026-08-15T17:41:06+03:00",
        save_path=str(save_dir / "design_digest"), posts_count=3,
        comments_count=first_comments, processed_posts=3, total_posts=3,
        media_files_count=4, warnings_json=json.dumps([], ensure_ascii=False),
    )
    db.update_parse_run(
        runs[1], status="partial", finished_at="2026-08-14T12:15:44+03:00",
        save_path=str(save_dir / "product_notes"), posts_count=2,
        comments_count=second_comments, processed_posts=2, total_posts=2,
        warnings_json=json.dumps(
            ["Один удалённый комментарий недоступен."], ensure_ascii=False
        ),
    )
    db.update_parse_run(
        runs[2], status="failed", finished_at="2026-08-10T10:00:12+03:00",
        error="Демо ошибки: пост доступен, но обсуждение временно закрыто.",
        save_path=str(save_dir / "frontend_weekly_ru"), posts_count=1,
        comments_count=0, processed_posts=1, total_posts=1,
    )
    db.add_run_post_error(
        runs[2], "frontend_weekly_ru", 529,
        "Комментарии к публикации недоступны.",
    )
