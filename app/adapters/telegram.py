"""Telegram Bot API adapter (long polling, stdlib only). Knows nothing about customers."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Buttons = Sequence[Sequence[Tuple[str, str]]]  # rows of (label, callback_data)


class TelegramError(Exception):
    pass


@dataclass(frozen=True)
class Incoming:
    update_id: int
    chat_id: int
    telegram_id: int
    display_name: str
    text: str                       # message text, or callback_data for button presses
    callback_id: Optional[str] = None
    media: Optional[dict] = None


def _name(frm: dict) -> str:
    full = " ".join(p for p in (frm.get("first_name"), frm.get("last_name")) if p)
    return full or frm.get("username") or str(frm.get("id"))


def parse_update(update: dict) -> Optional[Incoming]:
    """Normalize a raw update. Only private chats are served (groups are ignored)."""
    if "message" in update:
        m = update["message"]
        chat, frm = m.get("chat", {}), m.get("from", {})
        if chat.get("type") != "private" or frm.get("is_bot") or "id" not in frm:
            return None
        media = None
        photos = m.get("photo") or []
        video = m.get("video")
        if photos:
            # Telegram provides several photo sizes; retain the largest one.
            photo = max(photos, key=lambda item: (
                item.get("file_size", 0),
                item.get("width", 0) * item.get("height", 0),
            ))
            media = {
                "kind": "photo",
                "file_id": photo.get("file_id"),
                "file_unique_id": photo.get("file_unique_id"),
                "media_group_id": m.get("media_group_id"),
                "caption": m.get("caption") or "",
            }
        elif isinstance(video, dict):
            media = {
                "kind": "video",
                "file_id": video.get("file_id"),
                "file_unique_id": video.get("file_unique_id"),
                "media_group_id": m.get("media_group_id"),
                "caption": m.get("caption") or "",
            }
        text = m.get("text") or m.get("caption") or ""
        return Incoming(update["update_id"], chat["id"], frm["id"], _name(frm), text, media=media)
    if "callback_query" in update:
        cq = update["callback_query"]
        chat, frm = (cq.get("message") or {}).get("chat", {}), cq.get("from", {})
        if chat.get("type") != "private" or "id" not in frm:
            return None
        return Incoming(update["update_id"], chat["id"], frm["id"], _name(frm),
                        cq.get("data") or "", cq.get("id"))
    return None


class TelegramClient:
    def __init__(self, token: str, proxy: str = ""):
        self._base = f"https://api.telegram.org/bot{token}/"
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
        self._opener = urllib.request.build_opener(*handlers)

    def _call(self, method: str, payload: dict, timeout: int = 40):
        req = urllib.request.Request(
            self._base + method, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise TelegramError(f"{method}: HTTP {e.code}") from e   # never include the URL (token)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TelegramError(f"{method} failed: {type(e).__name__}") from e
        if not body.get("ok"):
            raise TelegramError(f"{method}: not ok")
        return body["result"]

    def get_updates(self, offset: int, poll_seconds: int = 30) -> List[dict]:
        return self._call("getUpdates", {"offset": offset, "timeout": poll_seconds,
                                         "allowed_updates": ["message", "callback_query"]},
                          timeout=poll_seconds + 10)

    def send_message(self, chat_id: int, text: str, buttons: Optional[Buttons] = None) -> None:
        payload = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row] for row in buttons]}
        self._call("sendMessage", payload)

    def answer_callback(self, callback_id: str) -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id})
