"""Deterministic rules applied on top of the LLM's suggestion.

Small local models often get numbers and regions wrong (e.g. "10 milliard" -> 1 milliard).
Whatever can be read reliably from the text (budget, property type, region, name next to the
phone number) is parsed here with plain code and overrides the LLM. The LLM's own values are
kept only if they pass sanity checks (they must actually appear in the text).
Works even when the LLM is down.
"""
from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from app.domain.schemas import (MAX_BUDGET, _PHONE_RE, CustomerDraft, normalize_digits,
                                normalize_phone)

_ARABIC = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
_LETTERS = re.compile(r"[^\W\d_]+")          # runs of letters (Persian or Latin), no digits

# ---------------------------------------------------------------- budget
_UNIT_VALUE = {"میلیارد": 10 ** 9, "میلیون": 10 ** 6}
_WORD_NUM = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8, "نه": 9,
    "ده": 10, "پانزده": 15, "بیست": 20, "سی": 30, "چهل": 40, "پنجاه": 50, "شصت": 60,
    "هفتاد": 70, "هشتاد": 80, "نود": 90, "صد": 100,
}
_WORD_RE = re.compile(
    r"(?<![^\W\d_])(" + "|".join(sorted(_WORD_NUM, key=len, reverse=True)) + r")"
    r"(\s+و\s+نیم)?\s+(میلیارد|میلیون)(?![^\W\d_])")
_NUM = r"\d+(?:[.,/]\d+)*"
_RANGE_RE = re.compile(rf"({_NUM})\s*(میلیارد|میلیون)?\s*(?:تا|الی|-|–|—)\s*({_NUM})\s*(میلیارد|میلیون)")
_ONE_RE = re.compile(rf"({_NUM})\s*(میلیارد|میلیون)")
_PLAIN_RE = re.compile(r"(?<![\d.,/])(\d{1,3}(?:,\d{3}){2,}|\d{8,})(?![\d,])")


def _dec(s: str) -> Optional[Decimal]:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".").replace("/", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _amount(num: str, unit: str) -> Optional[int]:
    d = _dec(num)
    if d is None:
        return None
    n = int(d * _UNIT_VALUE[unit])
    return n if 0 < n <= MAX_BUDGET else None


def _words_to_digits(t: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        value = Decimal(_WORD_NUM[m.group(1)]) + (Decimal("0.5") if m.group(2) else 0)
        return f"{value} {m.group(3)}"
    return _WORD_RE.sub(repl, t)


def has_budget_hint(t: str) -> bool:
    return "میلیارد" in t or "میلیون" in t or bool(_PLAIN_RE.search(t))


def find_budget(t: str) -> Tuple[Optional[int], Optional[int]]:
    """(budget_min, budget_max) from text that has NO phone number in it.

    A single amount means "up to" (budget_max), unless preceded by "حداقل" (at least)."""
    t = _words_to_digits(t)
    m = _RANGE_RE.search(t)
    if m:
        lo = _amount(m.group(1), m.group(2) or m.group(4))
        hi = _amount(m.group(3), m.group(4))
        if lo and hi:
            return min(lo, hi), max(lo, hi)
    m = _ONE_RE.search(t)
    if m:
        n = _amount(m.group(1), m.group(2))
        if n:
            at_least = "حداقل" in t[max(0, m.start() - 12):m.start()]
            return (n, None) if at_least else (None, n)
    m = _PLAIN_RE.search(t)
    if m:
        d = _dec(m.group(1))
        if d is not None and 0 < int(d) <= MAX_BUDGET:
            return None, int(d)
    return None, None


# ---------------------------------------------------------------- property type
_TYPE_WORDS = {
    "land": {"زمین"},
    "apartment": {"آپارتمان", "اپارتمان", "آپارتمانی"},
    "villa": {"ویلا", "ویلایی"},
    "commercial": {"تجاری", "مغازه"},
    "garden": {"باغ", "باغچه"},
}
_WORD_TO_TYPE = {w: k for k, ws in _TYPE_WORDS.items() for w in ws}


def find_property_type(t: str) -> Tuple[Optional[str], int]:
    """(type, end position of the keyword) for the first property keyword in the text."""
    for m in _LETTERS.finditer(t):
        kind = _WORD_TO_TYPE.get(m.group())
        if kind:
            return kind, m.end()
    return None, 0


# ---------------------------------------------------------------- region
_STOP = {
    "بودجه", "تومان", "میلیارد", "میلیون", "حداکثر", "حداقل", "تا", "از", "در", "برای", "با", "و",
    "که", "به", "را", "است", "دارد", "می", "مشتری", "جدید", "دنبال", "منطقه", "محدوده", "ناحیه",
    "اطراف", "حوالی", "واقع", "نوع", "ملک", "متر", "متری", "شماره", "موبایل", "تماس",
}
_FILLERS = {"در", "برای", "واقع", "منطقه", "محدوده", "ناحیه", "اطراف", "حوالی"}
_NEXT_WORD = re.compile(r"\s+([^\W\d_]+)")
_DISTRICT_RE = re.compile(r"منطقه\s*(\d{1,2})(?!\d)")
_MARKER_RE = re.compile(r"(?:منطقه|محدوده|ناحیه|اطراف|حوالی)\s+([^\W\d_]+(?:\s+[^\W\d_]+)?)")


def _is_filler_word(w: str) -> bool:
    return w in _STOP or w in _WORD_TO_TYPE


def _region_after(t: str, pos: int) -> Optional[str]:
    words, skipped = [], False
    while len(words) < 2:
        m = _NEXT_WORD.match(t, pos)
        if not m:
            break
        w, pos = m.group(1), m.end()
        if not words and not skipped and w in _FILLERS:
            skipped = True
            continue
        if _is_filler_word(w):
            break
        words.append(w)
    return " ".join(words) or None


def find_region(t: str, type_end: int) -> Optional[str]:
    m = _DISTRICT_RE.search(t)
    if m:
        return f"منطقه {m.group(1)}"
    m = _MARKER_RE.search(t)
    if m:
        words = []
        for w in m.group(1).split():
            if _is_filler_word(w):
                break
            words.append(w)
        if words:
            return " ".join(words)
    if type_end:
        return _region_after(t, type_end)
    return None


def _grounded(value: Optional[str], t: str) -> Optional[str]:
    """Keep an LLM string only if it literally appears in the user's text."""
    if not value:
        return None
    v = " ".join(value.translate(_ARABIC).split())
    return v if v and v in t else None


def _grounded_location(value: Optional[str], t: str) -> Optional[str]:
    v = _grounded(value, t)
    if v and all(_is_filler_word(w) for w in v.split()):
        return None                     # e.g. the model answered "زمین" (the property type)
    return v


# ---------------------------------------------------------------- name
def find_name_before_phone(t: str) -> Optional[str]:
    """Up to 3 words right before the phone number, e.g. «علی رضایی 0912...»."""
    for m in _PHONE_RE.finditer(t):
        if normalize_phone(m.group()):
            words = [w.group() for w in _LETTERS.finditer(t[:m.start()])]
            name = []
            for w in reversed(words):
                if _is_filler_word(w) or len(name) == 3:
                    break
                name.append(w)
            return " ".join(reversed(name)) or None
    return None


# ---------------------------------------------------------------- entry point
def apply_text_rules(draft: CustomerDraft, text: str) -> CustomerDraft:
    """Combine the LLM draft with what plain code can read from the text.

    The phone number is handled by the caller (find_phone)."""
    t = " ".join(normalize_digits(text).translate(_ARABIC).split())
    name_rule = find_name_before_phone(t)
    # remove the phone number so its digits are never mistaken for a budget
    plain = t
    for m in _PHONE_RE.finditer(t):
        if normalize_phone(m.group()):
            plain = t[:m.start()] + " " + t[m.end():]
            break

    lo, hi = find_budget(plain)
    ptype, type_end = find_property_type(plain)
    location = _grounded_location(draft.preferred_location, plain) or find_region(plain, type_end)
    name = _grounded(draft.full_name, t) or name_rule

    base = replace(draft, full_name=None, preferred_location=None)
    if lo or hi or not has_budget_hint(plain):
        base = replace(base, budget_min=None, budget_max=None)   # parsed values win / LLM guessed
    found = CustomerDraft(full_name=name, budget_min=lo, budget_max=hi,
                          preferred_location=location, property_type=ptype)
    return base.merged(found)
