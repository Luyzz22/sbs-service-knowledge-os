"""Verify every tenant's audit hash chain and print the heads as anchors for the next run.

Runs nightly after the retention job. A hash chain alone cannot reveal deleted newest events, so keep
the printed output outside the database (Log Analytics, write-once storage) and pass an earlier run's
output as AUDIT_ANCHOR_FILE to check that its heads still exist unchanged. Exits 1 when a chain is broken.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from compliance.audit import AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import PersistenceBackend, get_settings
from hydraulikdoc.repository import PostgresRepository


def _system_principal(tenant_id: str) -> UserPrincipal:
    return UserPrincipal(
        subject_id="system:audit-verification",
        tenant_id=tenant_id,
        display_name="Audit Chain Verification",
        role="admin",
        permissions=ROLE_PERMISSIONS["admin"],
        authentication_method="scheduled_job",
    )


def load_anchors(path: str | None) -> dict[str, tuple[int, str]]:
    """Read an earlier run's output (or a plain tenant mapping) as {tenant: (sequence, event_hash)}."""
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    tenants = payload.get("tenants", payload)
    return {
        tenant: (int(head["sequence"]), str(head["event_hash"]))
        for tenant, head in tenants.items()
        if head.get("sequence") is not None and head.get("event_hash")
    }


def main() -> int:
    settings = get_settings()
    if settings.persistence_backend is not PersistenceBackend.POSTGRES:
        raise RuntimeError("Audit chain verification requires PostgreSQL persistence")
    anchors = load_anchors(os.environ.get("AUDIT_ANCHOR_FILE"))
    repository = PostgresRepository(settings)
    tenants: dict[str, dict[str, Any]] = {}
    for tenant_id in repository.list_tenant_ids():
        principal = _system_principal(tenant_id)
        report = repository.verify_audit_chain(principal, anchors.get(tenant_id))
        repository.emit_audit(
            principal,
            action="audit.chain.verified",
            outcome=AuditOutcome.SUCCESS if report.intact else AuditOutcome.FAILURE,
            metadata={
                "source_count": report.event_count,
                "failure_count": 0 if report.intact else 1,
                "reason_code": report.reason,
            },
        )
        tenants[tenant_id] = {
            "intact": report.intact,
            "event_count": report.event_count,
            "sequence": report.head_sequence,
            "event_hash": report.head_hash,
            "starts_after_purge": report.starts_after_purge,
            "anchor_status": report.anchor_status,
            "reason": report.reason,
            "broken_sequence": report.broken_sequence,
        }
    failure_count = sum(1 for item in tenants.values() if not item["intact"])
    print(
        json.dumps(
            {
                "event": "audit_chain_verification_finished",
                "tenant_count": len(tenants),
                "failure_count": failure_count,
                "tenants": tenants,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 1 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
