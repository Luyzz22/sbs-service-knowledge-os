"""Authentication and authorization adapters for local development and Entra proxy auth."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import AppSettings, AuthMode, ConfigurationError

ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    "viewer": frozenset({"knowledge:read", "asset:read"}),
    "technician": frozenset(
        {
            "knowledge:read",
            "knowledge:write",
            "asset:read",
            "diagnostic:run",
            "incident:write",
            "review:write",
        }
    ),
    "supervisor": frozenset(
        {
            "knowledge:read",
            "knowledge:write",
            "asset:read",
            "asset:write",
            "diagnostic:run",
            "incident:write",
            "review:write",
            "analysis:export",
        }
    ),
    "admin": frozenset({"*"}),
}

_ROLE_ALIASES = {
    "hydraulikdoc.viewer": "viewer",
    "hydraulikdoc.technician": "technician",
    "hydraulikdoc.supervisor": "supervisor",
    "hydraulikdoc.admin": "admin",
}


@dataclass(frozen=True)
class UserPrincipal:
    subject_id: str
    tenant_id: str
    display_name: str
    role: str
    email: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    authentication_method: str = "unknown"

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


class AuthenticationError(RuntimeError):
    """Raised when identity evidence is missing or invalid."""


def _decode_principal(encoded: str) -> Mapping[str, Any]:
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = base64.b64decode(encoded + padding, validate=True)
        decoded = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthenticationError("Invalid Entra principal header") from error
    if not isinstance(decoded, dict):
        raise AuthenticationError("Invalid Entra principal payload")
    return decoded


def _claims(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for claim in payload.get("claims", []):
        if not isinstance(claim, dict):
            continue
        claim_type = str(claim.get("typ", ""))
        value = claim.get("val")
        if claim_type and isinstance(value, str):
            result.setdefault(claim_type, []).append(value)
    return result


def _first(claims: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = claims.get(name)
        if values:
            return values[0]
    return None


def principal_from_entra_header(encoded: str, default_tenant_id: str) -> UserPrincipal:
    payload = _decode_principal(encoded)
    claims = _claims(payload)
    subject = _first(
        claims,
        "http://schemas.microsoft.com/identity/claims/objectidentifier",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
        "oid",
        "sub",
    )
    tenant = (
        _first(
            claims,
            "http://schemas.microsoft.com/identity/claims/tenantid",
            "tid",
        )
        or default_tenant_id
    )
    display_name = _first(
        claims,
        "name",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    )
    email = _first(
        claims,
        "preferred_username",
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    )
    role_claim_type = str(payload.get("role_typ", "roles"))
    raw_roles = claims.get(role_claim_type, []) + claims.get("roles", [])
    mapped = {_ROLE_ALIASES.get(role.lower(), role.lower()) for role in raw_roles}
    mapped &= set(ROLE_PERMISSIONS)
    if not subject or not display_name:
        raise AuthenticationError("Entra principal is missing required identity claims")
    if not mapped:
        raise AuthenticationError("No HydraulikDoc application role assigned")
    role = max(mapped, key=lambda item: list(ROLE_PERMISSIONS).index(item))
    return UserPrincipal(
        subject_id=subject,
        tenant_id=tenant,
        display_name=display_name,
        email=email,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        authentication_method="entra_proxy",
    )


def verify_local_user(
    username: str,
    password: str,
    settings: AppSettings,
) -> UserPrincipal | None:
    if settings.auth_mode is not AuthMode.LOCAL or settings.is_production:
        raise AuthenticationError("Local password authentication is not permitted")
    record = settings.local_users().get(username)
    if not isinstance(record, dict):
        return None
    password_hash = record.get("password_hash")
    role = str(record.get("role", "viewer")).lower()
    if not isinstance(password_hash, str) or role not in ROLE_PERMISSIONS:
        raise ConfigurationError("Invalid local user record")
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import InvalidHashError, VerifyMismatchError

        PasswordHasher().verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return None
    return UserPrincipal(
        subject_id=f"local:{username}",
        tenant_id=settings.default_tenant_id,
        display_name=str(record.get("display_name") or username),
        email=None,
        role=role,
        permissions=ROLE_PERMISSIONS[role],
        authentication_method="local_argon2id",
    )


def require_permission(principal: UserPrincipal, permission: str) -> None:
    if not principal.can(permission):
        raise AuthenticationError(f"Permission denied: {permission}")
