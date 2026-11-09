"""Tenant-isolated persistence for application and compliance evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from compliance.audit import AuditEvent, AuditOutcome, SubjectPseudonymizer
from compliance.retention import RecordClass, RetentionPolicy

from .auth import UserPrincipal
from .config import AppSettings, PersistenceBackend
from .governance import GroundedAnswer, ReviewStatus
from .security import ValidatedUpload


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    tenant_id: str
    display_name: str
    sha256: str
    status: str
    page_count: int
    created_at: datetime
    retention_until: datetime
    release_status: str = "draft"
    revision: str = ""
    document_number: str = ""
    released_at: datetime | None = None
    review_due_at: datetime | None = None
    withdrawn_at: datetime | None = None
    withdrawal_reason: str = ""
    supersedes_document_id: str | None = None
    # True for the person who uploaded the document; they cannot release it themselves.
    is_own: bool = False

    @property
    def usable_for_answers(self) -> bool:
        """Only an indexed and released document may be retrieved as evidence."""
        return self.status == "ready" and self.release_status == "released"

    @property
    def release_recorded(self) -> bool:
        """False for documents that were in use before document control and still need a formal release."""
        return self.release_status != "released" or self.released_at is not None

    def review_overdue(self, now: datetime) -> bool:
        return self.release_status == "released" and self.review_due_at is not None and self.review_due_at <= now


@dataclass(frozen=True)
class DocumentEventRecord:
    event_id: str
    document_id: str
    event_type: str
    reason_code: str | None
    actor_role: str
    occurred_at: datetime
    is_own: bool = False


@dataclass(frozen=True)
class DocumentControl:
    """Revision data entered with an upload."""

    revision: str = "1"
    document_number: str = ""
    supersedes_document_id: str | None = None


@dataclass(frozen=True)
class DocumentRelease:
    document: DocumentRecord
    # The previous revision that this release took out of use, and how many stored answers cite it.
    superseded: DocumentRecord | None = None
    superseded_answer_count: int = 0


@dataclass(frozen=True)
class DocumentWithdrawal:
    document: DocumentRecord
    cited_answer_count: int


DOCUMENT_RELEASE_PERMISSION = "document:release"
DOCUMENT_REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,15}")
DOCUMENT_NUMBER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,63}")
DOCUMENT_WITHDRAWAL_REASONS = ("obsolete", "incorrect", "safety_notice", "no_longer_applicable")
# Set by the system when a newer revision is released; it cannot be chosen by hand.
DOCUMENT_SUPERSEDED_REASON = "superseded"
# A released document must come up for review within a year; an overdue review does not block answers.
DOCUMENT_MAX_REVIEW = timedelta(days=366)


def _check_document_control(
    control: DocumentControl, predecessor: DocumentRecord | None, successor_pending: bool
) -> DocumentControl:
    """Normalised revision data for a new upload; a replaced document must currently be in force."""
    revision = control.revision.strip()
    number = control.document_number.strip()
    if not DOCUMENT_REVISION_PATTERN.fullmatch(revision):
        raise ValueError("DOCUMENT_REVISION_INVALID")
    if number and not DOCUMENT_NUMBER_PATTERN.fullmatch(number):
        raise ValueError("DOCUMENT_NUMBER_INVALID")
    if control.supersedes_document_id is None:
        return DocumentControl(revision, number, None)
    if predecessor is None or predecessor.release_status != "released":
        raise ValueError("DOCUMENT_SUPERSEDES_INVALID")
    if successor_pending:
        raise ValueError("DOCUMENT_SUPERSEDES_PENDING")
    if revision == predecessor.revision:
        raise ValueError("DOCUMENT_REVISION_UNCHANGED")
    return DocumentControl(revision, number or predecessor.document_number, predecessor.document_id)


def _require_document_release(principal: UserPrincipal) -> None:
    if not principal.can(DOCUMENT_RELEASE_PERMISSION):
        raise PermissionError("DOCUMENT_RELEASE_REQUIRED")


def _check_review_date(review_due_at: datetime, now: datetime) -> None:
    if review_due_at.tzinfo is None or not now < review_due_at <= now + DOCUMENT_MAX_REVIEW:
        raise ValueError("DOCUMENT_REVIEW_DATE_INVALID")


def _check_document_release(document: DocumentRecord, review_due_at: datetime, now: datetime) -> None:
    """Fail closed unless the document can be released by this person; withdrawal is final."""
    if document.release_status == "withdrawn":
        raise ValueError("DOCUMENT_WITHDRAWN")
    if document.release_status == "released" and document.released_at is not None:
        raise ValueError("DOCUMENT_ALREADY_RELEASED")
    if document.status != "ready":
        raise ValueError("DOCUMENT_NOT_INDEXED")
    if document.is_own:
        raise PermissionError("FOUR_EYES_RELEASE_REQUIRED")
    _check_review_date(review_due_at, now)


def _check_document_withdrawal(document: DocumentRecord, reason_code: str) -> None:
    if reason_code not in DOCUMENT_WITHDRAWAL_REASONS:
        raise ValueError("DOCUMENT_WITHDRAWAL_REASON_INVALID")
    if document.release_status != "released":
        raise ValueError("DOCUMENT_NOT_RELEASED")


def _check_document_review(document: DocumentRecord, review_due_at: datetime, now: datetime) -> None:
    if document.release_status != "released":
        raise ValueError("DOCUMENT_NOT_RELEASED")
    if document.released_at is None:
        raise ValueError("DOCUMENT_RELEASE_NOT_RECORDED")
    _check_review_date(review_due_at, now)


def require_document_deletion(principal: UserPrincipal, repository: EnterpriseRepository, document_id: str) -> None:
    """Taking a released document out of use is a release decision, not an upload right.

    Drafts, withdrawn and failed documents stay deletable with the upload permission. An unknown id
    passes so that a repeated deletion can still clean up search and storage.
    """
    if principal.can(DOCUMENT_RELEASE_PERMISSION):
        return
    for document in repository.list_documents(principal):
        if document.document_id == document_id and document.release_status == "released":
            raise PermissionError("DOCUMENT_RELEASE_REQUIRED")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    tenant_id: str
    asset_id: str
    title: str
    severity: str
    status: str
    created_at: datetime
    details: str = ""
    updated_at: datetime | None = None
    containment_action: str = ""
    root_cause: str = ""
    corrective_action: str = ""
    effectiveness_check: str = ""


@dataclass(frozen=True)
class IncidentEventRecord:
    event_id: str
    incident_id: str
    event_type: str
    previous_status: str | None
    new_status: str | None
    actor_role: str
    occurred_at: datetime
    is_own: bool


@dataclass(frozen=True)
class StatusChange:
    previous_status: str | None
    new_status: str
    occurred_at: datetime


@dataclass(frozen=True)
class IncidentLifecycle:
    """Workflow timeline of one incident for asset-level figures; deliberately carries no actor data."""

    incident_id: str
    asset_id: str
    severity: str
    status: str
    created_at: datetime
    changes: tuple[StatusChange, ...]


INCIDENT_STATUSES = ("new", "acknowledged", "in_progress", "resolved", "closed")
INCIDENT_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "new": ("acknowledged", "in_progress"),
    "acknowledged": ("in_progress",),
    "in_progress": ("resolved",),
    "resolved": ("closed", "in_progress"),
    "closed": (),
}
INCIDENT_CLOSE_PERMISSION = "incident:close"


# 8D-light: severe incidents need containment, root cause and corrective action before they can be
# reported as resolved, and a documented effectiveness check before supervisor sign-off.
EIGHT_D_SEVERITIES = frozenset({"critical", "p1", "p2"})
INCIDENT_ANALYSIS_FIELDS = ("containment_action", "root_cause", "corrective_action", "effectiveness_check")
INCIDENT_ANALYSIS_MIN_CHARS = 10
INCIDENT_ANALYSIS_MAX_CHARS = 4000


class IncidentTransitionRejected(ValueError):
    """Raised when a requested incident change is not permitted by the workflow."""


def missing_analysis_fields(incident: IncidentRecord, target: str) -> tuple[str, ...]:
    """Return the analysis fields that must be documented before moving the incident to ``target``."""
    eight_d = incident.severity in EIGHT_D_SEVERITIES
    required: tuple[str, ...]
    if target == "resolved":
        required = ("containment_action", "root_cause", "corrective_action") if eight_d else ("corrective_action",)
    elif target == "closed" and eight_d:
        required = ("effectiveness_check",)
    else:
        required = ()
    return tuple(field for field in required if len(getattr(incident, field).strip()) < INCIDENT_ANALYSIS_MIN_CHARS)


def check_incident_transition(principal: UserPrincipal, current: IncidentRecord, expected: str, target: str) -> None:
    """Fail closed unless the role may perform this workflow step from the persisted status."""
    if not principal.can("incident:write"):
        raise PermissionError("INCIDENT_WRITE_REQUIRED")
    if current.status != expected:
        raise IncidentTransitionRejected("INCIDENT_STALE_STATUS")
    if target not in INCIDENT_TRANSITIONS.get(current.status, ()):
        raise IncidentTransitionRejected(f"INCIDENT_TRANSITION_{current.status}_TO_{target}".upper())
    if target == "closed" and not principal.can(INCIDENT_CLOSE_PERMISSION):
        raise PermissionError("INCIDENT_CLOSE_REQUIRED")
    if missing_analysis_fields(current, target):
        raise IncidentTransitionRejected("INCIDENT_ANALYSIS_INCOMPLETE")


def _check_analysis_update(principal: UserPrincipal, current: IncidentRecord, expected_updated_at: datetime) -> None:
    if not principal.can("incident:write"):
        raise PermissionError("INCIDENT_WRITE_REQUIRED")
    if current.status == "closed":
        raise IncidentTransitionRejected("INCIDENT_CLOSED")
    if current.updated_at != expected_updated_at:
        raise IncidentTransitionRejected("INCIDENT_STALE_VERSION")


def _bounded_analysis(values: Mapping[str, str]) -> dict[str, str]:
    return {field: values[field].strip()[:INCIDENT_ANALYSIS_MAX_CHARS] for field in INCIDENT_ANALYSIS_FIELDS}


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    tenant_id: str
    name: str
    site: str
    manufacturer: str
    model: str
    criticality: str
    status: str
    updated_at: datetime
    functional_location: str = ""
    equipment_number: str = ""


@dataclass(frozen=True)
class LegalHoldRecord:
    hold_id: str
    tenant_id: str
    case_reference: str
    reason_code: str
    record_classes: tuple[str, ...]
    review_at: datetime
    created_at: datetime
    released_at: datetime | None = None

    def review_overdue(self, now: datetime) -> bool:
        return self.released_at is None and self.review_at <= now


LEGAL_HOLD_PERMISSION = "legal_hold:manage"
LEGAL_HOLD_REASONS = ("litigation", "authority_request", "internal_investigation", "warranty_claim")
LEGAL_HOLD_CASE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,63}")
# A hold must come up for review within a year; it is never released automatically.
LEGAL_HOLD_MAX_REVIEW = timedelta(days=366)


def _check_legal_hold(
    principal: UserPrincipal,
    case_reference: str,
    reason_code: str,
    record_classes: tuple[str, ...],
    review_at: datetime,
    now: datetime,
) -> tuple[str, tuple[str, ...]]:
    if not principal.can(LEGAL_HOLD_PERMISSION):
        raise PermissionError("LEGAL_HOLD_MANAGE_REQUIRED")
    reference = case_reference.strip()
    if not LEGAL_HOLD_CASE_PATTERN.fullmatch(reference):
        raise ValueError("LEGAL_HOLD_CASE_REFERENCE_INVALID")
    if reason_code not in LEGAL_HOLD_REASONS:
        raise ValueError("LEGAL_HOLD_REASON_INVALID")
    classes = tuple(sorted(set(record_classes)))
    if not classes or not set(classes) <= {item.value for item in RecordClass}:
        raise ValueError("LEGAL_HOLD_SCOPE_INVALID")
    if review_at.tzinfo is None or not now < review_at <= now + LEGAL_HOLD_MAX_REVIEW:
        raise ValueError("LEGAL_HOLD_REVIEW_DATE_INVALID")
    return reference, classes


@dataclass(frozen=True)
class PrivacyRequestRecord:
    request_id: str
    tenant_id: str
    request_type: str
    status: str
    requested_at: datetime
    due_at: datetime
    completed_at: datetime | None = None
    evidence_reference: str | None = None
    decision_reason: str | None = None

    def overdue(self, now: datetime) -> bool:
        return self.status in PRIVACY_OPEN_STATUSES and self.due_at <= now


PRIVACY_MANAGE_PERMISSION = "privacy:manage"
PRIVACY_OPEN_STATUSES = frozenset({"submitted", "identity_verified", "in_review"})
PRIVACY_REQUEST_TRANSITIONS: Mapping[str, tuple[str, ...]] = {
    "submitted": ("identity_verified", "denied"),
    "identity_verified": ("in_review", "denied"),
    "in_review": ("completed", "denied"),
}
PRIVACY_DECISION_REASONS: Mapping[str, tuple[str, ...]] = {
    "completed": ("fulfilled", "no_data"),
    # Art. 12 (5), Art. 17 (3) (b) and (e) GDPR, or an identity that could not be verified.
    "denied": ("identity_not_verified", "legal_hold", "retention_obligation", "manifestly_unfounded"),
}
PRIVACY_EVIDENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,63}")


class PrivacyTransitionRejected(ValueError):
    """Raised when a privacy request change is not permitted by the case workflow."""


def _check_privacy_decision(
    principal: UserPrincipal,
    current: PrivacyRequestRecord,
    owner_is_principal: bool,
    expected: str,
    target: str,
    decision_reason: str | None,
    evidence_reference: str | None,
) -> str | None:
    """Fail closed unless the step is allowed; returns the normalised evidence reference."""
    if not principal.can(PRIVACY_MANAGE_PERMISSION):
        raise PermissionError("PRIVACY_MANAGE_REQUIRED")
    if owner_is_principal:
        raise PrivacyTransitionRejected("PRIVACY_OWN_REQUEST")
    if current.status != expected:
        raise PrivacyTransitionRejected("PRIVACY_STALE_STATUS")
    if target not in PRIVACY_REQUEST_TRANSITIONS.get(current.status, ()):
        raise PrivacyTransitionRejected(f"PRIVACY_TRANSITION_{current.status}_TO_{target}".upper())
    if target not in PRIVACY_DECISION_REASONS:
        return None
    if decision_reason not in PRIVACY_DECISION_REASONS[target]:
        raise PrivacyTransitionRejected("PRIVACY_DECISION_REASON_REQUIRED")
    reference = (evidence_reference or "").strip()
    if not PRIVACY_EVIDENCE_PATTERN.fullmatch(reference):
        raise PrivacyTransitionRejected("PRIVACY_EVIDENCE_REFERENCE_REQUIRED")
    return reference


def _principal_token(pseudonymizer: SubjectPseudonymizer, principal: UserPrincipal) -> str:
    token = pseudonymizer.token(principal.subject_id)
    if token is None:
        raise ValueError("Authenticated principal requires a subject identifier")
    return token


class EnterpriseRepository(Protocol):
    def upsert_asset(
        self,
        principal: UserPrincipal,
        *,
        asset_id: str,
        name: str,
        site: str,
        manufacturer: str,
        model: str,
        criticality: str,
        functional_location: str = "",
        equipment_number: str = "",
    ) -> AssetRecord: ...

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]: ...

    def register_document(
        self, principal: UserPrincipal, upload: ValidatedUpload, control: DocumentControl | None = None
    ) -> DocumentRecord: ...

    def mark_document_indexed(self, principal: UserPrincipal, document_id: str, page_count: int) -> None: ...

    def mark_document_failed(self, principal: UserPrincipal, document_id: str) -> None: ...

    def list_documents(self, principal: UserPrincipal) -> tuple[DocumentRecord, ...]: ...

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None: ...

    def release_document(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRelease: ...

    def withdraw_document(self, principal: UserPrincipal, document_id: str, reason_code: str) -> DocumentWithdrawal: ...

    def confirm_document_review(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRecord: ...

    def list_document_events(self, principal: UserPrincipal, document_id: str) -> tuple[DocumentEventRecord, ...]: ...

    def record_answer(self, principal: UserPrincipal, question: str, answer: GroundedAnswer) -> None: ...

    def record_review(
        self,
        principal: UserPrincipal,
        answer_id: str,
        status: ReviewStatus,
        reason_code: str | None = None,
    ) -> None: ...

    def answer_review_status(self, principal: UserPrincipal, answer_id: str) -> ReviewStatus: ...

    def create_incident(
        self,
        principal: UserPrincipal,
        *,
        asset_id: str,
        title: str,
        severity: str,
        details: str,
    ) -> IncidentRecord: ...

    def list_incidents(self, principal: UserPrincipal) -> tuple[IncidentRecord, ...]: ...

    def transition_incident(
        self, principal: UserPrincipal, incident_id: str, *, expected: str, target: str
    ) -> IncidentRecord: ...

    def update_incident_analysis(
        self,
        principal: UserPrincipal,
        incident_id: str,
        *,
        expected_updated_at: datetime,
        analysis: Mapping[str, str],
    ) -> IncidentRecord: ...

    def list_incident_events(self, principal: UserPrincipal, incident_id: str) -> tuple[IncidentEventRecord, ...]: ...

    def list_incident_lifecycles(
        self, principal: UserPrincipal, *, since: datetime, limit: int
    ) -> tuple[IncidentLifecycle, ...]: ...

    def record_acceptance(self, principal: UserPrincipal, notice_type: str, version: str, digest: str) -> None: ...

    def has_acceptance(self, principal: UserPrincipal, notice_type: str, version: str) -> bool: ...

    def create_privacy_request(self, principal: UserPrincipal, request_type: str) -> PrivacyRequestRecord: ...

    def list_privacy_requests(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]: ...

    def list_privacy_queue(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]: ...

    def decide_privacy_request(
        self,
        principal: UserPrincipal,
        request_id: str,
        *,
        expected: str,
        target: str,
        decision_reason: str | None = None,
        evidence_reference: str | None = None,
    ) -> PrivacyRequestRecord: ...

    def subject_export(self, principal: UserPrincipal) -> Mapping[str, Any]: ...

    def emit_audit(
        self,
        principal: UserPrincipal,
        *,
        action: str,
        outcome: AuditOutcome,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent: ...

    def verify_audit_chain(
        self, principal: UserPrincipal, anchor: tuple[int, str] | None = None
    ) -> AuditChainReport: ...

    def create_legal_hold(
        self,
        principal: UserPrincipal,
        *,
        case_reference: str,
        reason_code: str,
        record_classes: tuple[str, ...],
        review_at: datetime,
    ) -> LegalHoldRecord: ...

    def release_legal_hold(self, principal: UserPrincipal, hold_id: str) -> LegalHoldRecord: ...

    def list_legal_holds(self, principal: UserPrincipal) -> tuple[LegalHoldRecord, ...]: ...


def _now() -> datetime:
    return datetime.now(UTC)


# v2 adds uploaded documents, given reviews and own incident steps (GDPR Art. 15 completeness);
# v3 adds the person's own document control steps (upload, release, withdrawal, review).
SUBJECT_EXPORT_SCHEMA = "hydraulikdoc.subject-export.v3"


def _document_step(event: DocumentEventRecord) -> dict[str, Any]:
    return {
        "document_id": event.document_id,
        "event_type": event.event_type,
        "reason_code": event.reason_code,
        "actor_role": event.actor_role,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _incident_step(event: IncidentEventRecord) -> dict[str, Any]:
    return {
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "actor_role": event.actor_role,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _audit_chain_key(secret: str) -> bytes:
    return hmac.new(
        secret.encode(),
        b"hydraulikdoc:audit-chain:v1",
        hashlib.sha256,
    ).digest()


def _audit_lock_key(tenant_id: str) -> int:
    """Stable signed 64-bit advisory lock key for one tenant's audit chain."""
    digest = hashlib.sha256(b"hydraulikdoc-audit-chain:" + tenant_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


AUDIT_VERIFY_PERMISSION = "audit:verify"


@dataclass(frozen=True)
class AuditChainReport:
    """Result of recomputing one tenant's audit hash chain."""

    event_count: int
    intact: bool
    first_sequence: int | None
    head_sequence: int | None
    head_hash: str | None
    # The oldest kept event points to a predecessor that retention has purged.
    starts_after_purge: bool
    broken_sequence: int | None = None
    reason: str | None = None
    # Comparison with a head recorded outside the database by an earlier run: MATCH, PURGED or a failure.
    anchor_status: str | None = None


def verify_audit_chain_rows(
    key: bytes,
    rows: Iterable[tuple[int, str | None, str, AuditEvent]],
    anchor: tuple[int, str] | None = None,
) -> AuditChainReport:
    """Recompute every event hash and link in sequence order.

    A changed event fails HASH_MISMATCH, a removed or reordered event fails LINK_MISMATCH. Deleting the
    newest events leaves a valid but shorter chain; only an anchor kept outside the database (an earlier
    run's head) reveals that, as ANCHOR_MISSING or ANCHOR_MISMATCH.
    """
    count = 0
    first: int | None = None
    head: tuple[int, str] | None = None
    starts_after_purge = False
    anchored_hash: str | None = None
    for sequence, previous, stored, event in rows:
        if head is None:
            first = sequence
            starts_after_purge = previous is not None
        reason = None
        if head is not None and previous != head[1]:
            reason = "LINK_MISMATCH"
        elif not hmac.compare_digest(_event_hash(key, previous, event), stored.strip()):
            reason = "HASH_MISMATCH"
        if reason:
            return AuditChainReport(
                count,
                False,
                first,
                head[0] if head else None,
                head[1] if head else None,
                starts_after_purge,
                sequence,
                reason,
            )
        count += 1
        head = (sequence, stored.strip())
        if anchor and sequence == anchor[0]:
            anchored_hash = head[1]
    anchor_status = None
    if anchor:
        if anchored_hash is not None:
            anchor_status = "MATCH" if hmac.compare_digest(anchored_hash, anchor[1]) else "ANCHOR_MISMATCH"
        elif first is not None and anchor[0] < first:
            anchor_status = "PURGED"
        else:
            anchor_status = "ANCHOR_MISSING"
    intact = anchor_status not in {"ANCHOR_MISMATCH", "ANCHOR_MISSING"}
    return AuditChainReport(
        count,
        intact,
        first,
        head[0] if head else None,
        head[1] if head else None,
        starts_after_purge,
        reason=None if intact else anchor_status,
        anchor_status=anchor_status,
    )


def _event_hash(key: bytes, previous_hash: str | None, event: AuditEvent) -> str:
    material = {
        "previous_hash": previous_hash,
        "event": event.to_record(),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


class InMemoryRepository:
    """Development repository. Production configuration forbids this backend."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._retention = RetentionPolicy.from_environment()
        self._pseudonymizer = SubjectPseudonymizer(settings.audit_hmac_key.encode("utf-8"))
        self._audit_chain_key = _audit_chain_key(settings.audit_hmac_key)
        self._documents: dict[tuple[str, str], DocumentRecord] = {}
        self._assets: dict[tuple[str, str], AssetRecord] = {}
        self._answers: dict[tuple[str, str], tuple[str, GroundedAnswer]] = {}
        self._reviews: dict[tuple[str, str], ReviewStatus] = {}
        self._incidents: dict[tuple[str, str], IncidentRecord] = {}
        self._incident_events: list[tuple[str, str, IncidentEventRecord]] = []
        self._document_events: list[tuple[str, str, DocumentEventRecord]] = []
        self._acceptances: set[tuple[str, str, str, str]] = set()
        self._privacy_requests: dict[tuple[str, str], tuple[str, PrivacyRequestRecord]] = {}
        self._audit: list[tuple[AuditEvent, str]] = []
        self._scripted_times: dict[str, datetime] = {}
        # Pseudonyms of uploaders, reviewers and reporters, kept apart from the records like the database columns.
        self._uploaders: dict[tuple[str, str], str] = {}
        self._review_log: list[tuple[str, str, str, ReviewStatus, datetime]] = []
        self._reporters: dict[tuple[str, str], str] = {}
        self._legal_holds: dict[tuple[str, str], LegalHoldRecord] = {}
        self._lock = RLock()

    @contextmanager
    def scripted_time(self, principal: UserPrincipal, at: datetime) -> Iterator[None]:
        """Record this tenant's incident workflow at ``at`` instead of now.

        Only the demo seed uses this to stage a realistic history. It exists solely on the development
        backend: workflow times in PostgreSQL are always server time and cannot be backdated.
        """
        with self._lock:
            self._scripted_times[principal.tenant_id] = at
        try:
            yield
        finally:
            with self._lock:
                self._scripted_times.pop(principal.tenant_id, None)

    def _incident_time(self, principal: UserPrincipal) -> datetime:
        return self._scripted_times.get(principal.tenant_id) or _now()

    def upsert_asset(
        self,
        principal: UserPrincipal,
        *,
        asset_id: str,
        name: str,
        site: str,
        manufacturer: str,
        model: str,
        criticality: str,
        functional_location: str = "",
        equipment_number: str = "",
    ) -> AssetRecord:
        record = AssetRecord(
            asset_id=asset_id[:120],
            tenant_id=principal.tenant_id,
            name=name[:240],
            site=site[:240],
            manufacturer=manufacturer[:160],
            model=model[:160],
            criticality=criticality,
            status="active",
            updated_at=_now(),
            functional_location=functional_location[:40],
            equipment_number=equipment_number[:18],
        )
        with self._lock:
            self._assets[(principal.tenant_id, record.asset_id)] = record
        return record

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]:
        with self._lock:
            return tuple(item for (tenant, _), item in self._assets.items() if tenant == principal.tenant_id)

    def _find_document(self, tenant_id: str, document_id: str | None, actor: str | None) -> DocumentRecord | None:
        current = self._documents.get((tenant_id, document_id or ""))
        if current is None or current.status == "deleted":
            return None
        return replace(current, is_own=self._uploaders.get((tenant_id, current.document_id)) == actor)

    def _append_document_event(
        self,
        principal: UserPrincipal,
        actor: str,
        document_id: str,
        event_type: str,
        reason_code: str | None,
        occurred_at: datetime,
    ) -> None:
        event = DocumentEventRecord(
            str(uuid.uuid4()), document_id, event_type, reason_code, principal.role[:40], occurred_at
        )
        self._document_events.append((principal.tenant_id, actor, event))

    def _citing_answers(self, tenant_id: str, document_id: str) -> int:
        return sum(
            1
            for (tenant, _), (_, answer) in self._answers.items()
            if tenant == tenant_id and any(item.document_id == document_id for item in answer.citations)
        )

    def register_document(
        self, principal: UserPrincipal, upload: ValidatedUpload, control: DocumentControl | None = None
    ) -> DocumentRecord:
        created = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        requested = control or DocumentControl()
        replaced = requested.supersedes_document_id
        with self._lock:
            predecessor = self._find_document(principal.tenant_id, replaced, actor) if replaced else None
            pending = replaced is not None and any(
                item.supersedes_document_id == replaced
                and item.release_status == "draft"
                and item.status not in ("deleted", "failed")
                for (tenant, _), item in self._documents.items()
                if tenant == principal.tenant_id
            )
            checked = _check_document_control(requested, predecessor, pending)
            record = DocumentRecord(
                document_id=upload.document_id,
                tenant_id=principal.tenant_id,
                display_name=upload.display_name,
                sha256=upload.sha256,
                status="processing",
                page_count=0,
                created_at=created,
                retention_until=self._retention.expires_at(RecordClass.UPLOADED_CONTENT, created),
                release_status="draft",
                revision=checked.revision,
                document_number=checked.document_number,
                supersedes_document_id=checked.supersedes_document_id,
            )
            duplicate = any(
                item.sha256 == record.sha256 and item.status != "deleted"
                for (tenant, _), item in self._documents.items()
                if tenant == principal.tenant_id
            )
            if duplicate:
                raise ValueError("Dieses Dokument wurde für den Mandanten bereits erfasst.")
            self._documents[(principal.tenant_id, record.document_id)] = record
            self._uploaders[(principal.tenant_id, record.document_id)] = actor
            self._append_document_event(principal, actor, record.document_id, "uploaded", None, created)
        return replace(record, is_own=True)

    def mark_document_indexed(self, principal: UserPrincipal, document_id: str, page_count: int) -> None:
        key = (principal.tenant_id, document_id)
        with self._lock:
            current = self._documents[key]
            self._documents[key] = replace(current, status="ready", page_count=page_count)

    def mark_document_failed(self, principal: UserPrincipal, document_id: str) -> None:
        key = (principal.tenant_id, document_id)
        with self._lock:
            current = self._documents[key]
            self._documents[key] = replace(current, status="failed", retention_until=_now())

    def list_documents(self, principal: UserPrincipal) -> tuple[DocumentRecord, ...]:
        actor = self._pseudonymizer.token(principal.subject_id)
        with self._lock:
            return tuple(
                replace(item, is_own=self._uploaders.get((tenant, document_id)) == actor)
                for (tenant, document_id), item in self._documents.items()
                if tenant == principal.tenant_id and item.status != "deleted"
            )

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None:
        key = (principal.tenant_id, document_id)
        with self._lock:
            current = self._documents[key]
            self._documents[key] = replace(current, status="deleted")

    def release_document(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRelease:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        tenant = principal.tenant_id
        with self._lock:
            current = self._find_document(tenant, document_id, actor)
            if current is None:
                raise KeyError(document_id)
            _check_document_release(current, review_due_at, now)
            released = replace(current, release_status="released", released_at=now, review_due_at=review_due_at)
            self._documents[(tenant, document_id)] = replace(released, is_own=False)
            self._append_document_event(principal, actor, document_id, "released", None, now)
            superseded = None
            cited = 0
            previous = self._find_document(tenant, current.supersedes_document_id, actor)
            if previous is not None and previous.release_status == "released":
                superseded = replace(
                    previous,
                    release_status="withdrawn",
                    withdrawn_at=now,
                    withdrawal_reason=DOCUMENT_SUPERSEDED_REASON,
                )
                self._documents[(tenant, previous.document_id)] = replace(superseded, is_own=False)
                self._append_document_event(
                    principal, actor, previous.document_id, "withdrawn", DOCUMENT_SUPERSEDED_REASON, now
                )
                cited = self._citing_answers(tenant, previous.document_id)
        return DocumentRelease(released, superseded, cited)

    def withdraw_document(self, principal: UserPrincipal, document_id: str, reason_code: str) -> DocumentWithdrawal:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        tenant = principal.tenant_id
        with self._lock:
            current = self._find_document(tenant, document_id, actor)
            if current is None:
                raise KeyError(document_id)
            _check_document_withdrawal(current, reason_code)
            withdrawn = replace(current, release_status="withdrawn", withdrawn_at=now, withdrawal_reason=reason_code)
            self._documents[(tenant, document_id)] = replace(withdrawn, is_own=False)
            self._append_document_event(principal, actor, document_id, "withdrawn", reason_code, now)
            return DocumentWithdrawal(withdrawn, self._citing_answers(tenant, document_id))

    def confirm_document_review(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRecord:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        tenant = principal.tenant_id
        with self._lock:
            current = self._find_document(tenant, document_id, actor)
            if current is None:
                raise KeyError(document_id)
            _check_document_review(current, review_due_at, now)
            confirmed = replace(current, review_due_at=review_due_at)
            self._documents[(tenant, document_id)] = replace(confirmed, is_own=False)
            self._append_document_event(principal, actor, document_id, "review_confirmed", None, now)
            return confirmed

    def list_document_events(self, principal: UserPrincipal, document_id: str) -> tuple[DocumentEventRecord, ...]:
        subject = self._pseudonymizer.token(principal.subject_id)
        with self._lock:
            return tuple(
                replace(event, is_own=actor == subject)
                for tenant, actor, event in self._document_events
                if tenant == principal.tenant_id and event.document_id == document_id
            )

    def record_answer(self, principal: UserPrincipal, question: str, answer: GroundedAnswer) -> None:
        del question
        actor = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            self._answers[(principal.tenant_id, answer.answer_id)] = (actor, answer)

    def record_review(
        self,
        principal: UserPrincipal,
        answer_id: str,
        status: ReviewStatus,
        reason_code: str | None = None,
    ) -> None:
        del reason_code
        reviewer = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            stored = self._answers.get((principal.tenant_id, answer_id))
            if stored is None:
                raise KeyError(answer_id)
            actor, answer = stored
            if status is ReviewStatus.ACCEPTED and answer.risk_class.value == "heightened" and actor == reviewer:
                raise PermissionError("FOUR_EYES_REVIEW_REQUIRED")
            self._reviews[(principal.tenant_id, answer_id)] = status
            self._review_log.append((principal.tenant_id, reviewer, answer_id, status, _now()))

    def answer_review_status(self, principal: UserPrincipal, answer_id: str) -> ReviewStatus:
        with self._lock:
            stored = self._answers.get((principal.tenant_id, answer_id))
            if stored is None:
                raise KeyError(answer_id)
            return self._reviews.get((principal.tenant_id, answer_id), stored[1].review_status)

    def create_incident(
        self,
        principal: UserPrincipal,
        *,
        asset_id: str,
        title: str,
        severity: str,
        details: str,
    ) -> IncidentRecord:
        created = self._incident_time(principal)
        record = IncidentRecord(
            incident_id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            asset_id=asset_id[:120],
            title=title[:240],
            severity=severity,
            status="new",
            created_at=created,
            details=details[:8000],
            updated_at=created,
        )
        with self._lock:
            self._incidents[(principal.tenant_id, record.incident_id)] = record
            self._reporters[(principal.tenant_id, record.incident_id)] = _principal_token(
                self._pseudonymizer, principal
            )
            self._record_incident_event(principal, record.incident_id, "created", None, "new")
        return record

    def _record_incident_event(
        self,
        principal: UserPrincipal,
        incident_id: str,
        event_type: str,
        previous_status: str | None,
        new_status: str | None,
    ) -> None:
        actor = _principal_token(self._pseudonymizer, principal)
        event = IncidentEventRecord(
            str(uuid.uuid4()),
            incident_id,
            event_type,
            previous_status,
            new_status,
            principal.role,
            self._incident_time(principal),
            False,
        )
        self._incident_events.append((principal.tenant_id, actor, event))

    def list_incidents(self, principal: UserPrincipal) -> tuple[IncidentRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (item for (tenant, _), item in self._incidents.items() if tenant == principal.tenant_id),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            )

    def transition_incident(
        self, principal: UserPrincipal, incident_id: str, *, expected: str, target: str
    ) -> IncidentRecord:
        key = (principal.tenant_id, incident_id)
        with self._lock:
            current = self._incidents.get(key)
            if current is None:
                raise KeyError(incident_id)
            check_incident_transition(principal, current, expected, target)
            updated = replace(current, status=target, updated_at=self._incident_time(principal))
            self._incidents[key] = updated
            self._record_incident_event(principal, incident_id, "status_changed", current.status, target)
            return updated

    def update_incident_analysis(
        self,
        principal: UserPrincipal,
        incident_id: str,
        *,
        expected_updated_at: datetime,
        analysis: Mapping[str, str],
    ) -> IncidentRecord:
        key = (principal.tenant_id, incident_id)
        values = _bounded_analysis(analysis)
        with self._lock:
            current = self._incidents.get(key)
            if current is None:
                raise KeyError(incident_id)
            _check_analysis_update(principal, current, expected_updated_at)
            if all(getattr(current, field) == value for field, value in values.items()):
                return current
            updated = replace(
                current,
                updated_at=self._incident_time(principal),
                containment_action=values["containment_action"],
                root_cause=values["root_cause"],
                corrective_action=values["corrective_action"],
                effectiveness_check=values["effectiveness_check"],
            )
            self._incidents[key] = updated
            self._record_incident_event(principal, incident_id, "analysis_updated", None, None)
            return updated

    def list_incident_events(self, principal: UserPrincipal, incident_id: str) -> tuple[IncidentEventRecord, ...]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            return tuple(
                replace(event, is_own=actor == subject)
                for tenant, actor, event in self._incident_events
                if tenant == principal.tenant_id and event.incident_id == incident_id
            )

    def list_incident_lifecycles(
        self, principal: UserPrincipal, *, since: datetime, limit: int
    ) -> tuple[IncidentLifecycle, ...]:
        with self._lock:
            incidents = sorted(
                (
                    item
                    for (tenant, _), item in self._incidents.items()
                    if tenant == principal.tenant_id and item.created_at >= since
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )[:limit]
            changes: dict[str, list[StatusChange]] = {item.incident_id: [] for item in incidents}
            for tenant, _, event in self._incident_events:
                if tenant == principal.tenant_id and event.incident_id in changes and event.new_status:
                    changes[event.incident_id].append(
                        StatusChange(event.previous_status, event.new_status, event.occurred_at)
                    )
            return tuple(
                IncidentLifecycle(
                    item.incident_id,
                    item.asset_id,
                    item.severity,
                    item.status,
                    item.created_at,
                    tuple(sorted(changes[item.incident_id], key=lambda change: change.occurred_at)),
                )
                for item in incidents
            )

    def record_acceptance(self, principal: UserPrincipal, notice_type: str, version: str, digest: str) -> None:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            self._acceptances.add((principal.tenant_id, subject, notice_type, version + ":" + digest))

    def has_acceptance(self, principal: UserPrincipal, notice_type: str, version: str) -> bool:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            return any(
                tenant == principal.tenant_id
                and actor == subject
                and kind == notice_type
                and value.startswith(version + ":")
                for tenant, actor, kind, value in self._acceptances
            )

    def create_privacy_request(self, principal: UserPrincipal, request_type: str) -> PrivacyRequestRecord:
        if request_type not in {"access", "export", "rectification", "restriction", "erasure", "objection"}:
            raise ValueError("Nicht unterstützter Datenschutzantrag")
        requested = _now()
        record = PrivacyRequestRecord(
            request_id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            request_type=request_type,
            status="submitted",
            requested_at=requested,
            due_at=requested + timedelta(days=28),
        )
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            self._privacy_requests[(principal.tenant_id, record.request_id)] = (subject, record)
        return record

    def list_privacy_requests(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            return tuple(
                record
                for (tenant, _), (owner, record) in self._privacy_requests.items()
                if tenant == principal.tenant_id and owner == subject
            )

    def list_privacy_queue(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]:
        if not principal.can(PRIVACY_MANAGE_PERMISSION):
            raise PermissionError("PRIVACY_MANAGE_REQUIRED")
        with self._lock:
            records = [
                record for (tenant, _), (_, record) in self._privacy_requests.items() if tenant == principal.tenant_id
            ]
        return tuple(sorted(records, key=_privacy_queue_order))

    def decide_privacy_request(
        self,
        principal: UserPrincipal,
        request_id: str,
        *,
        expected: str,
        target: str,
        decision_reason: str | None = None,
        evidence_reference: str | None = None,
    ) -> PrivacyRequestRecord:
        actor = _principal_token(self._pseudonymizer, principal)
        key = (principal.tenant_id, request_id)
        with self._lock:
            stored = self._privacy_requests.get(key)
            if stored is None:
                raise KeyError(request_id)
            owner, current = stored
            reference = _check_privacy_decision(
                principal, current, owner == actor, expected, target, decision_reason, evidence_reference
            )
            final = target in PRIVACY_DECISION_REASONS
            updated = replace(
                current,
                status=target,
                completed_at=_now() if final else None,
                evidence_reference=reference,
                decision_reason=decision_reason if final else None,
            )
            self._privacy_requests[key] = (owner, updated)
            return updated

    def subject_export(self, principal: UserPrincipal) -> Mapping[str, Any]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._lock:
            answers = [
                {
                    "answer_id": answer.answer_id,
                    "answer_text": answer.text,
                    "use_case": answer.use_case.value,
                    "review_status": self._reviews.get(
                        (principal.tenant_id, answer.answer_id), answer.review_status
                    ).value,
                    "generated_at": answer.provenance.generated_at.isoformat(),
                    "provenance": answer.provenance.__dict__,
                }
                for (tenant, _), (actor, answer) in self._answers.items()
                if tenant == principal.tenant_id and actor == subject
            ]
            notices = [
                {"notice_type": kind, "version_digest": value}
                for tenant, actor, kind, value in self._acceptances
                if tenant == principal.tenant_id and actor == subject
            ]
            documents = [
                {
                    "document_id": item.document_id,
                    "display_name": item.display_name,
                    "created_at": item.created_at.isoformat(),
                }
                for (tenant, document_id), item in self._documents.items()
                if tenant == principal.tenant_id and self._uploaders.get((tenant, document_id)) == subject
            ]
            reviews = [
                {"answer_id": answer_id, "status": status.value, "reviewed_at": reviewed_at.isoformat()}
                for tenant, reviewer, answer_id, status, reviewed_at in self._review_log
                if tenant == principal.tenant_id and reviewer == subject
            ]
            incidents = [
                {
                    "incident_id": item.incident_id,
                    "asset_id": item.asset_id,
                    "title": item.title,
                    "details": item.details,
                    "severity": item.severity,
                    "status": item.status,
                    "created_at": item.created_at.isoformat(),
                }
                for (tenant, incident_id), item in self._incidents.items()
                if tenant == principal.tenant_id and self._reporters.get((tenant, incident_id)) == subject
            ]
            steps = [
                _incident_step(event)
                for tenant, actor, event in self._incident_events
                if tenant == principal.tenant_id and actor == subject
            ]
            document_steps = [
                _document_step(event)
                for tenant, actor, event in self._document_events
                if tenant == principal.tenant_id and actor == subject
            ]
        return {
            "schema": SUBJECT_EXPORT_SCHEMA,
            "generated_at": _now().isoformat(),
            "subject_token": subject,
            "analysis_runs": answers,
            "notice_acceptances": notices,
            "documents_uploaded": documents,
            "reviews_given": reviews,
            "incidents_created": incidents,
            "incident_steps": steps,
            "document_steps": document_steps,
            "privacy_requests": [item.__dict__ for item in self.list_privacy_requests(principal)],
        }

    def emit_audit(
        self,
        principal: UserPrincipal,
        *,
        action: str,
        outcome: AuditOutcome,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            outcome=outcome,
            actor_token=_principal_token(self._pseudonymizer, principal),
            resource_type=resource_type,
            resource_token=self._pseudonymizer.token(resource_id),
            expires_at=self._retention.expires_at(RecordClass.AUDIT_EVENT, _now()),
            metadata=metadata or {},
        )
        with self._lock:
            previous = self._audit[-1][1] if self._audit else None
            self._audit.append((event, _event_hash(self._audit_chain_key, previous, event)))
        return event

    def verify_audit_chain(self, principal: UserPrincipal, anchor: tuple[int, str] | None = None) -> AuditChainReport:
        if not principal.can(AUDIT_VERIFY_PERMISSION):
            raise PermissionError("AUDIT_VERIFY_REQUIRED")
        # The development backend keeps one chain for all tenants; PostgreSQL chains each tenant separately.
        with self._lock:
            rows = [
                (index, self._audit[index - 2][1] if index > 1 else None, digest, event)
                for index, (event, digest) in enumerate(self._audit, start=1)
            ]
        return verify_audit_chain_rows(self._audit_chain_key, rows, anchor)

    def create_legal_hold(
        self,
        principal: UserPrincipal,
        *,
        case_reference: str,
        reason_code: str,
        record_classes: tuple[str, ...],
        review_at: datetime,
    ) -> LegalHoldRecord:
        now = _now()
        reference, classes = _check_legal_hold(principal, case_reference, reason_code, record_classes, review_at, now)
        record = LegalHoldRecord(
            str(uuid.uuid4()), principal.tenant_id, reference, reason_code, classes, review_at, now
        )
        with self._lock:
            self._legal_holds[(principal.tenant_id, record.hold_id)] = record
        return record

    def release_legal_hold(self, principal: UserPrincipal, hold_id: str) -> LegalHoldRecord:
        if not principal.can(LEGAL_HOLD_PERMISSION):
            raise PermissionError("LEGAL_HOLD_MANAGE_REQUIRED")
        key = (principal.tenant_id, hold_id)
        with self._lock:
            current = self._legal_holds.get(key)
            if current is None or current.released_at is not None:
                raise KeyError(hold_id)
            released = replace(current, released_at=_now())
            self._legal_holds[key] = released
            return released

    def list_legal_holds(self, principal: UserPrincipal) -> tuple[LegalHoldRecord, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (item for (tenant, _), item in self._legal_holds.items() if tenant == principal.tenant_id),
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            )


# Column order matches IncidentRecord. Statements are complete literals so no SQL is assembled at runtime.
_SELECT_INCIDENTS_SQL = """SELECT incident_id::text, tenant_id, asset_id, title, severity, status, created_at, details, updated_at,
    containment_action, root_cause, corrective_action, effectiveness_check
    FROM incidents ORDER BY created_at DESC LIMIT 250"""
_LOCK_INCIDENT_SQL = """SELECT incident_id::text, tenant_id, asset_id, title, severity, status, created_at, details, updated_at,
    containment_action, root_cause, corrective_action, effectiveness_check
    FROM incidents WHERE incident_id=%s FOR UPDATE"""
_SELECT_LIFECYCLE_INCIDENTS_SQL = """SELECT incident_id::text, asset_id, severity, status, created_at
    FROM incidents WHERE created_at >= %s ORDER BY created_at DESC LIMIT %s"""
_SELECT_LIFECYCLE_CHANGES_SQL = """SELECT incident_id::text, previous_status, new_status, occurred_at
    FROM incident_events WHERE incident_id = ANY(%s::uuid[]) AND new_status IS NOT NULL
    ORDER BY occurred_at, event_id"""
_UPDATE_INCIDENT_STATUS_SQL = """UPDATE incidents SET status=%s, updated_at=now() WHERE incident_id=%s
    RETURNING incident_id::text, tenant_id, asset_id, title, severity, status, created_at, details, updated_at,
    containment_action, root_cause, corrective_action, effectiveness_check"""
_UPDATE_INCIDENT_ANALYSIS_SQL = """UPDATE incidents SET containment_action=%s, root_cause=%s, corrective_action=%s,
    effectiveness_check=%s, updated_at=now() WHERE incident_id=%s
    RETURNING incident_id::text, tenant_id, asset_id, title, severity, status, created_at, details, updated_at,
    containment_action, root_cause, corrective_action, effectiveness_check"""


class PostgresRepository:
    """PostgreSQL repository using forced RLS and per-transaction tenant context."""

    def __init__(self, settings: AppSettings) -> None:
        if not settings.database_url:
            raise ValueError("database_url is required")
        self._settings = settings
        self._database_url = settings.database_url
        self._retention = RetentionPolicy.from_environment()
        self._pseudonymizer = SubjectPseudonymizer(settings.audit_hmac_key.encode("utf-8"))
        self._audit_chain_key = _audit_chain_key(settings.audit_hmac_key)

    def _connect(self):
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("psycopg is required for PostgreSQL persistence") from error
        return psycopg.connect(self._database_url, connect_timeout=10)

    @staticmethod
    def _tenant(cursor, tenant_id: str) -> None:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def ensure_schema(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "db" / "migrations" / "001_enterprise.sql"
        sql = migration.read_text(encoding="utf-8")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(83024177)")
                cursor.execute(sql)

    def check_schema(self) -> None:
        required_tables = {
            "tenants",
            "assets",
            "documents",
            "document_events",
            "analysis_runs",
            "analysis_reviews",
            "incidents",
            "incident_events",
            "notice_acceptances",
            "privacy_requests",
            "legal_holds",
            "audit_events",
        }
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT relname FROM pg_class
                    WHERE relnamespace='public'::regnamespace
                      AND relname = ANY(%s)
                      AND relkind='r'
                      AND relforcerowsecurity""",
                    (list(required_tables),),
                )
                protected = {row[0] for row in cursor.fetchall()}
                cursor.execute("SELECT to_regprocedure('public.purge_expired_tenant_data(text)')")
                purge_function = cursor.fetchone()[0]
                cursor.execute("SELECT to_regprocedure('public.list_retention_tenant_ids()')")
                tenant_function = cursor.fetchone()[0]
                cursor.execute(
                    """SELECT count(*) FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='assets'
                      AND column_name IN ('functional_location', 'equipment_number')"""
                )
                sap_columns = cursor.fetchone()[0]
                cursor.execute(_COUNT_DOCUMENT_RELEASE_COLUMNS_SQL)
                release_columns = cursor.fetchone()[0]
        if protected != required_tables or purge_function is None or tenant_function is None:
            raise RuntimeError("Database schema is missing required RLS or lifecycle controls")
        if sap_columns != 2:
            raise RuntimeError("Database schema is missing asset SAP reference columns; run the bootstrap migration")
        if release_columns != 8:
            raise RuntimeError("Database schema is missing document release columns; run the bootstrap migration")

    def upsert_asset(
        self,
        principal: UserPrincipal,
        *,
        asset_id: str,
        name: str,
        site: str,
        manufacturer: str,
        model: str,
        criticality: str,
        functional_location: str = "",
        equipment_number: str = "",
    ) -> AssetRecord:
        updated = _now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (principal.tenant_id, principal.tenant_id),
                )
                cursor.execute(
                    """INSERT INTO assets
                    (asset_id, tenant_id, name, site, manufacturer, model, criticality, status, updated_at,
                     functional_location, equipment_number)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
                    ON CONFLICT (tenant_id, asset_id) DO UPDATE SET
                    name=excluded.name, site=excluded.site, manufacturer=excluded.manufacturer,
                    model=excluded.model, criticality=excluded.criticality, updated_at=excluded.updated_at,
                    functional_location=excluded.functional_location,
                    equipment_number=excluded.equipment_number""",
                    (
                        asset_id[:120],
                        principal.tenant_id,
                        name[:240],
                        site[:240],
                        manufacturer[:160],
                        model[:160],
                        criticality,
                        updated,
                        functional_location[:40],
                        equipment_number[:18],
                    ),
                )
        return AssetRecord(
            asset_id[:120],
            principal.tenant_id,
            name[:240],
            site[:240],
            manufacturer[:160],
            model[:160],
            criticality,
            "active",
            updated,
            functional_location[:40],
            equipment_number[:18],
        )

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT asset_id, tenant_id, name, site, manufacturer, model,
                    criticality, status, updated_at, functional_location, equipment_number
                    FROM assets ORDER BY site, name"""
                )
                return tuple(AssetRecord(*row) for row in cursor.fetchall())

    @staticmethod
    def _locked_document(cursor, document_id: str | None, actor: str) -> DocumentRecord | None:
        """Row-locked current state of a document that is not deleted, or None."""
        if document_id is None or not _is_uuid(document_id):
            return None
        cursor.execute(_LOCK_DOCUMENT_SQL, (actor, document_id))
        row = cursor.fetchone()
        return None if row is None else DocumentRecord(*row)

    def _insert_document_event(
        self,
        cursor,
        principal: UserPrincipal,
        actor: str,
        document_id: str,
        event_type: str,
        reason_code: str | None,
        occurred_at: datetime,
    ) -> None:
        cursor.execute(
            _INSERT_DOCUMENT_EVENT_SQL,
            (
                str(uuid.uuid4()),
                principal.tenant_id,
                document_id,
                event_type,
                reason_code,
                principal.role[:40],
                actor,
                occurred_at,
            ),
        )

    @staticmethod
    def _citing_answers(cursor, document_id: str) -> int:
        cursor.execute(_COUNT_CITING_ANSWERS_SQL, (json.dumps([{"document_id": document_id}]),))
        return int(cursor.fetchone()[0])

    def register_document(
        self, principal: UserPrincipal, upload: ValidatedUpload, control: DocumentControl | None = None
    ) -> DocumentRecord:
        created = _now()
        expires = self._retention.expires_at(RecordClass.UPLOADED_CONTENT, created)
        actor = _principal_token(self._pseudonymizer, principal)
        requested = control or DocumentControl()
        replaced = requested.supersedes_document_id
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (principal.tenant_id, principal.tenant_id),
                )
                # Locking the replaced document serialises two uploads that try to replace it at once.
                predecessor = self._locked_document(cursor, replaced, actor)
                pending = False
                if predecessor is not None:
                    cursor.execute(_COUNT_PENDING_SUCCESSORS_SQL, (predecessor.document_id,))
                    pending = cursor.fetchone()[0] > 0
                checked = _check_document_control(requested, predecessor, pending)
                cursor.execute(
                    _INSERT_DOCUMENT_SQL,
                    (
                        upload.document_id,
                        principal.tenant_id,
                        upload.display_name,
                        upload.sha256,
                        actor,
                        created,
                        expires,
                        checked.revision,
                        checked.document_number,
                        checked.supersedes_document_id,
                    ),
                )
                self._insert_document_event(cursor, principal, actor, upload.document_id, "uploaded", None, created)
        return DocumentRecord(
            upload.document_id,
            principal.tenant_id,
            upload.display_name,
            upload.sha256,
            "processing",
            0,
            created,
            expires,
            release_status="draft",
            revision=checked.revision,
            document_number=checked.document_number,
            supersedes_document_id=checked.supersedes_document_id,
            is_own=True,
        )

    def mark_document_indexed(self, principal: UserPrincipal, document_id: str, page_count: int) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "UPDATE documents SET status='ready', page_count=%s, indexed_at=now() WHERE document_id=%s",
                    (page_count, document_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(document_id)

    def mark_document_failed(self, principal: UserPrincipal, document_id: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "UPDATE documents SET status='failed', retention_until=now() WHERE document_id=%s",
                    (document_id,),
                )
                if cursor.rowcount != 1:
                    raise KeyError(document_id)

    def list_documents(self, principal: UserPrincipal) -> tuple[DocumentRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_DOCUMENTS_SQL, (self._pseudonymizer.token(principal.subject_id),))
                return tuple(DocumentRecord(*row) for row in cursor.fetchall())

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """UPDATE documents SET status='deleted', deleted_at=now(),
                    retention_until=LEAST(retention_until, now()) WHERE document_id=%s""",
                    (document_id,),
                )
                if cursor.rowcount != 1:
                    raise KeyError(document_id)

    def release_document(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRelease:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        superseded = None
        cited = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                current = self._locked_document(cursor, document_id, actor)
                if current is None:
                    raise KeyError(document_id)
                _check_document_release(current, review_due_at, now)
                cursor.execute(_RELEASE_DOCUMENT_SQL, (now, review_due_at, document_id))
                self._insert_document_event(cursor, principal, actor, document_id, "released", None, now)
                # The new revision takes its predecessor out of use in the same transaction.
                previous = self._locked_document(cursor, current.supersedes_document_id, actor)
                if previous is not None and previous.release_status == "released":
                    cursor.execute(_WITHDRAW_DOCUMENT_SQL, (now, DOCUMENT_SUPERSEDED_REASON, previous.document_id))
                    self._insert_document_event(
                        cursor, principal, actor, previous.document_id, "withdrawn", DOCUMENT_SUPERSEDED_REASON, now
                    )
                    superseded = replace(
                        previous,
                        release_status="withdrawn",
                        withdrawn_at=now,
                        withdrawal_reason=DOCUMENT_SUPERSEDED_REASON,
                    )
                    cited = self._citing_answers(cursor, previous.document_id)
        released = replace(current, release_status="released", released_at=now, review_due_at=review_due_at)
        return DocumentRelease(released, superseded, cited)

    def withdraw_document(self, principal: UserPrincipal, document_id: str, reason_code: str) -> DocumentWithdrawal:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                current = self._locked_document(cursor, document_id, actor)
                if current is None:
                    raise KeyError(document_id)
                _check_document_withdrawal(current, reason_code)
                cursor.execute(_WITHDRAW_DOCUMENT_SQL, (now, reason_code, document_id))
                self._insert_document_event(cursor, principal, actor, document_id, "withdrawn", reason_code, now)
                cited = self._citing_answers(cursor, document_id)
        withdrawn = replace(current, release_status="withdrawn", withdrawn_at=now, withdrawal_reason=reason_code)
        return DocumentWithdrawal(withdrawn, cited)

    def confirm_document_review(
        self, principal: UserPrincipal, document_id: str, *, review_due_at: datetime
    ) -> DocumentRecord:
        _require_document_release(principal)
        now = _now()
        actor = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                current = self._locked_document(cursor, document_id, actor)
                if current is None:
                    raise KeyError(document_id)
                _check_document_review(current, review_due_at, now)
                cursor.execute(_CONFIRM_DOCUMENT_REVIEW_SQL, (review_due_at, document_id))
                self._insert_document_event(cursor, principal, actor, document_id, "review_confirmed", None, now)
        return replace(current, review_due_at=review_due_at)

    def list_document_events(self, principal: UserPrincipal, document_id: str) -> tuple[DocumentEventRecord, ...]:
        if not _is_uuid(document_id):
            return ()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    _SELECT_DOCUMENT_EVENTS_SQL, (self._pseudonymizer.token(principal.subject_id), document_id)
                )
                return tuple(DocumentEventRecord(*row) for row in cursor.fetchall())

    def record_answer(self, principal: UserPrincipal, question: str, answer: GroundedAnswer) -> None:
        actor = _principal_token(self._pseudonymizer, principal)
        question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
        expiry = self._retention.expires_at(RecordClass.AI_INTERACTION, answer.provenance.generated_at)
        citations = [citation.__dict__ for citation in answer.citations]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """INSERT INTO analysis_runs
                    (answer_id, tenant_id, actor_token, question_hash, answer_text,
                     use_case, risk_class, review_status, provider, deployment,
                     model_snapshot, region, prompt_key, prompt_version, citations,
                     generated_at, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                    (
                        answer.answer_id,
                        principal.tenant_id,
                        actor,
                        question_hash,
                        answer.text,
                        answer.use_case.value,
                        answer.risk_class.value,
                        answer.review_status.value,
                        answer.provenance.provider,
                        answer.provenance.deployment,
                        answer.provenance.model_snapshot,
                        answer.provenance.region,
                        answer.provenance.prompt_key,
                        answer.provenance.prompt_version,
                        json.dumps(citations),
                        answer.provenance.generated_at,
                        expiry,
                    ),
                )

    def record_review(
        self, principal: UserPrincipal, answer_id: str, status: ReviewStatus, reason_code: str | None = None
    ) -> None:
        reviewer = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "SELECT actor_token, risk_class FROM analysis_runs WHERE answer_id=%s FOR UPDATE",
                    (answer_id,),
                )
                answer = cursor.fetchone()
                if answer is None:
                    raise KeyError(answer_id)
                if status is ReviewStatus.ACCEPTED and answer[1] == "heightened" and answer[0] == reviewer:
                    raise PermissionError("FOUR_EYES_REVIEW_REQUIRED")
                cursor.execute(
                    """INSERT INTO analysis_reviews
                    (review_id, tenant_id, answer_id, reviewer_token, status, reason_code)
                    VALUES (%s,%s,%s,%s,%s,%s)""",
                    (str(uuid.uuid4()), principal.tenant_id, answer_id, reviewer, status.value, reason_code),
                )
                cursor.execute(
                    "UPDATE analysis_runs SET review_status=%s WHERE answer_id=%s",
                    (status.value, answer_id),
                )

    def answer_review_status(self, principal: UserPrincipal, answer_id: str) -> ReviewStatus:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute("SELECT review_status FROM analysis_runs WHERE answer_id=%s", (answer_id,))
                row = cursor.fetchone()
        if row is None:
            raise KeyError(answer_id)
        return ReviewStatus(row[0])

    def create_incident(
        self, principal: UserPrincipal, *, asset_id: str, title: str, severity: str, details: str
    ) -> IncidentRecord:
        created = _now()
        expires = self._retention.expires_at(RecordClass.INCIDENT, created)
        incident_id = str(uuid.uuid4())
        actor = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """INSERT INTO incidents
                    (incident_id, tenant_id, asset_id, title, details, severity, status, created_by_token,
                     created_at, updated_at, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,'new',%s,%s,%s,%s)""",
                    (
                        incident_id,
                        principal.tenant_id,
                        asset_id[:120],
                        title[:240],
                        details[:8000],
                        severity,
                        actor,
                        created,
                        created,
                        expires,
                    ),
                )
                self._insert_incident_event(cursor, principal, incident_id, "created", None, "new")
        return IncidentRecord(
            incident_id,
            principal.tenant_id,
            asset_id[:120],
            title[:240],
            severity,
            "new",
            created,
            details[:8000],
            created,
        )

    def list_incidents(self, principal: UserPrincipal) -> tuple[IncidentRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_INCIDENTS_SQL)
                return tuple(IncidentRecord(*row) for row in cursor.fetchall())

    def transition_incident(
        self, principal: UserPrincipal, incident_id: str, *, expected: str, target: str
    ) -> IncidentRecord:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                current = self._locked_incident(cursor, incident_id)
                check_incident_transition(principal, current, expected, target)
                cursor.execute(
                    _UPDATE_INCIDENT_STATUS_SQL,
                    (target, incident_id),
                )
                updated = cursor.fetchone()
                if updated is None:
                    raise KeyError(incident_id)
                self._insert_incident_event(cursor, principal, incident_id, "status_changed", current.status, target)
                return IncidentRecord(*updated)

    @staticmethod
    def _locked_incident(cursor, incident_id: str) -> IncidentRecord:
        cursor.execute(_LOCK_INCIDENT_SQL, (incident_id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(incident_id)
        return IncidentRecord(*row)

    def _insert_incident_event(
        self,
        cursor,
        principal: UserPrincipal,
        incident_id: str,
        event_type: str,
        previous_status: str | None,
        new_status: str | None,
    ) -> None:
        cursor.execute(
            """INSERT INTO incident_events
            (event_id, tenant_id, incident_id, event_type, previous_status, new_status, actor_role, actor_token)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                str(uuid.uuid4()),
                principal.tenant_id,
                incident_id,
                event_type,
                previous_status,
                new_status,
                principal.role[:40],
                _principal_token(self._pseudonymizer, principal),
            ),
        )

    def update_incident_analysis(
        self,
        principal: UserPrincipal,
        incident_id: str,
        *,
        expected_updated_at: datetime,
        analysis: Mapping[str, str],
    ) -> IncidentRecord:
        values = _bounded_analysis(analysis)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                current = self._locked_incident(cursor, incident_id)
                _check_analysis_update(principal, current, expected_updated_at)
                if all(getattr(current, field) == value for field, value in values.items()):
                    return current
                cursor.execute(
                    _UPDATE_INCIDENT_ANALYSIS_SQL,
                    (*(values[field] for field in INCIDENT_ANALYSIS_FIELDS), incident_id),
                )
                updated = cursor.fetchone()
                if updated is None:
                    raise KeyError(incident_id)
                self._insert_incident_event(cursor, principal, incident_id, "analysis_updated", None, None)
                return IncidentRecord(*updated)

    def list_incident_events(self, principal: UserPrincipal, incident_id: str) -> tuple[IncidentEventRecord, ...]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT event_id::text, incident_id::text, event_type, previous_status, new_status, actor_role,
                    occurred_at, actor_token = %s
                    FROM incident_events WHERE incident_id=%s ORDER BY occurred_at, event_id""",
                    (subject, incident_id),
                )
                return tuple(IncidentEventRecord(*row) for row in cursor.fetchall())

    def list_incident_lifecycles(
        self, principal: UserPrincipal, *, since: datetime, limit: int
    ) -> tuple[IncidentLifecycle, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_LIFECYCLE_INCIDENTS_SQL, (since, limit))
                incidents = cursor.fetchall()
                changes: dict[str, list[StatusChange]] = {row[0]: [] for row in incidents}
                if changes:
                    cursor.execute(_SELECT_LIFECYCLE_CHANGES_SQL, (list(changes),))
                    for incident_id, previous_status, new_status, occurred_at in cursor.fetchall():
                        changes[incident_id].append(StatusChange(previous_status, new_status, occurred_at))
                return tuple(
                    IncidentLifecycle(incident_id, asset_id, severity, status, created_at, tuple(changes[incident_id]))
                    for incident_id, asset_id, severity, status, created_at in incidents
                )

    def record_acceptance(self, principal: UserPrincipal, notice_type: str, version: str, digest: str) -> None:
        actor = _principal_token(self._pseudonymizer, principal)
        expiry = self._retention.expires_at(RecordClass.CONTRACT_ACCEPTANCE, _now())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """INSERT INTO notice_acceptances
                    (acceptance_id, tenant_id, actor_token, notice_type, version, digest, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (str(uuid.uuid4()), principal.tenant_id, actor, notice_type, version, digest, expiry),
                )

    def has_acceptance(self, principal: UserPrincipal, notice_type: str, version: str) -> bool:
        actor = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "SELECT 1 FROM notice_acceptances WHERE actor_token=%s AND notice_type=%s AND version=%s LIMIT 1",
                    (actor, notice_type, version),
                )
                return cursor.fetchone() is not None

    def create_privacy_request(self, principal: UserPrincipal, request_type: str) -> PrivacyRequestRecord:
        if request_type not in {"access", "export", "rectification", "restriction", "erasure", "objection"}:
            raise ValueError("Nicht unterstützter Datenschutzantrag")
        requested = _now()
        due = requested + timedelta(days=28)
        expiry = self._retention.expires_at(RecordClass.DATA_SUBJECT_REQUEST, requested)
        request_id = str(uuid.uuid4())
        subject = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """INSERT INTO privacy_requests
                    (request_id, tenant_id, subject_token, request_type, status, requested_at,
                     due_at, retention_until)
                    VALUES (%s,%s,%s,%s,'submitted',%s,%s,%s)""",
                    (request_id, principal.tenant_id, subject, request_type, requested, due, expiry),
                )
        return PrivacyRequestRecord(request_id, principal.tenant_id, request_type, "submitted", requested, due)

    def list_privacy_requests(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT request_id::text, tenant_id, request_type, status, requested_at, due_at, completed_at,
                    evidence_reference, decision_reason
                    FROM privacy_requests WHERE subject_token=%s ORDER BY requested_at DESC""",
                    (subject,),
                )
                return tuple(PrivacyRequestRecord(*row) for row in cursor.fetchall())

    def list_privacy_queue(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]:
        if not principal.can(PRIVACY_MANAGE_PERMISSION):
            raise PermissionError("PRIVACY_MANAGE_REQUIRED")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_PRIVACY_QUEUE_SQL)
                return tuple(
                    sorted((PrivacyRequestRecord(*row) for row in cursor.fetchall()), key=_privacy_queue_order)
                )

    def decide_privacy_request(
        self,
        principal: UserPrincipal,
        request_id: str,
        *,
        expected: str,
        target: str,
        decision_reason: str | None = None,
        evidence_reference: str | None = None,
    ) -> PrivacyRequestRecord:
        actor = _principal_token(self._pseudonymizer, principal)
        final = target in PRIVACY_DECISION_REASONS
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_LOCK_PRIVACY_REQUEST_SQL, (request_id,))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(request_id)
                current = PrivacyRequestRecord(*row[:9])
                reference = _check_privacy_decision(
                    principal, current, row[9] == actor, expected, target, decision_reason, evidence_reference
                )
                cursor.execute(
                    _UPDATE_PRIVACY_REQUEST_SQL,
                    (target, _now() if final else None, reference, decision_reason if final else None, request_id),
                )
                return PrivacyRequestRecord(*cursor.fetchone())

    def subject_export(self, principal: UserPrincipal) -> Mapping[str, Any]:
        subject = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT answer_id::text, question_hash, answer_text, use_case, risk_class,
                    review_status, provider, deployment, model_snapshot, region, prompt_key,
                    prompt_version, citations, generated_at
                    FROM analysis_runs WHERE actor_token=%s ORDER BY generated_at DESC""",
                    (subject,),
                )
                analysis = [
                    {
                        "answer_id": row[0],
                        "question_hash": row[1],
                        "answer_text": row[2],
                        "use_case": row[3],
                        "risk_class": row[4],
                        "review_status": row[5],
                        "provider": row[6],
                        "deployment": row[7],
                        "model_snapshot": row[8],
                        "region": row[9],
                        "prompt_key": row[10],
                        "prompt_version": row[11],
                        "citations": row[12],
                        "generated_at": row[13].isoformat(),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """SELECT notice_type, version, digest, accepted_at FROM notice_acceptances
                    WHERE actor_token=%s ORDER BY accepted_at DESC""",
                    (subject,),
                )
                notices = [
                    {
                        "notice_type": row[0],
                        "version": row[1],
                        "digest": row[2],
                        "accepted_at": row[3].isoformat(),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """SELECT incident_id::text, asset_id, title, details, severity, status, created_at
                    FROM incidents WHERE created_by_token=%s ORDER BY created_at DESC""",
                    (subject,),
                )
                incidents = [
                    {
                        "incident_id": row[0],
                        "asset_id": row[1],
                        "title": row[2],
                        "details": row[3],
                        "severity": row[4],
                        "status": row[5],
                        "created_at": row[6].isoformat(),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """SELECT document_id::text, display_name, created_at FROM documents
                    WHERE created_by_token=%s ORDER BY created_at DESC""",
                    (subject,),
                )
                documents = [
                    {"document_id": row[0], "display_name": row[1], "created_at": row[2].isoformat()}
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """SELECT answer_id::text, status, reviewed_at FROM analysis_reviews
                    WHERE reviewer_token=%s ORDER BY reviewed_at DESC""",
                    (subject,),
                )
                reviews = [
                    {"answer_id": row[0], "status": row[1], "reviewed_at": row[2].isoformat()}
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """SELECT event_id::text, incident_id::text, event_type, previous_status, new_status,
                    actor_role, occurred_at, true FROM incident_events
                    WHERE actor_token=%s ORDER BY occurred_at, event_id""",
                    (subject,),
                )
                steps = [_incident_step(IncidentEventRecord(*row)) for row in cursor.fetchall()]
                cursor.execute(_SELECT_OWN_DOCUMENT_EVENTS_SQL, (subject,))
                document_steps = [_document_step(DocumentEventRecord(*row)) for row in cursor.fetchall()]
        return {
            "schema": SUBJECT_EXPORT_SCHEMA,
            "generated_at": _now().isoformat(),
            "subject_token": subject,
            "analysis_runs": analysis,
            "notice_acceptances": notices,
            "documents_uploaded": documents,
            "reviews_given": reviews,
            "incidents_created": incidents,
            "incident_steps": steps,
            "document_steps": document_steps,
            "privacy_requests": [item.__dict__ for item in self.list_privacy_requests(principal)],
        }

    def list_tenant_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT tenant_id FROM list_retention_tenant_ids()")
                return tuple(row[0] for row in cursor.fetchall())

    def list_expired_documents(self, principal: UserPrincipal) -> tuple[DocumentRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_EXPIRED_DOCUMENTS_SQL)
                return tuple(DocumentRecord(*row) for row in cursor.fetchall())

    def purge_expired_records(self, principal: UserPrincipal) -> Mapping[str, int]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute("SELECT purge_expired_tenant_data(%s)", (principal.tenant_id,))
                counts = cursor.fetchone()[0]
        if not isinstance(counts, dict) or any(not isinstance(value, int) for value in counts.values()):
            raise RuntimeError("Retention function returned an invalid result")
        return counts

    def emit_audit(
        self,
        principal: UserPrincipal,
        *,
        action: str,
        outcome: AuditOutcome,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent:
        occurred = _now()
        event = AuditEvent(
            action=action,
            outcome=outcome,
            actor_token=_principal_token(self._pseudonymizer, principal),
            resource_type=resource_type,
            resource_token=self._pseudonymizer.token(resource_id),
            occurred_at=occurred,
            expires_at=self._retention.expires_at(RecordClass.AUDIT_EVENT, occurred),
            metadata=metadata or {},
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (principal.tenant_id, principal.tenant_id),
                )
                # Serialise the per-tenant hash chain without a row lock: FOR UPDATE would need UPDATE rights on
                # tenants, which the runtime and lifecycle roles deliberately do not have.
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_audit_lock_key(principal.tenant_id),))
                cursor.execute("SELECT event_hash FROM audit_events ORDER BY sequence_id DESC LIMIT 1")
                previous_row = cursor.fetchone()
                previous = previous_row[0] if previous_row else None
                digest = _event_hash(self._audit_chain_key, previous, event)
                cursor.execute(
                    """INSERT INTO audit_events
                    (event_id, tenant_id, action, outcome, actor_token, resource_type,
                     resource_token, metadata, occurred_at, retention_until, previous_hash, event_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                    (
                        event.event_id,
                        principal.tenant_id,
                        event.action,
                        event.outcome.value,
                        event.actor_token,
                        event.resource_type,
                        event.resource_token,
                        json.dumps(dict(event.metadata)),
                        event.occurred_at,
                        event.expires_at,
                        previous,
                        digest,
                    ),
                )
        return event

    def verify_audit_chain(self, principal: UserPrincipal, anchor: tuple[int, str] | None = None) -> AuditChainReport:
        if not principal.can(AUDIT_VERIFY_PERMISSION):
            raise PermissionError("AUDIT_VERIFY_REQUIRED")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
            # A server-side cursor streams the chain, so a long audit history never sits in memory at once.
            with connection.cursor(name="audit_chain_verification") as stream:
                stream.execute(_SELECT_AUDIT_CHAIN_SQL)
                return verify_audit_chain_rows(self._audit_chain_key, (_audit_chain_row(row) for row in stream), anchor)

    def create_legal_hold(
        self,
        principal: UserPrincipal,
        *,
        case_reference: str,
        reason_code: str,
        record_classes: tuple[str, ...],
        review_at: datetime,
    ) -> LegalHoldRecord:
        reference, classes = _check_legal_hold(
            principal, case_reference, reason_code, record_classes, review_at, _now()
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    _INSERT_LEGAL_HOLD_SQL,
                    (
                        str(uuid.uuid4()),
                        principal.tenant_id,
                        reference,
                        reason_code,
                        list(classes),
                        review_at,
                        _principal_token(self._pseudonymizer, principal),
                    ),
                )
                return _legal_hold(cursor.fetchone())

    def release_legal_hold(self, principal: UserPrincipal, hold_id: str) -> LegalHoldRecord:
        if not principal.can(LEGAL_HOLD_PERMISSION):
            raise PermissionError("LEGAL_HOLD_MANAGE_REQUIRED")
        released = _now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    _RELEASE_LEGAL_HOLD_SQL,
                    (
                        _principal_token(self._pseudonymizer, principal),
                        released,
                        self._retention.expires_at(RecordClass.AUDIT_EVENT, released),
                        hold_id,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(hold_id)
                return _legal_hold(row)

    def list_legal_holds(self, principal: UserPrincipal) -> tuple[LegalHoldRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(_SELECT_LEGAL_HOLDS_SQL)
                return tuple(_legal_hold(row) for row in cursor.fetchall())


# Column order matches DocumentRecord; the last column tells whether the caller uploaded the document.
_SELECT_DOCUMENTS_SQL = """SELECT document_id::text, tenant_id, display_name, sha256, status, page_count, created_at,
    retention_until, release_status, revision, document_number, released_at, review_due_at, withdrawn_at,
    withdrawal_reason, supersedes_document_id::text, created_by_token = %s
    FROM documents WHERE deleted_at IS NULL ORDER BY created_at DESC"""
_LOCK_DOCUMENT_SQL = """SELECT document_id::text, tenant_id, display_name, sha256, status, page_count, created_at,
    retention_until, release_status, revision, document_number, released_at, review_due_at, withdrawn_at,
    withdrawal_reason, supersedes_document_id::text, created_by_token = %s
    FROM documents WHERE document_id=%s AND deleted_at IS NULL FOR UPDATE"""
# The retention job runs without a person, so no document counts as its own.
_SELECT_EXPIRED_DOCUMENTS_SQL = """SELECT document_id::text, tenant_id, display_name, sha256, status, page_count,
    created_at, retention_until, release_status, revision, document_number, released_at, review_due_at, withdrawn_at,
    withdrawal_reason, supersedes_document_id::text, false
    FROM documents WHERE deleted_at IS NULL AND retention_until <= now()
      AND NOT EXISTS (SELECT 1 FROM legal_holds
        WHERE released_at IS NULL AND 'uploaded_content' = ANY(record_classes))
    ORDER BY retention_until"""
_INSERT_DOCUMENT_SQL = """INSERT INTO documents
    (document_id, tenant_id, display_name, sha256, status, page_count, created_by_token, created_at, retention_until,
     release_status, revision, document_number, supersedes_document_id)
    VALUES (%s, %s, %s, %s, 'processing', 0, %s, %s, %s, 'draft', %s, %s, %s)"""
_COUNT_PENDING_SUCCESSORS_SQL = """SELECT count(*) FROM documents
    WHERE supersedes_document_id=%s AND deleted_at IS NULL AND status <> 'failed' AND release_status='draft'"""
_RELEASE_DOCUMENT_SQL = """UPDATE documents SET release_status='released', released_at=%s, review_due_at=%s
    WHERE document_id=%s"""
_WITHDRAW_DOCUMENT_SQL = """UPDATE documents SET release_status='withdrawn', withdrawn_at=%s, withdrawal_reason=%s
    WHERE document_id=%s"""
_CONFIRM_DOCUMENT_REVIEW_SQL = "UPDATE documents SET review_due_at=%s WHERE document_id=%s"
_INSERT_DOCUMENT_EVENT_SQL = """INSERT INTO document_events
    (event_id, tenant_id, document_id, event_type, reason_code, actor_role, actor_token, occurred_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"""
_SELECT_DOCUMENT_EVENTS_SQL = """SELECT event_id::text, document_id::text, event_type, reason_code, actor_role,
    occurred_at, actor_token = %s FROM document_events WHERE document_id=%s ORDER BY occurred_at, event_id"""
_SELECT_OWN_DOCUMENT_EVENTS_SQL = """SELECT event_id::text, document_id::text, event_type, reason_code, actor_role,
    occurred_at, true FROM document_events WHERE actor_token=%s ORDER BY occurred_at, event_id"""
# Stored answers keep their citations as JSON; containment finds every answer that cites the document.
_COUNT_CITING_ANSWERS_SQL = "SELECT count(*) FROM analysis_runs WHERE citations @> %s::jsonb"
_COUNT_DOCUMENT_RELEASE_COLUMNS_SQL = """SELECT count(*) FROM information_schema.columns
    WHERE table_schema='public' AND table_name='documents'
      AND column_name IN ('release_status', 'revision', 'document_number', 'released_at', 'review_due_at',
                          'withdrawn_at', 'withdrawal_reason', 'supersedes_document_id')"""

_SELECT_PRIVACY_QUEUE_SQL = """SELECT request_id::text, tenant_id, request_type, status, requested_at, due_at, completed_at,
    evidence_reference, decision_reason FROM privacy_requests ORDER BY requested_at DESC LIMIT 500"""
# FOR UPDATE needs only the column UPDATE grant; the owner's pseudonym is read to block self-handling.
_LOCK_PRIVACY_REQUEST_SQL = """SELECT request_id::text, tenant_id, request_type, status, requested_at, due_at, completed_at,
    evidence_reference, decision_reason, subject_token FROM privacy_requests WHERE request_id=%s FOR UPDATE"""
_UPDATE_PRIVACY_REQUEST_SQL = """UPDATE privacy_requests
    SET status=%s, completed_at=%s, evidence_reference=%s, decision_reason=%s WHERE request_id=%s
    RETURNING request_id::text, tenant_id, request_type, status, requested_at, due_at, completed_at,
    evidence_reference, decision_reason"""


def _privacy_queue_order(record: PrivacyRequestRecord) -> tuple[bool, datetime]:
    # Open requests first, the closest deadline on top; closed ones follow by their deadline.
    return (record.status not in PRIVACY_OPEN_STATUSES, record.due_at)


_INSERT_LEGAL_HOLD_SQL = """INSERT INTO legal_holds
    (hold_id, tenant_id, case_reference, reason_code, record_classes, review_at, created_by_token)
    VALUES (%s,%s,%s,%s,%s,%s,%s)
    RETURNING hold_id::text, tenant_id, case_reference, reason_code, record_classes, review_at, created_at, released_at"""
# Releasing is the only change to a hold; the column grant for the runtime role allows nothing else.
_RELEASE_LEGAL_HOLD_SQL = """UPDATE legal_holds SET released_by_token=%s, released_at=%s, retention_until=%s
    WHERE hold_id=%s AND released_at IS NULL
    RETURNING hold_id::text, tenant_id, case_reference, reason_code, record_classes, review_at, created_at, released_at"""
_SELECT_LEGAL_HOLDS_SQL = """SELECT hold_id::text, tenant_id, case_reference, reason_code, record_classes, review_at,
    created_at, released_at FROM legal_holds ORDER BY created_at DESC LIMIT 200"""


def _legal_hold(row: tuple[Any, ...]) -> LegalHoldRecord:
    return LegalHoldRecord(row[0], row[1], row[2], row[3], tuple(row[4]), row[5], row[6], row[7])


_SELECT_AUDIT_CHAIN_SQL = """SELECT sequence_id, previous_hash, event_hash, event_id::text, action, outcome, actor_token,
    resource_type, resource_token, metadata, occurred_at, retention_until FROM audit_events ORDER BY sequence_id"""


def _audit_chain_row(row: tuple[Any, ...]) -> tuple[int, str | None, str, AuditEvent]:
    """Rebuild the hashed event from its row; timestamps return in the session time zone and are hashed in UTC."""
    (
        sequence,
        previous,
        stored,
        event_id,
        action,
        outcome,
        actor,
        resource_type,
        resource,
        metadata,
        occurred,
        retention,
    ) = row
    event = AuditEvent(
        action=action,
        outcome=AuditOutcome(outcome),
        actor_token=actor,
        resource_type=resource_type,
        resource_token=resource,
        expires_at=retention.astimezone(UTC),
        metadata=metadata or {},
        event_id=event_id,
        occurred_at=occurred.astimezone(UTC),
    )
    return sequence, previous.strip() if previous else None, stored, event


@lru_cache(maxsize=2)
def get_repository(settings: AppSettings) -> EnterpriseRepository:
    if settings.persistence_backend is PersistenceBackend.POSTGRES:
        repository = PostgresRepository(settings)
        if settings.auto_migrate_database:
            repository.ensure_schema()
        else:
            repository.check_schema()
        return repository
    return InMemoryRepository(settings)
