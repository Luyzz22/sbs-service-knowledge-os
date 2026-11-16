"""A sealed evidence bundle: control results, the audit trail of the period and the configuration.

Integrity has two layers. The manifest lists the SHA-256 of every file, so a recipient can check
without any secret that nothing changed after the bundle was written. The seal is an HMAC over the
manifest with a key derived from the instance secret; only the operator can check it, which shows
that this instance produced the bundle. It is not a digital signature and proves nothing to a third
party on its own; the audit chain head in the manifest links the bundle to the anchors that the
nightly verification stores outside the database.

Persons appear neither by name nor by their stored pseudonym. Every pseudonym is replaced by an
alias that is valid for one bundle: two events of the same person can be related inside the bundle,
but not across bundles, and only the operator can map an alias back.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import uuid
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .evidence import (
    FINDING_LABELS,
    KIND_LABELS,
    RESOURCE_LABELS,
    STATUS_LABELS,
    ControlResult,
    ControlStatus,
    EvidenceReport,
)
from .evidence_data import AuditTrailEntry
from .i18n import msg, translate
from .interop import to_spreadsheet_csv

BUNDLE_SCHEMA = "hydraulikdoc.evidence-bundle.v1"
MANIFEST_NAME = "manifest.json"
MAX_BUNDLE_EVENTS = 50_000
# Upper bound for one file when a bundle is verified, so a crafted archive cannot exhaust memory.
MAX_VERIFIED_FILE_BYTES = 256 * 1024 * 1024
CONTROL_CSV_COLUMNS = (
    "control_id",
    "title",
    "kind",
    "status",
    "population",
    "findings",
    "prevented_attempts",
    "untested",
    "incomplete",
    "references",
)
_README = (
    msg("HydraulikDoc Nachweispaket"),
    msg(
        "Inhalt: controls.json und controls.csv (Ergebnis der Kontrolltests), audit-events.jsonl (Auditereignisse "
        "des Zeitraums), configuration.json (Konfiguration ohne Geheimnisse) und manifest.json."
    ),
    msg(
        "Integrität: manifest.json nennt die SHA-256-Summe jeder Datei. Prüfung ohne Geheimnis mit "
        "ops/scripts/verify-evidence-bundle.py; das Siegel kann nur der Betreiber mit dem Instanzgeheimnis prüfen."
    ),
    msg(
        "Personen: Das Paket enthält keine Namen. Akteure und Objekte erscheinen als Alias, der nur innerhalb "
        "dieses Pakets gilt. Das Paket bleibt pseudonymisiertes Personendatum und ist vertraulich zu behandeln."
    ),
    msg(
        "Grenzen: Die Kontrolltests belegen die technische Durchsetzung in dieser Instanz für den genannten "
        "Zeitraum. Sie sind keine Konformitätsaussage und ersetzen weder Audit noch Zertifizierung."
    ),
)


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    file_name: str
    content: bytes
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class BundleVerification:
    # True when every listed file matches its hash and, if checked, the seal is valid.
    intact: bool
    # "valid", "invalid" or "not_checked" when no instance secret was given.
    seal: str
    problems: tuple[str, ...]
    manifest: Mapping[str, Any] | None = None


def _seal_key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), b"hydraulikdoc:evidence-seal:v1", hashlib.sha256).digest()


def alias_key(secret: str, bundle_id: str) -> bytes:
    return hmac.new(_seal_key(secret), f"alias:{bundle_id}".encode(), hashlib.sha256).digest()


def scoped_alias(key: bytes, token: str | None, prefix: str) -> str | None:
    """Replace a stored pseudonym by an alias that only relates events inside one bundle."""
    if not token:
        return None
    return f"{prefix}-{hmac.new(key, token.encode('utf-8'), hashlib.sha256).hexdigest()[:12]}"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _seal(secret: str, manifest: Mapping[str, Any]) -> str:
    unsealed = {key: value for key, value in manifest.items() if key != "seal"}
    return hmac.new(_seal_key(secret), _canonical(unsealed), hashlib.sha256).hexdigest()


def control_record(result: ControlResult, language: str) -> dict[str, Any]:
    definition = result.definition
    return {
        "control_id": definition.control_id,
        "kind": definition.kind.value,
        "kind_label": translate(KIND_LABELS[definition.kind], language),
        "title": translate(definition.title, language),
        "objective": translate(definition.objective, language),
        "method": translate(definition.method, language),
        "references": list(definition.references),
        "status": result.status.value,
        "status_label": translate(STATUS_LABELS[result.status], language),
        "population": result.population,
        "prevented_attempts": result.prevented,
        "untested": result.untested,
        "incomplete": result.incomplete,
        "findings": [
            {
                "resource_type": finding.resource_type,
                "resource_label": translate(
                    RESOURCE_LABELS.get(finding.resource_type, finding.resource_type), language
                ),
                "resource_id": finding.resource_id,
                "code": finding.code,
                "text": translate(FINDING_LABELS.get(finding.code, finding.code), language),
                "occurred_at": _iso(finding.occurred_at),
            }
            for finding in result.findings
        ],
    }


def control_csv_rows(report: EvidenceReport, language: str) -> list[dict[str, str]]:
    return [
        {
            "control_id": item.definition.control_id,
            "title": translate(item.definition.title, language),
            "kind": translate(KIND_LABELS[item.definition.kind], language),
            "status": translate(STATUS_LABELS[item.status], language),
            "population": str(item.population),
            "findings": str(len(item.findings)),
            "prevented_attempts": str(item.prevented),
            "untested": str(item.untested),
            "incomplete": "1" if item.incomplete else "0",
            "references": "; ".join(item.definition.references),
        }
        for item in report.results
    ]


def audit_event_records(events: Iterable[AuditTrailEntry], key: bytes) -> list[dict[str, Any]]:
    return [
        {
            "sequence": event.sequence,
            "event_id": event.event_id,
            "occurred_at": _iso(event.occurred_at),
            "action": event.action,
            "outcome": event.outcome,
            "actor": scoped_alias(key, event.actor_token, "akteur"),
            "resource_type": event.resource_type,
            "resource": scoped_alias(key, event.resource_token, "objekt"),
            "metadata": dict(event.metadata),
            "event_hash": event.event_hash,
        }
        for event in events
    ]


def _json_file(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_bundle(
    *,
    report: EvidenceReport,
    events: Sequence[AuditTrailEntry],
    events_truncated: bool,
    configuration: Mapping[str, Any],
    tenant_id: str,
    language: str,
    secret: str,
    bundle_id: str | None = None,
    generated_at: datetime | None = None,
) -> EvidenceBundle:
    """Write the bundle. The same input, identifier and time give byte-identical content."""
    identifier = bundle_id or str(uuid.uuid4())
    created = (generated_at or datetime.now(UTC)).astimezone(UTC)
    key = alias_key(secret, identifier)
    ordered = sorted(events, key=lambda item: item.sequence)
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in audit_event_records(ordered, key)]
    files: dict[str, bytes] = {
        "README.txt": ("\n\n".join(translate(line, language) for line in _README) + "\n").encode("utf-8"),
        "controls.json": _json_file([control_record(item, language) for item in report.results]),
        "controls.csv": to_spreadsheet_csv(control_csv_rows(report, language), CONTROL_CSV_COLUMNS),
        "audit-events.jsonl": ("\n".join(lines) + "\n" if lines else "").encode("utf-8"),
        "configuration.json": _json_file(dict(configuration)),
    }
    chain = report.chain
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "bundle_id": identifier,
        "tenant_id": tenant_id,
        "generated_at": _iso(created),
        "language": language,
        "period": {"since": _iso(report.since), "until": _iso(report.until)},
        "summary": {status.value: report.count(status) for status in ControlStatus},
        "audit_chain": {
            "verified": chain is not None,
            "intact": chain.intact if chain else None,
            "event_count": chain.event_count if chain else None,
            "head_sequence": chain.head_sequence if chain else None,
            "head_hash": chain.head_hash if chain else None,
        },
        "audit_events": {"count": len(ordered), "truncated": events_truncated},
        "files": [
            {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in sorted(files.items())
        ],
    }
    manifest["seal"] = {
        "algorithm": "HMAC-SHA256",
        "scope": "manifest without seal, canonical JSON",
        "value": _seal(secret, manifest),
    }
    files[MANIFEST_NAME] = _json_file(manifest)
    buffer = io.BytesIO()
    stamp = (created.year, created.month, created.day, created.hour, created.minute, created.second)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return EvidenceBundle(
        identifier,
        f"hydraulikdoc-nachweispaket-{created:%Y%m%d-%H%M}-{identifier[:8]}.zip",
        buffer.getvalue(),
        manifest,
    )


def verify_bundle(content: bytes, secret: str | None = None) -> BundleVerification:
    """Check every file against the manifest and, with the instance secret, the seal."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return BundleVerification(False, "not_checked", ("NOT_A_BUNDLE",))
    with archive:
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        if MANIFEST_NAME not in sizes or sizes[MANIFEST_NAME] > MAX_VERIFIED_FILE_BYTES:
            return BundleVerification(False, "not_checked", ("MANIFEST_MISSING",))
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            listed = {str(item["name"]): (str(item["sha256"]), int(item["bytes"])) for item in manifest["files"]}
            sealed = str(manifest["seal"]["value"])
        except (ValueError, KeyError, TypeError):
            return BundleVerification(False, "not_checked", ("MANIFEST_INVALID",))
        if manifest.get("schema") != BUNDLE_SCHEMA:
            return BundleVerification(False, "not_checked", ("SCHEMA_UNKNOWN",), manifest)
        problems = [f"UNLISTED_FILE:{name}" for name in sorted(set(sizes) - set(listed) - {MANIFEST_NAME})]
        for name, (digest, size) in sorted(listed.items()):
            if name not in sizes:
                problems.append(f"FILE_MISSING:{name}")
            elif sizes[name] != size or size > MAX_VERIFIED_FILE_BYTES:
                problems.append(f"SIZE_MISMATCH:{name}")
            elif not hmac.compare_digest(hashlib.sha256(archive.read(name)).hexdigest(), digest):
                problems.append(f"HASH_MISMATCH:{name}")
    seal = "not_checked"
    if secret is not None:
        seal = "valid" if hmac.compare_digest(_seal(secret, manifest), sealed) else "invalid"
        if seal == "invalid":
            problems.append("SEAL_INVALID")
    return BundleVerification(not problems, seal, tuple(problems), manifest)
