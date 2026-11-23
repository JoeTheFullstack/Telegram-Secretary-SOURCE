"""Shape + validation of property data (stdlib only). Prices are in toman."""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional

from app.domain.schemas import _clean_property_type, _clean_text, _to_int

TYPE_FA = {"land": "زمین", "apartment": "آپارتمان", "villa": "ویلا",
           "commercial": "تجاری", "garden": "باغ", "other": "سایر"}
REQUIRED_PROPERTY_FIELDS = ("property_type", "location", "area_m2", "price")
MAX_AREA_M2 = 10_000_000


def _clean_location(v: Any) -> Optional[str]:
    s = _clean_text(v, 100)
    if not s or len(s) < 2 or not re.search(r"[^\W\d_]", s):
        return None
    return s


def _clean_area(v: Any) -> Optional[int]:
    n = _to_int(v)
    return n if n is not None and n <= MAX_AREA_M2 else None


@dataclass(frozen=True)
class PropertyDraft:
    property_type: Optional[str] = None
    location: Optional[str] = None
    area_m2: Optional[int] = None
    price: Optional[int] = None

    @classmethod
    def from_raw(cls, data: Any) -> "PropertyDraft":
        """Build from an untrusted dict (session JSON). Invalid values become None."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            property_type=_clean_property_type(data.get("property_type")),
            location=_clean_location(data.get("location")),
            area_m2=_clean_area(data.get("area_m2")),
            price=_to_int(data.get("price")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)
                if getattr(self, f.name) is not None}

    def is_empty(self) -> bool:
        return not self.to_dict()

    def merged(self, other: "PropertyDraft") -> "PropertyDraft":
        """Values from `other` override this draft's values where they are set."""
        return PropertyDraft(**{**self.to_dict(), **other.to_dict()})

    def missing(self) -> List[str]:
        return [f for f in REQUIRED_PROPERTY_FIELDS if getattr(self, f) is None]

    def title(self) -> str:
        """Built automatically, e.g. «زمین 500 متری، شمال»."""
        return f"{TYPE_FA[self.property_type]} {self.area_m2} متری، {self.location}"
