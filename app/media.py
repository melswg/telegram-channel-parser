"""Voice message download and detection."""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional, Callable, Awaitable

from .models import Media, Comment

log = logging.getLogger(__name__)

# Async download function type — we inject the Telethon client
DownloadFn = Callable[[object, str], Awaitable[str]]


def comment_media_path(media_dir: str, channel_username: str,
                       post_msg_id: int, comment_msg_id: int) -> str:
    """Build deterministic file path for a voice message."""
    path = Path(media_dir) / channel_username / str(post_msg_id)
    path.mkdir(parents=True, exist_ok=True)
    return str(path / f"{comment_msg_id}.ogg")


def compute_sha256(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def download_voice(
    download_fn: DownloadFn,
    media_dir: str,
    channel_username: str,
    comment: Comment,
    msg_object,
) -> Optional[Media]:
    """Download voice media from a comment.

    Returns Media dataclass with download status, or None if no voice media.

    Args:
        download_fn: Async function(msg, file_path) -> downloaded_path
        media_dir: Base media storage directory
        channel_username: Channel username (for subdirectory)
        comment: Comment dataclass
        msg_object: Original Telethon Message with media
    """
    if not hasattr(msg_object, "media") or not msg_object.media:
        log.warning("No media on msg %d", comment.comment_msg_id)
        return None

    # Determine file extension
    doc = getattr(msg_object.media, "document", None)
    mime_type = getattr(doc, "mime_type", "audio/ogg") if doc else "audio/ogg"

    ext = ".ogg"
    if mime_type == "audio/mpeg":
        ext = ".mp3"
    elif mime_type == "audio/mp4" or mime_type == "audio/aac":
        ext = ".m4a"

    filepath = Path(media_dir) / channel_username / str(comment.post_msg_id)
    filepath.mkdir(parents=True, exist_ok=True)
    full_path = str(filepath / f"{comment.comment_msg_id}{ext}")

    # Check if already exists (resume)
    if os.path.exists(full_path):
        existing_sha = compute_sha256(full_path)
        duration = _get_audio_duration(msg_object)
        return Media(
            comment_id=comment.id or 0,
            document_id=getattr(doc, "id", None) if doc else None,
            mime_type=mime_type,
            local_path=full_path,
            size=os.path.getsize(full_path),
            duration=duration,
            sha256=existing_sha,
            download_status="downloaded",
        )

    log.info("Downloading voice msg %d -> %s", comment.comment_msg_id, full_path)
    try:
        await download_fn(msg_object, full_path)
    except Exception as e:
        log.error("Download failed for msg %d: %s", comment.comment_msg_id, e)
        return Media(
            comment_id=comment.id or 0,
            mime_type=mime_type,
            download_status="failed",
        )

    if not os.path.exists(full_path):
        log.warning("Download returned but file missing: %s", full_path)
        return Media(
            comment_id=comment.id or 0,
            mime_type=mime_type,
            download_status="failed",
        )

    sha = compute_sha256(full_path)
    duration = _get_audio_duration(msg_object)
    size = os.path.getsize(full_path)

    return Media(
        comment_id=comment.id or 0,
        document_id=getattr(doc, "id", None) if doc else None,
        mime_type=mime_type,
        local_path=full_path,
        size=size,
        duration=duration,
        sha256=sha,
        download_status="downloaded",
    )


def _get_audio_duration(msg_object) -> Optional[float]:
    """Extract audio duration from message media attributes."""
    media = getattr(msg_object, "media", None)
    if not media:
        return None
    doc = getattr(media, "document", None)
    if not doc:
        return None
    for attr in getattr(doc, "attributes", []) or []:
        if hasattr(attr, "duration") and attr.duration:
            return float(attr.duration)
    return None
