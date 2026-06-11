"""Telethon client: authentication, posts, comments."""

import json
import logging
from typing import Optional, AsyncIterator, Tuple

from telethon import TelegramClient, errors
from telethon.tl.types import (
    Message, Channel as TLChannel, MessageService,
    MessageMediaDocument, DocumentAttributeAudio,
    MessageMediaWebPage,
)

from .models import Channel, Post, Comment, now_iso

log = logging.getLogger(__name__)


class TelegramBackend:
    """Wrapper around Telethon client for syncing channel data."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = "telegram_importer"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self._me = None

    async def start(self):
        """Connect and authenticate. Interactive on first run."""
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        await self.client.start()
        self._me = await self.client.get_me()
        log.info("Logged in as %s", self._me.username or self._me.phone or self._me.id)
        return self._me

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def resolve_channel(self, identifier: str) -> Tuple[TLChannel, Optional[Channel]]:
        """Resolve a channel @username, https://t.me/..., or raw string. Returns (entity, Channel or None)."""
        # Strip URL prefixes
        name = identifier.strip().rstrip("/")
        if "/" in name:
            name = name.rsplit("/", 1)[-1]
        name = name.lstrip("@")

        try:
            entity = await self.client.get_entity(name)
        except errors.UsernameNotOccupiedError:
            raise ValueError(f"Channel @{name} not found")
        except errors.ChannelPrivateError:
            raise ValueError(f"Channel @{name} is private/inaccessible")
        except ValueError as e:
            raise ValueError(f"Cannot resolve '{identifier}': {e}")

        if not isinstance(entity, TLChannel) or not getattr(entity, "username", None):
            raise ValueError(f"@{name} is not a public channel (entity type: {type(entity).__name__})")

        return entity, Channel.from_entity(entity)

    async def iter_posts(self, entity, limit: Optional[int] = None,
                         offset_id: Optional[int] = None,
                         min_id: Optional[int] = None,
                         reverse: bool = False) -> AsyncIterator[Message]:
        """Iterate channel posts (skip service messages)."""
        kwargs = dict(limit=limit, reverse=reverse)
        if offset_id:
            kwargs["offset_id"] = offset_id
        if min_id:
            kwargs["min_id"] = min_id

        async for msg in self.client.iter_messages(entity, **kwargs):
            if isinstance(msg, MessageService):
                continue
            if msg.message or msg.media:
                yield msg

    async def iter_comments(self, entity, post_msg_id: int,
                            limit: Optional[int] = None) -> AsyncIterator[Message]:
        """Iterate comments/replies for a channel post.

        Uses reply_to parameter to fetch the discussion thread.
        Falls back to GetRepliesRequest via low-level API if needed.
        """
        try:
            # Try high-level first
            async for msg in self.client.iter_messages(
                entity, reply_to=post_msg_id, limit=limit
            ):
                if isinstance(msg, MessageService):
                    continue
                yield msg
        except (errors.RPCError, ValueError):
            # Fallback: low-level GetRepliesRequest
            from telethon import functions
            offset_id = 0
            fetched = 0
            while True:
                try:
                    result = await self.client(functions.messages.GetRepliesRequest(
                        peer=entity,
                        msg_id=post_msg_id,
                        offset_id=offset_id,
                        offset_date=None,
                        add_offset=0,
                        limit=min(limit or 100, 100),
                        max_id=0,
                        min_id=0,
                        hash=0,
                    ))
                except errors.RPCError as e:
                    log.warning("GetRepliesRequest failed for post %d: %s", post_msg_id, e)
                    break

                msgs = getattr(result, "messages", [])
                if not msgs:
                    break

                for msg in msgs:
                    if isinstance(msg, MessageService):
                        continue
                    if limit and fetched >= limit:
                        return
                    yield msg
                    fetched += 1

                # Update offset_id for pagination
                offset_id = getattr(msgs[-1], "id", 0)
                if len(msgs) < 100:
                    break

    def message_to_post(self, msg: Message, channel_id: int) -> Optional[Post]:
        """Convert a Telethon Message to a Post dataclass."""
        text = msg.message or ""
        raw = self._message_to_json(msg)

        return Post(
            channel_id=channel_id,
            post_msg_id=msg.id,
            date=msg.date.isoformat() if msg.date else "",
            text=text,
            views=getattr(msg, "views", None),
            forwards=getattr(msg, "forwards", None),
            raw_json=raw,
        )

    def message_to_comment(self, msg: Message, channel_id: int,
                           post_msg_id: int) -> Comment:
        """Convert a Telethon Message to a Comment dataclass."""
        text = msg.message or ""
        raw = self._message_to_json(msg)
        sender = msg.sender

        # Detect voice
        has_voice, media_type = self._detect_media_type(msg)

        return Comment(
            channel_id=channel_id,
            post_msg_id=post_msg_id,
            comment_msg_id=msg.id,
            discussion_chat_id=msg.peer_id.channel_id if hasattr(msg.peer_id, 'channel_id') else None,
            sender_id=sender.id if sender else None,
            sender_username=getattr(sender, "username", None) if sender else None,
            date=msg.date.isoformat() if msg.date else "",
            text=text,
            reply_to_comment_id=msg.reply_to.reply_to_msg_id if msg.reply_to else None,
            has_voice=has_voice,
            media_type=media_type,
            raw_json=raw,
        )

    @staticmethod
    def _detect_media_type(msg: Message) -> tuple[bool, Optional[str]]:
        """Detect if message has voice/media. Returns (has_voice, media_type)."""
        media = msg.media
        if not media:
            return False, None

        # Direct voice message attribute
        if hasattr(media, "voice") and media.voice:
            return True, "voice"

        # Document with audio attributes
        if isinstance(media, MessageMediaDocument):
            attrs = getattr(media, "attributes", []) or []
            for attr in attrs:
                if isinstance(attr, DocumentAttributeAudio):
                    if attr.voice:
                        return True, "voice"
                    return True, "audio"
            for attr in attrs:
                if hasattr(attr, "voice") and attr.voice:
                    return True, "voice"

            mime = getattr(media.document, "mime_type", "") if media.document else ""
            if mime and mime.startswith("audio/"):
                return True, "audio"

            if media.photo:
                return False, "photo"

        if hasattr(media, "photo") and media.photo:
            return False, "photo"

        if isinstance(media, MessageMediaWebPage):
            return False, None

        return False, "other"

    @staticmethod
    def _message_to_json(msg: Message) -> str:
        """Serialize message to JSON-safe dict."""
        data = {
            "id": msg.id,
            "date": msg.date.isoformat() if msg.date else None,
            "message": msg.message,
            "views": getattr(msg, "views", None),
            "forwards": getattr(msg, "forwards", None),
            "reply_to": msg.reply_to.reply_to_msg_id if msg.reply_to else None,
        }
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"id": msg.id})
