import unittest
from datetime import datetime, timezone

from telethon.tl.types import (
    Document,
    DocumentAttributeVideo,
    MessageMediaDocument,
)

from app.telegram import TelegramBackend


def video_message(*, round_message=False, attributes=True):
    document_attributes = []
    if attributes:
        document_attributes.append(DocumentAttributeVideo(
            duration=12,
            w=640,
            h=360,
            round_message=round_message,
        ))
    document = Document(
        id=1,
        access_hash=2,
        file_reference=b"",
        date=datetime.now(timezone.utc),
        mime_type="video/mp4",
        size=100,
        dc_id=2,
        attributes=document_attributes,
    )
    media = MessageMediaDocument(
        document=document,
        video=not round_message,
        round=round_message,
    )
    return type("Message", (), {"media": media})()


class TelegramMediaTypeTests(unittest.TestCase):
    def test_video_attribute_is_read_from_document(self):
        self.assertEqual(
            TelegramBackend._detect_media_type(video_message()),
            (False, "video"),
        )

    def test_round_video_is_detected_as_video_note(self):
        self.assertEqual(
            TelegramBackend._detect_media_type(
                video_message(round_message=True)
            ),
            (False, "video_note"),
        )

    def test_video_mime_type_is_not_labeled_as_document(self):
        self.assertEqual(
            TelegramBackend._detect_media_type(
                video_message(attributes=False)
            ),
            (False, "video"),
        )


if __name__ == "__main__":
    unittest.main()
