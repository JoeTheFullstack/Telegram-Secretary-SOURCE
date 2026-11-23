"""Who may do what. Decided by the user's stored role, never by LLM output or message text."""
from __future__ import annotations

ROLES = ("owner", "manager", "staff", "customer")

_STAFF = {"chat", "customer.create", "property.create"}
ROLE_ACTIONS = {
    "customer": {"chat"},
    "staff": set(_STAFF),
    "manager": _STAFF | {"approve"},
    "owner": _STAFF | {"approve", "users.manage"},
}


class PermissionDenied(Exception):
    pass


def can(role: str, action: str) -> bool:
    return action in ROLE_ACTIONS.get(role, set())


def require(role: str, action: str) -> None:
    if not can(role, action):
        raise PermissionDenied(f"role '{role}' may not do '{action}'")
