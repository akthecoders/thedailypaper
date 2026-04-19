"""Single LLM call path. Every model call in this project goes through here.

Routes 100% through OpenRouter (OpenAI-compatible chat completions endpoint).
No direct provider SDKs — one key, one billing surface, trivial model swapping.

Uses SSE streaming for any request >4k tokens so long generations don't hit
OpenRouter's non-streaming gateway timeout (we saw Opus at 20k tokens get
truncated, corrupting the JSON response).
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
STREAMING_THRESHOLD = 4000  # max_tokens above this → stream


def call_llm(
    model: str,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float | None = None,
    timeout: int = 600,
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

    use_stream = max_tokens > STREAMING_THRESHOLD
    if use_stream:
        payload["stream"] = True

    log.info(
        f"OpenRouter call → {model} (max_tokens={max_tokens}, stream={use_stream})"
    )

    if not use_stream:
        return _non_stream(headers, payload, timeout)
    return _stream(headers, payload, timeout)


def _non_stream(headers: dict, payload: dict, timeout: int) -> str:
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
    if not resp.ok:
        raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"OpenRouter returned non-JSON (status={resp.status_code}, "
            f"content-type={resp.headers.get('content-type')}).\n"
            f"First 500: {resp.text[:500]}\nLast 500: {resp.text[-500:]}"
        ) from e
    if "error" in body:
        raise RuntimeError(f"OpenRouter error: {body['error']}")
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected response shape: {body}") from e


def _stream(headers: dict, payload: dict, timeout: int) -> str:
    """Accumulate SSE chunks into a single content string."""
    chunks: list[str] = []
    finish_reason: str | None = None
    with requests.post(
        OPENROUTER_URL, headers=headers, json=payload, timeout=timeout, stream=True
    ) as resp:
        if not resp.ok:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            # OpenRouter sends "OPENROUTER PROCESSING" heartbeats as comments starting with ':'
            if raw_line.startswith(":"):
                continue
            if not raw_line.startswith("data: "):
                continue
            data = raw_line[6:].strip()
            if data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except Exception:
                log.warning(f"Skipping unparseable SSE chunk: {data[:120]}")
                continue
            if "error" in evt:
                raise RuntimeError(f"OpenRouter stream error: {evt['error']}")
            choices = evt.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                chunks.append(piece)
            if choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]
    if not chunks:
        raise RuntimeError("OpenRouter stream closed with no content")
    if finish_reason == "length":
        log.warning(
            "OpenRouter stream ended due to max_tokens cap — output may be truncated."
        )
    return "".join(chunks)
