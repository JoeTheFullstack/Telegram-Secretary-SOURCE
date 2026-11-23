"""Property search presentation and callback navigation."""
from __future__ import annotations

import json
import sqlite3
from typing import List

from app.core import permissions
from app.core.customer_flow import Reply, _fmt_toman
from app.repositories.users import User
from app.services import property_service

PAGE_SIZE = 5
_TYPE_FA = {
    "land": "زمین", "apartment": "آپارتمان", "villa": "ویلا",
    "commercial": "تجاری", "garden": "باغ", "other": "سایر",
}
_STATUS_FA = {"available": "موجود", "reserved": "رزرو", "sold": "فروخته‌شده"}


def _state_key(user: User) -> str:
    return f"property_search:{user.id}"


def _save_state(conn: sqlite3.Connection, user: User, query: str) -> None:
    conn.execute(
        "INSERT INTO kv(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_state_key(user), json.dumps({"query": query}, ensure_ascii=False)),
    )


def _load_query(conn: sqlite3.Connection, user: User) -> str:
    row = conn.execute("SELECT value FROM kv WHERE key=?", (_state_key(user),)).fetchone()
    if row is None:
        return ""
    try:
        data = json.loads(row["value"])
        return str(data.get("query") or "")
    except (ValueError, TypeError, AttributeError):
        return ""


def _page(conn: sqlite3.Connection, user: User, query: str, offset: int) -> List[Reply]:
    total, rows = property_service.search_properties(conn, user, query, PAGE_SIZE, offset)
    if total == 0:
        return [Reply("ملکی با این مشخصات پیدا نشد.\nمی‌توانی عبارت جست‌وجو را تغییر بدهی و دوباره /search را اجرا کنی.")]
    start = offset + 1
    end = min(offset + len(rows), total)
    lines = [f"🔎 نتایج جست‌وجو ({start} تا {end} از {total} ملک):"]
    buttons = []
    for row in rows:
        status = _STATUS_FA.get(row["status"], row["status"])
        lines.append(
            f"\n🏠 کد {row['id']} — {row['title']}\n"
            f"نوع: {_TYPE_FA.get(row['property_type'], row['property_type'])} | "
            f"متراژ: {row['area_m2']} متر\n"
            f"منطقه: {row['location']}\n"
            f"قیمت: {_fmt_toman(row['price'])} | وضعیت: {status}"
        )
        buttons.append([(f"مشاهدهٔ ملک {row['id']}", f"pv:{row['id']}")])
    nav = []
    if offset > 0:
        nav.append(("⬅️ قبلی", "ps:prev"))
    if offset + len(rows) < total:
        nav.append(("بعدی ➡️", "ps:next"))
    if nav:
        buttons.append(nav)
    return [Reply("\n".join(lines), buttons)]


def start(conn: sqlite3.Connection, user: User, query: str = "") -> List[Reply]:
    if not permissions.can(user.role, "property.search"):
        return [Reply("شما اجازهٔ جست‌وجوی ملک را ندارید.")]
    _save_state(conn, user, query.strip())
    return _page(conn, user, query.strip(), 0)


def paginate(conn: sqlite3.Connection, user: User, direction: int) -> List[Reply]:
    if not permissions.can(user.role, "property.search"):
        return [Reply("شما اجازهٔ جست‌وجوی ملک را ندارید.")]
    query = _load_query(conn, user)
    total, _ = property_service.search_properties(conn, user, query, PAGE_SIZE, 0)
    if total == 0:
        return [Reply("نتیجه‌ای برای نمایش وجود ندارد. دستور /search را دوباره اجرا کن.")]
    current = 0
    if direction > 0:
        # Find the next page from the callback's current message-independent state.
        row = conn.execute("SELECT value FROM kv WHERE key=?", (_state_key(user),)).fetchone()
        try:
            current = int(json.loads(row["value"]).get("offset", 0)) if row else 0
        except (ValueError, TypeError, AttributeError):
            current = 0
        current += PAGE_SIZE
        if current >= total:
            current = max(0, ((total - 1) // PAGE_SIZE) * PAGE_SIZE)
    else:
        row = conn.execute("SELECT value FROM kv WHERE key=?", (_state_key(user),)).fetchone()
        try:
            current = int(json.loads(row["value"]).get("offset", 0)) if row else 0
        except (ValueError, TypeError, AttributeError):
            current = 0
        current = max(0, current - PAGE_SIZE)
    conn.execute(
        "INSERT INTO kv(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_state_key(user), json.dumps({"query": query, "offset": current}, ensure_ascii=False)),
    )
    return _page(conn, user, query, current)


def view(conn: sqlite3.Connection, user: User, property_id: int) -> List[Reply]:
    if not permissions.can(user.role, "property.search"):
        return [Reply("شما اجازهٔ مشاهدهٔ ملک را ندارید.")]
    result = property_service.get_property_for_view(conn, user, property_id)
    if result is None:
        return [Reply("ملک موردنظر پیدا نشد یا برای نمایش به شما در دسترس نیست.")]
    row, media = result
    lines = [
        f"🏠 جزئیات ملک شمارهٔ {row['id']}",
        f"عنوان: {row['title']}",
        f"نوع: {_TYPE_FA.get(row['property_type'], row['property_type'])}",
        f"منطقه: {row['location']}",
        f"متراژ: {row['area_m2']} متر",
        f"قیمت: {_fmt_toman(row['price'])}",
        f"وضعیت: {_STATUS_FA.get(row['status'], row['status'])}",
        f"تعداد عکس و فیلم: {len(media)}",
    ]
    replies = [Reply("\n".join(lines))]
    if not media:
        replies.append(Reply("برای این ملک هنوز عکس یا فیلمی ثبت نشده است."))
    else:
        # Limit one request's media burst; users can reopen the property to see them again.
        for item in media[:10]:
            replies.append(Reply("", media={
                "kind": item["kind"], "file_id": item["file_id"],
                "caption": item["caption"] or "",
            }))
        if len(media) > 10:
            replies.append(Reply(f"۱۰ رسانهٔ اول ارسال شد؛ این ملک در مجموع {len(media)} رسانه دارد."))
    return replies
