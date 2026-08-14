"""Propagate approved retention expiry across Azure storage, search and PostgreSQL."""

from __future__ import annotations

import json

from compliance.audit import AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.azure_ai import AzureRAGService
from hydraulikdoc.config import PersistenceBackend, get_settings
from hydraulikdoc.repository import PostgresRepository


def _system_principal(tenant_id: str) -> UserPrincipal:
    return UserPrincipal(
        subject_id="system:retention",
        tenant_id=tenant_id,
        display_name="Retention Lifecycle",
        role="admin",
        permissions=ROLE_PERMISSIONS["admin"],
        authentication_method="scheduled_job",
    )


def main() -> None:
    settings = get_settings()
    if not settings.is_production or settings.persistence_backend is not PersistenceBackend.POSTGRES:
        raise RuntimeError("Retention enforcement requires the production PostgreSQL profile")
    if not settings.retention_policy_approved or not settings.retention_policy_id:
        raise RuntimeError("Retention enforcement requires approved policy evidence")

    repository = PostgresRepository(settings)
    rag = AzureRAGService(settings, repository)
    tenant_count = 0
    deleted_count = 0
    failure_count = 0

    for tenant_id in repository.list_tenant_ids():
        tenant_count += 1
        principal = _system_principal(tenant_id)
        try:
            documents = repository.list_expired_documents(principal)
            for document in documents:
                rag.delete_document(principal, document.document_id)
            counts = repository.purge_expired_records(principal)
            tenant_deleted = len(documents) + sum(counts.values())
            deleted_count += tenant_deleted
            repository.emit_audit(
                principal,
                action="retention.lifecycle.completed",
                outcome=AuditOutcome.SUCCESS,
                metadata={
                    "deletion_count": tenant_deleted,
                    "document_count": len(documents),
                    "evidence_id": settings.retention_policy_id,
                },
            )
        except Exception:
            failure_count += 1
            repository.emit_audit(
                principal,
                action="retention.lifecycle.failed",
                outcome=AuditOutcome.FAILURE,
                metadata={
                    "error_code": "RETENTION_PROPAGATION_FAILED",
                    "evidence_id": settings.retention_policy_id,
                },
            )

    print(
        json.dumps(
            {
                "event": "retention_lifecycle_finished",
                "tenant_count": tenant_count,
                "deletion_count": deleted_count,
                "failure_count": failure_count,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if failure_count:
        raise RuntimeError("Retention propagation failed for one or more tenants")


if __name__ == "__main__":
    main()
