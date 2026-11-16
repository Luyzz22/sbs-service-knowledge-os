"""Control tests re-performed from stored records, as evidence for audits.

The application enforces its rules when a request arrives. An auditor needs more than that claim:
evidence that a rule held for every record of a period, including records that were changed outside
the application. Each test here reads the stored facts again and applies the rule independently of
the code path that enforced it, so a release by the uploader shows up even if it was written straight
into the database.

Two kinds of control are told apart. An *enforced* control is a rule the application does not let
anyone break; a finding means the rule was bypassed and is a security incident. A *monitored* control
is a deadline or a state that people have to keep; a finding is an open item. A control without any
case in the period is reported as not exercised, never as effective.

A result names records, not persons. The references to standards say which requirement a test
supports; they are no statement of conformity and replace neither an audit nor a certification.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .ai_quality import REVIEW_TARGET
from .auth import ROLE_PERMISSIONS
from .evidence_data import (
    RETENTION_GRACE,
    AnswerEvidence,
    DeniedAttempts,
    DocumentEvidence,
    EvidenceSnapshot,
    ReviewStep,
)
from .i18n import Message, msg
from .repository import (
    EIGHT_D_SEVERITIES,
    INCIDENT_ANALYSIS_FIELDS,
    INCIDENT_CLOSE_PERMISSION,
    PRIVACY_OPEN_STATUSES,
    REVIEW_EXPERT_PERMISSION,
    REVIEW_REJECTION_REASONS,
    AuditChainReport,
)

EVIDENCE_WINDOW_DAYS = (30, 90, 365)
EVIDENCE_ROW_LIMIT = 10_000
# A query that was already running when a source was withdrawn may still cite it; clocks of several
# application instances also differ slightly. Times closer than this are not treated as a violation.
TIME_TOLERANCE = timedelta(minutes=5)
AI_NOTICE_TYPE = "ai_literacy"


class ControlKind(StrEnum):
    ENFORCED = "enforced"
    MONITORED = "monitored"


class ControlStatus(StrEnum):
    EFFECTIVE = "effective"
    DEVIATION = "deviation"
    OPEN_ITEMS = "open_items"
    NOT_EXERCISED = "not_exercised"


def _roles_with(permission: str) -> frozenset[str]:
    return frozenset(role for role, granted in ROLE_PERMISSIONS.items() if "*" in granted or permission in granted)


EXPERT_ROLES = _roles_with(REVIEW_EXPERT_PERMISSION)
CLOSING_ROLES = _roles_with(INCIDENT_CLOSE_PERMISSION)


@dataclass(frozen=True)
class ControlFinding:
    """One record that does not meet the control. It refers to the record, never to a person."""

    resource_type: str
    resource_id: str
    code: str
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class ControlDefinition:
    control_id: str
    kind: ControlKind
    title: Message
    objective: Message
    method: Message
    references: tuple[str, ...]
    # Datasets of the snapshot the test reads; a truncated one makes the result incomplete.
    datasets: tuple[str, ...]
    # Denied audit events (action, reason code) that show the control stopping an attempt.
    prevented_by: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class ControlResult:
    definition: ControlDefinition
    population: int
    findings: tuple[ControlFinding, ...]
    # Attempts that the application refused in the period, taken from the audit trail.
    prevented: int = 0
    # Cases the stored records cannot decide, such as answers citing a document that has been purged.
    untested: int = 0
    incomplete: bool = False

    @property
    def status(self) -> ControlStatus:
        if self.findings:
            enforced = self.definition.kind is ControlKind.ENFORCED
            return ControlStatus.DEVIATION if enforced else ControlStatus.OPEN_ITEMS
        if self.population == 0:
            return ControlStatus.NOT_EXERCISED
        return ControlStatus.EFFECTIVE


@dataclass(frozen=True)
class EvidenceReport:
    since: datetime
    until: datetime
    results: tuple[ControlResult, ...]
    chain: AuditChainReport | None
    # Requests the application refused in the period, by action and reason.
    denied: tuple[DeniedAttempts, ...] = ()
    truncated: frozenset[str] = frozenset()

    def count(self, status: ControlStatus) -> int:
        return sum(1 for item in self.results if item.status is status)

    @property
    def deviations(self) -> tuple[ControlResult, ...]:
        return tuple(item for item in self.results if item.status is ControlStatus.DEVIATION)


_Outcome = tuple[int, list[ControlFinding], int]
_Test = Callable[[EvidenceSnapshot], _Outcome]


def _within(snapshot: EvidenceSnapshot, moment: datetime | None) -> bool:
    return moment is not None and snapshot.since <= moment <= snapshot.until


def _in_force(document: DocumentEvidence) -> bool:
    return document.status == "ready" and document.release_status == "released"


def _in_force_at(document: DocumentEvidence, moment: datetime) -> bool | None:
    """Whether the document was a released source at ``moment``; None when the records cannot tell."""
    if document.status == "deleted" and document.deleted_at is None:
        return None
    # Documents from before document control have no upload step and were in use from the start.
    legacy = not any(step.event_type == "uploaded" for step in document.steps)
    start = document.created_at if legacy else document.released_at
    if start is None or moment + TIME_TOLERANCE < start:
        return False
    ends = [value for value in (document.withdrawn_at, document.deleted_at) if value is not None]
    return not (ends and moment - TIME_TOLERANCE > min(ends))


def _document_release(snapshot: EvidenceSnapshot) -> _Outcome:
    population = 0
    findings = []
    for document in snapshot.documents:
        for step in document.steps:
            if step.event_type != "released" or not _within(snapshot, step.occurred_at):
                continue
            population += 1
            if step.actor_token == document.uploader_token:
                findings.append(ControlFinding("document", document.document_id, "SAME_PERSON", step.occurred_at))
    return population, findings, 0


def _cited_sources(snapshot: EvidenceSnapshot) -> _Outcome:
    register = {item.document_id: item for item in snapshot.documents}
    population = untested = 0
    findings = []
    for answer in snapshot.answers:
        if not answer.document_ids or not _within(snapshot, answer.generated_at):
            continue
        population += 1
        states = [
            _in_force_at(register[document_id], answer.generated_at) if document_id in register else None
            for document_id in answer.document_ids
        ]
        if False in states:
            findings.append(ControlFinding("analysis", answer.answer_id, "SOURCE_NOT_RELEASED", answer.generated_at))
        elif None in states:
            untested += 1
    return population, findings, untested


def _document_review(snapshot: EvidenceSnapshot) -> _Outcome:
    findings = []
    in_force = [item for item in snapshot.documents if _in_force(item)]
    for document in in_force:
        if document.released_at is None:
            findings.append(ControlFinding("document", document.document_id, "NO_RECORDED_RELEASE"))
        elif document.review_due_at is not None and document.review_due_at <= snapshot.until:
            findings.append(ControlFinding("document", document.document_id, "REVIEW_OVERDUE", document.review_due_at))
    return len(in_force), findings, 0


def _decisions(answer: AnswerEvidence) -> list[ReviewStep]:
    return [item for item in answer.reviews if item.status in ("accepted", "rejected")]


def _answer_four_eyes(snapshot: EvidenceSnapshot) -> _Outcome:
    population = 0
    findings = []
    for answer in snapshot.answers:
        if answer.risk_class != "heightened":
            continue
        for review in answer.reviews:
            if review.status != "accepted" or not _within(snapshot, review.reviewed_at):
                continue
            population += 1
            if review.reviewer_token == answer.asker_token:
                findings.append(ControlFinding("analysis", answer.answer_id, "SAME_PERSON", review.reviewed_at))
    return population, findings, 0


def _review_decisions(snapshot: EvidenceSnapshot) -> _Outcome:
    population = untested = 0
    findings = []
    for answer in snapshot.answers:
        decisions = _decisions(answer)
        decided = answer.review_status in ("accepted", "rejected")
        if not decisions:
            # A decided status without any review row was not set through the review workflow.
            if decided and _within(snapshot, answer.generated_at):
                population += 1
                findings.append(
                    ControlFinding("analysis", answer.answer_id, "DECISION_WITHOUT_REVIEW", answer.generated_at)
                )
            continue
        current = [item for item in decisions if _within(snapshot, item.reviewed_at)]
        if not current:
            continue
        # Reviews from before the role was stored predate the rules tested here.
        if not all(item.reviewer_role for item in current):
            untested += 1
            continue
        population += 1
        codes = []
        if len(decisions) > 1:
            codes.append("DECIDED_TWICE")
        if any(item.status == "rejected" and item.reason_code not in REVIEW_REJECTION_REASONS for item in current):
            codes.append("REASON_MISSING")
        escalated = min((item.reviewed_at for item in answer.reviews if item.status == "needs_expert"), default=None)
        if escalated is not None and any(
            item.reviewed_at >= escalated and item.reviewer_role not in EXPERT_ROLES for item in current
        ):
            codes.append("NOT_EXPERT")
        if decisions[-1].status != answer.review_status:
            codes.append("STATUS_MISMATCH")
        findings += [ControlFinding("analysis", answer.answer_id, code, current[-1].reviewed_at) for code in codes]
    return population, findings, untested


def _open_second_reviews(snapshot: EvidenceSnapshot) -> _Outcome:
    waiting = [
        item
        for item in snapshot.answers
        if item.review_status == "needs_expert" or (item.review_status == "draft" and item.risk_class == "heightened")
    ]
    findings = [
        ControlFinding("analysis", item.answer_id, "REVIEW_OVERDUE", item.generated_at + REVIEW_TARGET)
        for item in waiting
        if snapshot.until - item.generated_at > REVIEW_TARGET
    ]
    return len(waiting), findings, 0


def _notice_before_use(snapshot: EvidenceSnapshot) -> _Outcome:
    accepted: dict[str, datetime] = {}
    for notice in snapshot.notices:
        if notice.notice_type == AI_NOTICE_TYPE:
            accepted[notice.actor_token] = min(notice.accepted_at, accepted.get(notice.actor_token, notice.accepted_at))
    first_use: dict[str, AnswerEvidence] = {}
    for answer in snapshot.answers:
        if not _within(snapshot, answer.generated_at):
            continue
        known = first_use.get(answer.asker_token)
        if known is None or answer.generated_at < known.generated_at:
            first_use[answer.asker_token] = answer
    findings = []
    for token, answer in first_use.items():
        confirmed = accepted.get(token)
        if confirmed is None or confirmed > answer.generated_at + TIME_TOLERANCE:
            # The finding points at the answer; who asked is deliberately not part of a result.
            findings.append(ControlFinding("analysis", answer.answer_id, "NOTICE_MISSING", answer.generated_at))
    return len(first_use), findings, 0


def _limit_release(snapshot: EvidenceSnapshot) -> _Outcome:
    population = 0
    findings = []
    for limit in snapshot.limits:
        if limit.status not in ("released", "superseded") or not _within(snapshot, limit.decided_at):
            continue
        population += 1
        if limit.decider_token is None:
            findings.append(ControlFinding("operating_limits", limit.limit_set_id, "DECIDER_MISSING", limit.decided_at))
        elif limit.decider_token == limit.proposer_token:
            findings.append(ControlFinding("operating_limits", limit.limit_set_id, "SAME_PERSON", limit.decided_at))
    return population, findings, 0


def _limit_sources(snapshot: EvidenceSnapshot) -> _Outcome:
    register = {item.document_id: item for item in snapshot.documents}
    linked = [item for item in snapshot.limits if item.status == "released" and item.source_document_id]
    findings = []
    for limit in linked:
        document = register.get(limit.source_document_id or "")
        if document is None or not _in_force(document):
            findings.append(ControlFinding("operating_limits", limit.limit_set_id, "SOURCE_NOT_RELEASED"))
    return len(linked), findings, 0


def _incident_sign_off(snapshot: EvidenceSnapshot) -> _Outcome:
    population = untested = 0
    findings = []
    for incident in snapshot.incidents:
        closing = [
            step for step in incident.steps if step.event_type == "status_changed" and step.new_status == "closed"
        ]
        if not closing:
            # Closed incidents from before the history was recorded carry no step to test.
            if incident.status == "closed" and _within(snapshot, incident.created_at):
                untested += 1
            continue
        step = closing[-1]
        if not _within(snapshot, step.occurred_at):
            continue
        population += 1
        if step.actor_role not in CLOSING_ROLES:
            findings.append(ControlFinding("incident", incident.incident_id, "ROLE_NOT_AUTHORISED", step.occurred_at))
        required = INCIDENT_ANALYSIS_FIELDS if incident.severity in EIGHT_D_SEVERITIES else ("corrective_action",)
        if not set(required) <= incident.documented_fields:
            findings.append(ControlFinding("incident", incident.incident_id, "ANALYSIS_INCOMPLETE", step.occurred_at))
    return population, findings, untested


def _privacy_deadlines(snapshot: EvidenceSnapshot) -> _Outcome:
    population = 0
    findings = []
    for request in snapshot.privacy_requests:
        is_open = request.status in PRIVACY_OPEN_STATUSES
        if not (is_open or _within(snapshot, request.requested_at) or _within(snapshot, request.completed_at)):
            continue
        population += 1
        if is_open and request.due_at <= snapshot.until:
            findings.append(ControlFinding("privacy_request", request.request_id, "DEADLINE_OVERDUE", request.due_at))
        elif request.completed_at is not None and request.completed_at > request.due_at:
            findings.append(ControlFinding("privacy_request", request.request_id, "DECIDED_LATE", request.completed_at))
    return population, findings, 0


def _retention(snapshot: EvidenceSnapshot) -> _Outcome:
    held = {
        record_class
        for hold in snapshot.legal_holds
        if hold.released_at is None
        for record_class in hold.record_classes
    }
    findings = [
        ControlFinding("record_class", item.record_class, "RETENTION_OVERDUE", item.oldest_due)
        for item in snapshot.retention
        if item.overdue and item.record_class not in held
    ]
    return len(snapshot.retention), findings, 0


def _hold_reviews(snapshot: EvidenceSnapshot) -> _Outcome:
    active = [item for item in snapshot.legal_holds if item.released_at is None]
    findings = [
        ControlFinding("legal_hold", item.hold_id, "REVIEW_OVERDUE", item.review_at)
        for item in active
        if item.review_at <= snapshot.until
    ]
    return len(active), findings, 0


_SEGREGATION = "ISO/IEC 27001:2022 A.5.3"

CONTROLS: tuple[tuple[ControlDefinition, _Test | None], ...] = (
    (
        ControlDefinition(
            "DOC-01",
            ControlKind.ENFORCED,
            msg("Dokumente gibt eine zweite Person frei"),
            msg("Kein Dokument wird zur KI-Quelle, das nur die hochladende Person geprüft hat."),
            msg(
                "Für jede Freigabe im Zeitraum wird das Pseudonym der freigebenden Person mit dem der "
                "hochladenden Person verglichen."
            ),
            (_SEGREGATION, "ISO 9001:2015 7.5.2", "ISO 9001:2015 7.5.3"),
            ("documents",),
            frozenset({("knowledge.document.release_denied", "FOUR_EYES_RELEASE_REQUIRED")}),
        ),
        _document_release,
    ),
    (
        ControlDefinition(
            "DOC-02",
            ControlKind.ENFORCED,
            msg("Die KI zitiert nur freigegebene Dokumente"),
            msg("Entwürfe, zurückgezogene und gelöschte Dokumente erreichen keine Antwort."),
            msg(
                "Für jede Antwort mit Quellen im Zeitraum wird geprüft, ob jedes zitierte Dokument zum Zeitpunkt der "
                "Antwort freigegeben und weder zurückgezogen noch gelöscht war (Toleranz {minutes} Minuten für "
                "laufende Abfragen).",
                minutes=int(TIME_TOLERANCE / timedelta(minutes=1)),
            ),
            ("ISO 9001:2015 7.5.3", "Verordnung (EU) 2024/1689 Art. 10"),
            ("documents", "answers"),
        ),
        _cited_sources,
    ),
    (
        ControlDefinition(
            "DOC-03",
            ControlKind.MONITORED,
            msg("Freigegebene Dokumente sind formal freigegeben und überprüft"),
            msg("Jedes Dokument in Verwendung hat eine dokumentierte Freigabe und einen nicht überschrittenen Termin."),
            msg(
                "Alle derzeit freigegebenen Dokumente werden auf eine dokumentierte Freigabe und einen überfälligen "
                "Überprüfungstermin geprüft."
            ),
            ("ISO 9001:2015 7.5.3",),
            ("documents",),
        ),
        _document_review,
    ),
    (
        ControlDefinition(
            "AI-01",
            ControlKind.ENFORCED,
            msg("Sicherheitsrelevante KI-Antworten akzeptiert eine zweite Person"),
            msg("Niemand gibt die Antwort auf die eigene sicherheitsrelevante Frage selbst frei."),
            msg(
                "Für jede im Zeitraum akzeptierte sicherheitsrelevante Antwort wird das Pseudonym der prüfenden mit "
                "dem der fragenden Person verglichen."
            ),
            (_SEGREGATION, "Verordnung (EU) 2024/1689 Art. 14"),
            ("answers",),
            frozenset({("analysis.review.denied", "FOUR_EYES_REVIEW_REQUIRED")}),
        ),
        _answer_four_eyes,
    ),
    (
        ControlDefinition(
            "AI-02",
            ControlKind.ENFORCED,
            msg("Prüfentscheidungen sind endgültig, begründet und von der zuständigen Rolle"),
            msg(
                "Jede Entscheidung stammt aus der Fachprüfung, Ablehnungen tragen einen festen Grund, und über "
                "eskalierte Antworten entscheidet eine Expertenrolle."
            ),
            msg(
                "Für jede Antwort mit Entscheidung im Zeitraum wird geprüft: genau eine Entscheidung, fester "
                "Ablehnungsgrund, Expertenrolle nach einer Eskalation, und der gespeicherte Status entspricht der "
                "Entscheidung."
            ),
            ("Verordnung (EU) 2024/1689 Art. 14", "ISO/IEC 27001:2022 A.5.36"),
            ("answers",),
            frozenset(
                {
                    ("analysis.review.denied", "EXPERT_REVIEW_REQUIRED"),
                    ("analysis.review.denied", "REVIEW_ALREADY_DECIDED"),
                    ("analysis.review.denied", "REVIEW_ALREADY_ESCALATED"),
                    ("analysis.review.denied", "REVIEW_REASON_REQUIRED"),
                    ("analysis.review.denied", "REVIEW_SOURCE_NOT_RELEASED"),
                }
            ),
        ),
        _review_decisions,
    ),
    (
        ControlDefinition(
            "AI-03",
            ControlKind.MONITORED,
            msg(
                "Antworten warten nicht länger als {hours} Stunden auf die zweite Person",
                hours=int(REVIEW_TARGET / timedelta(hours=1)),
            ),
            msg("Sicherheitsrelevante und eskalierte Antworten bleiben nicht ungeprüft liegen."),
            msg("Alle offenen Antworten, die eine zweite Person brauchen, werden gegen die Zielzeit geprüft."),
            ("Verordnung (EU) 2024/1689 Art. 14",),
            ("answers",),
        ),
        _open_second_reviews,
    ),
    (
        ControlDefinition(
            "AI-04",
            ControlKind.ENFORCED,
            msg("Der KI-Nutzerhinweis ist vor der ersten Nutzung bestätigt"),
            msg("Niemand erhält einen KI-Entwurf, ohne die Grenzen des Systems bestätigt zu haben."),
            msg(
                "Für jede Person mit einer KI-Anfrage im Zeitraum wird geprüft, ob vor ihrer ersten Anfrage eine "
                "Bestätigung des KI-Nutzerhinweises gespeichert ist. Das Ergebnis nennt die Antwort, nicht die Person."
            ),
            ("Verordnung (EU) 2024/1689 Art. 4", "Verordnung (EU) 2024/1689 Art. 50"),
            ("answers", "notices"),
        ),
        _notice_before_use,
    ),
    (
        ControlDefinition(
            "LIM-01",
            ControlKind.ENFORCED,
            msg("Betriebsgrenzen gibt eine zweite Person frei"),
            msg("Keine Abschalt- oder Warngrenze gilt, die nur die vorschlagende Person geprüft hat."),
            msg(
                "Für jede Freigabe von Betriebsgrenzen im Zeitraum wird das Pseudonym der freigebenden mit dem der "
                "vorschlagenden Person verglichen."
            ),
            (_SEGREGATION, "ISO 9001:2015 7.5.3"),
            ("limits",),
            frozenset({("asset.limits.release_denied", "FOUR_EYES_LIMITS_REQUIRED")}),
        ),
        _limit_release,
    ),
    (
        ControlDefinition(
            "LIM-02",
            ControlKind.MONITORED,
            msg("Gültige Betriebsgrenzen stützen sich auf eine freigegebene Quelle"),
            msg("Grenzen, deren Quelldokument zurückgezogen wurde, werden neu bewertet."),
            msg(
                "Für alle gültigen Betriebsgrenzen mit verknüpftem Dokument wird geprüft, ob das Dokument noch "
                "freigegeben ist."
            ),
            ("ISO 9001:2015 7.5.3",),
            ("limits", "documents"),
        ),
        _limit_sources,
    ),
    (
        ControlDefinition(
            "INC-01",
            ControlKind.ENFORCED,
            msg("Incidents schließt eine berechtigte Rolle mit vollständiger Analyse"),
            msg(
                "Kein Incident wird ohne Abnahme durch Supervisor oder Admin und ohne dokumentierte Analyse geschlossen."
            ),
            msg(
                "Für jeden im Zeitraum geschlossenen Incident werden die Rolle der abnehmenden Person und die "
                "Pflichtfelder der Analyse geprüft (8D-Felder bei Schwere kritisch, P1 und P2)."
            ),
            ("ISO 9001:2015 10.2", "IATF 16949:2016 10.2.3"),
            ("incidents",),
            frozenset(
                {
                    ("incident.status.denied", "INCIDENT_CLOSE_REQUIRED"),
                    ("incident.status.denied", "INCIDENT_ANALYSIS_INCOMPLETE"),
                }
            ),
        ),
        _incident_sign_off,
    ),
    (
        ControlDefinition(
            "PRIV-01",
            ControlKind.MONITORED,
            msg("Datenschutzanträge werden fristgerecht entschieden"),
            msg("Kein Antrag überschreitet die interne Zielfrist von 28 Tagen."),
            msg(
                "Alle offenen und alle im Zeitraum gestellten oder entschiedenen Anträge werden gegen ihre Frist "
                "geprüft."
            ),
            ("DSGVO Art. 12 Abs. 3", "ISO/IEC 27001:2022 A.5.34"),
            ("privacy_requests",),
        ),
        _privacy_deadlines,
    ),
    (
        ControlDefinition(
            "RET-01",
            ControlKind.MONITORED,
            msg("Löschfristen werden durchgesetzt"),
            msg("Kein Datensatz bleibt über seine Löschfrist hinaus gespeichert, außer unter einem Legal Hold."),
            msg(
                "Je Datenklasse werden die Datensätze gezählt, deren Löschfrist seit mehr als {hours} Stunden "
                "abgelaufen ist; Datenklassen unter einem aktiven Legal Hold sind ausgenommen.",
                hours=int(RETENTION_GRACE / timedelta(hours=1)),
            ),
            ("DSGVO Art. 5 Abs. 1 lit. e", "ISO/IEC 27001:2022 A.8.10"),
            ("retention", "legal_holds"),
        ),
        _retention,
    ),
    (
        ControlDefinition(
            "RET-02",
            ControlKind.MONITORED,
            msg("Legal Holds werden fristgerecht wiedervorgelegt"),
            msg("Kein Legal Hold setzt die Löschung länger aus, als seine Wiedervorlage erlaubt."),
            msg("Alle aktiven Legal Holds werden auf eine überfällige Wiedervorlage geprüft."),
            ("ISO/IEC 27001:2022 A.5.28", "ISO/IEC 27001:2022 A.5.33"),
            ("legal_holds",),
        ),
        _hold_reviews,
    ),
    (
        ControlDefinition(
            "LOG-01",
            ControlKind.ENFORCED,
            msg("Das Auditprotokoll ist unverändert"),
            msg("Kein Auditereignis wurde nachträglich geändert, entfernt oder umsortiert."),
            msg(
                "Jedes Auditereignis des Mandanten wird neu berechnet und seine Verkettung geprüft. Das Löschen der "
                "jüngsten Ereignisse erkennt nur der nächtliche Abgleich mit den extern gespeicherten Ankern."
            ),
            ("ISO/IEC 27001:2022 A.8.15", "Verordnung (EU) 2024/1689 Art. 12"),
            (),
        ),
        None,
    ),
)

FINDING_LABELS: Mapping[str, Message] = {
    "SAME_PERSON": msg("Dieselbe Person hat beide Schritte ausgeführt"),
    "SOURCE_NOT_RELEASED": msg("Eine Quelle war nicht freigegeben"),
    "NO_RECORDED_RELEASE": msg("Keine dokumentierte Freigabe (Altbestand)"),
    "REVIEW_OVERDUE": msg("Termin überschritten"),
    "DECISION_WITHOUT_REVIEW": msg("Status entschieden, aber keine Fachprüfung gespeichert"),
    "DECIDED_TWICE": msg("Mehr als eine Entscheidung gespeichert"),
    "REASON_MISSING": msg("Ablehnung ohne festen Grund"),
    "NOT_EXPERT": msg("Eskalation nicht von einer Expertenrolle entschieden"),
    "STATUS_MISMATCH": msg("Gespeicherter Status weicht von der Entscheidung ab"),
    "NOTICE_MISSING": msg("Keine Bestätigung des KI-Nutzerhinweises vor der Anfrage"),
    "DECIDER_MISSING": msg("Freigabe ohne gespeicherte freigebende Person"),
    "ROLE_NOT_AUTHORISED": msg("Abnahme durch eine nicht berechtigte Rolle"),
    "ANALYSIS_INCOMPLETE": msg("Pflichtfelder der Analyse fehlen"),
    "DEADLINE_OVERDUE": msg("Frist überschritten, Antrag noch offen"),
    "DECIDED_LATE": msg("Nach Fristablauf entschieden"),
    "RETENTION_OVERDUE": msg("Datensätze über der Löschfrist"),
    "LINK_MISMATCH": msg("Verkettung unterbrochen: Ereignis entfernt oder umsortiert"),
    "HASH_MISMATCH": msg("Ereignis nachträglich geändert"),
    "ANCHOR_MISMATCH": msg("Kette weicht vom extern gespeicherten Anker ab"),
    "ANCHOR_MISSING": msg("Extern verankertes Ereignis fehlt"),
    "NOT_VERIFIED": msg("Kette konnte nicht geprüft werden"),
}

RESOURCE_LABELS: Mapping[str, Message] = {
    "document": msg("Dokument"),
    "analysis": msg("KI-Antwort"),
    "operating_limits": msg("Betriebsgrenzen"),
    "incident": msg("Incident"),
    "privacy_request": msg("Datenschutzantrag"),
    "record_class": msg("Datenklasse"),
    "legal_hold": msg("Legal Hold"),
    "audit_event": msg("Auditereignis"),
}

STATUS_LABELS: Mapping[ControlStatus, Message] = {
    ControlStatus.EFFECTIVE: msg("Wirksam"),
    ControlStatus.DEVIATION: msg("Abweichung"),
    ControlStatus.OPEN_ITEMS: msg("Offene Punkte"),
    ControlStatus.NOT_EXERCISED: msg("Kein Fall im Zeitraum"),
}

KIND_LABELS: Mapping[ControlKind, Message] = {
    ControlKind.ENFORCED: msg("Technisch erzwungen"),
    ControlKind.MONITORED: msg("Überwacht"),
}


def _audit_chain(chain: AuditChainReport | None) -> _Outcome:
    if chain is None:
        return 0, [ControlFinding("audit_event", "–", "NOT_VERIFIED")], 0
    if chain.intact:
        return chain.event_count, [], 0
    reference = str(chain.broken_sequence) if chain.broken_sequence is not None else "–"
    return chain.event_count, [ControlFinding("audit_event", reference, chain.reason or "NOT_VERIFIED")], 0


def _prevented(definition: ControlDefinition, snapshot: EvidenceSnapshot) -> int:
    return sum(item.count for item in snapshot.denied if (item.action, item.reason_code) in definition.prevented_by)


def evaluate_controls(snapshot: EvidenceSnapshot, chain: AuditChainReport | None) -> EvidenceReport:
    """Run every control test over the snapshot; ``chain`` is the verification of the audit hash chain."""
    results = []
    for definition, test in CONTROLS:
        population, findings, untested = test(snapshot) if test is not None else _audit_chain(chain)
        results.append(
            ControlResult(
                definition,
                population,
                tuple(findings),
                prevented=_prevented(definition, snapshot),
                untested=untested,
                incomplete=bool(snapshot.truncated & set(definition.datasets)),
            )
        )
    return EvidenceReport(snapshot.since, snapshot.until, tuple(results), chain, snapshot.denied, snapshot.truncated)


def window(now: datetime, days: int) -> tuple[datetime, datetime]:
    until = now.astimezone(UTC)
    return until - timedelta(days=days), until


def control_ids(results: Iterable[ControlResult]) -> tuple[str, ...]:
    return tuple(item.definition.control_id for item in results)
