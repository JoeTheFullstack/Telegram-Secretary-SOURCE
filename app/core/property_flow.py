"""'New property' conversation: collect fields -> show summary -> confirm -> save."""
from __future__ import annotations

import sqlite3
from typing import List

from app.core import permissions, sessions
from app.core.customer_flow import CONFIRM_WORDS, Reply, _CONFIRM_BUTTONS, _fmt_toman
from app.core.permissions import PermissionDenied
from app.core.sessions import Session
from app.domain import property_parsing
from app.domain.property_schemas import TYPE_FA, PropertyDraft
from app.repositories.users import User
from app.services import property_service
from app.services.customer_service import ServiceError

FLOW = "new_property"
MEDIA_FLOW = "property_media"

_QUESTIONS = {
    "property_type": "نوع ملک چیست؟ (زمین، آپارتمان، ویلا، تجاری، باغ)",
    "location": "منطقه یا محلهٔ ملک؟ (مثلاً شمال یا سعادت آباد)",
    "area_m2": "متراژ ملک چند متر است؟ (مثلاً 500)",
    "price": "قیمت ملک؟ (مثلاً 10 میلیارد)",
}
_RETRY = {
    "property_type": "نوع ملک را متوجه نشدم. یکی از این‌ها را بنویس: زمین، آپارتمان، ویلا، تجاری، باغ.",
    "location": "منطقه را متوجه نشدم. فقط نام منطقه یا محله را با حروف بنویس (مثلاً شمال).",
    "area_m2": "متراژ را متوجه نشدم. یک عدد بنویس (مثلاً 500).",
    "price": "قیمت را متوجه نشدم. با واحد بنویس (مثلاً 10 میلیارد یا 850 میلیون).",
}


def _summary(d: PropertyDraft) -> str:
    return "\n".join([
        "🏠 مشخصات ملک:",
        f"عنوان: {d.title()}",
        f"نوع: {TYPE_FA[d.property_type]}",
        f"منطقه: {d.location}",
        f"متراژ: {d.area_m2} متر",
        f"قیمت: {_fmt_toman(d.price)}",
        "\nاگر چیزی نادرست است همین‌جا بنویس تا اصلاح شود؛ وگرنه تأیید را بزن.",
    ])


def _advance(conn: sqlite3.Connection, user: User, draft: PropertyDraft) -> List[Reply]:
    missing = draft.missing()
    awaiting = missing[0] if missing else "confirm"
    sessions.save(conn, user.id, Session(FLOW, awaiting, draft.to_dict()))
    if missing:
        return [Reply(_QUESTIONS[awaiting])]
    return [Reply(_summary(draft), _CONFIRM_BUTTONS)]


def start(conn: sqlite3.Connection, user: User, rest_text: str) -> List[Reply]:
    draft = property_parsing.parse_property_text(rest_text) if rest_text else PropertyDraft()
    return _advance(conn, user, draft)


def handle(conn: sqlite3.Connection, user: User, session: Session, text: str) -> List[Reply]:
    draft = PropertyDraft.from_raw(session.data)

    if session.awaiting == "confirm":
        if text.strip().lower() in CONFIRM_WORDS:
            return _save(conn, user, draft)
        new = property_parsing.parse_property_text(text)
        if new.is_empty():
            return [Reply("برای ثبت «تأیید» را بزن، یا مورد اصلاحی را بنویس. انصراف: /cancel",
                          _CONFIRM_BUTTONS)]
        return _advance(conn, user, draft.merged(new))

    if text.strip().lower() in CONFIRM_WORDS:          # an old confirm button
        new = PropertyDraft()
    else:
        new = property_parsing.parse_awaited(session.awaiting, text)
    if new.is_empty():
        return [Reply(_RETRY.get(session.awaiting, _QUESTIONS.get(session.awaiting, "؟")))]
    return _advance(conn, user, draft.merged(new))


def _save(conn: sqlite3.Connection, user: User, draft: PropertyDraft) -> List[Reply]:
    try:
        property_id = property_service.create_property(conn, user, draft)
    except PermissionDenied:
        sessions.clear(conn, user.id)
        return [Reply("شما اجازهٔ ثبت ملک ندارید.")]
    except ServiceError as e:
        sessions.clear(conn, user.id)
        return [Reply(str(e))]
    sessions.save(conn, user.id, Session(
        MEDIA_FLOW, "media", {"property_id": property_id}
    ))
    return [Reply(
        f"✅ ملک ثبت شد (کد ملک {property_id}).\n\n"
        "حالا عکس‌ها و فیلم‌های این ملک را ارسال کن. می‌توانی چند رسانه را جداگانه یا به‌صورت آلبوم بفرستی.\n"
        "برای پایان دریافت رسانه: /done\n"
        "برای لغو دریافت رسانه: /cancel"
    )]


def handle_media(conn: sqlite3.Connection, user: User, session: Session, media: dict) -> List[Reply]:
    """Attach one Telegram photo/video to the property currently being collected."""
    if not permissions.can(user.role, "property.create"):
        sessions.clear(conn, user.id)
        return [Reply("شما اجازهٔ افزودن رسانه به ملک را ندارید.")]
    try:
        property_id = int(session.data.get("property_id"))
    except (TypeError, ValueError):
        sessions.clear(conn, user.id)
        return [Reply("اطلاعات مرحلهٔ دریافت رسانه معتبر نیست. لطفاً ثبت ملک را دوباره انجام بده.")]
    try:
        added = property_service.add_property_media(conn, user, property_id, media)
    except PermissionDenied:
        sessions.clear(conn, user.id)
        return [Reply("شما اجازهٔ افزودن رسانه به ملک را ندارید.")]
    except ServiceError as e:
        return [Reply(str(e))]
    if added:
        kind_label = "عکس" if media.get("kind") == "photo" else "ویدئو"
        return [Reply(f"✅ {kind_label} برای ملک {property_id} ذخیره شد.\nمی‌توانی رسانهٔ بعدی را بفرستی یا /done بزنی.")]
    return [Reply("این رسانه قبلاً برای همین ملک ثبت شده است. می‌توانی رسانهٔ بعدی را بفرستی یا /done بزنی.")]


def handle_media_text(conn: sqlite3.Connection, user: User, session: Session, text: str) -> List[Reply]:
    if text.strip().lower() == "/done":
        return finish_media(conn, user, session)
    return [Reply("در حال دریافت رسانهٔ ملک هستیم. عکس یا ویدئو بفرست؛ برای پایان /done و برای لغو /cancel را بزن.")]


def finish_media(conn: sqlite3.Connection, user: User, session: Session) -> List[Reply]:
    try:
        property_id = int(session.data.get("property_id"))
    except (TypeError, ValueError):
        sessions.clear(conn, user.id)
        return [Reply("مرحلهٔ دریافت رسانه پایان یافت، اما شناسهٔ ملک معتبر نبود.")]
    count = property_service.count_property_media(conn, property_id)
    sessions.clear(conn, user.id)
    return [Reply(f"✅ دریافت رسانهٔ ملک {property_id} تمام شد. تعداد رسانه‌های ثبت‌شده: {count} عدد.")]


def start_media_collection(conn: sqlite3.Connection, user: User, property_id: int) -> List[Reply]:
    """Open a media-upload session for an already saved property."""
    try:
        title = property_service.start_media_collection(conn, user, property_id)
    except PermissionDenied:
        return [Reply("شما اجازهٔ افزودن رسانه به ملک را ندارید.")]
    except ServiceError as e:
        return [Reply(str(e))]

    sessions.save(conn, user.id, Session(
        MEDIA_FLOW, "media", {"property_id": property_id}
    ))
    return [Reply(
        f"افزودن رسانه برای ملک {property_id} فعال شد.\n"
        f"عنوان ملک: {title}\n\n"
        "حالا عکس‌ها و فیلم‌های جدید را ارسال کن. رسانه‌های قبلی حذف نمی‌شوند.\n"
        "برای پایان: /done\n"
        "برای لغو: /cancel"
    )]
