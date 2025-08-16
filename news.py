from __future__ import annotations

import asyncio
import random
import requests
from typing import Dict, List, Optional, Set

# Import dependencies with absolute names to allow running this
# module directly without a package context.
from config import NEWS_API_KEY
from lmstudio_helpers import summarize_with_lmstudio

available_queries: List[str] = []
used_queries: List[str] = []


def load_topics_from_file(file_path: str = "topics.txt") -> List[str]:
    # Load news topics from a text file.
    topics: List[str] = []
    try:
        with open(file_path, "r") as file:
            topics = [line.strip() for line in file if line.strip()]
        print(f"✅ Loaded {len(topics)} topics from {file_path}.")
    except FileNotFoundError:
        print(f"❌ ERROR: {file_path} not found. Please create the file and add topics.")
        topics = []
    available_queries.extend(topics)
    return topics


load_topics_from_file()


async def handle_api_limit() -> None:
    # Wait for the NewsAPI rate limit to reset.
    print("⏳ Waiting for API rate limit to reset...")
    sleep_seconds = 15 * 60  # Wait 15 minutes
    while sleep_seconds > 0:
        await asyncio.sleep(min(60, sleep_seconds))
        sleep_seconds -= 60
        print(
            f"⏳ Still waiting for API rate limit to reset... {sleep_seconds // 60} minutes remaining."
        )
    print("✅ Resuming article fetching after API rate limit reset.")


async def fetch_article(recent_urls: Set[str]) -> Optional[Dict[str, object]]:
    global available_queries, used_queries

    if not NEWS_API_KEY:
        print("❌ ERROR: NEWS_API_KEY is not set. Set it in your environment or a .env file.")
        return None

    if not available_queries:
        print("🔄 No available queries left. Resetting queries...")
        available_queries.extend(used_queries)
        used_queries.clear()
        print(f"✅ Queries reset. {len(available_queries)} queries are now available.")

    random.shuffle(available_queries)

    api_url = "https://newsapi.org/v2/everything"
    params = {
        "apiKey": NEWS_API_KEY,
        "language": "en",
        "pageSize": 1,
    }

    for query in list(available_queries):
        params["q"] = query
        try:
            print(f"Fetching articles for query: {query} from: {api_url}")
            response = requests.get(api_url, params=params)
            if response.status_code == 429:
                print("❌ ERROR: API rate limit reached (429). Entering a wait state.")
                await handle_api_limit()
                return None
            response.raise_for_status()
            data = response.json()
            articles = data.get("articles") or []
            if articles:
                article = articles[0]
                url = article.get("url")
                if url in recent_urls:
                    print(f"⚠️ Skipping previously posted article: {url}")
                    continue
                # Move the query to the used list
                available_queries.remove(query)
                used_queries.append(query)
                result: Dict[str, object] = {
                    "title": article.get("title", ""),
                    "source": (article.get("source") or {}).get("name", ""),
                    "summary": article.get("description") or "No description available.",
                    "link": url,
                }
                lm_summary = summarize_with_lmstudio(result)
                if lm_summary:
                    result["summary"] = lm_summary  # Use LM Studio summary if available
                else:
                    print(
                        "ℹ️ Using NewsAPI description as summary (LM Studio unavailable or failed)."
                    )
                return result
            else:
                print(f"❌ No articles found for query: {query}. Trying next query...")
        except Exception as e:
            print(f"❌ ERROR: Failed to fetch article for query: {query}: {e}")

    print("❌ No articles found for any query.")
    return None