from __future__ import annotations

import asyncio

from config import (
    ensure_token,
    DISCORD_TOKEN,
    ADMIN_CHANNEL_ID,
    POST_CHANNEL_ID,
)
from lmstudio_helpers import lmstudio_models
from discord_bot import bot
from tasks import (
    fetch_and_post_articles,
    reset_queries_every_morning,
    check_channel_perms,
    list_accessible_text_channels,
)


def main() -> None:
    ensure_token()

    @bot.event
    async def on_ready() -> None:
        print(f"✅ Bot is ready! Logged in as {bot.user}")
        lmstudio_models()
        # List channels and check permissions
        await list_accessible_text_channels()
        await check_channel_perms(ADMIN_CHANNEL_ID, "Admin channel")
        await check_channel_perms(POST_CHANNEL_ID, "Public channel")
        # Schedule background tasks
        bot.loop.create_task(fetch_and_post_articles())
        bot.loop.create_task(reset_queries_every_morning())

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
