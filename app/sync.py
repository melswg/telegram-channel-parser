"""Sync orchestrator: coordinates posts → comments → media → transcription."""

import asyncio
import json
import logging
from typing import Optional

from telethon import TelegramClient

from .config import Config
from .db import Database
from .models import Channel, Post, Comment, Media, Transcript, now_iso
from .telegram import TelegramBackend
from .media import download_voice, compute_sha256
from .transcriber import Transcriber

log = logging.getLogger(__name__)


class SyncEngine:
    """Orchestrates the full sync pipeline for a single channel."""

    def __init__(self, config: Config, db: Database, tg: TelegramBackend):
        self.config = config
        self.db = db
        self.tg = tg
        self.client: TelegramClient = tg.client

    async def sync_channel(self, channel_username: str,
                           limit: Optional[int] = None,
                           since: Optional[str] = None,
                           until: Optional[str] = None,
                           resume: bool = False,
                           dry_run: bool = False) -> dict:
        """Sync one channel: posts → comments → (media enqueued).

        Returns summary dict with counts.
        """
        stats = {"posts": 0, "comments": 0, "voices_found": 0, "media_scheduled": 0}

        # 1. Resolve channel
        log.info("Resolving channel @%s ...", channel_username)
        entity, ch = await self.tg.resolve_channel(channel_username)
        channel_id = self.db.upsert_channel(ch)
        log.info("Channel ID %d: %s", channel_id, ch.title)

        if dry_run:
            log.info("[DRY RUN] Would sync channel @%s (%s)", channel_username, ch.title)

        # 2. Determine starting point for resume
        min_id = None
        if resume:
            min_id = self.db.get_last_post_id(channel_id)

        # 3. Iterate posts
        post_count = 0
        async for msg in self.tg.iter_posts(entity, limit=limit, min_id=min_id):
            post = self.tg.message_to_post(msg, channel_id)

            # Date filtering
            if since and post.date and post.date < since:
                continue
            if until and post.date and post.date > until:
                break

            if dry_run:
                log.info("[DRY RUN] Post %d: %s...", post.post_msg_id, (post.text or "")[:60])
                post_count += 1
                continue

            # Save post
            post_db_id = self.db.upsert_post(post)
            log.debug("Post %d saved (id=%d)", post.post_msg_id, post_db_id)

            # 4. Fetch comments for this post
            comment_count = 0
            async for cmt_msg in self.tg.iter_comments(entity, post.post_msg_id):
                comment = self.tg.message_to_comment(cmt_msg, channel_id, post.post_msg_id)
                comment_db_id = self.db.upsert_comment(comment)
                comment_count += 1
                stats["comments"] += 1

                # Check for voice
                if comment.has_voice:
                    stats["voices_found"] += 1
                    # Queue media download (comment.id is now set from DB upsert)
                    # We need the comment's actual DB id for the media record
                    cmt_in_db = self.db.upsert_comment(comment)
                    if cmt_in_db:
                        comment_db_id = cmt_in_db

                    # Schedule download immediately (or later via transcribe command)
                    media = await self._download_comment_voice(
                        cmt_msg, comment, comment_db_id, channel_username
                    )
                    if media:
                        media.comment_id = comment_db_id
                        self.db.upsert_media(media)
                        stats["media_scheduled"] += 1

            log.info("Post %d: %d comments (%d voice)", post.post_msg_id, comment_count, stats["voices_found"])
            post_count += 1
            stats["posts"] += 1

            # Checkpoint: save last synced post
            self.db.update_channel_last_post(channel_id, post.post_msg_id)

        if dry_run:
            log.info("[DRY RUN] Found %d posts for @%s", post_count, channel_username)
            return {"dry_run": True, "posts_found": post_count}

        log.info("Channel @%s done: %d posts, %d comments, %d voices downloaded",
                 channel_username, stats["posts"], stats["comments"], stats["media_scheduled"])
        return stats

    async def _download_comment_voice(self, msg, comment: Comment,
                                      comment_db_id: int,
                                      channel_username: str) -> Optional[Media]:
        """Download voice media from a comment."""
        media = await download_voice(
            download_fn=self.client.download_media,
            media_dir=self.config.media_dir,
            channel_username=channel_username,
            comment=comment,
            msg_object=msg,
        )
        if media:
            media.comment_id = comment_db_id
        return media

    async def process_pending_media(self, force: bool = False) -> dict:
        """Retry downloading pending/failed media.

        Returns summary.
        """
        stats = {"downloaded": 0, "failed": 0, "skipped": 0}
        pending = self.db.get_undownloaded_voice_comments()
        if not pending:
            log.info("No pending voice comments to download")
            return stats

        log.info("Found %d voice comments without media records", len(pending))

        # We need full Telethon messages to download media, so re-fetch from Telegram
        for comment in pending[:50]:  # Batch limit
            try:
                entity = await self.tg.client.get_entity(comment.discussion_chat_id or comment.channel_id)
                msg = await self.tg.client.get_messages(entity, ids=comment.comment_msg_id)
                if not msg:
                    log.warning("Message %d not found (may be deleted)", comment.comment_msg_id)
                    continue

                # Need channel username
                ch = self.db.get_channel_by_id(comment.channel_id)
                channel_username = ch.username if ch else "unknown"

                media = await download_voice(
                    download_fn=self.tg.client.download_media,
                    media_dir=self.config.media_dir,
                    channel_username=channel_username,
                    comment=comment,
                    msg_object=msg,
                )
                if media and media.download_status == "downloaded":
                    media.comment_id = comment.id or 0
                    self.db.upsert_media(media)
                    stats["downloaded"] += 1
                    log.info("Downloaded voice %d: %s", comment.comment_msg_id, media.local_path)
                else:
                    stats["failed"] += 1
            except Exception as e:
                log.error("Failed to download msg %d: %s", comment.comment_msg_id, e)
                stats["failed"] += 1

        return stats


async def run_sync(config: Config,
                   channels: Optional[list[str]] = None,
                   limit: Optional[int] = None,
                   since: Optional[str] = None,
                   until: Optional[str] = None,
                   resume: bool = False,
                   dry_run: bool = False) -> list[dict]:
    """Main sync entrypoint. Creates DB, connects Telegram, syncs channels."""
    channels = channels or config.channels
    if not channels:
        raise ValueError("No channels specified. Use --channel or set CHANNELS in .env")

    db = Database(config.db_path)
    db.open()

    tg = TelegramBackend(config.api_id, config.api_hash, config.session_name)
    try:
        await tg.start()
        engine = SyncEngine(config, db, tg)
        results = []
        for ch_name in channels:
            result = await engine.sync_channel(ch_name, limit=limit, since=since,
                                                until=until, resume=resume, dry_run=dry_run)
            results.append({"channel": ch_name, **result})
        return results
    finally:
        await tg.stop()
        db.close()


async def run_transcribe(config: Config,
                         model_size: Optional[str] = None,
                         language: Optional[str] = None,
                         force: bool = False) -> dict:
    """Transcribe all untranscribed downloaded media."""
    db = Database(config.db_path)
    db.open()

    model_size = model_size or config.whisper_model
    language = language or config.whisper_language

    transcriber = Transcriber(model_size=model_size, language=language)
    media_list = db.get_untranscribed_media()
    if not media_list:
        log.info("No untranscribed media found")
        return {"transcribed": 0, "total": 0}

    log.info("Transcribing %d media files...", len(media_list))
    stats = {"transcribed": 0, "total": len(media_list)}

    for media in media_list:
        try:
            transcript = transcriber.transcribe(media.local_path)
            transcript.media_id = media.id or 0
            db.insert_transcript(transcript)

            # Update media status
            db.update_media_status(media.id, "transcribed" if media.id else "done")
            stats["transcribed"] += 1
            log.info("Transcribed #%d: %.1fs -> %s...",
                     media.id, media.duration or 0,
                     (transcript.text or "")[:60])
        except Exception as e:
            log.error("Transcription failed for media #%d (%s): %s",
                      media.id, media.local_path, e)

    db.close()
    return stats
