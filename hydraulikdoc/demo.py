"""Demo tenant: synthetic data and an extractive answer path for sales demos without Azure.

Everything here is fictitious and labelled as such. The demo backend makes no model call; it
returns sentences copied verbatim from synthetic documents and still runs through the same
use-case gate, citation check, human review and audit trail as the Azure path.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from compliance.audit import AuditOutcome

from .auth import UserPrincipal, require_permission
from .config import AppSettings
from .governance import AIProvenance, GroundedAnswer, SourceCitation, UseCase, evaluate_use_case
from .repository import (
    INCIDENT_ANALYSIS_FIELDS,
    INCIDENT_CLOSE_PERMISSION,
    DocumentRecord,
    EnterpriseRepository,
    IncidentRecord,
)
from .security import InputRejected, ValidatedUpload, validate_question

DEMO_LABEL = "DEMO"
DEMO_PROVIDER = "HydraulikDoc Demo (kein Modellaufruf)"
DEMO_LIMITATION = "Demo-Modus: synthetische Dokumente, extrahierte Sätze statt KI-Generierung."

# Synthetic manuals of fictitious products. Page numbers are part of the citation evidence.
DEMO_DOCUMENTS: Mapping[str, Mapping[int, str]] = {
    "DEMO · Betriebsanleitung Hydraulikaggregat HA-250 (synthetisch)": {
        12: (
            "Kapitel 4.2 Betriebsgrenzen. Der zulässige Betriebsdruck beträgt 210 bar. "
            "Das Druckbegrenzungsventil ist werkseitig auf 250 bar eingestellt. "
            "Ein Prüfdruck von 300 bar darf nur im Rahmen der Abnahmeprüfung angefahren werden. "
            "Bei Drücken über 250 bar im Betrieb ist das Aggregat stillzusetzen und das Druckbegrenzungsventil zu prüfen."
        ),
        18: (
            "Kapitel 6.1 Fluidpflege. Verwendet wird Hydrauliköl HLP 46. "
            "Die Öltemperatur soll im Betrieb zwischen 40 °C und 60 °C liegen. "
            "Ab 70 °C Öltemperatur ist der Kühler zu prüfen, ab 85 °C ist das Aggregat abzuschalten. "
            "Der Wassergehalt im Hydrauliköl darf 0,1 % nicht überschreiten. "
            "Ein Ölwechsel ist nach 4000 Betriebsstunden oder bei Überschreitung der Grenzwerte erforderlich."
        ),
        24: (
            "Kapitel 7.3 Filterwechsel. Der Rücklauffilter ist bei Ansprechen der Verschmutzungsanzeige, "
            "spätestens nach 2000 Betriebsstunden, zu wechseln. "
            "Vor Arbeiten am Hydrauliksystem ist das Aggregat drucklos zu machen und gegen Wiedereinschalten "
            "zu sichern (LOTO)."
        ),
    },
    "DEMO · Wartungsplan Spritzgießmaschine SGM-80 (synthetisch)": {
        3: (
            "Wöchentliche Sichtprüfung. Schlauchleitungen und Verschraubungen sind auf Leckagen zu prüfen. "
            "Schlauchleitungen sind nach spätestens sechs Jahren Verwendungsdauer einschließlich Lagerzeit zu ersetzen."
        ),
        5: (
            "Partikelreinheit. Der Zielwert für die Ölreinheit ist ISO 4406 18/16/13. "
            "Bei einer Partikelzahl über 1000 je ml ist eine Nebenstromfiltration einzuplanen. "
            "Nach der Filtration ist eine Kontrollprobe nach 50 Betriebsstunden zu entnehmen."
        ),
    },
}

DEMO_ASSETS = (
    {
        "asset_id": "DEMO-W1-PRESSE-04",
        "name": "Hydraulikaggregat Presse 04 (Demo)",
        "site": "Demo-Werk 1 · Halle 3",
        "manufacturer": "Musterhydraulik (fiktiv)",
        "model": "HA-250",
        "criticality": "high",
        "functional_location": "DEMO-W1-H3-P04",
        "equipment_number": "90000401",
    },
    {
        "asset_id": "DEMO-W1-PRESSE-05",
        "name": "Hydraulikaggregat Presse 05 (Demo)",
        "site": "Demo-Werk 1 · Halle 3",
        "manufacturer": "Musterhydraulik (fiktiv)",
        "model": "HA-250",
        "criticality": "safety_critical",
        "functional_location": "DEMO-W1-H3-P05",
        "equipment_number": "90000402",
    },
    {
        "asset_id": "DEMO-W2-SGM-01",
        "name": "Spritzgießmaschine 01 (Demo)",
        "site": "Demo-Werk 2 · Halle 1",
        "manufacturer": "Musterkunststofftechnik (fiktiv)",
        "model": "SGM-80",
        "criticality": "medium",
        "functional_location": "DEMO-W2-H1-S01",
        "equipment_number": "",
    },
    {
        # Deliberately without SAP reference so the demo shows the missing-reference hint.
        "asset_id": "DEMO-W2-PUMPE-07",
        "name": "Kühlwasserpumpe 07 (Demo)",
        "site": "Demo-Werk 2 · Halle 1",
        "manufacturer": "",
        "model": "",
        "criticality": "low",
        "functional_location": "",
        "equipment_number": "",
    },
)


@dataclass(frozen=True)
class DemoIncident:
    asset_id: str
    title: str
    severity: str
    details: str
    path: tuple[str, ...]
    analysis: Mapping[str, str]


# Each incident shows one workflow state: open critical, 8D in progress, awaiting sign-off, closed.
DEMO_INCIDENTS = (
    DemoIncident(
        "DEMO-W1-PRESSE-04",
        "DEMO · Druckspitze 268 bar über Ventileinstellung",
        "critical",
        "P_HIGH: 268 bar (Warnung ab 250 bar)\nQuelle: synthetische Messreihe",
        (),
        {},
    ),
    DemoIncident(
        "DEMO-W2-SGM-01",
        "DEMO · Partikelzahl 1450 je ml",
        "warning",
        "PARTICLES_HIGH: 1450 #/ml (Warnung ab 1000 #/ml)",
        ("acknowledged", "in_progress"),
        {"containment_action": "Nebenstromfilter angeschlossen, Kontrollprobe veranlasst"},
    ),
    DemoIncident(
        "DEMO-W1-PRESSE-05",
        "DEMO · Öltemperatur 88 °C, Abschaltgrenze erreicht",
        "critical",
        "T_CRITICAL: 88 °C (Abschaltgrenze 85 °C)",
        ("in_progress", "resolved"),
        {
            "containment_action": "Aggregat abgeschaltet und gegen Wiedereinschalten gesichert",
            "root_cause": "Kühlerlamellen stark verschmutzt, Lüfter mit reduzierter Drehzahl",
            "corrective_action": "Kühler gereinigt, Lüftermotor getauscht, Reinigungsintervall verkürzt",
        },
    ),
    DemoIncident(
        "DEMO-W2-PUMPE-07",
        "DEMO · Leckage an Verschraubung Druckleitung",
        "warning",
        "Sichtprüfung: Tropfleckage an Verschraubung der Druckleitung",
        ("in_progress", "resolved", "closed"),
        {
            "corrective_action": "Verschraubung erneuert und mit Drehmoment nach Vorgabe angezogen",
            "effectiveness_check": "Nachkontrolle nach einer Woche ohne Leckage",
        },
    ),
)


@dataclass(frozen=True)
class DemoSeedResult:
    assets: int
    documents: int
    incidents: int


def tenant_has_data(principal: UserPrincipal, repository: EnterpriseRepository) -> bool:
    return bool(
        repository.list_assets(principal)
        or repository.list_incidents(principal)
        or repository.list_documents(principal)
    )


def demo_seed_blockers(principal: UserPrincipal, repository: EnterpriseRepository) -> tuple[str, ...]:
    """Reasons why the demo data cannot be loaded for this tenant; empty when seeding is allowed."""
    blockers = []
    if not (principal.can("asset:write") and principal.can(INCIDENT_CLOSE_PERMISSION)):
        blockers.append("Demodaten können nur Supervisor oder Admin laden.")
    if tenant_has_data(principal, repository):
        blockers.append("Demodaten werden nur in einen leeren Mandanten geladen, damit sie keine echten Daten mischen.")
    return tuple(blockers)


def seed_demo_tenant(principal: UserPrincipal, repository: EnterpriseRepository) -> DemoSeedResult:
    if blockers := demo_seed_blockers(principal, repository):
        raise PermissionError(blockers[0])
    for asset in DEMO_ASSETS:
        repository.upsert_asset(principal, **asset)
    for display_name, pages in DEMO_DOCUMENTS.items():
        content = "\n".join(pages.values()).encode("utf-8")
        record = repository.register_document(
            principal,
            ValidatedUpload(
                document_id=str(uuid.uuid4()),
                display_name=display_name,
                sha256=hashlib.sha256(content).hexdigest(),
                content=b"",
                content_type="text/plain",
            ),
        )
        repository.mark_document_indexed(principal, record.document_id, max(pages))
    for item in DEMO_INCIDENTS:
        incident = repository.create_incident(
            principal, asset_id=item.asset_id, title=item.title, severity=item.severity, details=item.details
        )
        analysis = {field: item.analysis.get(field, "") for field in INCIDENT_ANALYSIS_FIELDS}
        documented = False
        for target in item.path:
            # The 8D content has to exist before the workflow allows resolution, exactly as for users.
            if target == "resolved" and item.analysis:
                incident = _document(repository, principal, incident, analysis)
                documented = True
            incident = repository.transition_incident(
                principal, incident.incident_id, expected=incident.status, target=target
            )
        if item.analysis and not documented:
            _document(repository, principal, incident, analysis)
    repository.emit_audit(
        principal,
        action="demo.tenant.seeded",
        outcome=AuditOutcome.SUCCESS,
        metadata={"source_count": len(DEMO_ASSETS) + len(DEMO_DOCUMENTS) + len(DEMO_INCIDENTS)},
    )
    return DemoSeedResult(len(DEMO_ASSETS), len(DEMO_DOCUMENTS), len(DEMO_INCIDENTS))


def _document(
    repository: EnterpriseRepository,
    principal: UserPrincipal,
    incident: IncidentRecord,
    analysis: Mapping[str, str],
) -> IncidentRecord:
    return repository.update_incident_analysis(
        principal,
        incident.incident_id,
        expected_updated_at=incident.updated_at or incident.created_at,
        analysis=analysis,
    )


def demo_sensor_csv(start: datetime | None = None) -> bytes:
    """48 hourly readings: stable operation, then rising pressure, temperature and particles."""
    origin = start or datetime(2026, 11, 1, tzinfo=UTC)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("timestamp", "pressure_bar", "temperature_c", "flow_l_min", "particle_count", "water_content_pct"))
    for hour in range(48):
        drift = max(0, hour - 38)
        pressure = 205 + 3 * math.sin(hour / 3) + drift * 9.8
        temperature = 52 + 2 * math.sin(hour / 5) + drift * 2.1
        particles = 780 + hour * 4 + drift * 30
        writer.writerow(
            (
                (origin + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                f"{pressure:.1f}",
                f"{temperature:.1f}",
                "38.0",
                f"{particles:.0f}",
                "0.04",
            )
        )
    return buffer.getvalue().encode("utf-8")


_WORD = re.compile(r"[0-9a-zäöüß]+")
_STOPWORDS = frozenset(
    {
        "aber",
        "auch",
        "beim",
        "bitte",
        "dann",
        "dass",
        "darf",
        "dies",
        "diese",
        "dieser",
        "eine",
        "einem",
        "einen",
        "einer",
        "gibt",
        "gilt",
        "haben",
        "hier",
        "kann",
        "muss",
        "müssen",
        "nach",
        "nicht",
        "noch",
        "oder",
        "sein",
        "sind",
        "soll",
        "sollte",
        "über",
        "unter",
        "wann",
        "warum",
        "welche",
        "welchem",
        "welchen",
        "welcher",
        "welches",
        "wenn",
        "werden",
        "wird",
        "wieviel",
        "worauf",
    }
)
_MAX_HITS = 3


def _words(text: str) -> set[str]:
    return {
        word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS and (len(word) >= 4 or word.isdigit())
    }


def _stem(word: str) -> str:
    # A 7-character stem keeps simple German inflections together (stillgesetzt/stillzusetzen stay apart).
    return word[:7]


def _sentences(text: str) -> list[str]:
    # Chapter headings ("Kapitel 6.1 Fluidpflege.") are not evidence; keep sentences of four words or more.
    parts = (item.strip() for item in re.split(r"(?<=\.)\s+(?=[A-ZÄÖÜ])", text))
    return [part for part in parts if len(part.split()) >= 4]


@dataclass(frozen=True)
class _Hit:
    document: DocumentRecord
    page: int
    sentence: str
    score: int
    covered: frozenset[str]


def _match(question_words: set[str], sentence: str) -> tuple[int, frozenset[str]]:
    """Score exact words twice and stem-only matches once; coverage counts exact words only."""
    words = _words(sentence)
    stems = {_stem(word) for word in words}
    exact = question_words & words
    stemmed = {word for word in question_words - exact if _stem(word) in stems}
    return 2 * len(exact) + len(stemmed), frozenset(exact)


class DemoRAGService:
    """Same interface as AzureRAGService, answering only from the synthetic demo documents."""

    def __init__(self, settings: AppSettings, repository: EnterpriseRepository) -> None:
        if not settings.demo_mode:
            raise RuntimeError("DemoRAGService requires AI_BACKEND=demo")
        self._settings = settings
        self._repository = repository

    def ingest(self, principal: UserPrincipal, upload: ValidatedUpload) -> DocumentRecord:
        del principal, upload
        raise InputRejected("Im Demo-Modus können keine Dokumente hochgeladen werden.")

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None:
        require_permission(principal, "knowledge:write")
        self._repository.delete_document(principal, document_id)
        self._repository.emit_audit(
            principal,
            action="knowledge.document.deleted",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id=document_id,
            metadata={"provider": "demo"},
        )

    def _retrieve(self, principal: UserPrincipal, question: str) -> tuple[_Hit, ...]:
        wanted = _words(question)
        candidates: list[_Hit] = []
        for document in self._repository.list_documents(principal):
            pages = DEMO_DOCUMENTS.get(document.display_name)
            if not pages or document.status != "ready":
                continue
            for page, text in pages.items():
                for sentence in _sentences(text):
                    score, covered = _match(wanted, sentence)
                    # One exact word or two stem matches; a single stem overlap is noise.
                    if score >= 2:
                        candidates.append(_Hit(document, page, sentence, score, covered))
        # Greedy coverage: further sentences must answer a part of the question not covered yet.
        selected: list[_Hit] = []
        answered: set[str] = set()
        # Ties prefer the longer, usually more specific sentence.
        for hit in sorted(candidates, key=lambda item: (-item.score, -len(item.sentence), item.page)):
            if hit.covered - answered:
                selected.append(hit)
                answered |= hit.covered
            if len(selected) == _MAX_HITS:
                break
        return tuple(selected)

    def ask(self, principal: UserPrincipal, question: str, use_case: UseCase) -> GroundedAnswer:
        require_permission(principal, "knowledge:read")
        decision = evaluate_use_case(use_case)
        if not decision.allowed:
            self._repository.emit_audit(
                principal,
                action="knowledge.query.denied",
                outcome=AuditOutcome.DENIED,
                metadata={"reason_code": decision.reason_code, "risk_class": decision.risk_class.value},
            )
            raise PermissionError(decision.reason_code)
        cleaned = validate_question(question, self._settings.max_question_chars)
        started = time.monotonic()
        hits = self._retrieve(principal, cleaned)
        if hits:
            lines = "\n".join(f"- {hit.sentence} [S{index}]" for index, hit in enumerate(hits, start=1))
            text = (
                "**Demo-Antwort ohne Sprachmodell.** Die folgenden Sätze stammen unverändert aus synthetischen "
                f"Demodokumenten:\n\n{lines}\n\nVor jeder Handlung Originalunterlage, Betriebsanweisung und "
                "Gefährdungsbeurteilung prüfen."
            )
        else:
            text = (
                "In den Demodokumenten wurde keine passende Evidenz gefunden. Im Demo-Modus stehen nur die "
                "synthetischen Unterlagen zu HA-250 und SGM-80 zur Verfügung."
            )
        citations = tuple(
            SourceCitation(
                hit.document.document_id,
                hit.document.display_name,
                hit.page,
                hashlib.sha256(f"{hit.document.document_id}:{hit.page}:{hit.sentence}".encode()).hexdigest(),
                float(hit.score),
            )
            for hit in hits
        )
        answer = GroundedAnswer.create(
            text=text,
            citations=citations,
            provenance=AIProvenance(
                provider=DEMO_PROVIDER, deployment="demo-extractive", model_snapshot="none", region="local"
            ),
            use_case=use_case,
        )
        answer = replace(answer, limitations=(DEMO_LIMITATION, *answer.limitations))
        self._repository.record_answer(principal, cleaned, answer)
        self._repository.emit_audit(
            principal,
            action="knowledge.query.completed",
            outcome=AuditOutcome.SUCCESS,
            resource_type="analysis",
            resource_id=answer.answer_id,
            metadata={
                "duration_ms": int((time.monotonic() - started) * 1000),
                "source_count": len(citations),
                "provider": "demo",
                "risk_class": answer.risk_class.value,
                "review_status": answer.review_status.value,
            },
        )
        return answer
