"""Property business logic. Talks to repositories, never writes SQL itself."""
from __future__ import annotations

import sqlite3

from app.core import permissions
from app.domain import property_parsing
from app.domain.property_schemas import PropertyDraft
from app.infra.db import transaction
from app.repositories import audit, properties
from app.repositories.users import User
from app.services.customer_service import ServiceError


def create_property(conn: sqlite3.Connection, actor: User, draft: PropertyDraft) -> int:
    permissions.require(actor.role, "property.create")
    if draft.missing():
        raise ServiceError("اطلاعات ضروری ملک (نوع، منطقه، متراژ و قیمت) کامل نیست.")
    title = draft.title()
    with transaction(conn):
        property_id = properties.insert(conn, draft.to_dict(), title, created_by=actor.id)
        audit.log(conn, actor.id, "property.create", "property", property_id, {"title": title})
    return property_id


def add_property_media(conn: sqlite3.Connection, actor: User, property_id: int, media: dict) -> bool:
    """Store Telegram file identifiers; return False when this file is already linked."""
    permissions.require(actor.role, "property.create")
    kind = media.get("kind")
    file_id = media.get("file_id")
    if kind not in ("photo", "video") or not isinstance(file_id, str) or not file_id.strip():
        raise ServiceError("اطلاعات عکس یا ویدئو معتبر نیست؛ لطفاً دوباره ارسال کن.")
    file_unique_id = media.get("file_unique_id")
    with transaction(conn):
        if properties.get(conn, property_id) is None:
            raise ServiceError("ملک موردنظر پیدا نشد؛ دریافت رسانه متوقف شد.")
        if file_unique_id and properties.media_exists(conn, property_id, file_unique_id):
            return False
        try:
            media_id = properties.insert_media(conn, property_id, media, added_by=actor.id)
        except sqlite3.IntegrityError as e:
            raise ServiceError("ذخیره رسانه انجام نشد؛ لطفاً دوباره تلاش کن.") from e
        audit.log(conn, actor.id, "property.media.add", "property_media", media_id,
                  {"property_id": property_id, "kind": kind})
    return True


def count_property_media(conn: sqlite3.Connection, property_id: int) -> int:
    return properties.count_media(conn, property_id)


def start_media_collection(conn: sqlite3.Connection, actor: User, property_id: int) -> str:
    """Authorize and validate a request to append media to an existing property."""
    permissions.require(actor.role, "property.create")
    if property_id < 1:
        raise ServiceError("کد ملک معتبر نیست.")
    row = properties.get(conn, property_id)
    if row is None:
        raise ServiceError(f"ملک شمارهٔ {property_id} پیدا نشد.")
    with transaction(conn):
        audit.log(conn, actor.id, "property.media.session_start", "property", property_id, {})
    return row["title"]


def search_properties(conn: sqlite3.Connection, actor: User, query: str = "", limit: int = 5, offset: int = 0):
    """Search inventory; customers can only discover currently available properties."""
    permissions.require(actor.role, "property.search")
    query = (query or "").strip()
    parsed = property_parsing.parse_property_text(query) if query else PropertyDraft()
    keyword = query if query and parsed.is_empty() else None
    return properties.search(
        conn,
        property_type=parsed.property_type,
        location=parsed.location,
        keyword=keyword,
        min_area=parsed.area_m2,
        max_price=parsed.price,
        available_only=(actor.role == "customer"),
        limit=limit,
        offset=offset,
    )


def get_property_for_view(conn: sqlite3.Connection, actor: User, property_id: int):
    """Return details and media only when this role may see the property's status."""
    permissions.require(actor.role, "property.search")
    row = properties.get(conn, property_id)
    if row is None or (actor.role == "customer" and row["status"] != "available"):
        return None
    return row, properties.list_media(conn, property_id)
