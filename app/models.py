"""Data models for Telegram Comments Importer."""

from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone


@dataclass
class Channel:
    """Telegram channel."""
    username: str
    telegram_id: int
    title: str = ""
    access_hash: int = 0
    last_post_id_seen: Optional[int] = None
    id: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_entity(cls, entity) -> "Channel":
        """Create from Telethon entity."""
        return cls(
            username=getattr(entity, "username", "") or "",
            telegram_id=entity.id,
            title=getattr(entity, "title", "") or "",
            access_hash=getattr(entity, "access_hash", 0) or 0,
        )


@dataclass
class Post:
    """Channel post/message."""
    channel_id: int
    post_msg_id: int
    date: str = ""
    text: str = ""
    views: Optional[int] = None
    forwards: Optional[int] = None
    raw_json: str = ""
    id: Optional[int] = None


@dataclass
class Comment:
    """Comment (reply to a channel post)."""
    channel_id: int
    post_msg_id: int
    comment_msg_id: int
    discussion_chat_id: Optional[int] = None
    sender_id: Optional[int] = None
    sender_username: Optional[str] = None
    date: str = ""
    text: str = ""
    reply_to_comment_id: Optional[int] = None
    has_voice: bool = False
    media_type: Optional[str] = None
    raw_json: str = ""
    id: Optional[int] = None


@dataclass
class Media:
    """Downloaded voice/media file."""
    comment_id: int
    document_id: Optional[int] = None
    mime_type: str = ""
    local_path: str = ""
    size: Optional[int] = None
    duration: Optional[float] = None
    sha256: str = ""
    download_status: str = "pending"  # pending, downloading, downloaded, failed
    id: Optional[int] = None


@dataclass
class Transcript:
    """Voice message transcript."""
    media_id: int
    engine: str = "faster-whisper"
    language: str = ""
    text: str = ""
    segments_json: str = ""
    created_at: str = ""
    id: Optional[int] = None


def to_dict(obj) -> dict:
    """Convert dataclass to dict, excluding None values for optional fields."""
    return {k: v for k, v in asdict(obj).items() if v is not None or k in getattr(obj, '__dataclass_fields__', {})}


def now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
