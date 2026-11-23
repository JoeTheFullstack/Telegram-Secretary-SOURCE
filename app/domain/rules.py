"""Business rules for customers. No I/O here."""
from __future__ import annotations

from typing import List

from app.domain.schemas import CustomerDraft

REQUIRED_CUSTOMER_FIELDS = ("full_name", "phone")


def missing_customer_fields(draft: CustomerDraft) -> List[str]:
    return [f for f in REQUIRED_CUSTOMER_FIELDS if getattr(draft, f) is None]


def normalize_customer(draft: CustomerDraft) -> CustomerDraft:
    """Fix harmless inconsistencies (min > max -> swap)."""
    lo, hi = draft.budget_min, draft.budget_max
    if lo is not None and hi is not None and lo > hi:
        return CustomerDraft(**{**draft.to_dict(), "budget_min": hi, "budget_max": lo})
    return draft
