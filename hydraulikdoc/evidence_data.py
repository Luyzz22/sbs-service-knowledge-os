"""Stored facts that the control tests in :mod:`hydraulikdoc.evidence` re-perform.

These records carry pseudonyms of the acting persons, because a segregation-of-duties test has to
compare two of them. They are read with the ``evidence:read`` permission, stay on the server and are
never shown or exported as they are: a test result names records, not persons.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

EVIDENCE_PERMISSION = "evidence:read"
# The deletion job runs once a night; a record is overdue when it survives the following run as well.
RETENTION_GRACE = timedelta(hours=36)


@dataclass(frozen=True)
class DocumentStep:
    event_type: str
    actor_token: str
    actor_role: str
    occurred_at: datetime


@dataclass(frozen=True)
class DocumentEvidence:
    document_id: str
    uploader_token: str
    status: str
    release_status: str
    created_at: datetime
    released_at: datetime | None
    review_due_at: datetime | None
    withdrawn_at: datetime | None
    # Unknown on the development backend, which marks a document as deleted without a time.
    deleted_at: datetime | None
    steps: tuple[DocumentStep, ...] = ()


@dataclass(frozen=True)
class ReviewStep:
    status: str
    reason_code: str | None
    reviewer_token: str
    # Empty for reviews recorded before the role was stored.
    reviewer_role: str
    reviewed_at: datetime


@dataclass(frozen=True)
class AnswerEvidence:
    answer_id: str
    asker_token: str
    risk_class: str
    review_status: str
    generated_at: datetime
    document_ids: tuple[str, ...]
    reviews: tuple[ReviewStep, ...] = ()


@dataclass(frozen=True)
class IncidentStep:
    event_type: str
    previous_status: str | None
    new_status: str | None
    actor_token: str
    actor_role: str
    occurred_at: datetime


@dataclass(frozen=True)
class IncidentEvidence:
    incident_id: str
    severity: str
    status: str
    created_at: datetime
    # Analysis fields that meet the minimum length; the texts themselves are not read.
    documented_fields: frozenset[str]
    steps: tuple[IncidentStep, ...] = ()


@dataclass(frozen=True)
class LimitEvidence:
    limit_set_id: str
    asset_id: str
    version: int
    status: str
    proposer_token: str
    decider_token: str | None
    proposed_at: datetime
    decided_at: datetime | None
    source_document_id: str | None


@dataclass(frozen=True)
class PrivacyEvidence:
    request_id: str
    status: str
    requested_at: datetime
    due_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class HoldEvidence:
    hold_id: str
    record_classes: tuple[str, ...]
    review_at: datetime
    created_at: datetime
    released_at: datetime | None


@dataclass(frozen=True)
class NoticeEvidence:
    actor_token: str
    notice_type: str
    version: str
    accepted_at: datetime


@dataclass(frozen=True)
class RetentionEvidence:
    """Records of one class that are still stored although their retention date has passed."""

    record_class: str
    overdue: int
    oldest_due: datetime | None


@dataclass(frozen=True)
class DeniedAttempts:
    action: str
    reason_code: str
    count: int


@dataclass(frozen=True)
class AuditTrailEntry:
    sequence: int
    event_id: str
    occurred_at: datetime
    action: str
    outcome: str
    actor_token: str | None
    resource_type: str | None
    resource_token: str | None
    metadata: Mapping[str, Any]
    event_hash: str


@dataclass(frozen=True)
class EvidenceSnapshot:
    since: datetime
    until: datetime
    documents: tuple[DocumentEvidence, ...] = ()
    answers: tuple[AnswerEvidence, ...] = ()
    incidents: tuple[IncidentEvidence, ...] = ()
    limits: tuple[LimitEvidence, ...] = ()
    privacy_requests: tuple[PrivacyEvidence, ...] = ()
    legal_holds: tuple[HoldEvidence, ...] = ()
    notices: tuple[NoticeEvidence, ...] = ()
    retention: tuple[RetentionEvidence, ...] = ()
    denied: tuple[DeniedAttempts, ...] = ()
    # Names of the datasets that reached the row limit, so a test over them is marked incomplete.
    truncated: frozenset[str] = field(default_factory=frozenset)
