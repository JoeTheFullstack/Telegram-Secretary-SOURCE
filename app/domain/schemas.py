"""Shape + validation of data. Everything coming from the LLM or a user passes here.

Stdlib only (dataclasses). Easy to swap for Pydantic later; the interface
(CustomerDraft.from_raw / merged / to_dict) would stay the same.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, Dict, Optional

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
PROPERTY_TYPES = ("land", "apartment", "villa", "commercial", "garden", "other")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+98|0098|98|0)[\s\-]?9(?:[\s\-]?\d){9}(?!\d)")
MAX_BUDGET = 10 ** 15; _NOT_NAMES = {"سلام", "درود", "ممنون", "مرسی", "ok", "hi", "hello"}; _NOT_NAMES = {"سلام", "درود", "ممنون", "مرسی", "ok", "hi", "hello"}


def normalize_digits(text: str) -> str:
    """Persian/Arabic-Indic digits -> ASCII digits."""
    return str(text).translate(_DIGITS)


def normalize_phone(raw: Any) -> Optional[str]:
    """Iranian mobile -> '09xxxxxxxxx', or None if invalid."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", normalize_digits(raw))
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits if re.fullmatch(r"09\d{9}", digits) else None


def find_phone(text: str) -> Optional[str]:
    """Find the first valid Iranian mobile number inside free text."""
    for m in _PHONE_RE.finditer(normalize_digits(text)):
        phone = normalize_phone(m.group())
        if phone:
            return phone
    return None


def _clean_text(v: Any, max_len: int) -> Optional[str]:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = " ".join(str(v).split())[:max_len]
    return s or None


def _clean_name(v: Any) -> Optional[str]:
    s = _clean_text(v, 60)
    if not s or len(s.split()) < 2 or s.split()[0].lower() in _NOT_NAMES or any(ch.isdigit() for ch in normalize_digits(s)):
        return None
    return s


def _to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)):
            n = int(v)
        else:
            s = normalize_digits(v).replace(",", "").replace("٬", "").strip()
            if not re.fullmatch(r"\d+(\.\d+)?", s):
                return None
            n = int(float(s))
    except (ValueError, OverflowError):
        return None
    return n if 0 < n <= MAX_BUDGET else None


def _clean_property_type(v: Any) -> Optional[str]:
    s = _clean_text(v, 30)
    s = s.lower() if s else None
    return s if s in PROPERTY_TYPES else None


@dataclass(frozen=True)
class CustomerDraft:
    full_name: Optional[str] = None
    phone: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    preferred_location: Optional[str] = None
    property_type: Optional[str] = None

    @classmethod
    def from_raw(cls, data: Any) -> "CustomerDraft":
        """Build from untrusted dict (LLM output, session JSON). Unknown keys are ignored,
        invalid values become None."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            full_name=_clean_name(data.get("full_name")),
            phone=normalize_phone(data.get("phone")),
            budget_min=_to_int(data.get("budget_min")),
            budget_max=_to_int(data.get("budget_max")),
            preferred_location=_clean_text(data.get("preferred_location"), 100),
            property_type=_clean_property_type(data.get("property_type")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)
                if getattr(self, f.name) is not None}

    def is_empty(self) -> bool:
        return not self.to_dict()

    def merged(self, other: "CustomerDraft") -> "CustomerDraft":
        """Values from `other` override this draft's values where they are set."""
        return CustomerDraft(**{**self.to_dict(), **other.to_dict()})
