"""Tenant-isolated persistence for application and compliance evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
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


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    tenant_id: str
    asset_id: str
    title: str
    severity: str
    status: str
    created_at: datetime


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


@dataclass(frozen=True)
class PrivacyRequestRecord:
    request_id: str
    tenant_id: str
    request_type: str
    status: str
    requested_at: datetime
    due_at: datetime


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
    ) -> AssetRecord: ...

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]: ...

    def register_document(self, principal: UserPrincipal, upload: ValidatedUpload) -> DocumentRecord: ...

    def mark_document_indexed(self, principal: UserPrincipal, document_id: str, page_count: int) -> None: ...

    def mark_document_failed(self, principal: UserPrincipal, document_id: str) -> None: ...

    def list_documents(self, principal: UserPrincipal) -> tuple[DocumentRecord, ...]: ...

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None: ...

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

    def record_acceptance(self, principal: UserPrincipal, notice_type: str, version: str, digest: str) -> None: ...

    def has_acceptance(self, principal: UserPrincipal, notice_type: str, version: str) -> bool: ...

    def create_privacy_request(self, principal: UserPrincipal, request_type: str) -> PrivacyRequestRecord: ...

    def list_privacy_requests(self, principal: UserPrincipal) -> tuple[PrivacyRequestRecord, ...]: ...

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


def _now() -> datetime:
    return datetime.now(UTC)


def _audit_chain_key(secret: str) -> bytes:
    return hmac.new(
        secret.encode(),
        b"hydraulikdoc:audit-chain:v1",
        hashlib.sha256,
    ).digest()


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
        self._acceptances: set[tuple[str, str, str, str]] = set()
        self._privacy_requests: dict[tuple[str, str], tuple[str, PrivacyRequestRecord]] = {}
        self._audit: list[tuple[AuditEvent, str]] = []
        self._lock = RLock()

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
        )
        with self._lock:
            self._assets[(principal.tenant_id, record.asset_id)] = record
        return record

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]:
        with self._lock:
            return tuple(item for (tenant, _), item in self._assets.items() if tenant == principal.tenant_id)

    def register_document(self, principal: UserPrincipal, upload: ValidatedUpload) -> DocumentRecord:
        created = _now()
        record = DocumentRecord(
            document_id=upload.document_id,
            tenant_id=principal.tenant_id,
            display_name=upload.display_name,
            sha256=upload.sha256,
            status="processing",
            page_count=0,
            created_at=created,
            retention_until=self._retention.expires_at(RecordClass.UPLOADED_CONTENT, created),
        )
        with self._lock:
            duplicate = any(
                item.sha256 == record.sha256 and item.status != "deleted"
                for (tenant, _), item in self._documents.items()
                if tenant == principal.tenant_id
            )
            if duplicate:
                raise ValueError("Dieses Dokument wurde für den Mandanten bereits erfasst.")
            self._documents[(principal.tenant_id, record.document_id)] = record
        return record

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
        with self._lock:
            return tuple(
                item
                for (tenant, _), item in self._documents.items()
                if tenant == principal.tenant_id and item.status != "deleted"
            )

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None:
        key = (principal.tenant_id, document_id)
        with self._lock:
            current = self._documents[key]
            self._documents[key] = replace(current, status="deleted")

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
        del details
        record = IncidentRecord(
            incident_id=str(uuid.uuid4()),
            tenant_id=principal.tenant_id,
            asset_id=asset_id[:120],
            title=title[:240],
            severity=severity,
            status="new",
            created_at=_now(),
        )
        with self._lock:
            self._incidents[(principal.tenant_id, record.incident_id)] = record
        return record

    def list_incidents(self, principal: UserPrincipal) -> tuple[IncidentRecord, ...]:
        with self._lock:
            return tuple(item for (tenant, _), item in self._incidents.items() if tenant == principal.tenant_id)

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
        return {
            "schema": "hydraulikdoc.subject-export.v1",
            "generated_at": _now().isoformat(),
            "subject_token": subject,
            "analysis_runs": answers,
            "notice_acceptances": notices,
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
            "analysis_runs",
            "analysis_reviews",
            "incidents",
            "notice_acceptances",
            "privacy_requests",
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
        if protected != required_tables or purge_function is None or tenant_function is None:
            raise RuntimeError("Database schema is missing required RLS or lifecycle controls")

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
                    (asset_id, tenant_id, name, site, manufacturer, model, criticality, status, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s)
                    ON CONFLICT (tenant_id, asset_id) DO UPDATE SET
                    name=excluded.name, site=excluded.site, manufacturer=excluded.manufacturer,
                    model=excluded.model, criticality=excluded.criticality, updated_at=excluded.updated_at""",
                    (
                        asset_id[:120],
                        principal.tenant_id,
                        name[:240],
                        site[:240],
                        manufacturer[:160],
                        model[:160],
                        criticality,
                        updated,
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
        )

    def list_assets(self, principal: UserPrincipal) -> tuple[AssetRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT asset_id, tenant_id, name, site, manufacturer, model,
                    criticality, status, updated_at FROM assets ORDER BY site, name"""
                )
                return tuple(AssetRecord(*row) for row in cursor.fetchall())

    def register_document(self, principal: UserPrincipal, upload: ValidatedUpload) -> DocumentRecord:
        created = _now()
        expires = self._retention.expires_at(RecordClass.UPLOADED_CONTENT, created)
        actor = _principal_token(self._pseudonymizer, principal)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (principal.tenant_id, principal.tenant_id),
                )
                cursor.execute(
                    """INSERT INTO documents
                    (document_id, tenant_id, display_name, sha256, status, page_count,
                     created_by_token, created_at, retention_until)
                    VALUES (%s, %s, %s, %s, 'processing', 0, %s, %s, %s)""",
                    (
                        upload.document_id,
                        principal.tenant_id,
                        upload.display_name,
                        upload.sha256,
                        actor,
                        created,
                        expires,
                    ),
                )
        return DocumentRecord(
            upload.document_id,
            principal.tenant_id,
            upload.display_name,
            upload.sha256,
            "processing",
            0,
            created,
            expires,
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
                cursor.execute(
                    """SELECT document_id::text, tenant_id, display_name, sha256, status,
                    page_count, created_at, retention_until FROM documents
                    WHERE deleted_at IS NULL ORDER BY created_at DESC"""
                )
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
                     created_at, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,'new',%s,%s,%s)""",
                    (
                        incident_id,
                        principal.tenant_id,
                        asset_id[:120],
                        title[:240],
                        details[:8000],
                        severity,
                        actor,
                        created,
                        expires,
                    ),
                )
        return IncidentRecord(incident_id, principal.tenant_id, asset_id[:120], title[:240], severity, "new", created)

    def list_incidents(self, principal: UserPrincipal) -> tuple[IncidentRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._tenant(cursor, principal.tenant_id)
                cursor.execute(
                    """SELECT incident_id::text, tenant_id, asset_id, title, severity, status, created_at
                    FROM incidents ORDER BY created_at DESC LIMIT 250"""
                )
                return tuple(IncidentRecord(*row) for row in cursor.fetchall())

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
                    """SELECT request_id::text, tenant_id, request_type, status, requested_at, due_at
                    FROM privacy_requests WHERE subject_token=%s ORDER BY requested_at DESC""",
                    (subject,),
                )
                return tuple(PrivacyRequestRecord(*row) for row in cursor.fetchall())

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
        return {
            "schema": "hydraulikdoc.subject-export.v1",
            "generated_at": _now().isoformat(),
            "subject_token": subject,
            "analysis_runs": analysis,
            "notice_acceptances": notices,
            "incidents_created": incidents,
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
                cursor.execute(
                    """SELECT document_id::text, tenant_id, display_name, sha256, status,
                    page_count, created_at, retention_until FROM documents
                    WHERE deleted_at IS NULL AND retention_until <= now() ORDER BY retention_until"""
                )
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
                cursor.execute("SELECT tenant_id FROM tenants WHERE tenant_id=%s FOR UPDATE", (principal.tenant_id,))
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
