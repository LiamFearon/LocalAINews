from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

DISCORD_TOKEN: str | None = os.getenv("DISCORD_TOKEN")

_admin_id = os.getenv("ADMIN_CHANNEL_ID")
_post_id = os.getenv("POST_CHANNEL_ID")
ADMIN_CHANNEL_ID: int | None = int(_admin_id) if _admin_id else None
POST_CHANNEL_ID: int | None = int(_post_id) if _post_id else None

NEWS_API_KEY: str | None = os.getenv("NEWS_API_KEY")

LMSTUDIO_BASE_URL: str | None = os.getenv("LMSTUDIO_BASE_URL")
LMSTUDIO_MODEL: str | None = os.getenv("LMSTUDIO_MODEL")
LMSTUDIO_API_KEY: str | None = os.getenv("LMSTUDIO_API_KEY")

LMSTUDIO_TIMEOUT: int = int(os.getenv("LMSTUDIO_TIMEOUT_SECS", "120"))
LM_USE_TOOLS: bool = os.getenv("LM_USE_TOOLS", "0").lower() in {"1", "true", "yes", "on"}


def ensure_token() -> None:
    """Validate that the Discord bot token is present.

    Call this before attempting to start the bot. Exits with a clear error if
    the token is missing, rather than failing later during connection.
    """
    if not DISCORD_TOKEN or not isinstance(DISCORD_TOKEN, str) or not DISCORD_TOKEN.strip():
        print("❌ ERROR: DISCORD_TOKEN is not set. Set it in your environment or a .env file.")
        print("   Example (macOS/Linux): export DISCORD_TOKEN=\"<your-bot-token>\"")
        print("   Or create a .env file with: DISCORD_TOKEN=<your-bot-token>")
        sys.exit(1)


def ensure_required() -> None:
    """Fail fast if any required settings are missing.

    Use this at application startup (e.g., in main.py) alongside ensure_token().
    This avoids accidentally running with placeholder or missing values.
    """
    missing: list[str] = []
    if ADMIN_CHANNEL_ID is None:
        missing.append("ADMIN_CHANNEL_ID")
    if POST_CHANNEL_ID is None:
        missing.append("POST_CHANNEL_ID")
    if not LMSTUDIO_BASE_URL:
        missing.append("LMSTUDIO_BASE_URL")
    if not LMSTUDIO_MODEL:
        missing.append("LMSTUDIO_MODEL")

    if missing:
        print("❌ ERROR: Missing required config keys:", ", ".join(missing))
        print("   Add them to your .env or environment. See .env.example for placeholders.")
        sys.exit(1)