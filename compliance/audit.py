"""Data-minimising audit events for security and compliance evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


_ALLOWED_METADATA_KEYS = frozenset(
    {
        "collection",
        "deletion_count",
        "deployment",
        "document_count",
        "duration_ms",
        "error_code",
        "evidence_id",
        "failure_count",
        "model",
        "page_count",
        "prompt_version",
        "provider",
        "reason_code",
        "region",
        "request_type",
        "review_status",
        "risk_class",
        "role",
        "source_count",
        "status_code",
        "tenant_count",
        "tenant_mode",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _sanitise_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only explicitly approved, bounded technical metadata."""
    if not metadata:
        return {}

    sanitised: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in _ALLOWED_METADATA_KEYS:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            sanitised[key] = value
        elif isinstance(value, str):
            sanitised[key] = value[:256]
    return sanitised


class SubjectPseudonymizer:
    """Create stable, non-reversible tokens without logging raw identifiers."""

    def __init__(self, secret: bytes, namespace: str = "hydraulikdoc") -> None:
        if len(secret) < 32:
            raise ValueError("The audit pseudonymisation secret must be at least 32 bytes")
        self._secret = secret
        self._namespace = namespace

    def token(self, identifier: str | None) -> str | None:
        if not identifier:
            return None
        message = f"{self._namespace}:{identifier}".encode()
        digest = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return f"psn_v1_{digest}"


@dataclass(frozen=True)
class AuditEvent:
    action: str
    outcome: AuditOutcome
    actor_token: str | None = None
    subject_token: str | None = None
    resource_type: str | None = None
    resource_token: str | None = None
    legal_basis: str | None = None
    expires_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.action or len(self.action) > 120:
            raise ValueError("action must contain between 1 and 120 characters")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        object.__setattr__(self, "metadata", _sanitise_metadata(self.metadata))

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["outcome"] = self.outcome.value
        record["occurred_at"] = _isoformat(self.occurred_at)
        record["expires_at"] = _isoformat(self.expires_at)
        return record


class AuditLogger:
    """Emit one-line JSON events to the application log pipeline."""

    def __init__(
        self,
        pseudonymizer: SubjectPseudonymizer,
        logger: logging.Logger | None = None,
    ) -> None:
        self._pseudonymizer = pseudonymizer
        self._logger = logger or logging.getLogger("hydraulikdoc.audit")

    def emit(
        self,
        *,
        action: str,
        outcome: AuditOutcome,
        actor_id: str | None = None,
        subject_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        legal_basis: str | None = None,
        expires_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            outcome=outcome,
            actor_token=self._pseudonymizer.token(actor_id),
            subject_token=self._pseudonymizer.token(subject_id),
            resource_type=resource_type,
            resource_token=self._pseudonymizer.token(resource_id),
            legal_basis=legal_basis,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self._logger.info(
            json.dumps(
                event.to_record(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return event
