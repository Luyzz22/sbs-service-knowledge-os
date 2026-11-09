"""Inventory of every stored field that relates to a person, as the technical annex for works councils.

A works agreement under BetrVG § 87 (1) no. 6 needs to state which data about employees the system
stores, why, who sees it, how long it is kept and which evaluations are excluded. This inventory is
the single source for that annex: tests/test_personal_data.py fails when the database schema gains a
person-related column that is not listed here, and docs/compliance/works-council-annex.md is rendered
from it so the document cannot drift from the code.
"""

from __future__ import annotations

from dataclasses import dataclass

from compliance.retention import RecordClass, RetentionPolicy

from .i18n import Message, msg

# Column names that identify or describe the acting person; the schema test uses them to find new fields.
PERSON_COLUMN_SUFFIXES = ("_token",)
PERSON_COLUMNS = frozenset({"actor_role", "question_hash"})

PSEUDONYM = msg("Pseudonym der Person (HMAC, nicht umkehrbar)")
NOT_SHOWN = msg("In der Oberfläche nicht angezeigt")
NO_EVALUATION = msg("Keine Auswertung je Person")
HOLD_RETENTION = msg("Frist läuft erst ab Aufhebung des Holds")


@dataclass(frozen=True)
class PersonalDataField:
    table: str
    column: str
    content: Message
    purpose: Message
    visibility: Message
    evaluation: Message
    retention: RecordClass
    # Section of the self-service data export (GDPR Art. 15) that contains the field; None needs the stated route.
    export_section: str | None
    export_note: Message | None = None
    retention_note: Message | None = None


PERSONAL_DATA_FIELDS = (
    PersonalDataField(
        "documents",
        "created_by_token",
        PSEUDONYM,
        msg("Nachweis, wer ein Dokument in die Wissensbasis eingebracht hat; Vier-Augen-Prinzip bei der Freigabe"),
        msg("Nur als Markierung „Ihr Upload“ für die Person selbst"),
        msg("Keine Auswertung je Person; die Freigabe eigener Uploads wird gesperrt"),
        RecordClass.UPLOADED_CONTENT,
        "documents_uploaded",
    ),
    PersonalDataField(
        "document_events",
        "actor_token",
        PSEUDONYM,
        msg("Rückverfolgbarkeit der Dokumentenlenkung (Upload, Freigabe, Zurückziehung, Überprüfung)"),
        msg("Nur als Markierung „Sie“ für die Person selbst"),
        msg("Keine Auswertung je Person"),
        RecordClass.UPLOADED_CONTENT,
        "document_steps",
    ),
    PersonalDataField(
        "document_events",
        "actor_role",
        msg("App-Rolle der handelnden Person (z. B. Supervisor)"),
        msg("Nachvollziehbarkeit, welche Rolle ein Dokument freigegeben oder zurückgezogen hat"),
        msg("Im Dokumentverlauf für alle Rollen des Mandanten"),
        msg("Keine Auswertung je Person oder Rolle"),
        RecordClass.UPLOADED_CONTENT,
        "document_steps",
    ),
    PersonalDataField(
        "analysis_runs",
        "actor_token",
        PSEUDONYM,
        msg("Zuordnung eigener KI-Anfragen für Auskunft und Vier-Augen-Prinzip"),
        msg("Nur für die Person selbst; Prüfer sehen nur die Antwort"),
        msg("Keine Auswertung je Person; Selbstfreigabe sicherheitsrelevanter Antworten wird gesperrt"),
        RecordClass.AI_INTERACTION,
        "analysis_runs",
    ),
    PersonalDataField(
        "analysis_runs",
        "question_hash",
        msg("SHA-256 der Frage; der Fragetext wird nicht gespeichert"),
        msg("Nachweis, auf welche Frage sich eine Antwort bezieht, ohne den Wortlaut aufzubewahren"),
        NOT_SHOWN,
        msg("Keine Auswertung von Fragen oder Fragehäufigkeit je Person"),
        RecordClass.AI_INTERACTION,
        "analysis_runs",
    ),
    PersonalDataField(
        "analysis_reviews",
        "reviewer_token",
        PSEUDONYM,
        msg("Nachweis der menschlichen Prüfung (Human Oversight) und des Vier-Augen-Prinzips"),
        NOT_SHOWN,
        NO_EVALUATION,
        RecordClass.AI_INTERACTION,
        "reviews_given",
    ),
    PersonalDataField(
        "incidents",
        "created_by_token",
        PSEUDONYM,
        msg("Nachweis, wer eine technische Auffälligkeit gemeldet hat"),
        NOT_SHOWN,
        NO_EVALUATION,
        RecordClass.INCIDENT,
        "incidents_created",
    ),
    PersonalDataField(
        "incident_events",
        "actor_token",
        PSEUDONYM,
        msg("Rückverfolgbarkeit der Workflow-Schritte (8D, Abnahme)"),
        msg("Nur als Markierung „Sie“ für die Person selbst"),
        msg("Keine Auswertung je Person; Kennzahlen nur je Anlage"),
        RecordClass.INCIDENT,
        "incident_steps",
    ),
    PersonalDataField(
        "incident_events",
        "actor_role",
        msg("App-Rolle der handelnden Person (z. B. Technician)"),
        msg("Nachvollziehbarkeit, welche Rolle einen Schritt ausgeführt hat"),
        msg("Im Incident-Verlauf für alle Rollen des Mandanten"),
        msg("Keine Auswertung je Person oder Rolle; Kennzahlen nur je Anlage"),
        RecordClass.INCIDENT,
        "incident_steps",
    ),
    PersonalDataField(
        "notice_acceptances",
        "actor_token",
        PSEUDONYM,
        msg("Nachweis der Kenntnisnahme von KI- und Datenschutzhinweis"),
        msg("Nur für die Person selbst (Einrichtungsfortschritt)"),
        NO_EVALUATION,
        RecordClass.CONTRACT_ACCEPTANCE,
        "notice_acceptances",
    ),
    PersonalDataField(
        "privacy_requests",
        "subject_token",
        PSEUDONYM,
        msg("Bearbeitung eigener Datenschutzanfragen"),
        msg("Nur für die Person selbst"),
        NO_EVALUATION,
        RecordClass.DATA_SUBJECT_REQUEST,
        "privacy_requests",
    ),
    PersonalDataField(
        "legal_holds",
        "created_by_token",
        PSEUDONYM,
        msg("Nachweis, wer einen Legal Hold gesetzt hat"),
        NOT_SHOWN,
        NO_EVALUATION,
        RecordClass.AUDIT_EVENT,
        None,
        msg("Auf Antrag über das Datenschutzteam; Verwaltungsnachweis der Admin-Rolle"),
        HOLD_RETENTION,
    ),
    PersonalDataField(
        "legal_holds",
        "released_by_token",
        PSEUDONYM,
        msg("Nachweis, wer einen Legal Hold aufgehoben hat"),
        NOT_SHOWN,
        NO_EVALUATION,
        RecordClass.AUDIT_EVENT,
        None,
        msg("Auf Antrag über das Datenschutzteam; Verwaltungsnachweis der Admin-Rolle"),
        HOLD_RETENTION,
    ),
    PersonalDataField(
        "audit_events",
        "actor_token",
        PSEUDONYM,
        msg("Sicherheits- und Compliance-Nachweis (Anmeldung, Export, Freigaben)"),
        NOT_SHOWN,
        msg("Nur anlassbezogen bei Sicherheitsvorfällen nach Verfahren der Betriebsvereinbarung"),
        RecordClass.AUDIT_EVENT,
        None,
        msg("Auf Antrag über das Datenschutzteam; Sicherheitsprotokoll, nicht Teil der Selbstauskunft"),
    ),
    PersonalDataField(
        "audit_events",
        "resource_token",
        msg("Pseudonym des betroffenen Objekts (Dokument, Incident, Antwort, Anfrage)"),
        msg("Zuordnung eines Auditereignisses zu einem Objekt ohne Klartextkennung"),
        NOT_SHOWN,
        msg("Keine Auswertung je Person"),
        RecordClass.AUDIT_EVENT,
        None,
        msg("Bezieht sich auf Objekte, nicht auf Personen"),
    ),
)

# Evaluations the product does not offer and that a works agreement can rely on being absent.
EXCLUDED_EVALUATIONS = (
    msg("Leistungs-, Tempo- oder Fehlerquoten je Person"),
    msg("Rankings oder Vergleiche zwischen Beschäftigten oder Schichten"),
    msg("Anwesenheits-, Arbeitszeit- oder Standortauswertung"),
    msg("Auswertung von Fragetexten; gespeichert wird nur ein Hash"),
)


def is_person_column(column: str) -> bool:
    return column.endswith(PERSON_COLUMN_SUFFIXES) or column in PERSON_COLUMNS


def render_annex(policy: RetentionPolicy | None = None) -> str:
    """Markdown annex for the works agreement, in German like the agreement itself."""
    days = (policy or RetentionPolicy.from_environment({})).days_by_class
    lines = [
        "# Technische Anlage zur Betriebsvereinbarung: personenbezogene Daten",
        "",
        "Diese Datei wird aus `hydraulikdoc/personal_data.py` erzeugt "
        "(`python ops/scripts/render-works-council-annex.py`) und in CI gegen den Code geprüft. "
        "Löschfristen sind die technischen Standardwerte; die instanzbezogene Konfiguration "
        "(`*_RETENTION_DAYS`) und die Freigabe im Verarbeitungsverzeichnis gehen vor.",
        "",
        "Gespeichert wird keine Klartextkennung: Personen erscheinen nur als nicht umkehrbares Pseudonym "
        "aus der Entra-Kennung. Name und E-Mail werden nur für die laufende Sitzung verwendet.",
        "",
        "## Gespeicherte Felder",
        "",
        "| Tabelle.Spalte | Inhalt | Zweck | Sichtbarkeit | Auswertung | Löschfrist | Auskunft (Art. 15) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in PERSONAL_DATA_FIELDS:
        export = f"Selbstauskunft `{item.export_section}`" if item.export_section else str(item.export_note)
        lines.append(
            f"| `{item.table}.{item.column}` | {item.content} | {item.purpose} | {item.visibility} | "
            f"{item.evaluation} | {days[item.retention]} Tage ({item.retention.value})"
            f"{'; ' + str(item.retention_note) if item.retention_note else ''} | {export} |"
        )
    lines += ["", "## Ausgeschlossene Auswertungen", ""]
    lines += [f"- {item}" for item in EXCLUDED_EVALUATIONS]
    lines += [
        "",
        "Instandhaltungskennzahlen (Reaktions- und Behebungszeit, Wiederholungsfehler) werden ausschließlich "
        "je Anlage gebildet; die zugrunde liegende Abfrage liefert keine Personendaten.",
        "",
    ]
    return "\n".join(lines)
