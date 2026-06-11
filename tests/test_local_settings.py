import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.local_settings import (
    LocalSettings,
    mask_phone,
    validate_save_dir,
)


class StoragePathTests(unittest.TestCase):
    def test_safe_path_is_created(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            path = validate_save_dir(f"{root}/parsed")
            self.assertTrue(path.is_dir())

    def test_system_paths_are_rejected(self):
        for path in ("/", "/etc/telegram-importer", "/usr/local/share/importer"):
            with self.assertRaises(ValueError):
                validate_save_dir(path, create=False)

    def test_public_settings_mask_sensitive_values(self):
        settings = LocalSettings(
            api_id=12345678,
            api_hash="fake_api_hash_for_local_testing_123",
            authorized_user={"username": "reader", "phone": "79991234567"},
        )
        public = settings.public_dict()
        self.assertEqual(public["api_id_masked"], "••••••••")
        self.assertNotIn("fake_api_hash", public["api_hash_masked"])
        self.assertNotEqual(public["user"]["phone"], "79991234567")

    def test_phone_mask(self):
        self.assertEqual(mask_phone("79991234567"), "79••••••567")

    def test_clear_identity_removes_credentials_and_preserves_storage(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            local_dir = Path(root) / ".local"
            config_path = local_dir / "config.json"
            sessions_dir = local_dir / "sessions"
            save_dir = Path(root) / "results"
            with (
                patch("app.local_settings.LOCAL_DIR", local_dir),
                patch("app.local_settings.CONFIG_PATH", config_path),
                patch("app.local_settings.SESSIONS_DIR", sessions_dir),
            ):
                settings = LocalSettings(
                    api_id=12345678,
                    api_hash="0123456789abcdef0123456789abcdef",
                    session_name="first_user",
                    save_dir=str(save_dir),
                    authorized_user={"id": 1, "phone": "79991234567"},
                )
                settings.save()
                settings.clear_telegram_identity()
                loaded = LocalSettings.load()

            self.assertFalse(loaded.configured)
            self.assertIsNone(loaded.authorized_user)
            self.assertEqual(loaded.session_name, "telegram_importer")
            self.assertEqual(Path(loaded.save_dir), save_dir.resolve())
            self.assertTrue(loaded.ignore_env_credentials)

    def test_full_logout_prevents_env_credentials_from_returning(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            local_dir = Path(root) / ".local"
            config_path = local_dir / "config.json"
            sessions_dir = local_dir / "sessions"
            with (
                patch("app.local_settings.LOCAL_DIR", local_dir),
                patch("app.local_settings.CONFIG_PATH", config_path),
                patch("app.local_settings.SESSIONS_DIR", sessions_dir),
                patch.dict(
                    os.environ,
                    {
                        "API_ID": "87654321",
                        "API_HASH": "fedcba9876543210fedcba9876543210",
                    },
                    clear=False,
                ),
            ):
                settings = LocalSettings(ignore_env_credentials=True)
                settings.save()
                effective = LocalSettings.load_effective()

            self.assertFalse(effective.configured)
            self.assertIsNone(effective.api_id)
            self.assertEqual(effective.api_hash, "")


if __name__ == "__main__":
    unittest.main()
