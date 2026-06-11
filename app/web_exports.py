"""Export helpers for parsed Web UI data."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path


POST_INTERNAL_FIELDS = {"id", "raw_json", "last_run_id", "updated_at"}
COMMENT_INTERNAL_FIELDS = {"id", "raw_json", "last_run_id", "updated_at", "channel", "post_id"}


def clean_post(post: dict) -> dict:
    result = {
        key: value for key, value in post.items()
        if key not in POST_INTERNAL_FIELDS and key != "comments"
    }
    result["has_media"] = bool(result.get("has_media"))
    result["comments"] = [
        {
            key: value for key, value in comment.items()
            if key not in COMMENT_INTERNAL_FIELDS
        }
        for comment in post.get("comments", [])
    ]
    for comment in result["comments"]:
        comment["has_media"] = bool(comment.get("has_media"))
    return result


def render_export(posts: list[dict], fmt: str) -> tuple[bytes, str]:
    cleaned = [clean_post(post) for post in posts]
    if fmt == "json":
        payload = cleaned[0] if len(cleaned) == 1 else {"posts": cleaned}
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    records = []
    for post in cleaned:
        comments = post.pop("comments", [])
        if not comments:
            records.append({**post, "comment_id": None, "comment_text": ""})
            continue
        for comment in comments:
            records.append({
                **post,
                "comment_id": comment.get("comment_id"),
                "comment_date": comment.get("date"),
                "comment_text": comment.get("text"),
                "sender_id": comment.get("sender_id"),
                "sender_username": comment.get("sender_username"),
                "sender_name": comment.get("sender_name"),
                "reply_to_comment_id": comment.get("reply_to_comment_id"),
                "comment_has_media": comment.get("has_media"),
                "comment_media_type": comment.get("media_type"),
                "analysis_text": comment.get("text") or post.get("text") or "",
            })

    if fmt == "jsonl":
        text = "".join(
            json.dumps(record, ensure_ascii=False, default=str) + "\n"
            for record in records
        )
        return text.encode("utf-8"), "application/x-ndjson; charset=utf-8"

    if fmt == "csv":
        output = io.StringIO()
        if records:
            writer = csv.DictWriter(output, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        return output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"

    raise ValueError("Формат должен быть json, jsonl или csv.")


def render_export_archive(
    posts: list[dict],
    fmt: str,
    save_dir: Path,
) -> tuple[bytes, str, int]:
    """Bundle structured export and previously downloaded media into a ZIP."""
    content, _ = render_export(posts, fmt)
    files: list[tuple[Path, str, dict]] = []
    seen: set[Path] = set()

    for post in posts:
        channel = str(post.get("channel") or "unknown")
        post_id = int(post.get("post_id") or 0)
        post_root = (save_dir / channel / str(post_id)).resolve()
        entries = [("post", post.get("media"))]
        entries.extend(
            (f"comment_{comment.get('comment_id') or comment.get('id')}", comment.get("media"))
            for comment in post.get("comments", [])
        )
        for source, media in entries:
            if not isinstance(media, dict) or not media.get("downloaded"):
                continue
            relative = str(media.get("path") or "")
            path = (post_root / relative).resolve()
            if post_root not in path.parents or not path.is_file() or path in seen:
                continue
            seen.add(path)
            archive_name = (
                f"media/{channel}/{post_id}/{path.name}"
            )
            files.append((
                path,
                archive_name,
                {
                    "source": source,
                    "channel": channel,
                    "post_id": post_id,
                    "type": media.get("type"),
                    "size": path.stat().st_size,
                    "file": archive_name,
                },
            ))

    if not files:
        raise ValueError(
            "Media для этого экспорта не найдены. Почему: при предыдущем "
            "парсинге скачивание media не было включено либо в сообщениях нет "
            "скачиваемых файлов. Что сделать: повторите парсинг с опцией "
            "«Скачивать media»."
        )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"data.{fmt}", content)
        archive.writestr(
            "MEDIA_INFO.txt",
            (
                "Все скачанные файлы находятся в папке media.\n"
                "Структура: media/<channel>/<post_id>/<filename>.\n"
                "Описание файлов: media_manifest.json.\n"
            ),
        )
        archive.writestr(
            "media_manifest.json",
            json.dumps(
                {"media_files": [item[2] for item in files]},
                ensure_ascii=False,
                indent=2,
            ),
        )
        for path, archive_name, _ in files:
            archive.write(path, archive_name)
    return output.getvalue(), "application/zip", len(files)
