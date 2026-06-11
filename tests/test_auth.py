import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.auth import TelegramAuthManager
from app.local_settings import LocalSettings


class FakeTelegramClient:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.request = None

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def __call__(self, request):
        self.request = request
        return object()


class FakeLogoutClient:
    def __init__(self, authorized=True, logout_result=True):
        self.authorized = authorized
        self.logout_result = logout_result
        self.disconnected = False

    async def is_user_authorized(self):
        return self.authorized

    async def log_out(self):
        return self.logout_result

    async def disconnect(self):
        self.disconnected = True


class TelegramAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_credentials_check_uses_memory_client(self):
        fake = FakeTelegramClient()
        with patch("app.auth.TelegramClient", return_value=fake):
            manager = TelegramAuthManager()
            await manager.verify_credentials(
                12345678, "0123456789abcdef0123456789abcdef"
            )

        self.assertTrue(fake.connected)
        self.assertTrue(fake.disconnected)
        self.assertIsNotNone(fake.request)

    async def test_complete_login_uses_optional_2fa_password(self):
        manager = TelegramAuthManager()
        manager.sign_in = AsyncMock(return_value={"state": "2fa_required"})
        manager.sign_in_2fa = AsyncMock(
            return_value={"state": "authorized", "user": {"id": 1}}
        )

        result = await manager.complete_login("12345", "secret")

        self.assertEqual(result["state"], "authorized")
        manager.sign_in_2fa.assert_awaited_once_with("secret")

    async def test_reset_removes_session_and_all_login_data(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            session_path = Path(root) / "first_user"
            session_file = Path(f"{session_path}.session")
            session_file.write_text("session", encoding="utf-8")
            effective = LocalSettings(
                api_id=12345678,
                api_hash="0123456789abcdef0123456789abcdef",
                session_path_override=str(session_path),
            )
            local = MagicMock()
            local.configured = True
            local.authorized_user = {"id": 1}
            client = FakeLogoutClient()
            with (
                patch.object(LocalSettings, "load_effective", return_value=effective),
                patch.object(LocalSettings, "load", return_value=local),
                patch.object(
                    TelegramAuthManager,
                    "_new_client",
                    AsyncMock(return_value=client),
                ),
            ):
                result = await TelegramAuthManager().reset()

        self.assertFalse(session_file.exists())
        local.clear_telegram_identity.assert_called_once_with()
        self.assertTrue(result["removed"]["credentials"])
        self.assertEqual(result["removed"]["session_files"], ["first_user.session"])
        self.assertEqual(result["remote_logout"], "revoked")

    async def test_reset_keeps_local_data_when_remote_logout_fails(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            session_path = Path(root) / "first_user"
            session_file = Path(f"{session_path}.session")
            session_file.write_text("session", encoding="utf-8")
            effective = LocalSettings(
                api_id=12345678,
                api_hash="0123456789abcdef0123456789abcdef",
                session_path_override=str(session_path),
            )
            local = MagicMock()
            client = FakeLogoutClient(logout_result=False)
            with (
                patch.object(LocalSettings, "load_effective", return_value=effective),
                patch.object(LocalSettings, "load", return_value=local),
                patch.object(
                    TelegramAuthManager,
                    "_new_client",
                    AsyncMock(return_value=client),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "не подтвердил"):
                    await TelegramAuthManager().reset()
            self.assertTrue(session_file.exists())

        local.clear_telegram_identity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
