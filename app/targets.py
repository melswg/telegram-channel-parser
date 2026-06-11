"""Telegram URL and username parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")


@dataclass(frozen=True)
class TelegramTarget:
    kind: str
    channel: str
    post_id: int | None = None
    private_channel_id: int | None = None

    @property
    def canonical_url(self) -> str:
        if self.private_channel_id is not None:
            suffix = f"/{self.post_id}" if self.post_id is not None else ""
            return f"https://t.me/c/{self.private_channel_id}{suffix}"
        suffix = f"/{self.post_id}" if self.post_id is not None else ""
        return f"https://t.me/{self.channel}{suffix}"

    @property
    def telegram_identifier(self) -> str:
        if self.private_channel_id is not None:
            return f"c:{self.private_channel_id}"
        return self.channel

    def post_url(self, post_id: int) -> str:
        if self.private_channel_id is not None:
            return f"https://t.me/c/{self.private_channel_id}/{post_id}"
        return f"https://t.me/{self.channel}/{post_id}"


def parse_telegram_target(value: str) -> TelegramTarget:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Вставьте ссылку на Telegram-пост или канал.")

    if raw.startswith("@"):
        path = raw[1:]
    else:
        normalized = raw if "://" in raw else f"https://{raw}"
        parsed = urlparse(normalized)
        if parsed.hostname not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            raise ValueError("Поддерживаются ссылки t.me и публичные @username.")
        path = parsed.path.strip("/")

    parts = [part for part in path.split("/") if part]
    if not parts:
        raise ValueError("В ссылке не найден username канала.")
    if parts[0] in {"joinchat"} or parts[0].startswith("+"):
        raise ValueError("Приватные invite-ссылки пока не поддерживаются.")
    if parts[0] == "s":
        parts = parts[1:]
    if parts[0] == "c":
        if len(parts) not in {2, 3}:
            raise ValueError(
                "Для приватного канала ожидается ссылка вида t.me/c/123456789/42."
            )
        try:
            private_channel_id = int(parts[1])
        except ValueError as exc:
            raise ValueError("ID приватного канала должен быть числом.") from exc
        if private_channel_id <= 0:
            raise ValueError("ID приватного канала должен быть положительным.")
        channel = f"private_{private_channel_id}"
        if len(parts) == 2:
            return TelegramTarget(
                kind="channel",
                channel=channel,
                private_channel_id=private_channel_id,
            )
        try:
            post_id = int(parts[2])
        except ValueError as exc:
            raise ValueError("ID поста должен быть числом.") from exc
        if post_id <= 0:
            raise ValueError("ID поста должен быть положительным.")
        return TelegramTarget(
            kind="post",
            channel=channel,
            post_id=post_id,
            private_channel_id=private_channel_id,
        )
    if len(parts) not in {1, 2}:
        raise ValueError("Ожидается ссылка на канал или конкретный пост.")

    channel = parts[0].lstrip("@")
    if not USERNAME_RE.fullmatch(channel):
        raise ValueError("Некорректный публичный username Telegram-канала.")

    if len(parts) == 1:
        return TelegramTarget(kind="channel", channel=channel)
    try:
        post_id = int(parts[1])
    except ValueError as exc:
        raise ValueError("ID поста должен быть числом.") from exc
    if post_id <= 0:
        raise ValueError("ID поста должен быть положительным.")
    return TelegramTarget(kind="post", channel=channel, post_id=post_id)
