"""'New customer' conversation: collect fields -> show summary -> confirm -> save."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from app.core import sessions
from app.core.permissions import PermissionDenied
from app.core.sessions import Session
from app.domain import rules
from app.domain.schemas import CustomerDraft, find_phone
from app.repositories.users import User
from app.services import customer_service
from app.services.customer_service import ServiceError

FLOW = "new_customer"
CONFIRM_WORDS = {"confirm", "تایید", "تأیید", "ok", "بله"}


@dataclass
class Reply:
    text: str
    buttons: Optional[list] = None   # rows of (label, callback_data)
    media: Optional[dict] = None     # optional outgoing Telegram photo/video


_QUESTIONS = {
    "full_name": "نام و نام خانوادگی مشتری چیست؟",
    "phone": "شمارهٔ موبایل مشتری؟ (مثلاً 09121234567)",
}
_RETRY = {
    "full_name": "نام را متوجه نشدم. لطفاً فقط نام و نام خانوادگی را با حروف بنویس.",
    "phone": "شماره معتبر نیست. یک موبایل ۱۱ رقمی بنویس (مثلاً 09121234567).",
}
_TYPE_FA = {"land": "زمین", "apartment": "آپارتمان", "villa": "ویلا",
            "commercial": "تجاری", "garden": "باغ", "other": "سایر"}
_CONFIRM_BUTTONS = [[("✅ تأیید و ثبت", "confirm"), ("❌ لغو", "cancel")]]


def _fmt_toman(n: int) -> str:
    if n % 1_000_000_000 == 0:
        return f"{n // 1_000_000_000} میلیارد تومان"
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000} میلیون تومان"
    return f"{n:,} تومان"


def _summary(d: CustomerDraft) -> str:
    lines = ["📋 مشخصات مشتری:", f"نام: {d.full_name}", f"موبایل: {d.phone}"]
    if d.budget_min and d.budget_max:
        lines.append(f"بودجه: {_fmt_toman(d.budget_min)} تا {_fmt_toman(d.budget_max)}")
    elif d.budget_max:
        lines.append(f"بودجه: حداکثر {_fmt_toman(d.budget_max)}")
    elif d.budget_min:
        lines.append(f"بودجه: حداقل {_fmt_toman(d.budget_min)}")
    if d.preferred_location:
        lines.append(f"منطقه: {d.preferred_location}")
    if d.property_type:
        lines.append(f"نوع ملک: {_TYPE_FA[d.property_type]}")
    lines.append("\nاگر چیزی کم است (بودجه، منطقه، نوع ملک) همین‌جا بنویس؛ وگرنه تأیید را بزن.")
    return "\n".join(lines)


def _advance(conn: sqlite3.Connection, user: User, draft: CustomerDraft) -> List[Reply]:
    draft = rules.normalize_customer(draft)
    missing = rules.missing_customer_fields(draft)
    awaiting = missing[0] if missing else "confirm"
    sessions.save(conn, user.id, Session(FLOW, awaiting, draft.to_dict()))
    if missing:
        return [Reply(_QUESTIONS[awaiting])]
    return [Reply(_summary(draft), _CONFIRM_BUTTONS)]


def start(conn: sqlite3.Connection, llm, user: User, rest_text: str) -> List[Reply]:
    draft = customer_service.extract_draft(llm, rest_text) if rest_text else CustomerDraft()
    return _advance(conn, user, draft)


def _parse_awaited(llm, awaiting: Optional[str], text: str) -> CustomerDraft:
    """Cheap deterministic parsing for the field we asked about; LLM only as a fallback."""
    if awaiting == "phone":
        phone = find_phone(text)
        if phone:
            return CustomerDraft(phone=phone)
    elif awaiting == "full_name":
        name = CustomerDraft.from_raw({"full_name": text})
        if not name.is_empty():
            return name
    return customer_service.extract_draft(llm, text)


def handle(conn: sqlite3.Connection, llm, user: User, session: Session, text: str) -> List[Reply]:
    draft = CustomerDraft.from_raw(session.data)

    if session.awaiting == "confirm":
        if text.strip().lower() in CONFIRM_WORDS:
            return _save(conn, user, draft)
        new = customer_service.extract_draft(llm, text)
        if new.is_empty():
            return [Reply("برای ثبت «تأیید» را بزن، یا اطلاعات تکمیلی را بنویس. انصراف: /cancel",
                          _CONFIRM_BUTTONS)]
        return _advance(conn, user, draft.merged(new))

    new = CustomerDraft() if text.strip().lower() in CONFIRM_WORDS else _parse_awaited(llm, session.awaiting, text)
    if new.is_empty():
        return [Reply(_RETRY.get(session.awaiting, _QUESTIONS.get(session.awaiting, "؟")))]
    return _advance(conn, user, draft.merged(new))


def _save(conn: sqlite3.Connection, user: User, draft: CustomerDraft) -> List[Reply]:
    try:
        customer_id = customer_service.create_customer(conn, user, draft)
    except PermissionDenied:
        sessions.clear(conn, user.id)
        return [Reply("شما اجازهٔ ثبت مشتری ندارید.")]
    except ServiceError as e:
        sessions.clear(conn, user.id)
        return [Reply(str(e))]
    sessions.clear(conn, user.id)
    return [Reply(f"✅ مشتری ثبت شد (پرونده {customer_id}).")]
