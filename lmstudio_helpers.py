from __future__ import annotations

import json
import requests
from typing import Any, Dict, List, Optional

# Import configuration constants from the sibling module. We use
# absolute imports here so that these modules can be executed
# directly without requiring a package structure. See ``main.py`` for
# more information.
from config import (
    LMSTUDIO_BASE_URL,
    LMSTUDIO_MODEL,
    LMSTUDIO_API_KEY,
    LMSTUDIO_TIMEOUT,
    LM_USE_TOOLS,
)


print(
    f"LM Studio config → BASE: {LMSTUDIO_BASE_URL}  MODEL: {LMSTUDIO_MODEL}  TIMEOUT: {LMSTUDIO_TIMEOUT}s"
)


def lmstudio_models() -> List[str]:
    # Return the list of available model identifiers from LM Studio.
    try:
        url = f"{LMSTUDIO_BASE_URL.rstrip('/')}/v1/models"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        print("LM Studio /v1/models →", ids)
        return [m for m in ids if isinstance(m, str)]
    except Exception as e:
        print(f"⚠️ Could not reach LM Studio /v1/models: {e}")
        return []


def safe_json_parse(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def build_news_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 5,
            },
            "why_it_matters": {"type": "string"},
        },
        "required": ["title", "key_points", "why_it_matters"],
        "additionalProperties": False,
    }


def looks_like_instruct_model(model_id: str) -> bool:
    m = model_id.lower()
    if "instruct" in m:
        return True
    return any(x in m for x in ["qwen", "mistral", "llama", "phi", "gemma"]) and not any(
        y in m for y in ["r1", "reasoning"]
    )


def summarize_with_lmstudio(article: Dict[str, Any]) -> Optional[Dict[str, Any]]:

    models = lmstudio_models()
    if models and LMSTUDIO_MODEL not in models:
        print(f"⚠️ Requested model '{LMSTUDIO_MODEL}' not in /v1/models. Use an exact id from the list above.")
    if not looks_like_instruct_model(LMSTUDIO_MODEL):
        print(
            "ℹ️ Hint: prefer an instruct model for structured output (e.g., qwen2.5-7b-instruct-mlx, llama-3.1-8b-instruct-mlx)."
        )

    endpoint = f"{LMSTUDIO_BASE_URL.rstrip('/')}/v1/chat/completions"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
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

    schema_payload: Dict[str, Any] = {
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
                "strict": True,
            },
        },
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
                return parsed  # type: ignore[return-value]
            content = (msg.get("content") or "").strip()
            parsed2 = safe_json_parse(content)
            if isinstance(parsed2, dict) and parsed2.get("title"):
                return parsed2  # type: ignore[return-value]
            print("ℹ️ JSON Schema mode returned no parsed object; falling back.")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Cannot connect to LM Studio at {LMSTUDIO_BASE_URL}: {e}")
        return None
    except Exception as e:
        print(f"ℹ️ JSON Schema attempt failed: {e}. Falling back.")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "summarize_article",
                "description": "Summarize a news article for Discord in a structured way.",
                "parameters": build_news_schema(),
            },
        }
    ]

    payload: Dict[str, Any] = {
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
            return parsed  # type: ignore[return-value]
        tool_calls = msg2.get("tool_calls") or []
        if tool_calls:
            try:
                arguments = tool_calls[0]["function"]["arguments"]
                parsed2 = safe_json_parse(arguments)
                if isinstance(parsed2, dict) and parsed2.get("title"):
                    return parsed2  # type: ignore[return-value]
            except Exception as e:
                print(f"⚠️ Failed to parse tool call arguments: {e}")
    except Exception as e:
        print(f"ℹ️ Tool/JSON fallback attempt failed: {e}")

    try:
        plain = {
            "model": LMSTUDIO_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Return ONLY a compact JSON object with keys: title (string), key_points (array of 3 short strings), why_it_matters (string).",
                },
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
            return parsed3  # type: ignore[return-value]
    except Exception as e:
        print(f"⚠️ Plain JSON fallback failed: {e}")

    print("⚠️ No structured output from LM Studio after all attempts.")
    return None