"""Customer business logic. Talks to repositories, never writes SQL itself."""
from __future__ import annotations

import logging
import sqlite3

from app import prompts
from app.adapters.llm import LLMError, LLMOffline
from app.core import permissions
from app.domain import parsing, rules
from app.domain.schemas import CustomerDraft, find_phone
from app.infra.db import transaction
from app.repositories import audit, customers
from app.repositories.users import User

log = logging.getLogger("secretary")


class ServiceError(Exception):
    """Message is safe and meant to be shown to the user (Persian)."""


def extract_draft(llm, text: str) -> CustomerDraft:
    """Ask the LLM for fields, then validate everything.

    - LLM failure -> the LLM part is empty (caller falls back to step-by-step questions).
    - Budget, property type and region are re-read from the text by plain code and override
      the LLM; the LLM's values are kept only when they literally appear in the text.
    - The phone number is NEVER taken from the LLM; it is found deterministically in the text.
    """
    try:
        draft = CustomerDraft.from_raw(llm.chat_json(prompts.CUSTOMER_EXTRACTION_SYSTEM, text))
    except LLMOffline:
        draft = CustomerDraft()
    except LLMError as e:
        log.warning("LLM failed, using text rules only: %s", e)
        draft = CustomerDraft()
    draft = parsing.apply_text_rules(draft, text)
    phone = find_phone(text)
    return draft.merged(CustomerDraft(phone=phone)) if phone else draft


def create_customer(conn: sqlite3.Connection, actor: User, draft: CustomerDraft) -> int:
    permissions.require(actor.role, "customer.create")
    draft = rules.normalize_customer(draft)
    if rules.missing_customer_fields(draft):
        raise ServiceError("اطلاعات ضروری (نام و شماره تماس) کامل نیست.")
    with transaction(conn):
        existing = customers.find_by_phone(conn, draft.phone)
        if existing:
            raise ServiceError(
                f"این شماره قبلاً برای «{existing['full_name']}» ثبت شده است (پرونده {existing['id']}).")
        customer_id = customers.insert(conn, draft.to_dict(), created_by=actor.id)
        audit.log(conn, actor.id, "customer.create", "customer", customer_id,
                  {"full_name": draft.full_name})
    return customer_id
