"""Deterministic reading of a property description (no LLM involved).

Example: «زمین 500 متری شمال 10 میلیارد» -> type land, area 500, region شمال, price 10 milliard.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from app.domain import parsing
from app.domain.parsing import _ARABIC
from app.domain.property_schemas import MAX_AREA_M2, PropertyDraft, _clean_location
from app.domain.schemas import _PHONE_RE, normalize_digits

_AREA_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:متر\s*مربع|مترمربع|متری|متر|m2|m²)(?![^\W\d_])", re.IGNORECASE)
_AREA_WORD_RE = re.compile(r"(?:متراژ|مساحت)\s*:?\s*(\d+(?:[.,]\d+)?)")
_NOISE_WORDS = {"قیمت", "متراژ", "مساحت", "مبلغ", "فروشی", "فروش", "حدود", "تقریبا", "تقریباً"}
_NOISE_RE = re.compile(r"(?<![^\W\d_])(?:" + "|".join(_NOISE_WORDS) + r")(?![^\W\d_])")
_JUNK = {"سلام", "درود", "ممنون", "مرسی", "ok", "hi", "hello"}


def _norm(text: str) -> str:
    return " ".join(normalize_digits(text).translate(_ARABIC).split())


def _to_area(raw: str) -> Optional[int]:
    try:
        n = int(float(raw.replace(",", ".")))
    except ValueError:
        return None
    return n if 0 < n <= MAX_AREA_M2 else None


def find_area(t: str) -> Tuple[Optional[int], str]:
    """(area in square meters, the text with the area expression cut out)."""
    for regex in (_AREA_UNIT_RE, _AREA_WORD_RE):
        m = regex.search(t)
        if m:
            area = _to_area(m.group(1))
            if area:
                return area, t[:m.start()] + " " + t[m.end():]
    return None, t


def find_price(t: str) -> Optional[int]:
    """One price in toman. For a range the higher amount is used."""
    lo, hi = parsing.find_budget(t)
    return hi or lo


def _strip_prices(t: str) -> str:
    t = parsing._words_to_digits(t)
    for regex in (parsing._RANGE_RE, parsing._ONE_RE, parsing._PLAIN_RE):
        t = regex.sub(" ", t)
    return t


def parse_property_text(text: str) -> PropertyDraft:
    """Everything that plain code can read from a free-text description."""
    t = _norm(text)
    for m in _PHONE_RE.finditer(t):          # a phone number must never become a price
        t = t[:m.start()] + " " + t[m.end():]
        break
    area, t = find_area(t)
    price = find_price(t)
    cleaned = _NOISE_RE.sub(" ", _strip_prices(t))
    cleaned = " ".join(cleaned.split())
    ptype, type_end = parsing.find_property_type(cleaned)
    location = parsing.find_region(cleaned, type_end)
    return PropertyDraft(property_type=ptype, location=_clean_location(location),
                         area_m2=area, price=price)


def parse_awaited(awaiting: Optional[str], text: str) -> PropertyDraft:
    """Parse the answer to the single question we asked."""
    t = _norm(text)
    if awaiting == "property_type":
        return PropertyDraft(property_type=parsing.find_property_type(t)[0])
    if awaiting == "area_m2":
        area, _ = find_area(t)
        if area is None and re.fullmatch(r"\d+(?:[.,]\d+)?", t):
            area = _to_area(t)
        return PropertyDraft(area_m2=area)
    if awaiting == "price":
        return PropertyDraft(price=find_price(t))
    if awaiting == "location":
        if t.lower() in _JUNK or parsing.find_property_type(t)[0]:
            return PropertyDraft()
        if _AREA_UNIT_RE.search(t) or parsing._ONE_RE.search(t):
            return PropertyDraft()
        return PropertyDraft(location=_clean_location(t))
    return PropertyDraft()
