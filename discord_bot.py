
from __future__ import annotations

import discord
from discord.ext import commands
from typing import Dict, Iterable, Set

# Import configuration and state via absolute imports. Absolute imports
# allow the module to be executed without being part of a package.
from config import ADMIN_CHANNEL_ID, POST_CHANNEL_ID
from state import unactioned_articles, unactioned_articles_lock

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

# Create a global bot instance. Other modules import this to
# schedule tasks and access Discord API functionality.
bot = commands.Bot(command_prefix="!", intents=intents)


async def get_all_recent_bot_article_urls(channel: discord.TextChannel) -> Set[str]:
    """The bot scans the last 50 messages in the given channel and
    collects links. Avoids picking up duplicates.
    """
    urls: Set[str] = set()
    async for message in channel.history(limit=50):
        if message.author == bot.user and message.embeds:
            for embed in message.embeds:
                for field in embed.fields:
                    if field.name == "Link":
                        urls.add(str(field.value))
    return urls


async def send_moderation_message(article: Dict[str, object]) -> None:
    # Sends a message to the admin channel for moderation

    channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        print("❌ ERROR: ADMIN_CHANNEL_ID is invalid or the bot has no access to it.")
        return

    summary = article.get("summary")
    title_fallback = str(article.get("title", ""))

    # Determine the title: prefer structured summary title if available
    if isinstance(summary, dict) and summary.get("title"):
        title_text = str(summary.get("title"))
    else:
        title_text = title_fallback

    # Build the embed based on whether we have a structured summary
    if isinstance(summary, dict):
        key_points = summary.get("key_points", [])
        bullets = "\n".join(f"- {pt}" for pt in key_points)
        description = bullets
        embed = discord.Embed(title=title_text[:256], description=description[:4000])
        embed.add_field(name="Source", value=str(article.get("source", "")))
        embed.add_field(name="Link", value=str(article.get("link", "")), inline=False)
        why = summary.get("why_it_matters")
        if why:
            embed.add_field(name="Why it matters", value=str(why), inline=False)
    else:
        embed = discord.Embed(title=title_text[:256], description=str(summary)[:4000])
        embed.add_field(name="Source", value=str(article.get("source", "")))
        embed.add_field(name="Link", value=str(article.get("link", "")), inline=False)

    view = ArticleModerationView(article)
    await channel.send("New article for review:", embed=embed, view=view)


async def post_to_public_channel(article: Dict[str, object]) -> None:
    # Post an approved article to the public channel

    channel = bot.get_channel(POST_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        print("❌ ERROR: POST_CHANNEL_ID is invalid or the bot has no access to it.")
        return

    summary = article.get("summary")
    title_fallback = str(article.get("title", ""))
    if isinstance(summary, dict) and summary.get("title"):
        title_text = str(summary.get("title"))
    else:
        title_text = title_fallback

    if isinstance(summary, dict):
        bullets = "\n".join(f"- {pt}" for pt in summary.get("key_points", []))
        description = bullets
        embed = discord.Embed(title=title_text[:256], description=description[:4000])
        embed.add_field(name="Source", value=str(article.get("source", "")))
        embed.add_field(name="Link", value=str(article.get("link", "")), inline=False)
        why = summary.get("why_it_matters")
        if why:
            embed.add_field(name="Why it matters", value=str(why), inline=False)
    else:
        embed = discord.Embed(title=title_text[:256], description=str(summary)[:4000])
        embed.add_field(name="Source", value=str(article.get("source", "")))
        embed.add_field(name="Link", value=str(article.get("link", "")), inline=False)

    await channel.send(embed=embed)


class ArticleModerationView(discord.ui.View):
    # Interactive view for moderators to accept or reject articles.

    def __init__(self, article: Dict[str, object]) -> None:
        super().__init__()
        self.article = article

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        # Acknowledge the interaction immediately to avoid timeouts
        await interaction.response.defer(ephemeral=True)

        # Remove the article from the unactioned list under lock
        async with unactioned_articles_lock:
            if self.article in unactioned_articles:
                unactioned_articles.remove(self.article)
                print(
                    f"✅ Article approved by {interaction.user.name}: {self.article.get('title')} ({self.article.get('link')})"
                )
            else:
                await interaction.followup.send(
                    "⚠️ This article has already been moderated or is no longer available.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"Accepted ✅ by {interaction.user.name}. Posting now...",
            ephemeral=True,
        )
        # Remove the buttons from the original message
        original_message = interaction.message
        if original_message:
            await original_message.edit(content=f"✅ Accepted and posted by {interaction.user.name}!", view=None)
        # Post to the public channel
        await post_to_public_channel(self.article)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        await interaction.response.defer(ephemeral=True)
        async with unactioned_articles_lock:
            if self.article in unactioned_articles:
                unactioned_articles.remove(self.article)
                print(
                    f"❌ Article rejected by {interaction.user.name}: {self.article.get('title')} ({self.article.get('link')})"
                )
            else:
                await interaction.followup.send(
                    "⚠️ This article has already been moderated or is no longer available.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"Rejected ❌ by {interaction.user.name}.",
            ephemeral=True,
        )
        # Remove the buttons from the original message
        original_message = interaction.message
        if original_message:
            await original_message.edit(content=f"❌ Rejected by {interaction.user.name}.", view=None)
