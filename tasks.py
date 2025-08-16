from __future__ import annotations

import asyncio
import datetime
from typing import Optional

from discord import TextChannel

# Absolute imports from sibling modules. These allow running this module
# directly without requiring a package structure.
from config import ADMIN_CHANNEL_ID, POST_CHANNEL_ID
from discord_bot import (
    bot,
    send_moderation_message,
    get_all_recent_bot_article_urls,
)
from news import fetch_article, available_queries, used_queries
from state import unactioned_articles, unactioned_articles_lock


async def fetch_and_post_articles() -> None:
    while True:
        now = datetime.datetime.now()
        current_hour = now.hour

        # Active hours: 9 AM to 7 PM (09:00–22:00)
        if 9 <= current_hour < 22:
            admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
            if admin_channel is None or not isinstance(admin_channel, TextChannel):
                print(
                    "❌ ERROR: ADMIN_CHANNEL_ID is invalid or the bot has no access to it."
                )
                await list_accessible_text_channels()
                # Wait 30 minutes before retrying
                await asyncio.sleep(1800)
                continue

            # Determine which article URLs have been posted recently to avoid duplicates
            recent_urls = await get_all_recent_bot_article_urls(admin_channel)
            article_post = await fetch_article(recent_urls)
            if article_post:
                # Add article to the unactioned list
                async with unactioned_articles_lock:
                    unactioned_articles.append(article_post)
                    print(
                        f"🆕 New article added for moderation: {article_post.get('title')} ({article_post.get('link')})"
                    )
                    print("📋 Current articles awaiting approval:")
                    for idx, article in enumerate(unactioned_articles, start=1):
                        print(f"  {idx}. {article.get('title')} ({article.get('link')})")
                # Send to admin channel for review
                await send_moderation_message(article_post)
            else:
                print("❌ No new articles found or API rate limit reached.")
        else:
            print(
                f"⏳ Outside active hours (9 AM to 7 PM). Current time: {now.strftime('%H:%M')}"
            )

        # Sleep logic: if outside active hours, sleep until the next 9 AM
        if current_hour >= 22 or current_hour < 9:
            # Compute next day's 9 AM
            tomorrow = now + datetime.timedelta(days=1)
            next_morning = datetime.datetime(
                tomorrow.year, tomorrow.month, tomorrow.day, 9, 0
            )
            sleep_seconds = (next_morning - now).total_seconds()
            hours = int(sleep_seconds // 3600)
            minutes = int((sleep_seconds % 3600) // 60)
            print(
                f"🌙 Sleeping until 9 AM. Resuming in {hours} hours and {minutes} minutes."
            )
            while sleep_seconds > 0:
                await asyncio.sleep(min(60, sleep_seconds))
                sleep_seconds -= 60
                now = datetime.datetime.now()
                if 9 <= now.hour < 22:
                    break
        else:
            await asyncio.sleep(1800)


async def reset_queries_every_morning() -> None:
    while True:
        now = datetime.datetime.now()
        current_hour = now.hour
        if current_hour == 9:
            print("🌅 Resetting queries for the new day.")
            available_queries.extend(used_queries)
            used_queries.clear()
        await asyncio.sleep(3600)


async def check_channel_perms(channel_id: int, label: str) -> None:
    ch = bot.get_channel(channel_id)
    if not ch:
        print(
            f"❌ {label}: channel not found for ID {channel_id}. Is the bot in the same server and allowed to view it?"
        )
        return
    guild = ch.guild
    if not guild:
        print(f"❌ {label}: cannot resolve guild for channel {channel_id}")
        return
    me = guild.me
    if not me:
        print(f"❌ {label}: cannot resolve bot member in guild {guild.id}")
        return
    p = ch.permissions_for(me)
    required = {
        "view_channel": p.view_channel,
        "send_messages": p.send_messages,
        "embed_links": p.embed_links,
        "read_message_history": p.read_message_history,
    }
    if all(required.values()):
        print(
            f"✅ {label}: permissions OK in #{getattr(ch, 'name', 'unknown')} (guild: {guild.name} / {guild.id})"
        )
    else:
        missing = ", ".join([k for k, v in required.items() if not v])
        print(
            f"⚠️ {label}: missing permissions in #{getattr(ch, 'name', 'unknown')} "
            f"(guild: {guild.name} / {guild.id}) -> {missing}"
        )


async def list_accessible_text_channels() -> None:
    print("\n🔎 Listing accessible text channels per guild (first 50):")
    for g in bot.guilds:
        print(f"- Guild: {g.name} / {g.id}")
        count = 0
        for ch in g.text_channels:
            me = g.me
            if not me:
                print(f"❌ cannot resolve bot member in guild {g.id}")
                break
            p = ch.permissions_for(me)
            if p.view_channel:
                print(f"  - #{ch.name} (ID: {ch.id})")
                count += 1
            if count >= 50:
                break
        if count == 0:
            print("  No accessible text channels found.")