# Uses LM Studio's OpenAI-compatible /v1/chat/completions for summarization.
import sys
import json
import os
import discord
from discord.ext import commands
import requests
import asyncio
import datetime
import random
import traceback

# Load .env if present (optional dependency)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ------------------------------------
# Configuration and bot setup
# ------------------------------------

TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_CHANNEL_ID = 1404206314267217940
POST_CHANNEL_ID = 1304160017917808783
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Fail fast if token missing
if not TOKEN or not isinstance(TOKEN, str) or not TOKEN.strip():
    print("❌ ERROR: DISCORD_TOKEN is not set. Set it in your environment or a .env file.")
    print("   Example (macOS/Linux): export DISCORD_TOKEN=\"<your-bot-token>\"")
    print("   Or create a .env file with: DISCORD_TOKEN=<your-bot-token>")
    sys.exit(1)

# LM Studio configuration
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://100.67.152.225:9999")
LMSTUDIO_MODEL    = os.getenv("LMSTUDIO_MODEL", "qwen2.5-7b-instruct-mlx")
LMSTUDIO_API_KEY  = os.getenv("LMSTUDIO_API_KEY", "")
LMSTUDIO_TIMEOUT  = int(os.getenv("LMSTUDIO_TIMEOUT_SECS", "120"))

# LM Studio startup config log and tool toggle
print(f"LM Studio config → BASE: {LMSTUDIO_BASE_URL}  MODEL: {LMSTUDIO_MODEL}  TIMEOUT: {LMSTUDIO_TIMEOUT}s")
LM_USE_TOOLS = os.getenv("LM_USE_TOOLS", "0") in ("1", "true", "True")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

unactioned_articles = []  # List to store unactioned articles
unactioned_articles_lock = asyncio.Lock()  # Lock to manage access to the list

# ------------------------------------
# LM Studio summarization helper
# ------------------------------------

def lmstudio_models():
    try:
        url = f"{LMSTUDIO_BASE_URL.rstrip('/')}/v1/models"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        print("LM Studio /v1/models →", ids)
        return ids
    except Exception as e:
        print(f"⚠️ Could not reach LM Studio /v1/models: {e}")
        return []


def safe_json_parse(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None



# ---- Structured Output helpers ----
def build_news_schema():
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 5
            },
            "why_it_matters": {"type": "string"}
        },
        "required": ["title", "key_points", "why_it_matters"],
        "additionalProperties": False
    }


def looks_like_instruct_model(model_id: str) -> bool:
    m = model_id.lower()
    if "instruct" in m:
        return True
    return any(x in m for x in ["qwen", "mistral", "llama", "phi", "gemma"]) and not any(y in m for y in ["r1", "reasoning"])


def summarize_with_lmstudio(article: dict) -> dict | None:
    """Try JSON Schema structured output first; fall back to tool-calls, then plain-JSON."""
    # Preflight: is model present and instruct-like?
    models = lmstudio_models()
    if models and LMSTUDIO_MODEL not in models:
        print(f"⚠️ Requested model '{LMSTUDIO_MODEL}' not in /v1/models. Use an exact id from the list above.")
    if not looks_like_instruct_model(LMSTUDIO_MODEL):
        print("ℹ️ Hint: prefer an *instruct* model for structured output (e.g., qwen2.5-7b-instruct-mlx, llama-3.1-8b-instruct-mlx).")

    endpoint = f"{LMSTUDIO_BASE_URL.rstrip('/')}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    if LMSTUDIO_API_KEY:
        headers["Authorization"] = f"Bearer {LMSTUDIO_API_KEY}"

    desc = (article.get("summary") or "").strip()
    title = (article.get("title") or "").strip()
    src = (article.get("source") or "").strip()
    url = (article.get("link") or "").strip()

    user_prompt = (
        f"Source: {src}\nURL: {url}\nTitle: {title}\n\n"
        f"Description snippet (may be partial):\n{desc[:2000]}"
    )

    # 1) JSON Schema structured output (preferred)
    schema_payload = {
        "model": LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": "Return only what the schema requires."},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "NewsSummary",
                "schema": build_news_schema(),
                "strict": True
            }
        }
    }

    try:
        r = requests.post(endpoint, headers=headers, json=schema_payload, timeout=LMSTUDIO_TIMEOUT)
        if r.status_code in (400, 404, 415, 422, 500):
            print(f"ℹ️ JSON Schema mode not accepted (HTTP {r.status_code}). Falling back.")
        else:
            r.raise_for_status()
            data = r.json()
            msg = (data.get("choices") or [{}])[0].get("message", {})
            parsed = msg.get("parsed")
            if isinstance(parsed, dict) and parsed.get("title"):
                return parsed
            content = (msg.get("content") or "").strip()
            parsed2 = safe_json_parse(content)
            if isinstance(parsed2, dict) and parsed2.get("title"):
                return parsed2
            print("ℹ️ JSON Schema mode returned no parsed object; falling back.")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Cannot connect to LM Studio at {LMSTUDIO_BASE_URL}: {e}")
        return None
    except Exception as e:
        print(f"ℹ️ JSON Schema attempt failed: {e}. Falling back.")

    # 2) Tool/function calling (optional)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "summarize_article",
                "description": "Summarize a news article for Discord in a structured way.",
                "parameters": build_news_schema()
            }
        }
    ]

    payload = {
        "model": LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": "You are a crisp news summarizer for a Discord channel."},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }

    if LM_USE_TOOLS:
        payload["tools"] = tools
        payload["tool_choice"] = {"type": "function", "function": {"name": "summarize_article"}}

    try:
        r2 = requests.post(endpoint, headers=headers, json=payload, timeout=LMSTUDIO_TIMEOUT)
        r2.raise_for_status()
        data2 = r2.json()
        msg2 = (data2.get("choices") or [{}])[0].get("message", {})
        content = (msg2.get("content") or "").strip()
        parsed = safe_json_parse(content)
        if isinstance(parsed, dict) and parsed.get("title"):
            return parsed
        tool_calls = msg2.get("tool_calls") or []
        if tool_calls:
            try:
                arguments = tool_calls[0]["function"]["arguments"]
                parsed2 = safe_json_parse(arguments)
                if isinstance(parsed2, dict) and parsed2.get("title"):
                    return parsed2
            except Exception as e:
                print(f"⚠️ Failed to parse tool call arguments: {e}")
    except Exception as e:
        print(f"ℹ️ Tool/JSON fallback attempt failed: {e}")

    # 3) Plain JSON instruction (no tools)
    try:
        plain = {
            "model": LMSTUDIO_MODEL,
            "messages": [
                {"role": "system", "content": "Return ONLY a compact JSON object with keys: title (string), key_points (array of 3 short strings), why_it_matters (string)."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        r3 = requests.post(endpoint, headers=headers, json=plain, timeout=LMSTUDIO_TIMEOUT)
        r3.raise_for_status()
        data3 = r3.json()
        msg3 = (data3.get("choices") or [{}])[0].get("message", {})
        content3 = (msg3.get("content") or "").strip()
        parsed3 = safe_json_parse(content3)
        if isinstance(parsed3, dict) and parsed3.get("title"):
            return parsed3
    except Exception as e:
        print(f"⚠️ Plain JSON fallback failed: {e}")

    print("⚠️ No structured output from LM Studio after all attempts.")
    return None


def load_topics_from_file(file_path="topics.txt"):
    try:
        with open(file_path, "r") as file:
            topics = [line.strip() for line in file if line.strip()]  # Remove empty lines
        print(f"✅ Loaded {len(topics)} topics from {file_path}.")
        return topics
    except FileNotFoundError:
        print(f"❌ ERROR: {file_path} not found. Please create the file and add topics.")
        return []
    
available_queries = load_topics_from_file()
used_queries = []  # List to store queries that have been used successfully

# Fetch a news article from NewsAPI
async def fetch_article(recent_urls):
    global available_queries, used_queries

    # Reset queries if no available queries remain
    if not available_queries:
        print("🔄 No available queries left. Resetting queries...")
        available_queries.extend(used_queries)
        used_queries.clear()
        print(f"✅ Queries reset. {len(available_queries)} queries are now available.")

    # Shuffle the available queries to randomize the order
    random.shuffle(available_queries)

    api_url = "https://newsapi.org/v2/everything"
    params = {
        "apiKey": NEWS_API_KEY,
        "language": "en",
        "pageSize": 1  # Limit to 1 article
    }

    for query in available_queries:
        params["q"] = query  # Set the query parameter
        try:
            print(f"Fetching articles for query: {query} from: {api_url}")
            response = requests.get(api_url, params=params)
            if response.status_code == 429:
                print("❌ ERROR: API rate limit reached (429). Entering a wait state.")
                await handle_api_limit()
                return None  # Gracefully exit the function
            response.raise_for_status()
            data = response.json()
            if data["articles"]:
                article = data["articles"][0]
                if article["url"] in recent_urls:
                    print(f"⚠️ Skipping previously posted article: {article['url']}")
                    continue

                # Move the query to the used_queries list
                available_queries.remove(query)
                used_queries.append(query)
                result = {
                    "title": article["title"],
                    "source": article["source"]["name"],
                    "summary": article.get("description") or "No description available.",
                    "link": article["url"],
                }

                # Ask LM Studio for a concise, Discord-friendly summary; fall back to description on failure
                lm_summary = summarize_with_lmstudio(result)
                if lm_summary:
                    result["summary"] = lm_summary
                else:
                    print("ℹ️ Using NewsAPI description as summary (LM Studio unavailable or failed).")

                return result
            else:
                print(f"❌ No articles found for query: {query}. Trying next query...")
        except Exception as e:
            print(f"❌ ERROR: Failed to fetch article for query: {query}: {e}")

    print("❌ No articles found for any query.")
    return None

async def handle_api_limit():
    print("⏳ Waiting for API rate limit to reset...")
    # Wait for 15 minutes (API rate limits typically reset within this time)
    sleep_seconds = 15 * 60  # 15 minutes
    while sleep_seconds > 0:
        await asyncio.sleep(min(60, sleep_seconds))  # Sleep for 1 minute at a time
        sleep_seconds -= 60
        print(f"⏳ Still waiting for API rate limit to reset... {sleep_seconds // 60} minutes remaining.")
    print("✅ Resuming article fetching after API rate limit reset.")

async def get_all_recent_bot_article_urls(channel):
    urls = set()
    async for message in channel.history(limit=50):  # Scan the last 50 messages
        if message.author == bot.user and message.embeds:
            for embed in message.embeds:
                for field in embed.fields:
                    if field.name == "Link":
                        urls.add(field.value)
    return urls

async def fetch_and_post_articles():
    global unactioned_articles
    while True:
        # Get the current time
        now = datetime.datetime.now()
        current_hour = now.hour

        # Check if the current time is between 9 AM and 7 PM
        if 9 <= current_hour < 23:  # 9 AM to 7 PM
            admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
            if admin_channel is None:
                print("❌ ERROR: ADMIN_CHANNEL_ID is invalid or the bot has no access to it.")
                print("   → Check the console above for the channel list and pick the correct ID.")
                print("   → Ensure the bot was invited to THIS server and has View Channel permission.")
                await list_accessible_text_channels()
                await asyncio.sleep(1800)  # Wait 30 minutes before retrying
                continue

            recent_urls = await get_all_recent_bot_article_urls(admin_channel)
            article_post = await fetch_article(recent_urls)
            if article_post:
                async with unactioned_articles_lock:
                    unactioned_articles.append(article_post)  # Add to unactioned articles
                    print(f"🆕 New article added for moderation: {article_post['title']} ({article_post['link']})")
                    print("📋 Current articles awaiting approval:")
                    for idx, article in enumerate(unactioned_articles, start=1):
                        print(f"  {idx}. {article['title']} ({article['link']})")
                await send_moderation_message(article_post)
            else:
                print("❌ No new articles found or API rate limit reached.")
        else:
            print(f"⏳ Outside active hours (9 AM to 7 PM). Current time: {now.strftime('%H:%M')}")

        # If outside active hours or rate limit is hit, calculate sleep time until 9 AM
        if current_hour >= 19 or current_hour < 9:
            tomorrow = now + datetime.timedelta(days=1)
            next_morning = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 9, 0)
            sleep_seconds = (next_morning - now).total_seconds()
            print(f"🌙 Sleeping until 9 AM. Resuming in {int(sleep_seconds // 3600)} hours and {int((sleep_seconds % 3600) // 60)} minutes.")
            
            # Non-blocking sleep loop
            while sleep_seconds > 0:
                await asyncio.sleep(min(60, sleep_seconds))  # Sleep for 1 minute at a time
                sleep_seconds -= 60
                now = datetime.datetime.now()
                if 9 <= now.hour < 19:  # If it's within active hours, break early
                    break
        else:
            # Wait 30 minutes before checking again
            await asyncio.sleep(1800)

async def send_moderation_message(article):
    channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if channel is None:
        print("❌ ERROR: ADMIN_CHANNEL_ID is invalid or the bot has no access to it.")
        return

    summary = article["summary"]

    # Determine the title (prefer structured summary title if available)
    title_text = summary.get("title") if isinstance(summary, dict) and summary.get("title") else article.get("title", "")

    if isinstance(summary, dict):
        bullets = "\n".join(f"- {pt}" for pt in summary.get("key_points", []))
        description = bullets
        embed = discord.Embed(title=title_text[:256], description=description[:4000])
        embed.add_field(name="Source", value=article["source"])\
             .add_field(name="Link", value=article["link"], inline=False)
        if summary.get("why_it_matters"):
            embed.add_field(name="Why it matters", value=summary["why_it_matters"], inline=False)
    else:
        embed = discord.Embed(title=title_text[:256], description=str(summary)[:4000])
        embed.add_field(name="Source", value=article["source"])\
             .add_field(name="Link", value=article["link"], inline=False)

    view = ArticleModerationView(article)
    await channel.send("New article for review:", embed=embed, view=view)

class ArticleModerationView(discord.ui.View):
    def __init__(self, article):
        super().__init__()
        self.article = article

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        global unactioned_articles
        # Send an immediate acknowledgment to avoid timeout
        await interaction.response.defer(ephemeral=True)

        async with unactioned_articles_lock:
            if self.article in unactioned_articles:
                unactioned_articles.remove(self.article)  # Remove from unactioned articles
                print(f"✅ Article approved by {interaction.user.name}: {self.article['title']} ({self.article['link']})")
            else:
                await interaction.followup.send("⚠️ This article has already been moderated or is no longer available.", ephemeral=True)
                return

        await interaction.followup.send(f"Accepted ✅ by {interaction.user.name}. Posting now...", ephemeral=True)
        original_message = interaction.message
        await original_message.edit(content=f"✅ Accepted and posted by {interaction.user.name}!", view=None)
        await post_to_public_channel(self.article)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        global unactioned_articles
        # Send an immediate acknowledgment to avoid timeout
        await interaction.response.defer(ephemeral=True)

        async with unactioned_articles_lock:
            if self.article in unactioned_articles:
                unactioned_articles.remove(self.article)  # Remove from unactioned articles
                print(f"❌ Article rejected by {interaction.user.name}: {self.article['title']} ({self.article['link']})")
            else:
                await interaction.followup.send("⚠️ This article has already been moderated or is no longer available.", ephemeral=True)
                return

        await interaction.followup.send(f"Rejected ❌ by {interaction.user.name}.", ephemeral=True)
        original_message = interaction.message
        await original_message.edit(content=f"❌ Rejected by {interaction.user.name}.", view=None)

async def post_to_public_channel(article):
    channel = bot.get_channel(POST_CHANNEL_ID)
    if channel is None:
        print("❌ ERROR: POST_CHANNEL_ID is invalid or the bot has no access to it.")
        return

    summary = article["summary"]

    # Determine the title (prefer structured summary title if available)
    title_text = summary.get("title") if isinstance(summary, dict) and summary.get("title") else article.get("title", "")

    if isinstance(summary, dict):
        bullets = "\n".join(f"- {pt}" for pt in summary.get("key_points", []))
        description = bullets
        embed = discord.Embed(title=title_text[:256], description=description[:4000])
        embed.add_field(name="Source", value=article["source"])\
             .add_field(name="Link", value=article["link"], inline=False)
        if summary.get("why_it_matters"):
            embed.add_field(name="Why it matters", value=summary["why_it_matters"], inline=False)
    else:
        embed = discord.Embed(title=title_text[:256], description=str(summary)[:4000])
        embed.add_field(name="Source", value=article["source"])\
             .add_field(name="Link", value=article["link"], inline=False)

    await channel.send(embed=embed)

async def reset_queries_every_morning():
    global available_queries, used_queries
    while True:
        now = datetime.datetime.now()
        current_hour = now.hour

        # Check if it's 9 AM
        if current_hour == 9:
            print("🌅 Resetting queries for the new day.")
            available_queries.extend(used_queries)
            used_queries.clear()

        # Sleep for 1 hour before checking again
        await asyncio.sleep(3600)

async def check_channel_perms(channel_id: int, label: str):
    ch = bot.get_channel(channel_id)
    if not ch:
        print(f"❌ {label}: channel not found for ID {channel_id}. Is the bot in the same server and allowed to view it?")
        return
    me = ch.guild.me
    if not me:
        print(f"❌ {label}: cannot resolve bot member in guild {ch.guild.id}")
        return
    p = ch.permissions_for(me)
    required = {
        "view_channel": p.view_channel,
        "send_messages": p.send_messages,
        "embed_links": p.embed_links,
        "read_message_history": p.read_message_history,
    }
    if all(required.values()):
        print(f"✅ {label}: permissions OK in #{ch.name} (guild: {ch.guild.name} / {ch.guild.id})")
    else:
        missing = ", ".join([k for k, v in required.items() if not v])
        print(f"⚠️ {label}: missing permissions in #{ch.name} (guild: {ch.guild.name} / {ch.guild.id}) -> {missing}")

async def list_accessible_text_channels():
    print("\n🔎 Listing accessible text channels per guild (first 50):")
    for g in bot.guilds:
        print(f"- Guild: {g.name} / {g.id}")
        count = 0
        for ch in g.text_channels:
            me = g.me  # FIXED: was g.guild.me
            if not me:
                print(f"❌ cannot resolve bot member in guild {g.id}")
                continue
            p = ch.permissions_for(me)
            if p.view_channel:
                print(f"  - #{ch.name} (ID: {ch.id})")
                count += 1
            if count >= 50:
                break  # Limit to 50 channels per guild
        if count == 0:
            print("  No accessible text channels found.")

if __name__ == "__main__":
    @bot.event
    async def on_ready():
        print(f"✅ Bot is ready! Logged in as {bot.user}")
        # LM Studio preflight
        lmstudio_models()
        await list_accessible_text_channels()
        await check_channel_perms(ADMIN_CHANNEL_ID, "Admin channel")
        await check_channel_perms(POST_CHANNEL_ID, "Public channel")
        bot.loop.create_task(fetch_and_post_articles())
        bot.loop.create_task(reset_queries_every_morning())

    bot.run(TOKEN)