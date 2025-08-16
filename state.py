from __future__ import annotations

import asyncio

unactioned_articles: list[dict] = []

unactioned_articles_lock: asyncio.Lock = asyncio.Lock()