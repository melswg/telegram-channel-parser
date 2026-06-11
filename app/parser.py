"""Read-only parsing service shared by the Web UI and CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from telethon import errors

from .config import Config
from .db import Database
from .local_settings import LocalSettings, validate_save_dir
from .models import now_iso
from .targets import TelegramTarget
from .telegram import TelegramBackend


def friendly_telegram_error(exc: Exception) -> str:
    if isinstance(exc, errors.FloodWaitError):
        return f"Telegram установил паузу на {exc.seconds} сек. Повторите позже."
    if isinstance(exc, errors.ChannelPrivateError):
        return "Канал приватный или недоступен этому Telegram-аккаунту."
    if isinstance(exc, errors.UsernameNotOccupiedError):
        return "Публичный канал с таким username не найден."
    if isinstance(exc, PermissionError):
        return "Telegram session не авторизована. Завершите вход в разделе настройки."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"Не удалось получить данные Telegram: {type(exc).__name__}"


def _media_metadata(tg: TelegramBackend, msg) -> tuple[bool, str | None]:
    has_voice, media_type = tg._detect_media_type(msg)
    if has_voice and media_type:
        return True, media_type
    media = getattr(msg, "media", None)
    if not media:
        return False, None
    return True, media_type or type(media).__name__


def _sender_name(sender) -> str:
    if not sender:
        return ""
    name = " ".join(
        part for part in (
            getattr(sender, "first_name", None),
            getattr(sender, "last_name", None),
        ) if part
    )
    return name or getattr(sender, "title", None) or ""


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def _existing_media_file(media_dir: Path, stem: str) -> Path | None:
    candidates = [
        path for path in media_dir.glob(f"{stem}*")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    return sorted(candidates)[0] if candidates else None


async def _prepare_media(
    tg: TelegramBackend,
    msg,
    media_dir: Path,
    stem: str,
    media_type: str | None,
    should_download: bool,
) -> tuple[dict[str, Any], str | None]:
    info: dict[str, Any] = {
        "type": media_type or "other",
        "downloaded": False,
    }
    existing = _existing_media_file(media_dir, stem)
    if existing:
        info.update({
            "downloaded": True,
            "filename": existing.name,
            "path": f"media/{existing.name}",
            "size": existing.stat().st_size,
        })
        return info, None
    if not should_download:
        info["reason"] = "Скачивание media не было выбрано при парсинге."
        return info, None

    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        downloaded = await tg.client.download_media(
            msg,
            file=str(media_dir / stem),
        )
    except errors.FloodWaitError:
        raise
    except Exception as exc:
        info["reason"] = (
            f"Telegram не отдал файл: {type(exc).__name__}. "
            "Текст сообщения сохранён."
        )
        return info, info["reason"]

    if not downloaded:
        info["reason"] = (
            "У сообщения есть media-объект, но Telegram не предоставил "
            "скачиваемый файл."
        )
        return info, info["reason"]

    path = Path(downloaded).resolve()
    media_root = media_dir.resolve()
    if path != media_root and media_root not in path.parents:
        info["reason"] = "Telegram вернул файл вне ожидаемой папки media."
        return info, info["reason"]
    if not path.exists():
        info["reason"] = "Telegram завершил загрузку, но файл не найден на диске."
        return info, info["reason"]

    info.update({
        "downloaded": True,
        "filename": path.name,
        "path": f"media/{path.name}",
        "size": path.stat().st_size,
    })
    return info, None


async def _publication_numbers(
    tg: TelegramBackend,
    entity,
    message_ids: set[int],
) -> dict[int, int]:
    """Return exact chronological positions among existing channel posts."""
    if not message_ids:
        return {}
    numbers: dict[int, int] = {}
    position = 0
    async for historical in tg.iter_posts(entity, reverse=True):
        position += 1
        if historical.id in message_ids:
            numbers[historical.id] = position
            if len(numbers) == len(message_ids):
                break
    return numbers


async def _parse_message(
    tg: TelegramBackend,
    db: Database,
    entity,
    channel_model,
    channel_db_id: int,
    msg,
    run_id: int,
    save_dir: Path,
    target: TelegramTarget,
    download_media: bool,
    publication_number: int | None,
) -> tuple[dict, Path, list[str], int]:
    post = tg.message_to_post(msg, channel_db_id)
    db.upsert_post(post)
    has_media, media_type = _media_metadata(tg, msg)
    post_dir = save_dir / channel_model.username / str(msg.id)
    media_dir = post_dir / "media"
    media_warnings: list[str] = []
    media_files_count = 0
    post_media = None
    if has_media:
        post_media, warning = await _prepare_media(
            tg, msg, media_dir, f"post_{msg.id}", media_type, download_media
        )
        if post_media.get("downloaded"):
            media_files_count += 1
        if warning:
            media_warnings.append(f"Media поста {msg.id}: {warning}")

    comments: list[dict[str, Any]] = []
    async for comment_msg in tg.iter_comments(entity, msg.id):
        try:
            sender = await comment_msg.get_sender()
        except (errors.RPCError, ValueError):
            sender = getattr(comment_msg, "sender", None)
        comment = tg.message_to_comment(comment_msg, channel_db_id, msg.id)
        db.upsert_comment(comment)
        comment_has_media, comment_media_type = _media_metadata(tg, comment_msg)
        comment_media = None
        if comment_has_media:
            comment_media, warning = await _prepare_media(
                tg,
                comment_msg,
                media_dir,
                f"comment_{comment_msg.id}",
                comment_media_type,
                download_media,
            )
            if comment_media.get("downloaded"):
                media_files_count += 1
            if warning:
                media_warnings.append(
                    f"Media комментария {comment_msg.id}: {warning}"
                )
        comments.append({
            "id": comment_msg.id,
            "date": comment_msg.date.isoformat() if comment_msg.date else "",
            "text": comment_msg.message or "",
            "reply_to": (
                comment_msg.reply_to.reply_to_msg_id
                if comment_msg.reply_to else None
            ),
            "sender_id": getattr(sender, "id", None),
            "sender_username": getattr(sender, "username", None),
            "sender_name": _sender_name(sender),
            "has_media": comment_has_media,
            "media_type": comment_media_type,
            "media": comment_media,
        })

    result = {
        "channel": channel_model.username,
        "channel_title": channel_model.title,
        "post_id": msg.id,
        "publication_number": publication_number,
        "url": target.post_url(msg.id),
        "date": msg.date.isoformat() if msg.date else "",
        "text": msg.message or "",
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "has_media": has_media,
        "media_type": media_type,
        "media": post_media,
        "media_directory": "media" if media_files_count else None,
        "media_download_requested": download_media,
        "comments_count": len(comments),
        "comments": comments,
    }
    db.upsert_parsed_post(result, run_id)
    db.replace_parsed_comments(channel_model.username, msg.id, comments, run_id)
    path = post_dir / "post.json"
    _write_json(path, result)
    return result, path, media_warnings, media_files_count


async def execute_parse_run(
    run_id: int,
    target: TelegramTarget,
    limit: int = 10,
    db_path: str = "db.sqlite3",
    download_media: bool = False,
) -> dict:
    """Execute one parse run and persist all status updates."""
    settings = LocalSettings.load_effective()
    if not settings.configured:
        raise ValueError("Сначала настройте api_id и api_hash.")
    save_dir = validate_save_dir(settings.save_dir)
    config = Config(
        api_id=int(settings.api_id),
        api_hash=settings.api_hash,
        session_name=settings.session_path,
        db_path=db_path,
    )
    db = Database(config.db_path)
    db.open()
    tg = TelegramBackend(config.api_id, config.api_hash, config.session_name)
    posts: list[dict] = []
    warnings: list[str] = []
    save_path = ""
    media_files_count = 0

    db.update_parse_run(run_id, status="running")
    try:
        await tg.connect()
        entity, channel_model = await tg.resolve_channel(target.telegram_identifier)
        channel_db_id = db.upsert_channel(channel_model)

        if target.kind == "post":
            msg = await tg.client.get_messages(entity, ids=target.post_id)
            if not msg or not getattr(msg, "id", None):
                raise ValueError(f"Пост @{target.channel}/{target.post_id} не найден.")
            messages = [msg]
        else:
            messages = [msg async for msg in tg.iter_posts(entity, limit=limit)]

        publication_numbers = await _publication_numbers(
            tg,
            entity,
            {msg.id for msg in messages},
        )
        db.update_parse_run(run_id, total_posts=len(messages))
        for index, msg in enumerate(messages, start=1):
            try:
                parsed, post_path, media_warnings, post_media_count = await _parse_message(
                    tg, db, entity, channel_model, channel_db_id,
                    msg, run_id, save_dir, target, download_media,
                    publication_numbers.get(msg.id),
                )
                posts.append(parsed)
                warnings.extend(media_warnings)
                media_files_count += post_media_count
                if target.kind == "post":
                    save_path = str(post_path)
            except errors.FloodWaitError:
                raise
            except Exception as exc:
                message = friendly_telegram_error(exc)
                warnings.append(f"Пост {getattr(msg, 'id', '?')}: {message}")
                db.add_run_post_error(
                    run_id, channel_model.username, getattr(msg, "id", 0), message
                )
                if target.kind == "post":
                    raise
            finally:
                db.update_parse_run(
                    run_id,
                    processed_posts=index,
                    posts_count=len(posts),
                    comments_count=sum(post["comments_count"] for post in posts),
                    media_files_count=media_files_count,
                    warnings_json=json.dumps(warnings, ensure_ascii=False),
                )

        if target.kind == "channel":
            summary = {
                "run_id": run_id,
                "channel": channel_model.username,
                "channel_title": channel_model.title,
                "source_url": target.canonical_url,
                "parsed_at": now_iso(),
                "posts_count": len(posts),
                "comments_count": sum(post["comments_count"] for post in posts),
                "media_files_count": media_files_count,
                "media_directory": (
                    "В каждом каталоге поста: media/" if media_files_count else None
                ),
                "warnings": warnings,
                "posts": posts,
            }
            summary_path = (
                save_dir / channel_model.username / f"channel_run_{run_id}.json"
            )
            _write_json(summary_path, summary)
            save_path = str(summary_path)

        status = "partial" if warnings else "success"
        db.update_parse_run(
            run_id,
            status=status,
            finished_at=now_iso(),
            save_path=save_path,
            posts_count=len(posts),
            comments_count=sum(post["comments_count"] for post in posts),
            media_files_count=media_files_count,
            warnings_json=json.dumps(warnings, ensure_ascii=False),
        )
        return db.get_parse_run(run_id) or {}
    except Exception as exc:
        message = friendly_telegram_error(exc)
        db.update_parse_run(
            run_id,
            status="failed",
            finished_at=now_iso(),
            error=message,
            warnings_json=json.dumps(warnings, ensure_ascii=False),
        )
        return db.get_parse_run(run_id) or {"id": run_id, "status": "failed", "error": message}
    finally:
        await tg.stop()
        db.close()
