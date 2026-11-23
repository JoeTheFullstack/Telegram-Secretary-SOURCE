"""Routes a message to the right handler. Rule-based on purpose: the LLM never picks the route."""
from __future__ import annotations

import sqlite3
from typing import Iterable, List

from app.core import customer_flow, permissions, property_flow, property_search, sessions
from app.core.customer_flow import Reply
from app.infra.db import transaction
from app.repositories import audit, users
from app.repositories.users import User

CANCEL_WORDS = {"/cancel", "cancel", "لغو"}
NEW_CUSTOMER_PREFIXES = ("/newcustomer", "مشتری جدید")
NEW_PROPERTY_PREFIXES = ("/newproperty", "ملک جدید")

HELP_STAFF = (
    "منشی دیجیتال 👋\n"
    "• جست‌وجوی ملک و دیدن عکس/فیلم: /search [عبارت]\n"
    "• ثبت مشتری: /newcustomer  یا  «مشتری جدید علی رضایی ۰۹۱۲... بودجه ۱۰ میلیارد زمین شمال»\n"
    "• ثبت ملک: /newproperty  یا  «ملک جدید زمین 500 متری شمال 10 میلیارد»\n"
    "• افزودن عکس و فیلم به ملک قبلی: /addmedia <کد ملک>\n"
    "• انصراف از کار جاری: /cancel\n"
    "• شناسهٔ تلگرام شما: /myid"
)
HELP_CUSTOMER = (
    "سلام 👋 منشی دیجیتال مشاور املاک هستم.\n"
    "برای جست‌وجوی ملک‌های موجود دستور /search را بفرست؛ "
    "برای محدودکردن نتایج می‌توانی نوع، منطقه، حداقل متراژ یا سقف قیمت را هم بنویسی."
)
DENIED = "شما اجازهٔ انجام این کار را ندارید."


class Router:
    def __init__(self, conn: sqlite3.Connection, llm, owner_ids: Iterable[int] = ()):
        self._conn = conn
        self._llm = llm
        self._owner_ids = set(owner_ids)

    # -- users -------------------------------------------------------------
    def _get_user(self, telegram_id: int, display_name: str) -> User:
        user = users.get_by_telegram_id(self._conn, telegram_id)
        if user is None:
            role = "owner" if telegram_id in self._owner_ids else "customer"
            return users.create(self._conn, telegram_id, display_name, role)
        if telegram_id in self._owner_ids and user.role != "owner":
            users.set_role(self._conn, user.id, "owner")
            return User(user.id, user.telegram_id, user.display_name, "owner")
        return user

    # -- main entry --------------------------------------------------------
    def handle(self, telegram_id: int, display_name: str, text: str, media: dict | None = None) -> List[Reply]:
        user = self._get_user(telegram_id, display_name)
        text = (text or "").strip()
        low = text.lower()
        session = sessions.get(self._conn, user.id)

        if low == "/myid":
            return [Reply(f"Telegram ID: {telegram_id}")]
        if low in CANCEL_WORDS:
            was_media = bool(session and session.flow == property_flow.MEDIA_FLOW)
            sessions.clear(self._conn, user.id)
            if was_media:
                return [Reply("دریافت رسانه لغو شد. خود ملک ثبت‌شده حذف نمی‌شود.")]
            return [Reply("لغو شد.")]

        # Media is accepted only while this same user has an active property-media session.
        if media is not None:
            if session and session.flow == property_flow.MEDIA_FLOW:
                return property_flow.handle_media(self._conn, user, session, media)
            if session and session.flow == property_flow.FLOW:
                return [Reply("ابتدا مشخصات ملک را کامل و ثبت کن؛ بعد عکس‌ها و فیلم‌ها را بفرست.")]
            if not permissions.can(user.role, "property.create"):
                return [Reply(DENIED)]
            return [Reply("در حال حاضر مرحلهٔ دریافت رسانه فعال نیست. ابتدا یک ملک را ثبت کن.")]

        if low == "/done":
            if session and session.flow == property_flow.MEDIA_FLOW:
                return property_flow.finish_media(self._conn, user, session)
            return [Reply("مرحلهٔ دریافت رسانه‌ای فعال نیست که تمام شود.")]

        if low == "/addmedia" or low.startswith("/addmedia "):
            if not permissions.can(user.role, "property.create"):
                return [Reply(DENIED)]
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdecimal():
                return [Reply("فرمت دستور: /addmedia <کد ملک>\nمثال: /addmedia 1")]
            if session is not None:
                return [Reply("یک عملیات دیگر هنوز فعال است. ابتدا آن را با /done تمام کن یا با /cancel لغو کن.")]
            return property_flow.start_media_collection(self._conn, user, int(parts[1]))

        # Search is deliberately independent of the create/upload conversation session.
        if low == "/search" or low.startswith("/search "):
            if not permissions.can(user.role, "property.search"):
                return [Reply(DENIED)]
            query = text[len("/search"):].strip()
            return property_search.start(self._conn, user, query)
        if low == "جستجوی ملک" or low.startswith("جستجوی ملک "):
            if not permissions.can(user.role, "property.search"):
                return [Reply(DENIED)]
            query = text[len("جستجوی ملک"):].strip()
            return property_search.start(self._conn, user, query)
        if low == "ps:next":
            return property_search.paginate(self._conn, user, 1)
        if low == "ps:prev":
            return property_search.paginate(self._conn, user, -1)
        if low.startswith("pv:"):
            raw_id = text[3:].strip()
            if not raw_id.isdecimal() or int(raw_id) < 1:
                return [Reply("شناسهٔ ملک معتبر نیست.")]
            return property_search.view(self._conn, user, int(raw_id))

        if not text:
            return []
        if low in ("/start", "/help"):
            return [Reply(HELP_CUSTOMER if user.role == "customer" else HELP_STAFF)]
        if low.startswith("/setrole"):
            return self._set_role(user, text)

        # Starting a new flow always wins over a half-finished one (restart).
        for prefix in NEW_CUSTOMER_PREFIXES:
            if text.startswith(prefix):
                if not permissions.can(user.role, "customer.create"):
                    return [Reply(DENIED)]
                rest = text[len(prefix):].strip(" :،-\n")
                return customer_flow.start(self._conn, self._llm, user, rest)

        for prefix in NEW_PROPERTY_PREFIXES:
            if text.startswith(prefix):
                if not permissions.can(user.role, "property.create"):
                    return [Reply(DENIED)]
                rest = text[len(prefix):].strip(" :،-\n")
                return property_flow.start(self._conn, user, rest)

        # Unknown /commands must never be swallowed as flow data (e.g. as a customer name).
        if text.startswith("/"):
            return [Reply(HELP_CUSTOMER if user.role == "customer" else HELP_STAFF)]

        if session and session.flow == property_flow.MEDIA_FLOW:
            return property_flow.handle_media_text(self._conn, user, session, text)
        if session and session.flow == customer_flow.FLOW:
            return customer_flow.handle(self._conn, self._llm, user, session, text)
        if session and session.flow == property_flow.FLOW:
            return property_flow.handle(self._conn, user, session, text)

        return [Reply(HELP_CUSTOMER if user.role == "customer" else HELP_STAFF)]

    # -- owner command: /setrole <telegram_id> <staff|manager|customer> ------
    def _set_role(self, actor: User, text: str) -> List[Reply]:
        if not permissions.can(actor.role, "users.manage"):
            return [Reply(DENIED)]
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ("staff", "manager", "customer"):
            return [Reply("فرمت: /setrole <telegram_id> <staff|manager|customer>")]
        target_tid, role = int(parts[1]), parts[2]
        if target_tid in self._owner_ids:
            return [Reply("نقش مالک از فایل تنظیمات می‌آید و از اینجا قابل تغییر نیست.")]
        with transaction(self._conn):
            target = users.get_by_telegram_id(self._conn, target_tid)
            if target is None:
                target = users.create(self._conn, target_tid, None, role)
            else:
                users.set_role(self._conn, target.id, role)
            audit.log(self._conn, actor.id, "user.set_role", "user", target.id, {"role": role})
        return [Reply(f"نقش کاربر {target_tid} شد: {role}")]
