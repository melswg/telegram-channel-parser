"""Configuration loader from environment or the local Web UI config."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    """Application configuration."""
    # Telegram
    api_id: int
    api_hash: str
    session_name: str = "telegram_importer"

    # Channels list
    channels: list = field(default_factory=list)

    # Whisper
    whisper_model: str = "base"
    whisper_language: Optional[str] = None  # None = auto-detect

    # Paths
    db_path: str = "db.sqlite3"
    media_dir: str = "data/media"
    export_dir: str = "data/exports"

    def ensure_dirs(self):
        """Create required directories."""
        Path(self.media_dir).mkdir(parents=True, exist_ok=True)
        Path(self.export_dir).mkdir(parents=True, exist_ok=True)


def load_config(env_path: Optional[str] = None) -> Config:
    """Load config from environment, .env, or the ignored local config."""
    from dotenv import load_dotenv
    from .local_settings import LocalSettings

    if env_path:
        load_dotenv(env_path, override=True)
    else:
        # Try .env in CWD and parent directories
        cwd = Path.cwd()
        for p in [cwd, cwd.parent, Path.home()]:
            test = p / ".env"
            if test.exists():
                load_dotenv(test, override=True)
                break

    local = LocalSettings.load_effective()
    api_id_str = os.getenv("API_ID", "") or str(local.api_id or "")
    api_hash = os.getenv("API_HASH", "") or local.api_hash

    if not api_id_str or not api_hash:
        raise ValueError(
            "API_ID and API_HASH must be set in .env file or environment.\n"
            "Get yours at https://my.telegram.org/apps"
        )

    api_id = int(api_id_str)

    channels_raw = os.getenv("CHANNELS", "")
    channels = [c.strip() for c in channels_raw.split(",") if c.strip()]

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        session_name=local.session_path,
        channels=channels,
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_language=os.getenv("WHISPER_LANGUAGE") or None,
        db_path=os.getenv("DB_PATH", "db.sqlite3"),
        media_dir=os.getenv("MEDIA_DIR", "data/media"),
        export_dir=os.getenv("EXPORT_DIR", "data/exports"),
    )
