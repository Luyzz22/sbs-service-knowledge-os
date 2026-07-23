"""Data-minimising audit events for security and compliance evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import json
import logging
from typing import Any, Mapping, Optional
import uuid


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


_ALLOWED_METADATA_KEYS = frozenset(
    {
        "collection",
        "document_count",
        "duration_ms",
        "error_code",
        "model",
        "page_count",
        "provider",
        "reason_code",
        "request_type",
        "role",
        "source_count",
        "status_code",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _sanitise_metadata(metadata: Optional[Mapping[str, Any]]) -> dict[str, Any]:
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

    def token(self, identifier: Optional[str]) -> Optional[str]:
        if not identifier:
            return None
        message = f"{self._namespace}:{identifier}".encode("utf-8")
        digest = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return f"psn_v1_{digest}"


@dataclass(frozen=True)
class AuditEvent:
    action: str
    outcome: AuditOutcome
    actor_token: Optional[str] = None
    subject_token: Optional[str] = None
    resource_type: Optional[str] = None
    resource_token: Optional[str] = None
    legal_basis: Optional[str] = None
    expires_at: Optional[datetime] = None
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
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._pseudonymizer = pseudonymizer
        self._logger = logger or logging.getLogger("hydraulikdoc.audit")

    def emit(
        self,
        *,
        action: str,
        outcome: AuditOutcome,
        actor_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        legal_basis: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        metadata: Optional[Mapping[str, Any]] = None,
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
