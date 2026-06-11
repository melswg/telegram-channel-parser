"""Ignored local settings used by the single-user Web application."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = Path(
    os.getenv("TELEGRAM_IMPORTER_LOCAL_DIR", str(PROJECT_ROOT / ".local"))
).expanduser()
CONFIG_PATH = LOCAL_DIR / "config.json"
SESSIONS_DIR = LOCAL_DIR / "sessions"
DEFAULT_SAVE_DIR = PROJECT_ROOT / "data" / "parsed"

SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
FORBIDDEN_STORAGE_ROOTS = tuple(
    Path(path).resolve()
    for path in (
        "/",
        "/Applications",
        "/Library",
        "/System",
        "/bin",
        "/etc",
        "/sbin",
        "/usr",
        "/var",
    )
)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}…{value[-4:]}"


def mask_phone(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 5:
        return "•••••"
    return f"{value[:2]}{'•' * max(len(value) - 5, 3)}{value[-3:]}"


def validate_session_name(value: str) -> str:
    value = (value or "telegram_importer").strip()
    if not SESSION_RE.fullmatch(value):
        raise ValueError(
            "Имя session может содержать только буквы, цифры, точку, дефис и подчёркивание."
        )
    return value


def validate_save_dir(value: str, create: bool = True) -> Path:
    raw = (value or str(DEFAULT_SAVE_DIR)).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()

    for root in FORBIDDEN_STORAGE_ROOTS:
        if path == root or (root != Path("/") and root in path.parents):
            raise ValueError(f"Нельзя сохранять результаты в системную директорию: {path}")

    if create:
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise ValueError(f"Нет прав на запись в директорию: {path}")
    return path


@dataclass
class LocalSettings:
    api_id: int | None = None
    api_hash: str = ""
    session_name: str = "telegram_importer"
    save_dir: str = str(DEFAULT_SAVE_DIR)
    authorized_user: dict[str, Any] | None = None
    session_path_override: str = ""
    ignore_env_credentials: bool = False

    @classmethod
    def load(cls) -> "LocalSettings":
        if not CONFIG_PATH.exists():
            return cls()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        return cls(
            api_id=data.get("api_id"),
            api_hash=str(data.get("api_hash") or ""),
            session_name=validate_session_name(data.get("session_name") or "telegram_importer"),
            save_dir=str(data.get("save_dir") or DEFAULT_SAVE_DIR),
            authorized_user=data.get("authorized_user"),
            ignore_env_credentials=bool(data.get("ignore_env_credentials", False)),
        )

    @classmethod
    def load_effective(cls) -> "LocalSettings":
        """Use ignored Web config first, then fall back to .env/environment."""
        local = cls.load()
        if local.configured or local.ignore_env_credentials:
            return local

        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        api_id = os.getenv("API_ID", "")
        api_hash = os.getenv("API_HASH", "")
        if not api_id or not api_hash:
            return local
        try:
            parsed_api_id = int(api_id)
        except ValueError:
            return local

        session_name = validate_session_name(
            os.getenv("SESSION_NAME", "telegram_importer")
        )
        session_base = Path(os.getenv("SESSION_NAME", session_name)).expanduser()
        if not session_base.is_absolute():
            session_base = PROJECT_ROOT / session_base
        return cls(
            api_id=parsed_api_id,
            api_hash=api_hash,
            session_name=session_name,
            save_dir=os.getenv("PARSED_DIR", local.save_dir),
            authorized_user=local.authorized_user,
            session_path_override=str(session_base),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    @property
    def session_path(self) -> str:
        if self.session_path_override:
            return self.session_path_override
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        return str(SESSIONS_DIR / validate_session_name(self.session_name))

    @property
    def session_file(self) -> Path:
        return Path(f"{self.session_path}.session")

    def public_dict(self) -> dict[str, Any]:
        user = dict(self.authorized_user or {})
        if user.get("phone"):
            user["phone"] = mask_phone(str(user["phone"]))
        return {
            "configured": self.configured,
            "api_id_masked": "••••••••" if self.api_id else "",
            "api_hash_masked": mask_secret(self.api_hash),
            "session_name": self.session_name,
            "session_exists": self.session_file.exists(),
            "save_dir": str(validate_save_dir(self.save_dir, create=False)),
            "user": user or None,
        }

    def private_dict(self) -> dict[str, Any]:
        return {
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "session_name": self.session_name,
            "session_path": str(self.session_file),
            "save_dir": str(validate_save_dir(self.save_dir, create=False)),
            "user": self.authorized_user,
        }

    def save(self) -> None:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "session_name": validate_session_name(self.session_name),
            "save_dir": str(validate_save_dir(self.save_dir)),
            "authorized_user": self.authorized_user,
            "ignore_env_credentials": self.ignore_env_credentials,
        }
        temp_path = CONFIG_PATH.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        temp_path.replace(CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)

    def update_credentials(self, api_id: int, api_hash: str, session_name: str) -> None:
        if api_id <= 0:
            raise ValueError("api_id должен быть положительным числом.")
        api_hash = api_hash.strip()
        if len(api_hash) < 16:
            raise ValueError("api_hash выглядит слишком коротким.")
        next_session = validate_session_name(session_name)
        credentials_changed = (
            self.api_id != api_id
            or self.api_hash != api_hash
            or self.session_name != next_session
        )
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = next_session
        self.ignore_env_credentials = False
        if credentials_changed:
            self.authorized_user = None
        self.save()

    def clear_telegram_identity(self) -> None:
        """Remove login data while retaining non-identity local preferences."""
        self.api_id = None
        self.api_hash = ""
        self.session_name = "telegram_importer"
        self.authorized_user = None
        self.session_path_override = ""
        self.ignore_env_credentials = True
        self.save()

    def update_save_dir(self, value: str) -> None:
        self.save_dir = str(validate_save_dir(value))
        self.save()
