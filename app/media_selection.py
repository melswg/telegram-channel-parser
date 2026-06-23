"""Media download categories shared by the Web UI and parser."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal


MediaDownloadType = Literal[
    "photo",
    "video",
    "video_note",
    "animation",
    "document",
    "audio",
    "voice",
    "sticker",
]

MEDIA_DOWNLOAD_TYPES: tuple[MediaDownloadType, ...] = (
    "photo",
    "video",
    "video_note",
    "animation",
    "document",
    "audio",
    "voice",
    "sticker",
)

MEDIA_DOWNLOAD_LABELS: dict[str, str] = {
    "photo": "Фото",
    "video": "Видео",
    "video_note": "Кружки",
    "animation": "GIF",
    "document": "Файлы",
    "audio": "Аудиофайлы",
    "voice": "Голосовые",
    "sticker": "Стикеры",
}

MEDIA_TYPE_CATEGORIES = {
    "image": "photo",
}


def normalize_media_selection(
    download_all: bool,
    media_types: Iterable[str] | None,
) -> tuple[bool, tuple[MediaDownloadType, ...]]:
    selected = set(media_types or ())
    ordered = tuple(
        media_type
        for media_type in MEDIA_DOWNLOAD_TYPES
        if media_type in selected
    )
    if download_all or len(ordered) == len(MEDIA_DOWNLOAD_TYPES):
        return True, ()
    return False, ordered


def should_download_media(
    media_type: str | None,
    download_all: bool,
    media_types: Iterable[str] | None,
) -> bool:
    if download_all:
        return True
    category = MEDIA_TYPE_CATEGORIES.get(media_type or "", media_type)
    return bool(category and category in set(media_types or ()))


def media_selection_label(
    download_all: bool,
    media_types: Iterable[str] | None,
) -> str:
    download_all, selected = normalize_media_selection(
        download_all,
        media_types,
    )
    if download_all:
        return "Все типы"
    if not selected:
        return "Выключены"
    return ", ".join(MEDIA_DOWNLOAD_LABELS[item] for item in selected)
