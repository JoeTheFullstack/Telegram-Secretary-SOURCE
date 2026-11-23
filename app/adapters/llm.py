"""LLM adapter: any OpenAI-compatible /chat/completions endpoint.

Works with Atlas Cloud, DeepSeek API, OpenRouter, or local Ollama
(base_url http://localhost:11434/v1). The LLM only *suggests* JSON; it never touches the DB.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class LLMError(Exception):
    pass


class LLMOffline(LLMError):
    """Raised by OfflineLLM: expected, not worth a warning."""


def extract_json_object(text: str) -> dict:
    """Pull the first {...} block out of a model reply (handles ``` fences / chatter)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("no JSON object in model reply")
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError as e:
        raise LLMError("invalid JSON in model reply") from e
    if not isinstance(obj, dict):
        raise LLMError("JSON reply is not an object")
    return obj


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self._url = base_url.rstrip("/") + "/chat/completions"
        # A local server (Ollama) must never be sent through the Windows system proxy / VPN:
        # the proxy would answer 503. Remote APIs keep using the system proxy settings.
        host = urllib.parse.urlparse(base_url).hostname or ""
        if host in ("localhost", "127.0.0.1", "::1"):
            self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            self._opener = urllib.request.build_opener()
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def chat_json(self, system: str, user: str) -> dict:
        body = json.dumps({
            "model": self._model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(self._url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        })
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode())
            content = payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise LLMError(f"LLM HTTP {e.code}") from e          # no URL/key in message
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"LLM call failed: {type(e).__name__}") from e
        return extract_json_object(content or "")


class OfflineLLM:
    """Stand-in that always fails -> the bot falls back to step-by-step questions."""

    def chat_json(self, system: str, user: str) -> dict:
        raise LLMOffline("offline mode")
