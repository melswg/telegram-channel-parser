"""Read-only parsing service shared by the Web UI and CLI."""

from __future__ import annotations

import asyncio
import json
import mimetypes
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


def build_parse_preview(
    target: TelegramTarget,
    total_posts: int,
    requested_limit: int | None,
    download_media: bool,
) -> dict[str, Any]:
    selected_posts = (
        1
        if target.kind == "post"
        else total_posts if requested_limit is None else min(total_posts, requested_limit)
    )
    media_state = "включены" if download_media else "выключены"
    if selected_posts % 10 == 1 and selected_posts % 100 != 11:
        noun = "публикация"
    elif selected_posts % 10 in {2, 3, 4} and selected_posts % 100 not in {12, 13, 14}:
        noun = "публикации"
    else:
        noun = "публикаций"
    return {
        "available_posts": total_posts,
        "posts_count": selected_posts,
        "all_posts": target.kind == "channel" and requested_limit is None,
        "download_media": download_media,
        "confirmation": (
            f"Будет загружено {selected_posts} {noun}. "
            f"Media {media_state}. Вы согласны?"
        ),
    }


async def preview_parse(
    target: TelegramTarget,
    limit: int | None,
    download_media: bool,
) -> dict[str, Any]:
    """Count available posts before the user confirms a parse run."""
    settings = LocalSettings.load_effective()
    if not settings.configured:
        raise ValueError("Сначала настройте api_id и api_hash.")
    config = Config(
        api_id=int(settings.api_id),
        api_hash=settings.api_hash,
        session_name=settings.session_path,
    )
    tg = TelegramBackend(config.api_id, config.api_hash, config.session_name)
    try:
        await tg.connect()
        entity, _ = await tg.resolve_channel(target.telegram_identifier)
        if target.kind == "post":
            message = await tg.client.get_messages(entity, ids=target.post_id)
            if not message or not getattr(message, "id", None):
                raise ValueError(
                    f"Пост {target.canonical_url} не найден или недоступен."
                )
            total_posts = 1
        else:
            total_posts = 0
            async for _ in tg.iter_posts(entity):
                total_posts += 1
        return build_parse_preview(
            target,
            total_posts,
            limit,
            download_media,
        )
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(friendly_telegram_error(exc)) from exc
    finally:
        await tg.stop()


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


def _unprocessed_messages(messages: list, processed_ids: set[int]) -> list:
    return [
        message for message in messages
        if int(getattr(message, "id", 0)) not in processed_ids
    ]


async def _wait_until_resumed(db: Database, run_id: int) -> bool:
    while True:
        status = db.get_parse_run_status(run_id)
        if status == "paused":
            await asyncio.sleep(0.25)
            continue
        return status in {"queued", "running"}


async def _collect_messages(
    tg: TelegramBackend,
    entity,
    limit: int | None,
    db: Database,
    run_id: int,
) -> list:
    messages = []
    async for message in tg.iter_posts(entity, limit=limit):
        if not await _wait_until_resumed(db, run_id):
            break
        messages.append(message)
    return messages


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


def _media_duration(msg) -> float | None:
    media = getattr(msg, "media", None)
    document = getattr(media, "document", None)
    for attribute in getattr(document, "attributes", []) or []:
        duration = getattr(attribute, "duration", None)
        if duration is not None:
            return float(duration)
    return None


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
        "duration": _media_duration(msg),
    }
    existing = _existing_media_file(media_dir, stem)
    if existing:
        info.update({
            "downloaded": True,
            "filename": existing.name,
            "path": f"media/{existing.name}",
            "size": existing.stat().st_size,
            "mime_type": mimetypes.guess_type(existing.name)[0] or "",
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
        "mime_type": mimetypes.guess_type(path.name)[0] or "",
    })
    return info, None


async def _publication_numbers(
    tg: TelegramBackend,
    entity,
    message_ids: set[int],
    db: Database | None = None,
    run_id: int | None = None,
) -> dict[int, int]:
    """Return exact chronological positions among existing channel posts."""
    if not message_ids:
        return {}
    numbers: dict[int, int] = {}
    position = 0
    async for historical in tg.iter_posts(entity, reverse=True):
        if db is not None and run_id is not None:
            if not await _wait_until_resumed(db, run_id):
                break
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
    if not await _wait_until_resumed(db, run_id):
        raise asyncio.CancelledError
    post = tg.message_to_post(msg, channel_db_id)
    db.upsert_post(post)
    has_media, media_type = _media_metadata(tg, msg)
    post_dir = save_dir / channel_model.username / str(msg.id)
    media_dir = post_dir / "media"
    media_warnings: list[str] = []
    media_files_count = 0
    post_media = None
    if has_media:
        if not await _wait_until_resumed(db, run_id):
            raise asyncio.CancelledError
        post_media, warning = await _prepare_media(
            tg, msg, media_dir, f"post_{msg.id}", media_type, download_media
        )
        if post_media.get("downloaded"):
            media_files_count += 1
        if warning:
            media_warnings.append(f"Media поста {msg.id}: {warning}")

    comments: list[dict[str, Any]] = []
    async for comment_msg in tg.iter_comments(entity, msg.id):
        if not await _wait_until_resumed(db, run_id):
            raise asyncio.CancelledError
        try:
            sender = await comment_msg.get_sender()
        except (errors.RPCError, ValueError):
            sender = getattr(comment_msg, "sender", None)
        comment = tg.message_to_comment(comment_msg, channel_db_id, msg.id)
        db.upsert_comment(comment)
        comment_has_media, comment_media_type = _media_metadata(tg, comment_msg)
        comment_media = None
        if comment_has_media:
            if not await _wait_until_resumed(db, run_id):
                raise asyncio.CancelledError
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
    limit: int | None = 10,
    db_path: str = "db.sqlite3",
    download_media: bool = False,
    resume: bool = False,
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
    existing_run = db.get_parse_run(run_id) or {}
    processed_ids = (
        db.get_parse_run_post_ids(run_id) if resume else set()
    )
    existing_processed = len(processed_ids)
    posts_count = int(existing_run.get("posts_count") or 0)
    comments_count = int(existing_run.get("comments_count") or 0)
    warnings: list[str] = list(existing_run.get("warnings") or [])
    save_path = str(existing_run.get("save_path") or "")
    media_files_count = int(existing_run.get("media_files_count") or 0)

    if db.get_parse_run_status(run_id) != "paused":
        db.update_parse_run(run_id, status="running", error="")
    try:
        if not await _wait_until_resumed(db, run_id):
            return db.get_parse_run(run_id) or {}
        await tg.connect()
        entity, channel_model = await tg.resolve_channel(target.telegram_identifier)
        channel_db_id = db.upsert_channel(channel_model)

        queued_ids = db.get_parse_run_queue(run_id) if resume else []
        if queued_ids:
            pending_ids = [
                post_id for post_id in queued_ids
                if post_id not in processed_ids
            ]
            loaded = (
                await tg.client.get_messages(entity, ids=pending_ids)
                if pending_ids else []
            )
            loaded_messages = (
                list(loaded)
                if isinstance(loaded, (list, tuple))
                else [loaded]
            )
            by_id = {
                int(message.id): message
                for message in loaded_messages
                if message and getattr(message, "id", None)
            }
            missing_ids = [
                post_id for post_id in pending_ids if post_id not in by_id
            ]
            for post_id in missing_ids:
                message = (
                    f"Публикация Telegram ID #{post_id} была удалена или "
                    "стала недоступна во время паузы."
                )
                warnings.append(message)
                db.add_run_post_error(
                    run_id, channel_model.username, post_id, message
                )
            existing_processed += len(missing_ids)
            messages = [
                by_id[post_id] for post_id in pending_ids if post_id in by_id
            ]
            total_posts = len(queued_ids)
        elif target.kind == "post":
            msg = await tg.client.get_messages(entity, ids=target.post_id)
            if not msg or not getattr(msg, "id", None):
                raise ValueError(f"Пост @{target.channel}/{target.post_id} не найден.")
            messages = [msg]
            total_posts = 1
        else:
            messages = await _collect_messages(
                tg, entity, limit, db, run_id
            )
            total_posts = len(messages)
        if not queued_ids:
            db.save_parse_run_queue(
                run_id,
                [int(message.id) for message in messages],
            )
        pending_messages = _unprocessed_messages(messages, processed_ids)

        if target.kind == "channel" and limit is None:
            publication_numbers = {
                msg.id: position
                for position, msg in enumerate(reversed(messages), start=1)
            }
        else:
            publication_numbers = await _publication_numbers(
                tg,
                entity,
                {msg.id for msg in messages},
                db,
                run_id,
            )
        db.update_parse_run(run_id, total_posts=total_posts)
        for offset, msg in enumerate(pending_messages, start=1):
            if not await _wait_until_resumed(db, run_id):
                return db.get_parse_run(run_id) or {}
            processed_posts = existing_processed + offset
            try:
                parsed, post_path, media_warnings, post_media_count = await _parse_message(
                    tg, db, entity, channel_model, channel_db_id,
                    msg, run_id, save_dir, target, download_media,
                    publication_numbers.get(msg.id),
                )
                posts_count += 1
                comments_count += parsed["comments_count"]
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
                    processed_posts=processed_posts,
                    posts_count=posts_count,
                    comments_count=comments_count,
                    media_files_count=media_files_count,
                    warnings_json=json.dumps(warnings, ensure_ascii=False),
                )

        if target.kind == "channel":
            run_posts = (db.get_parse_run(run_id) or {}).get("posts", [])
            all_posts = [
                post
                for item in run_posts
                if not item.get("error")
                for post in [db.get_parsed_post(item["channel"], item["post_id"])]
                if post
            ]
            summary = {
                "run_id": run_id,
                "channel": channel_model.username,
                "channel_title": channel_model.title,
                "source_url": target.canonical_url,
                "parsed_at": now_iso(),
                "posts_count": posts_count,
                "comments_count": comments_count,
                "media_files_count": media_files_count,
                "media_directory": (
                    "В каждом каталоге поста: media/" if media_files_count else None
                ),
                "warnings": warnings,
                "posts": all_posts,
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
            posts_count=posts_count,
            comments_count=comments_count,
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
