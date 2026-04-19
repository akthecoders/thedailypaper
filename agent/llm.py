"""Single LLM call path. Every model call in this project goes through here.

Routes 100% through OpenRouter (OpenAI-compatible chat completions endpoint).
No direct provider SDKs — one key, one billing surface, trivial model swapping.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def call_llm(
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float | None = None,
    timeout: int = 300,
) -> str:
    """Call an OpenRouter-hosted model. Returns the assistant text.

    `model` is an OpenRouter slug, e.g. "anthropic/claude-opus-4.1",
    "google/gemini-2.5-flash", "openai/gpt-4o".

    `messages` is an OpenAI-style list of {"role", "content"} dicts.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Get a key at https://openrouter.ai/keys "
            "and add it to .env or GitHub Actions secrets."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("SITE_URL", "https://thedailypaper.akshaykumar.me"),
        "X-Title": "The Daily Paper",
    }
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature

    log.info(f"OpenRouter call → {model} (max_tokens={max_tokens})")
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)

    if not resp.ok:
        raise RuntimeError(
            f"OpenRouter {resp.status_code}: {resp.text[:500]}"
        )

    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"OpenRouter error: {body['error']}")

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {body}") from e
