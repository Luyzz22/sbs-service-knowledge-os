"""Evidence-led Streamlit interface for HydraulikDoc Enterprise."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from compliance.audit import AuditOutcome
from compliance.retention import RetentionPolicy
from fluid_advisor import FLUID_STATUS_LABELS, FluidLimits, FluidSample, assess_fluid

from .auth import (
    AuthenticationError,
    UserPrincipal,
    principal_from_entra_header,
    verify_local_user,
)
from .azure_ai import AzureRAGService
from .condition_monitoring import (
    ConditionAssessment,
    OperatingEnvelope,
    SensorReading,
    Severity,
    assess_condition,
)
from .config import AppSettings, AuthMode, ConfigurationError, get_settings
from .demo import DemoRAGService, demo_seed_blockers, demo_sensor_csv, seed_demo_tenant, tenant_has_data
from .governance import GroundedAnswer, ReviewStatus, UseCase, evaluate_use_case
from .i18n import DEFAULT_LANGUAGE, LANGUAGES, msg, preferred_language, translate, translate_plural
from .interop import (
    ASSET_ID_PATTERN,
    EQUIPMENT_PATTERN,
    FUNCTIONAL_LOCATION_PATTERN,
    SAP_NOTIFICATION_COLUMNS,
    asset_import_template,
    build_sap_notifications,
    parse_asset_csv,
    to_spreadsheet_csv,
)
from .maintenance_kpis import (
    KPI_EXPORT_COLUMNS,
    KPI_INCIDENT_LIMIT,
    KPI_WINDOW_DAYS,
    REPEAT_FAILURE_SPAN,
    MaintenanceKpis,
    kpi_export_rows,
    maintenance_kpis,
)
from .personal_data import EXCLUDED_EVALUATIONS, PERSONAL_DATA_FIELDS
from .repository import (
    AUDIT_VERIFY_PERMISSION,
    EIGHT_D_SEVERITIES,
    INCIDENT_ANALYSIS_FIELDS,
    INCIDENT_ANALYSIS_MAX_CHARS,
    INCIDENT_ANALYSIS_MIN_CHARS,
    INCIDENT_CLOSE_PERMISSION,
    INCIDENT_STATUSES,
    INCIDENT_TRANSITIONS,
    LEGAL_HOLD_PERMISSION,
    LEGAL_HOLD_REASONS,
    PRIVACY_DECISION_REASONS,
    PRIVACY_MANAGE_PERMISSION,
    PRIVACY_OPEN_STATUSES,
    PRIVACY_REQUEST_TRANSITIONS,
    AssetRecord,
    AuditChainReport,
    DocumentRecord,
    EnterpriseRepository,
    IncidentRecord,
    IncidentTransitionRejected,
    PrivacyRequestRecord,
    PrivacyTransitionRejected,
    get_repository,
    missing_analysis_fields,
)
from .security import InputRejected, public_error_code, validate_pdf_upload

APP_VERSION = "5.0.0-enterprise"
# Notices are complete texts per language, not catalogue snippets: the acceptance record stores the
# digest of exactly the wording that was shown.
AI_LITERACY_NOTICE = {
    "de": """HydraulikDoc erzeugt quellengebundene KI-Entwürfe. Ergebnisse können
unvollständig oder falsch sein. Vor Wartung, Freigabe, Ersatzteilbestellung oder einer
Maschinenhandlung muss eine qualifizierte Person die Originalquelle, Betriebsanweisung,
Gefährdungsbeurteilung und anwendbare LOTO-Regeln prüfen. HydraulikDoc steuert keine Maschine
und ersetzt weder Herstellerfreigaben noch Fachverantwortung.""",
    "en": """HydraulikDoc produces source-bound AI drafts. Results may be incomplete or wrong.
Before maintenance, release, spare-part orders or any machine action, a qualified person must
check the original source, operating instructions, risk assessment and applicable LOTO rules.
HydraulikDoc does not control any machine and replaces neither manufacturer approvals nor
professional responsibility.""",
}
INCIDENT_STATUS_LABELS = {
    "new": msg("Neu"),
    "acknowledged": msg("Bestätigt"),
    "in_progress": msg("In Bearbeitung"),
    "resolved": msg("Behoben"),
    "closed": msg("Abgeschlossen"),
}
INCIDENT_ACTION_LABELS = {
    "acknowledged": msg("Bestätigen"),
    "in_progress": msg("Bearbeitung starten"),
    "resolved": msg("Als behoben melden"),
    "closed": msg("Abnehmen und abschließen"),
}
INCIDENT_SEVERITY_LABELS = {
    "ok": msg("OK"),
    "warning": msg("Warnung"),
    "critical": msg("Kritisch"),
    "p1": msg("P1 · kritisch"),
    "p2": msg("P2 · hoch"),
    "p3": msg("P3 · mittel"),
    "p4": msg("P4 · niedrig"),
}
OPEN_INCIDENT_STATUSES = ("new", "acknowledged", "in_progress")
ANALYSIS_LABELS = {
    "containment_action": msg("D3 Sofortmaßnahme"),
    "root_cause": msg("D4 Ursache"),
    "corrective_action": msg("D5/D6 Abstellmaßnahme"),
    "effectiveness_check": msg("D7 Wirksamkeitsprüfung"),
}
ANALYSIS_HELP = {
    "containment_action": msg("Wie wurde der Schaden begrenzt? Zum Beispiel Stillsetzung, Sperrung, Sortierung."),
    "root_cause": msg("Technische Ursache und, falls bekannt, warum sie nicht früher entdeckt wurde."),
    "corrective_action": msg("Dauerhafte Abstellung: Reparatur, Tausch, Einstellung, Prozessänderung."),
    "effectiveness_check": msg("Womit ist belegt, dass die Maßnahme wirkt? Messreihe, Folgeprobe, Zeitraum."),
}
DOCUMENT_STATUS_LABELS = {
    "processing": msg("wird verarbeitet"),
    "ready": msg("bereit"),
    "failed": msg("fehlgeschlagen"),
}
REVIEW_STATUS_LABELS = {
    "accepted": msg("Geprüft und akzeptiert"),
    "needs_expert": msg("Experte erforderlich"),
    "rejected": msg("Abgelehnt"),
    "draft": msg("Entwurf"),
}
ROLE_LABELS = {
    "viewer": msg("Leser"),
    "technician": msg("Techniker"),
    "supervisor": msg("Supervisor"),
    "admin": msg("Admin"),
}
CRITICAL_SEVERITIES = frozenset({"critical", "p1"})
CRITICALITY_LABELS = {
    "low": msg("Niedrig"),
    "medium": msg("Mittel"),
    "high": msg("Hoch"),
    "safety_critical": msg("Sicherheitskritisch"),
}
ASSET_STATUS_LABELS = {
    "active": msg("Aktiv"),
    "maintenance": msg("In Wartung"),
    "out_of_service": msg("Außer Betrieb"),
    "retired": msg("Stillgelegt"),
}
NAV_PAGES = (
    "Leitstand",
    "Assets",
    "Wissensbasis",
    "Condition Monitoring",
    "Fluid",
    "Incidents",
    "Kennzahlen",
    "Governance",
    "System",
)
NAV_LABELS = {
    "Leitstand": msg("Leitstand"),
    "Assets": msg("Assets"),
    "Wissensbasis": msg("Wissensbasis"),
    "Condition Monitoring": msg("Condition Monitoring"),
    "Fluid": msg("Fluid"),
    "Incidents": msg("Incidents"),
    "Kennzahlen": msg("Kennzahlen"),
    "Governance": msg("Governance"),
    "System": msg("System"),
}
OVERVIEW_KPI_DAYS = 90
# Resolved incidents stay visible by default because they still await supervisor sign-off.
DEFAULT_INCIDENT_FILTER = (*OPEN_INCIDENT_STATUSES, "resolved")
PRIVACY_NOTICE = {
    "de": """HydraulikDoc verarbeitet Ihre Entra-Kennung pseudonymisiert für Rollenprüfung,
Auditnachweise, KI-Interaktionen und von Ihnen ausgelöste Incidents. Freitextfragen werden nicht
protokolliert; in der Fachdatenbank wird nur ein Hash gespeichert. Die konkrete Rechtsgrundlage,
Verantwortlichenkontaktdaten, Empfänger und genehmigten Löschfristen werden in der
instanzbezogenen Datenschutzerklärung Ihres Unternehmens ausgewiesen.""",
    "en": """HydraulikDoc processes your Entra identifier in pseudonymised form for role checks,
audit evidence, AI interactions and incidents you raise. Free-text questions are not logged; only
a hash is stored in the business database. The specific legal basis, controller contact details,
recipients and approved retention periods are stated in your company's instance-specific privacy
notice.""",
}


def _language() -> str:
    language = str(st.session_state.get("language", ""))
    if language not in LANGUAGES:
        # First visit: follow the browser preference; nothing about the person is stored.
        try:
            fallback = get_settings().default_language
        except ConfigurationError:
            fallback = DEFAULT_LANGUAGE
        language = preferred_language(_header_value("Accept-Language"), fallback)
        st.session_state.language = language
    return language


def tr(text: str, **params: object) -> str:
    return translate(text, _language(), **params)


def tr_plural(count: int, singular: str, plural: str, **params: object) -> str:
    return translate_plural(count, singular, plural, _language(), **params)


def label(table: Mapping[Any, str], key: Any) -> str:
    return tr(table.get(key, key))


def fmt_datetime(value: datetime) -> str:
    # ISO order in English avoids the US/UK day-month ambiguity for international plants.
    return value.strftime("%Y-%m-%d %H:%M" if _language() == "en" else "%d.%m.%Y %H:%M")


def label_nav(page: str) -> str:
    return label(NAV_LABELS, page)


def tr_error(error: BaseException) -> str:
    """Render an exception raised with a translatable message; other exceptions keep their text."""
    return tr(error.args[0]) if error.args and isinstance(error.args[0], str) else str(error)


def _inject_css() -> None:
    stylesheet = Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{stylesheet}</style>", unsafe_allow_html=True)


def _header_value(name: str) -> str | None:
    try:
        headers = st.context.headers
    except Exception:
        return None
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _language_selector() -> None:
    _language()  # initialise from the browser preference before the widget reads its state
    # Fixed bilingual label so the switch can be found in either language.
    st.selectbox("Sprache · Language", tuple(LANGUAGES), format_func=LANGUAGES.__getitem__, key="language")


def _local_login(settings: AppSettings) -> UserPrincipal | None:
    if st.session_state.get("principal"):
        return st.session_state.principal
    st.title("HydraulikDoc Enterprise")
    _language_selector()
    st.caption(
        tr("Lokale Entwicklungsanmeldung mit Argon2id. In Produktion ist ausschließlich Microsoft Entra ID zulässig.")
    )
    if not settings.local_users():
        st.warning(tr("Keine lokalen Benutzer konfiguriert. Hinterlegen Sie LOCAL_USERS_JSON mit Argon2id-Hashes."))
        st.code(
            "python -c \"from argon2 import PasswordHasher; print(PasswordHasher().hash('change-me'))\"",
            language="bash",
        )
        return None
    with st.form("local-login", clear_on_submit=False):
        username = st.text_input(tr("Benutzerkennung"), autocomplete="username")
        password = st.text_input(tr("Passwort"), type="password", autocomplete="current-password")
        submitted = st.form_submit_button(tr("Anmelden"), type="primary", width="stretch")
    if submitted:
        principal = verify_local_user(username.strip(), password, settings)
        if principal:
            st.session_state.principal = principal
            st.session_state.last_activity = time.monotonic()
            st.rerun()
        st.error(tr("Anmeldung fehlgeschlagen."))
    return None


def _principal(settings: AppSettings) -> UserPrincipal | None:
    if settings.auth_mode is AuthMode.ENTRA_PROXY:
        encoded = _header_value("X-MS-CLIENT-PRINCIPAL")
        if not encoded:
            st.error(tr("Zugriff verweigert: Es liegt kein verifizierter Entra-Prinzipal vor."))
            return None
        try:
            return principal_from_entra_header(encoded, settings.default_tenant_id)
        except AuthenticationError:
            st.error(tr("Zugriff verweigert: Identität oder App-Rolle ist unvollständig."))
            return None
    return _local_login(settings)


def _enforce_session(principal: UserPrincipal, settings: AppSettings) -> bool:
    now = time.monotonic()
    previous = st.session_state.get("last_activity", now)
    if now - previous > settings.session_idle_minutes * 60:
        st.session_state.clear()
        st.warning(tr("Die Sitzung wurde wegen Inaktivität beendet."))
        return False
    st.session_state.last_activity = now
    st.session_state.principal = principal
    return True


def _rag(settings: AppSettings, repository: EnterpriseRepository) -> AzureRAGService | DemoRAGService:
    existing = st.session_state.get("azure_rag")
    if existing is None:
        existing = DemoRAGService(settings, repository) if settings.demo_mode else AzureRAGService(settings, repository)
        st.session_state.azure_rag = existing
    return existing


def _notice_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_ai_acceptance(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    settings: AppSettings,
) -> bool:
    return repository.has_acceptance(principal, "ai_literacy", settings.ai_notice_version)


def _render_ai_acceptance(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    settings: AppSettings,
) -> bool:
    accepted = _has_ai_acceptance(principal, repository, settings)
    if accepted:
        st.success(tr("KI-Nutzerhinweis {version} bestätigt.", version=settings.ai_notice_version))
        return True
    notice = AI_LITERACY_NOTICE[_language()]
    st.markdown(f'<div class="hd-notice">{notice}</div>', unsafe_allow_html=True)
    acknowledgement = st.checkbox(
        tr("Ich verstehe die Grenzen und bestätige die Pflicht zur fachlichen Prüfung."),
        key="ai-literacy-check",
    )
    if st.button(
        tr("Nutzerhinweis bestätigen"),
        disabled=not acknowledgement,
        type="primary",
        key="ai-literacy-submit",
    ):
        repository.record_acceptance(
            principal,
            "ai_literacy",
            settings.ai_notice_version,
            _notice_digest(notice),
        )
        repository.emit_audit(
            principal,
            action="ai_literacy.notice.accepted",
            outcome=AuditOutcome.SUCCESS,
            metadata={"evidence_id": settings.ai_notice_version, "role": principal.role},
        )
        st.rerun()
    return False


def _render_privacy_notice(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    settings: AppSettings,
) -> None:
    notice = PRIVACY_NOTICE[_language()]
    if repository.has_acceptance(principal, "privacy", settings.privacy_notice_version):
        st.caption(
            tr(
                "Datenschutzhinweis {version} zur Kenntnis genommen.",
                version=settings.privacy_notice_version,
            )
        )
        return
    st.markdown(f'<div class="hd-notice">{notice}</div>', unsafe_allow_html=True)
    if st.button(tr("Datenschutzhinweis zur Kenntnis nehmen")):
        repository.record_acceptance(principal, "privacy", settings.privacy_notice_version, _notice_digest(notice))
        repository.emit_audit(
            principal,
            action="privacy.notice.acknowledged",
            outcome=AuditOutcome.SUCCESS,
            metadata={"evidence_id": settings.privacy_notice_version, "role": principal.role},
        )
        st.rerun()


def _render_shell(principal: UserPrincipal, settings: AppSettings, page: str) -> None:
    release = html.escape(settings.release_state)
    tenant = html.escape(principal.tenant_id)
    role = html.escape(principal.role)
    tenant_label = html.escape(tr("Mandant"))
    role_label = html.escape(tr("Rolle"))
    release_label = html.escape(tr("Releasezustand"))
    if settings.demo_mode:
        st.markdown(
            f'<div class="hd-demo" role="status"><strong>{html.escape(tr("Demo-Modus"))}</strong> '
            + html.escape(
                tr(
                    "Alle Daten sind synthetisch. Antworten werden ohne Sprachmodell aus Demodokumenten extrahiert. "
                    "Nicht für reale Instandhaltungsentscheidungen verwenden."
                )
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    if page != "Leitstand":
        # Working pages lead with the task; the context stays visible in one compact line.
        st.markdown(
            f"""
            <div class="hd-context">
              <span><strong>{tenant_label}</strong> <code>{tenant}</code></span>
              <span><strong>{role_label}</strong> <code>{role}</code></span>
              <span><strong>{release_label}</strong> <code>{release}</code></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"""
        <section class="hd-hero">
          <div>
            <h1>{html.escape(tr("Servicewissen wird zur überprüfbaren Entscheidung."))}</h1>
            <p>{html.escape(tr(HERO_TEXT))}</p>
          </div>
          <div class="hd-proof">
            <div><strong>{release_label}</strong><code>{release}</code></div>
            <div><strong>{tenant_label}</strong><code>{tenant}</code></div>
            <div><strong>{role_label}</strong><code>{role}</code></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


HERO_TEXT = msg(
    "HydraulikDoc verbindet technische Dokumentation, Zustandsdaten und einen menschlich freizugebenden "
    "KI-Entwurf. Für Instandhaltungsteams, die Quellen, Grenzwerte und Verantwortung an einem Ort brauchen."
)


def _go_to(page: str) -> None:
    st.session_state.nav = page


def _sidebar(principal: UserPrincipal, settings: AppSettings) -> str:
    with st.sidebar:
        st.markdown("## HydraulikDoc")
        st.caption(f"Enterprise {APP_VERSION}")
        _language_selector()
        st.divider()
        st.write(principal.display_name)
        st.caption(f"{label(ROLE_LABELS, principal.role)} · {principal.authentication_method}")
        st.divider()
        # Page keys stay German and stable; only their display follows the interface language.
        selected = st.radio(
            tr("Arbeitsbereich"), NAV_PAGES, key="nav", label_visibility="collapsed", format_func=label_nav
        )
        st.divider()
        if settings.demo_mode:
            ai_state = tr("Demo, kein Modellaufruf")
        elif settings.azure_ready:
            ai_state = tr("Azure konfiguriert")
        else:
            ai_state = tr("nicht konfiguriert")
        st.caption(tr("KI: {ai_state}", ai_state=ai_state))
        if settings.demo_mode:
            region = tr("lokal, keine Datenübertragung")
        else:
            region = settings.azure_region or tr("nicht attestiert")
        st.caption(tr("Region: {region}", region=region))
        if settings.auth_mode is AuthMode.LOCAL and st.button(tr("Abmelden"), width="stretch"):
            st.session_state.clear()
            st.rerun()
        return selected


def _overview(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    documents = repository.list_documents(principal)
    assets = repository.list_assets(principal)
    incidents = repository.list_incidents(principal)
    open_incidents = [item for item in incidents if item.status in OPEN_INCIDENT_STATUSES]
    st.header(tr("Leitstand"))
    st.caption(tr("Operativer Überblick ohne erfundene Verfügbarkeits- oder ROI-Kennzahlen."))
    tiles = (
        (tr("Dokumente"), tr("{n} aktive Dokumentdatensätze", n=len(documents))),
        (tr("Assets"), tr("{n} aktive Anlagenobjekte", n=len(assets))),
        (tr("Offene Incidents"), tr("{n} im Workflow", n=len(open_incidents))),
    )
    st.markdown(
        '<div class="hd-state">'
        + "".join(f"<div><strong>{html.escape(title)}</strong>{html.escape(text)}</div>" for title, text in tiles)
        + "</div>",
        unsafe_allow_html=True,
    )
    if settings.demo_mode:
        _render_demo_seed(principal, repository)
    st.subheader(tr("Handlungsbedarf"))
    critical = [item for item in open_incidents if item.severity in CRITICAL_SEVERITIES]
    unacknowledged = [item for item in incidents if item.status == "new"]
    awaiting_signoff = [item for item in incidents if item.status == "resolved"]
    actions: list[tuple[str, str]] = []
    if critical:
        actions.append(
            (
                "hd-notice hd-blocked",
                tr_plural(
                    len(critical),
                    "{n} kritischer Incident ist offen. Abschalt-, Sicherheits- und LOTO-Bewertung dokumentieren.",
                    "{n} kritische Incidents sind offen. Abschalt-, Sicherheits- und LOTO-Bewertung dokumentieren.",
                ),
            )
        )
    if unacknowledged:
        actions.append(
            (
                "hd-notice",
                tr_plural(
                    len(unacknowledged),
                    "{n} neuer Incident ist noch nicht bestätigt.",
                    "{n} neue Incidents sind noch nicht bestätigt.",
                ),
            )
        )
    if awaiting_signoff:
        if principal.can(INCIDENT_CLOSE_PERMISSION):
            text = tr_plural(
                len(awaiting_signoff),
                "{n} behobener Incident wartet auf Ihre Abnahme.",
                "{n} behobene Incidents warten auf Ihre Abnahme.",
            )
        else:
            text = tr_plural(
                len(awaiting_signoff),
                "{n} behobener Incident wartet auf die Abnahme durch einen Supervisor.",
                "{n} behobene Incidents warten auf die Abnahme durch einen Supervisor.",
            )
        actions.append(("hd-notice", text))
    now = datetime.now(UTC)
    since = now - timedelta(days=OVERVIEW_KPI_DAYS)
    repeat = maintenance_kpis(
        repository.list_incident_lifecycles(principal, since=since, limit=KPI_INCIDENT_LIMIT),
        assets,
        window_start=since,
        now=now,
    ).repeat_failure_assets
    if actions or repeat:
        for css_class, text in actions:
            st.markdown(f'<div class="{css_class}">{html.escape(text)}</div>', unsafe_allow_html=True)
        if repeat:
            text = tr_plural(
                len(repeat),
                "An {n} Anlage traten in den letzten {days} Tagen Wiederholungsfehler auf. Ursache prüfen.",
                "An {n} Anlagen traten in den letzten {days} Tagen Wiederholungsfehler auf. Ursache prüfen.",
                days=OVERVIEW_KPI_DAYS,
            )
            st.markdown(f'<div class="hd-notice">{html.escape(text)}</div>', unsafe_allow_html=True)
        incidents_column, kpis_column = st.columns(2)
        if actions:
            incidents_column.button(
                tr("Zum Incident Workflow"), on_click=_go_to, args=("Incidents",), key="overview-incidents"
            )
        if repeat:
            kpis_column.button(tr("Zu den Kennzahlen"), on_click=_go_to, args=("Kennzahlen",), key="overview-kpis")
    else:
        st.success(tr("Kein offener Handlungsbedarf im Incident Workflow."))
    if principal.can(LEGAL_HOLD_PERMISSION):
        overdue = [item for item in repository.list_legal_holds(principal) if item.review_overdue(datetime.now(UTC))]
        if overdue:
            st.warning(
                tr_plural(
                    len(overdue),
                    "{n} Legal Hold ist zur Wiedervorlage fällig: Weitergeltung prüfen oder aufheben.",
                    "{n} Legal Holds sind zur Wiedervorlage fällig: Weitergeltung prüfen oder aufheben.",
                )
            )
            st.button(tr("Zu Legal Hold"), on_click=_go_to, args=("Governance",), key="overview-legal-hold")
    if principal.can(PRIVACY_MANAGE_PERMISSION):
        late = [item for item in repository.list_privacy_queue(principal) if item.overdue(datetime.now(UTC))]
        if late:
            st.warning(
                tr_plural(
                    len(late),
                    "{n} Datenschutzantrag hat die interne Frist überschritten.",
                    "{n} Datenschutzanträge haben die interne Frist überschritten.",
                )
            )
            st.button(tr("Zu den Datenschutzanträgen"), on_click=_go_to, args=("Governance",), key="overview-privacy")
    _render_setup_progress(principal, repository, settings, assets, documents)
    st.subheader(tr("Freigabegrenzen"))
    st.warning(tr("Keine autonome Maschinensteuerung. Keine automatische Sicherheitsfreigabe."))
    if settings.release_state != "configured":
        st.info(tr("Produktionsfreigabe bleibt offen, bis Deployment-Evidenz und Compliance-Gate bestätigt sind."))


def _render_demo_seed(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    if counts := st.session_state.pop("demo_notice", None):
        st.success(tr("Demodaten geladen: {assets} Assets, {documents} Dokumente, {incidents} Incidents.", **counts))
    if tenant_has_data(principal, repository):
        return
    blockers = demo_seed_blockers(principal, repository)
    st.subheader(tr("Demo starten"))
    st.write(
        tr(
            "Lädt vier fiktive Anlagen mit SAP-Referenzen, zwei synthetische Handbücher und fünf Incidents der "
            "letzten vier Wochen in allen Workflow-Zuständen, darunter ein Wiederholungsfehler und ein "
            "wiedereröffneter Incident für die Kennzahlen."
        )
    )
    if blockers:
        st.caption(tr(blockers[0]))
        return
    if st.button(tr("Demodaten laden"), type="primary", key="demo-seed"):
        result = seed_demo_tenant(principal, repository)
        st.session_state.demo_notice = {
            "assets": result.assets,
            "documents": result.documents,
            "incidents": result.incidents,
        }
        st.rerun()


SETUP_STEPS = {
    "assets": msg("Assets erfasst"),
    "sap": msg("SAP-Referenz je Asset gepflegt"),
    "documents": msg("Herstellerunterlagen indexiert"),
    "ai_notice": msg("KI-Nutzerhinweis bestätigt"),
    "privacy": msg("Datenschutzhinweis zur Kenntnis genommen"),
}


def _render_setup_progress(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    settings: AppSettings,
    assets: tuple[AssetRecord, ...],
    documents: tuple[DocumentRecord, ...],
) -> None:
    st.subheader(tr("Einrichtung"))
    linked = sum(1 for item in assets if item.functional_location or item.equipment_number)
    ready_documents = sum(1 for item in documents if item.status == "ready")
    steps = (
        (
            "assets",
            bool(assets),
            "Assets",
            tr_plural(len(assets), "{n} Anlagenobjekt", "{n} Anlagenobjekte"),
        ),
        (
            "sap",
            bool(assets) and linked == len(assets),
            "Assets",
            tr("{linked} von {total} mit Technischem Platz oder Equipment", linked=linked, total=len(assets)),
        ),
        (
            "documents",
            ready_documents > 0,
            "Wissensbasis",
            tr_plural(ready_documents, "{n} Dokument bereit", "{n} Dokumente bereit"),
        ),
        (
            "ai_notice",
            _has_ai_acceptance(principal, repository, settings),
            "Governance",
            tr("Version {version}", version=settings.ai_notice_version),
        ),
        (
            "privacy",
            repository.has_acceptance(principal, "privacy", settings.privacy_notice_version),
            "Governance",
            tr("Version {version}", version=settings.privacy_notice_version),
        ),
    )
    done = sum(1 for _, complete, _, _ in steps if complete)
    st.caption(tr("{done} von {total} Schritten erledigt", done=done, total=len(steps)))
    done_label, open_label = html.escape(tr("Erledigt")), html.escape(tr("Offen"))
    items = "".join(
        f"""<li><span class="hd-status hd-status-{"resolved" if complete else "open"}">"""
        f"{done_label if complete else open_label}</span>"
        f"<div><strong>{html.escape(label(SETUP_STEPS, step))}</strong><small>{html.escape(detail)}</small></div></li>"
        for step, complete, _, detail in steps
    )
    st.markdown(f'<ul class="hd-checklist">{items}</ul>', unsafe_allow_html=True)
    next_step = next(((step, page) for step, complete, page, _ in steps if not complete), None)
    if next_step:
        st.button(
            tr("Weiter: {step}", step=label(SETUP_STEPS, next_step[0])),
            on_click=_go_to,
            args=(next_step[1],),
            key="overview-next-setup",
            width="stretch",
        )


def _assets(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.title(tr("Asset Register"))
    st.caption(tr("OEM-neutrale Anlagen- und Komponentenreferenz für Dokumente, Messwerte und Incidents."))
    if imported := st.session_state.pop("asset_import_notice", None):
        st.success(tr_plural(imported, "{n} Asset wurde importiert.", "{n} Assets wurden importiert."))
    assets = repository.list_assets(principal)
    if assets:
        st.dataframe(
            [
                {
                    tr("Asset-ID"): item.asset_id,
                    tr("Name"): item.name,
                    tr("Standort"): item.site,
                    tr("Hersteller"): item.manufacturer,
                    tr("Modell"): item.model,
                    tr("Kritikalität"): label(CRITICALITY_LABELS, item.criticality),
                    tr("Status"): label(ASSET_STATUS_LABELS, item.status),
                    tr("Technischer Platz"): item.functional_location,
                    tr("Equipment"): item.equipment_number,
                }
                for item in assets
            ],
            width="stretch",
            hide_index=True,
        )
        unlinked = sum(1 for item in assets if not item.functional_location and not item.equipment_number)
        if unlinked:
            st.caption(
                tr_plural(
                    unlinked,
                    "{n} Asset hat noch keinen Technischen Platz oder Equipment. Ohne Referenz lassen sich "
                    "Incidents in SAP PM keinem Technischen Objekt zuordnen.",
                    "{n} Assets haben noch keinen Technischen Platz oder Equipment. Ohne Referenz lassen sich "
                    "Incidents in SAP PM keinem Technischen Objekt zuordnen.",
                )
            )
    else:
        st.info(tr("Noch keine Assets erfasst. Einzelne Anlagen unten anlegen oder den Stammdatenimport nutzen."))
    if not principal.can("asset:write"):
        return
    with st.expander(tr("Asset anlegen oder aktualisieren")):
        with st.form("asset-form"):
            asset_id = st.text_input(tr("Asset-ID"), placeholder="WERK1-PRESSE-04-HYD")
            name = st.text_input(tr("Bezeichnung"), placeholder=tr("Hydraulikaggregat Presse 04"))
            site = st.text_input(tr("Standort"), placeholder=tr("Werk 1 · Halle 3"))
            manufacturer = st.text_input(tr("Hersteller"))
            model = st.text_input(tr("Modell / Baureihe"))
            criticality = st.selectbox(
                tr("Kritikalität"),
                tuple(CRITICALITY_LABELS),
                index=2,
                format_func=lambda option: label(CRITICALITY_LABELS, option),
            )
            sap_left, sap_right = st.columns(2)
            functional_location = sap_left.text_input(
                tr("Technischer Platz (SAP TPLNR)"), max_chars=40, placeholder="1000-W1-H3-P04"
            )
            equipment_number = sap_right.text_input(tr("Equipment (SAP EQUNR)"), max_chars=18, placeholder="10004711")
            submitted = st.form_submit_button(tr("Asset speichern"), type="primary")
        if submitted:
            functional_location = functional_location.strip()
            equipment_number = equipment_number.strip()
            if not ASSET_ID_PATTERN.fullmatch(asset_id):
                st.error(tr("Asset-ID enthält unzulässige Zeichen oder ist zu kurz."))
            elif not name.strip() or not site.strip():
                st.error(tr("Bezeichnung und Standort sind erforderlich."))
            elif functional_location and not FUNCTIONAL_LOCATION_PATTERN.fullmatch(functional_location):
                st.error(tr("Technischer Platz enthält unzulässige Zeichen."))
            elif equipment_number and not EQUIPMENT_PATTERN.fullmatch(equipment_number):
                st.error(tr("Equipment darf nur Buchstaben und Ziffern enthalten (max. 18)."))
            else:
                repository.upsert_asset(
                    principal,
                    asset_id=asset_id,
                    name=name.strip(),
                    site=site.strip(),
                    manufacturer=manufacturer.strip(),
                    model=model.strip(),
                    criticality=criticality,
                    functional_location=functional_location,
                    equipment_number=equipment_number,
                )
                repository.emit_audit(
                    principal,
                    action="asset.upserted",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="asset",
                    resource_id=asset_id,
                )
                st.rerun()
    with st.expander(tr("Stammdaten importieren (CSV, z. B. aus SAP PM)")):
        st.caption(
            tr(
                "UTF-8-CSV mit Semikolon oder Komma. Pflichtspalten: asset_id, name, site, criticality "
                "(niedrig, mittel, hoch, sicherheitskritisch). Optional: manufacturer, model, "
                "functional_location (TPLNR), equipment_number (EQUNR). Der Import wird vollständig geprüft "
                "und nur übernommen, wenn alle Zeilen gültig sind; bestehende Asset-IDs werden aktualisiert."
            )
        )
        st.download_button(
            tr("Importvorlage herunterladen"),
            asset_import_template(),
            file_name="hydraulikdoc-asset-import-vorlage.csv",
            mime="text/csv",
            key="asset-import-template",
        )
        uploaded = st.file_uploader(tr("Stammdaten-CSV"), type=["csv"], key="asset-import-file")
        if uploaded and st.button(tr("Prüfen und importieren"), type="primary", key="asset-import-submit"):
            try:
                rows = parse_asset_csv(uploaded.getvalue())
            except ValueError as error:
                repository.emit_audit(
                    principal,
                    action="asset.import.rejected",
                    outcome=AuditOutcome.FAILURE,
                    resource_type="asset",
                    metadata={"reason_code": "VALIDATION_FAILED"},
                )
                st.error(tr_error(error))
            else:
                for row in rows:
                    repository.upsert_asset(
                        principal,
                        asset_id=row.asset_id,
                        name=row.name,
                        site=row.site,
                        manufacturer=row.manufacturer,
                        model=row.model,
                        criticality=row.criticality,
                        functional_location=row.functional_location,
                        equipment_number=row.equipment_number,
                    )
                repository.emit_audit(
                    principal,
                    action="asset.import.completed",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="asset",
                    metadata={"source_count": len(rows)},
                )
                st.session_state.asset_import_notice = len(rows)
                st.rerun()


def _render_answer(
    answer: GroundedAnswer,
    principal: UserPrincipal,
    repository: EnterpriseRepository,
) -> None:
    st.markdown(
        f'<div class="hd-notice"><strong>{html.escape(tr("KI-Entwurf"))}</strong><br>'
        f"{html.escape(tr('Vor jeder technischen Handlung fachlich prüfen.'))}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(answer.text)
    st.subheader(tr("Evidenz"))
    if answer.citations:
        for index, citation in enumerate(answer.citations, start=1):
            st.markdown(
                tr(
                    "**S{index}** · {document} · Seite {page} · Chunk `{chunk}`",
                    index=index,
                    document=citation.display_name,
                    page=citation.page,
                    chunk=citation.chunk_id[:12],
                )
            )
    else:
        st.warning(tr("Keine Dokumentevidenz gefunden."))
    with st.expander(tr("Provenienz und Grenzen")):
        st.json(
            {
                "answer_id": answer.answer_id,
                "provider": answer.provenance.provider,
                "deployment": answer.provenance.deployment,
                "model_snapshot": answer.provenance.model_snapshot,
                "region": answer.provenance.region,
                "prompt": f"{answer.provenance.prompt_key}@{answer.provenance.prompt_version}",
                "use_case": answer.use_case.value,
                "risk_class": answer.risk_class.value,
                "review_status": answer.review_status.value,
                "limitations": answer.limitations,
            }
        )
    review = st.session_state.get(f"review:{answer.answer_id}")
    if principal.can("review:write") and not review:
        st.write(tr("Fachprüfung"))
        accept, expert, reject = st.columns(3)
        if accept.button(tr("Geprüft und akzeptiert"), key=f"accept:{answer.answer_id}", width="stretch"):
            try:
                repository.record_review(principal, answer.answer_id, ReviewStatus.ACCEPTED)
                repository.emit_audit(
                    principal,
                    action="analysis.review.recorded",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="analysis",
                    resource_id=answer.answer_id,
                    metadata={"review_status": ReviewStatus.ACCEPTED.value, "risk_class": answer.risk_class.value},
                )
                st.session_state[f"review:{answer.answer_id}"] = ReviewStatus.ACCEPTED.value
                st.rerun()
            except PermissionError:
                repository.emit_audit(
                    principal,
                    action="analysis.review.denied",
                    outcome=AuditOutcome.DENIED,
                    resource_type="analysis",
                    resource_id=answer.answer_id,
                    metadata={"reason_code": "FOUR_EYES_REVIEW_REQUIRED", "risk_class": answer.risk_class.value},
                )
                st.error(tr("Für sicherheitsrelevante Analysen gilt das Vier-Augen-Prinzip."))
        if expert.button(tr("Experte erforderlich"), key=f"expert:{answer.answer_id}", width="stretch"):
            repository.record_review(principal, answer.answer_id, ReviewStatus.NEEDS_EXPERT, "EXPERT_REVIEW")
            repository.emit_audit(
                principal,
                action="analysis.review.recorded",
                outcome=AuditOutcome.SUCCESS,
                resource_type="analysis",
                resource_id=answer.answer_id,
                metadata={"review_status": ReviewStatus.NEEDS_EXPERT.value, "risk_class": answer.risk_class.value},
            )
            st.session_state[f"review:{answer.answer_id}"] = ReviewStatus.NEEDS_EXPERT.value
            st.rerun()
        if reject.button(tr("Ablehnen"), key=f"reject:{answer.answer_id}", width="stretch"):
            repository.record_review(principal, answer.answer_id, ReviewStatus.REJECTED, "TECHNICAL_REJECTION")
            repository.emit_audit(
                principal,
                action="analysis.review.recorded",
                outcome=AuditOutcome.SUCCESS,
                resource_type="analysis",
                resource_id=answer.answer_id,
                metadata={"review_status": ReviewStatus.REJECTED.value, "risk_class": answer.risk_class.value},
            )
            st.session_state[f"review:{answer.answer_id}"] = ReviewStatus.REJECTED.value
            st.rerun()
    if review:
        st.info(tr("Dokumentierter Reviewstatus: {status}", status=label(REVIEW_STATUS_LABELS, review)))
    persisted_review = repository.answer_review_status(principal, answer.answer_id)
    if persisted_review is ReviewStatus.ACCEPTED and principal.can("analysis:export"):
        payload = {
            "answer_id": answer.answer_id,
            "answer": answer.text,
            "citations": [citation.__dict__ for citation in answer.citations],
            "provenance": answer.provenance.__dict__,
            "review_status": persisted_review.value,
        }
        exported = st.download_button(
            tr("Geprüften Nachweis exportieren"),
            json.dumps(payload, default=str, ensure_ascii=False, indent=2),
            file_name=f"hydraulikdoc-analysis-{answer.answer_id}.json",
            mime="application/json",
        )
        if exported:
            repository.emit_audit(
                principal,
                action="analysis.evidence.exported",
                outcome=AuditOutcome.SUCCESS,
                resource_type="analysis",
                resource_id=answer.answer_id,
                metadata={"review_status": persisted_review.value, "risk_class": answer.risk_class.value},
            )


USE_CASE_LABELS = {
    UseCase.MAINTENANCE_ASSISTANCE: msg("Instandhaltungsunterstützung"),
    UseCase.SAFETY_RELEVANT_DIAGNOSIS: msg("Sicherheitsrelevante Diagnose mit Pflichtreview"),
    UseCase.AUTOMATED_MACHINE_CONTROL: msg("Autonome Maschinensteuerung (gesperrt)"),
    UseCase.EMPLOYEE_MONITORING: msg("Beschäftigtenüberwachung (gesperrt)"),
    UseCase.OTHER: msg("Sonstige technische Recherche"),
}


def _knowledge(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.title(tr("Wissensbasis"))
    if settings.demo_mode:
        st.caption(tr("Demo-Modus: synthetische Handbücher und extraktive Antworten ohne Modellaufruf."))
    else:
        st.caption(tr("Azure Document Intelligence, tenant-gefilterte Hybrid-Suche und quellengebundene Antworten."))
    documents = repository.list_documents(principal)
    if documents:
        for document in documents:
            columns = st.columns([5, 2, 2])
            columns[0].write(document.display_name)
            columns[1].caption(
                tr(
                    "{pages} Seiten · {status}",
                    pages=document.page_count,
                    status=label(DOCUMENT_STATUS_LABELS, document.status),
                )
            )
            if principal.can("knowledge:write") and columns[2].button(
                tr("Löschen"), key=f"delete:{document.document_id}"
            ):
                try:
                    _rag(settings, repository).delete_document(principal, document.document_id)
                    st.rerun()
                except Exception as error:
                    st.error(
                        tr("Löschung nicht abgeschlossen. Referenz {reference}", reference=public_error_code(error))
                    )
    else:
        st.info(tr("Für diesen Mandanten sind noch keine Dokumente indexiert."))

    if principal.can("knowledge:write"):
        uploaded = st.file_uploader(tr("Technisches PDF hinzufügen"), type=["pdf"], key="manual-upload")
        if uploaded and st.button(tr("Validieren und indexieren"), type="primary", disabled=not settings.azure_ready):
            try:
                validated = validate_pdf_upload(uploaded.name, uploaded.getvalue(), settings.max_upload_bytes)
                with st.spinner(tr("Dokument wird sicher gespeichert, strukturiert und indexiert …")):
                    _rag(settings, repository).ingest(principal, validated)
                st.success(tr("Dokument wurde indexiert."))
                st.rerun()
            except (InputRejected, ValueError) as error:
                st.error(tr_error(error))
            except Exception as error:
                st.error(tr("Indexierung fehlgeschlagen. Referenz {reference}", reference=public_error_code(error)))
        if settings.demo_mode:
            st.caption(tr("Upload ist im Demo-Modus gesperrt; es stehen nur synthetische Dokumente zur Verfügung."))
        elif not settings.azure_ready:
            st.caption(tr("Upload ist gesperrt, bis alle Azure-Endpunkte und Deployments konfiguriert sind."))

    st.divider()
    st.subheader(tr("Quellengebundene Abfrage"))
    accepted = _has_ai_acceptance(principal, repository, settings)
    use_case = st.selectbox(
        tr("Verwendungszweck"), tuple(USE_CASE_LABELS), format_func=lambda option: label(USE_CASE_LABELS, option)
    )
    decision = evaluate_use_case(use_case)
    if not decision.allowed:
        st.markdown(
            '<div class="hd-notice hd-blocked">'
            + html.escape(tr("Dieser Zweck ist technisch gesperrt: {reason}", reason=decision.reason_code))
            + "</div>",
            unsafe_allow_html=True,
        )
    question = st.text_area(
        tr("Technische Frage"),
        max_chars=settings.max_question_chars,
        placeholder=tr(
            "Welcher Betriebsdruck gilt für die konfigurierte Pumpenbaureihe und welche Prüfhinweise nennt das Handbuch?"
        ),
    )
    if settings.demo_mode:
        st.caption(
            tr(
                "Beispielfragen: Welcher Betriebsdruck gilt für HA-250? · Wie hoch darf der Wassergehalt sein? · "
                "Was ist bei hoher Partikelzahl zu tun?"
            )
        )
    disabled = not accepted or not settings.ai_ready or not decision.allowed
    if st.button(tr("KI-Entwurf erzeugen"), type="primary", disabled=disabled):
        try:
            with st.spinner(tr("Hybrid Retrieval und Evidenzprüfung laufen …")):
                st.session_state.current_answer = _rag(settings, repository).ask(
                    principal, question, use_case, language=_language()
                )
        except (InputRejected, PermissionError, AuthenticationError) as error:
            st.error(tr_error(error))
        except Exception as error:
            st.error(tr("Abfrage fehlgeschlagen. Referenz {reference}", reference=public_error_code(error)))
    answer = st.session_state.get("current_answer")
    if answer:
        _render_answer(answer, principal, repository)
    if not accepted:
        st.info(tr("Der KI-Nutzerhinweis muss im Bereich Governance bestätigt werden."))


def _parse_optional_float(row: dict[str, str], key: str) -> float | None:
    value = (row.get(key) or "").strip().replace(",", ".")
    if not value:
        return None
    parsed = float(value)
    limits = {
        "pressure_bar": 10_000.0,
        "temperature_c": 1_000.0,
        "flow_l_min": 10_000_000.0,
        "particle_count": 1_000_000_000_000.0,
        "water_content_pct": 100.0,
    }
    if not 0 <= parsed <= limits[key]:
        raise ValueError(msg("{column} liegt außerhalb des zulässigen technischen Wertebereichs", column=key))
    return parsed


def _parse_sensor_csv(content: bytes) -> tuple[SensorReading, ...]:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError(msg("CSV überschreitet 5 MB"))
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"timestamp"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(msg("CSV benötigt mindestens die Spalte timestamp"))
    allowed = {"timestamp", "pressure_bar", "temperature_c", "flow_l_min", "particle_count", "water_content_pct"}
    if not set(reader.fieldnames).issubset(allowed):
        raise ValueError(msg("CSV enthält nicht freigegebene Spalten"))
    readings = []
    for index, row in enumerate(reader):
        if index >= 10_000:
            raise ValueError(msg("CSV darf höchstens 10.000 Messzeilen enthalten"))
        stamp = (row.get("timestamp") or "").replace("Z", "+00:00")
        try:
            timestamp = datetime.fromisoformat(stamp)
        except ValueError as error:
            raise ValueError(msg("Ungültiger Zeitstempel in Zeile {line}", line=index + 2)) from error
        if timestamp.tzinfo is None:
            raise ValueError(msg("Zeitstempel müssen eine Zeitzone enthalten"))
        readings.append(
            SensorReading(
                timestamp=timestamp,
                pressure_bar=_parse_optional_float(row, "pressure_bar"),
                temperature_c=_parse_optional_float(row, "temperature_c"),
                flow_l_min=_parse_optional_float(row, "flow_l_min"),
                particle_count=_parse_optional_float(row, "particle_count"),
                water_content_pct=_parse_optional_float(row, "water_content_pct"),
            )
        )
    if not readings:
        raise ValueError(msg("CSV enthält keine Messwerte"))
    return tuple(sorted(readings, key=lambda item: item.timestamp))


def _condition_monitoring(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.title(tr("Condition Monitoring"))
    st.caption(
        tr(
            "Deterministische Grenzwertprüfung für Druck, Temperatur, Volumenstrom und Fluidzustand. Grenzwerte sind anlagenbezogen zu bestätigen."
        )
    )
    assets = repository.list_assets(principal)
    asset_ids = [item.asset_id for item in assets]
    asset_id = st.selectbox(tr("Asset"), asset_ids) if asset_ids else st.text_input(tr("Asset-ID"))
    with st.expander(tr("Betriebsgrenzen"), expanded=True):
        c1, c2, c3 = st.columns(3)
        pressure_warning = c1.number_input(tr("Druckwarnung (bar)"), min_value=0.0, value=250.0)
        pressure_critical = c1.number_input(tr("Druck-Prüfgrenze (bar)"), min_value=0.0, value=300.0)
        temperature_warning = c2.number_input(tr("Temperaturwarnung (°C)"), min_value=0.0, value=70.0)
        temperature_critical = c2.number_input(tr("Temperatur-Prüfgrenze (°C)"), min_value=0.0, value=85.0)
        minimum_flow = c3.number_input(tr("Mindestvolumenstrom (l/min)"), min_value=0.0, value=5.0)
        particle_warning = c3.number_input(tr("Partikelwarnung (#/ml)"), min_value=0.0, value=1000.0)
    uploaded = st.file_uploader(
        tr("Messdaten-CSV"),
        type=["csv"],
        help=tr("Spalten: timestamp, pressure_bar, temperature_c, flow_l_min, particle_count, water_content_pct"),
    )
    use_sample = settings.demo_mode and st.toggle(
        tr("Synthetische Beispiel-Messreihe verwenden (48 h, steigender Druck und Temperatur)"),
        key="condition-demo-sample",
    )
    limits_confirmed = st.checkbox(
        tr("Ich bestätige, dass diese Betriebsgrenzen für das ausgewählte Asset fachlich freigegeben sind."),
        key="condition-limits-confirmed",
    )
    if (uploaded or use_sample) and st.button(tr("Messreihe prüfen"), type="primary", disabled=not limits_confirmed):
        try:
            content = demo_sensor_csv() if use_sample or uploaded is None else uploaded.getvalue()
            readings = _parse_sensor_csv(content)
            envelope = OperatingEnvelope(
                pressure_warning_bar=pressure_warning,
                pressure_critical_bar=pressure_critical,
                temperature_warning_c=temperature_warning,
                temperature_critical_c=temperature_critical,
                minimum_flow_l_min=minimum_flow,
                particle_warning=particle_warning,
            )
            computed_assessment = assess_condition(readings, envelope)
            st.session_state.condition_assessment = computed_assessment
            st.session_state.condition_asset_id = asset_id
            repository.emit_audit(
                principal,
                action="condition.series.assessed",
                outcome=AuditOutcome.SUCCESS,
                resource_type="asset",
                resource_id=asset_id,
                metadata={
                    "source_count": computed_assessment.sample_count,
                    "reason_code": computed_assessment.severity.value,
                },
            )
        except Exception as error:
            st.error(tr_error(error))
    assessment: ConditionAssessment | None = st.session_state.get("condition_assessment")
    if not assessment:
        return
    st.metric(
        tr("Zustand"),
        label(INCIDENT_SEVERITY_LABELS, assessment.severity.value),
        tr("{n} Messpunkte", n=assessment.sample_count),
        delta_color="off",
    )
    if assessment.requires_shutdown_assessment:
        st.error(tr("Kritische Prüfgrenze erreicht. Qualifizierte Abschalt- und Sicherheitsbewertung erforderlich."))
    if assessment.signals:
        st.dataframe(
            [
                {
                    tr("Code"): signal.code,
                    tr("Stufe"): label(INCIDENT_SEVERITY_LABELS, signal.severity.value),
                    tr("Hinweis"): tr(signal.message),
                    tr("Wert"): signal.value,
                    tr("Grenze"): signal.threshold,
                    tr("Einheit"): signal.unit,
                }
                for signal in assessment.signals
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.success(tr("Keine konfigurierte Grenze wurde verletzt."))
    if principal.can("incident:write") and assessment.severity is not Severity.OK:
        if st.button(tr("Incident aus Bewertung anlegen")):
            incident = repository.create_incident(
                principal,
                asset_id=st.session_state.get("condition_asset_id") or "unassigned",
                title=f"Condition-Monitoring {assessment.severity.value}",
                severity=assessment.severity.value,
                details="\n".join(f"{signal.code}: {signal.message}" for signal in assessment.signals),
            )
            st.success(tr("Incident {incident_id} wurde angelegt.", incident_id=incident.incident_id))


def _fluid(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.title(tr("Fluid & Service Advisor"))
    st.caption(tr("Regelbasierte Vorbewertung. ISO-/Herstellergrenzen müssen je Anlage freigegeben werden."))
    assets = repository.list_assets(principal)
    asset_id = (
        st.selectbox(tr("Asset"), [item.asset_id for item in assets], key="fluid-asset")
        if assets
        else st.text_input(tr("Asset-ID"), key="fluid-asset-text")
    )
    left, right = st.columns(2)
    particle_count = left.number_input(tr("Partikelzahl (#/ml)"), min_value=0.0, value=0.0)
    water_content = right.number_input(tr("Wassergehalt (%)"), min_value=0.0, max_value=100.0, value=0.0, step=0.01)
    particle_warning = left.number_input(tr("Freigegebene Partikelwarngrenze (#/ml)"), min_value=0.0, value=1000.0)
    water_critical = right.number_input(
        tr("Freigegebene Wasser-Prüfgrenze (%)"), min_value=0.0, max_value=100.0, value=0.1, step=0.01
    )
    limits_confirmed = st.checkbox(
        tr("Ich bestätige, dass die Fluidgrenzen für dieses Asset fachlich freigegeben sind."),
        key="fluid-limits-confirmed",
    )
    if st.button(tr("Fluidprobe bewerten"), type="primary", disabled=not limits_confirmed):
        st.session_state.fluid_assessment = assess_fluid(
            FluidSample(
                asset_id=asset_id or "unassigned",
                taken_at=datetime.now(UTC),
                particle_count=particle_count or None,
                water_content=water_content or None,
            ),
            FluidLimits(particle_warning=particle_warning, water_critical_pct=water_critical),
        )
    assessment = st.session_state.get("fluid_assessment")
    if assessment:
        st.metric(
            tr("Regelindikator (nicht normiert)"),
            f"{assessment.score}/100",
            label(FLUID_STATUS_LABELS, assessment.status),
            delta_color="off",
        )
        st.write(tr(assessment.summary))
        for recommendation in assessment.recommendations:
            st.write(f"• {tr(recommendation)}")
        if principal.can("incident:write") and assessment.status != "OK" and st.button(tr("Fluid-Incident anlegen")):
            incident = repository.create_incident(
                principal,
                asset_id=assessment.asset_id,
                title=assessment.summary,
                severity="critical" if assessment.status == "KRITISCH" else "warning",
                details="\n".join(assessment.recommendations),
            )
            st.success(tr("Incident {incident_id} wurde angelegt.", incident_id=incident.incident_id))


def _incident_option_label(incident: IncidentRecord) -> str:
    # Status is shown in the detail panel; Streamlit may keep a stale option label after a rerun.
    return f"{incident.title} · {incident.asset_id} · {incident.incident_id[:8]}"


def _transition_incident(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    incident: IncidentRecord,
    target: str,
) -> None:
    try:
        updated = repository.transition_incident(
            principal, incident.incident_id, expected=incident.status, target=target
        )
    except (PermissionError, IncidentTransitionRejected, KeyError) as error:
        reason = error.args[0] if isinstance(error, (PermissionError, IncidentTransitionRejected)) else "NOT_FOUND"
        repository.emit_audit(
            principal,
            action="incident.status.denied",
            outcome=AuditOutcome.DENIED,
            resource_type="incident",
            resource_id=incident.incident_id,
            metadata={"reason_code": reason, "previous_status": incident.status, "incident_status": target},
        )
        st.error(
            tr(
                "Statuswechsel nicht durchgeführt. Der Incident wurde zwischenzeitlich geändert oder Ihre Rolle "
                "ist dafür nicht freigegeben. Referenz {reason}",
                reason=reason,
            )
        )
        return
    repository.emit_audit(
        principal,
        action="incident.status.changed",
        outcome=AuditOutcome.SUCCESS,
        resource_type="incident",
        resource_id=updated.incident_id,
        metadata={"previous_status": incident.status, "incident_status": updated.status, "role": principal.role},
    )
    st.session_state.incident_notice = ("status", updated.incident_id[:8], updated.status)
    st.rerun()


def _incident_detail(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    status_label = label(INCIDENT_STATUS_LABELS, incident.status)
    severity_label = label(INCIDENT_SEVERITY_LABELS, incident.severity)
    critical = incident.severity in CRITICAL_SEVERITIES and incident.status in OPEN_INCIDENT_STATUSES
    fields = {
        "status": html.escape(tr("Status")),
        "severity": html.escape(tr("Schwere")),
        "asset": html.escape(tr("Asset")),
        "created": html.escape(tr("Erstellt")),
        "updated": html.escape(tr("Letzte Änderung")),
    }
    st.markdown(
        f"""
        <div class="hd-incident{" hd-incident-critical" if critical else ""}">
          <div><strong>{fields["status"]}</strong><span class="hd-status hd-status-{html.escape(incident.status)}">{html.escape(status_label)}</span></div>
          <div><strong>{fields["severity"]}</strong>{html.escape(severity_label)}</div>
          <div><strong>{fields["asset"]}</strong><code>{html.escape(incident.asset_id)}</code></div>
          <div><strong>{fields["created"]}</strong>{fmt_datetime(incident.created_at)} UTC</div>
          <div><strong>{fields["updated"]}</strong>{fmt_datetime(incident.updated_at or incident.created_at)} UTC</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"**{incident.title}**")
    if incident.details:
        st.text(incident.details)
    else:
        st.caption(tr("Keine Befunddetails hinterlegt."))
    if critical:
        st.warning(
            tr(
                "Kritischer Befund: Abschalt-, Sicherheits- und LOTO-Bewertung durch eine qualifizierte Person dokumentieren."
            )
        )
    _incident_analysis(principal, repository, incident)
    _incident_actions(principal, repository, incident)
    _incident_history(principal, repository, incident)


def _incident_analysis(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    st.markdown(f"#### {tr('Analyse und Maßnahmen (8D)')}")
    if incident.severity in EIGHT_D_SEVERITIES:
        st.caption(
            tr(
                "8D-pflichtig: D3, D4 und D5/D6 sind vor „Als behoben melden“ zu dokumentieren, D7 vor der "
                "Abnahme. Je Feld mindestens {min_chars} Zeichen.",
                min_chars=INCIDENT_ANALYSIS_MIN_CHARS,
            )
        )
    else:
        st.caption(
            tr(
                "Vor „Als behoben melden“ ist mindestens die Abstellmaßnahme (D5/D6) zu dokumentieren. "
                "Die übrigen Felder sind empfohlen."
            )
        )
    editable = principal.can("incident:write") and incident.status != "closed"
    if not editable:
        for field in INCIDENT_ANALYSIS_FIELDS:
            st.markdown(f"**{label(ANALYSIS_LABELS, field)}**")
            value = getattr(incident, field)
            if value:
                st.text(value)
            else:
                st.caption(tr("Nicht dokumentiert."))
        return
    st.caption(
        tr(
            "Ursachen technisch und prozessbezogen beschreiben. Keine Personennamen, Schuldzuweisungen oder "
            "Leistungsbewertungen eintragen; HydraulikDoc ist kein Werkzeug zur Beschäftigtenbewertung."
        )
    )
    version = (incident.updated_at or incident.created_at).timestamp()
    with st.form(f"incident-analysis:{incident.incident_id}"):
        values = {
            field: st.text_area(
                label(ANALYSIS_LABELS, field),
                value=getattr(incident, field),
                max_chars=INCIDENT_ANALYSIS_MAX_CHARS,
                height=90,
                key=f"analysis:{incident.incident_id}:{field}:{version}",
                help=label(ANALYSIS_HELP, field),
            )
            for field in INCIDENT_ANALYSIS_FIELDS
        }
        submitted = st.form_submit_button(tr("Analyse speichern"))
    if not submitted:
        return
    try:
        repository.update_incident_analysis(
            principal,
            incident.incident_id,
            expected_updated_at=incident.updated_at or incident.created_at,
            analysis=values,
        )
    except (PermissionError, IncidentTransitionRejected, KeyError) as error:
        reason = error.args[0] if isinstance(error, (PermissionError, IncidentTransitionRejected)) else "NOT_FOUND"
        st.error(
            tr(
                "Analyse nicht gespeichert. Der Incident wurde zwischenzeitlich geändert oder ist abgeschlossen; "
                "bitte Ansicht neu laden. Referenz {reason}",
                reason=reason,
            )
        )
        return
    repository.emit_audit(
        principal,
        action="incident.analysis.updated",
        outcome=AuditOutcome.SUCCESS,
        resource_type="incident",
        resource_id=incident.incident_id,
        metadata={"incident_status": incident.status, "role": principal.role},
    )
    st.session_state.incident_notice = ("analysis", incident.incident_id[:8], incident.status)
    st.rerun()


def _incident_actions(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    next_statuses = INCIDENT_TRANSITIONS.get(incident.status, ())
    if not next_statuses:
        st.caption(tr("Abgeschlossen. Weitere Statuswechsel und Änderungen der Analyse sind nicht vorgesehen."))
        return
    if not principal.can("incident:write"):
        st.caption(tr("Ihre Rolle darf Incidents einsehen, aber keinen Status ändern."))
        return
    st.write(tr("Nächster Schritt"))
    columns = st.columns(len(next_statuses))
    for column, target in zip(columns, next_statuses, strict=True):
        action_label = label(INCIDENT_ACTION_LABELS, target)
        if target == "in_progress" and incident.status == "resolved":
            action_label = tr("Wieder öffnen")
        missing = missing_analysis_fields(incident, target)
        role_allowed = target != "closed" or principal.can(INCIDENT_CLOSE_PERMISSION)
        allowed = role_allowed and not missing
        if column.button(
            action_label,
            key=f"incident:{incident.incident_id}:{target}",
            type="primary" if target == next_statuses[0] and allowed else "secondary",
            disabled=not allowed,
            width="stretch",
        ):
            _transition_incident(principal, repository, incident, target)
        if not role_allowed:
            column.caption(tr("Abnahme erfordert die Rolle Supervisor oder Admin."))
        elif missing:
            column.caption(
                tr(
                    "Zuerst dokumentieren: {fields}.",
                    fields=", ".join(label(ANALYSIS_LABELS, field) for field in missing),
                )
            )


def _incident_history(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    st.markdown(f"#### {tr('Verlauf')}")
    events = repository.list_incident_events(principal, incident.incident_id)
    if not events:
        st.caption(tr("Für diesen Incident liegt kein Verlauf vor (vor Einführung der Verlaufserfassung angelegt)."))
        return
    entries = []
    for event in events:
        if event.event_type == "created":
            text = tr("Angelegt")
        elif event.event_type == "status_changed":
            text = tr(
                "Status {previous} → {current}",
                previous=label(INCIDENT_STATUS_LABELS, event.previous_status or "–"),
                current=label(INCIDENT_STATUS_LABELS, event.new_status or "–"),
            )
        else:
            text = tr("Analyse und Maßnahmen aktualisiert")
        actor = label(ROLE_LABELS, event.actor_role)
        if event.is_own:
            actor = tr("{role} (Sie)", role=actor)
        entries.append(
            f'<li><time datetime="{event.occurred_at.isoformat()}">{fmt_datetime(event.occurred_at)} UTC</time>'
            f"<span>{html.escape(text)}</span><small>{html.escape(actor)}</small></li>"
        )
    st.markdown(f'<ol class="hd-timeline">{"".join(entries)}</ol>', unsafe_allow_html=True)
    st.caption(tr("Personen werden nur mit Rolle angezeigt; die pseudonymisierte Kennung bleibt im Auditnachweis."))


def _render_sap_handover(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    incidents: list[IncidentRecord],
) -> None:
    with st.expander(tr("Übergabe an SAP PM (Instandhaltungsmeldung)")):
        st.caption(
            tr(
                "Erzeugt eine CSV-Übergabedatei für die gefilterten Incidents mit den SAP-PM-Feldern QMART, QMTXT "
                "(40 Zeichen), PRIOK, TPLNR und EQUNR sowie HydraulikDoc-Referenzen. Es besteht keine Live-Verbindung "
                "zu SAP; Feldmapping und Prioritätsschema sind vor dem Upload durch Ihr SAP-Team zu validieren."
            )
        )
        notification_type = (
            st.text_input(tr("Meldungsart (QMART)"), value="M2", max_chars=2, key="sap-notification-type")
            .strip()
            .upper()
        )
        try:
            export = build_sap_notifications(incidents, repository.list_assets(principal), notification_type)
        except ValueError as error:
            st.error(tr_error(error))
            return
        if export.missing_reference:
            st.warning(
                tr_plural(
                    len(export.missing_reference),
                    "{n} Incident hat kein Asset mit Technischem Platz oder Equipment. Die Meldung ist dann keinem "
                    "Technischen Objekt zugeordnet; Referenz im Asset Register ergänzen.",
                    "{n} Incidents haben kein Asset mit Technischem Platz oder Equipment. Die Meldung ist dann keinem "
                    "Technischen Objekt zugeordnet; Referenz im Asset Register ergänzen.",
                )
            )
        exported = st.download_button(
            tr_plural(
                len(export.rows),
                "{n} Meldung als SAP-PM-Übergabedatei herunterladen",
                "{n} Meldungen als SAP-PM-Übergabedatei herunterladen",
            ),
            to_spreadsheet_csv(export.rows, SAP_NOTIFICATION_COLUMNS),
            file_name=f"hydraulikdoc-sap-pm-meldungen-{datetime.now(UTC):%Y%m%d-%H%M}.csv",
            mime="text/csv",
            key="sap-export",
        )
        if exported:
            repository.emit_audit(
                principal,
                action="incident.sap_export.generated",
                outcome=AuditOutcome.SUCCESS,
                resource_type="incident",
                metadata={"source_count": len(export.rows), "failure_count": len(export.missing_reference)},
            )


def _incidents(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.title(tr("Incident Workflow"))
    st.caption(
        tr(
            "Technische Auffälligkeiten werden nachvollziehbar erfasst; Meldepflichten bleiben organisatorisch zu bewerten."
        )
    )
    if notice := st.session_state.pop("incident_notice", None):
        kind, short_id, status = notice
        if kind == "analysis":
            st.success(tr("Analyse für Incident {id} wurde gespeichert.", id=short_id))
        else:
            st.success(
                tr(
                    "Incident {id} steht jetzt auf „{status}“.",
                    id=short_id,
                    status=label(INCIDENT_STATUS_LABELS, status),
                )
            )
    incidents = repository.list_incidents(principal)
    if not incidents:
        st.info(
            tr(
                "Keine Incidents vorhanden. Incidents entstehen aus einer Bewertung im Condition Monitoring oder im Fluid-Bereich."
            )
        )
        return

    counts = {status: sum(1 for item in incidents if item.status == status) for status in INCIDENT_STATUSES}
    st.markdown(
        '<div class="hd-state hd-state-wide">'
        + "".join(
            f"<div><strong>{html.escape(label(INCIDENT_STATUS_LABELS, status))}</strong>{counts[status]}</div>"
            for status in INCIDENT_STATUSES
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    status_filter, severity_filter, asset_filter = st.columns(3)
    selected_statuses = status_filter.multiselect(
        tr("Status"),
        INCIDENT_STATUSES,
        default=DEFAULT_INCIDENT_FILTER,
        format_func=lambda option: label(INCIDENT_STATUS_LABELS, option),
        key="incident-status-filter",
    )
    severities = sorted(
        {item.severity for item in incidents},
        key=lambda option: tuple(INCIDENT_SEVERITY_LABELS).index(option) if option in INCIDENT_SEVERITY_LABELS else 99,
    )
    selected_severities = severity_filter.multiselect(
        tr("Schwere"),
        severities,
        format_func=lambda option: label(INCIDENT_SEVERITY_LABELS, option),
        placeholder=tr("Alle"),
        key="incident-severity-filter",
    )
    asset_ids = sorted({item.asset_id for item in incidents})
    selected_asset = asset_filter.selectbox(
        tr("Asset"), ("", *asset_ids), format_func=lambda option: option or tr("Alle"), key="incident-asset-filter"
    )
    visible = [
        item
        for item in incidents
        if (not selected_statuses or item.status in selected_statuses)
        and (not selected_severities or item.severity in selected_severities)
        and (not selected_asset or item.asset_id == selected_asset)
    ]
    if not visible:
        st.info(tr("Kein Incident entspricht den gewählten Filtern."))
        return
    st.dataframe(
        [
            {
                tr("ID"): item.incident_id[:8],
                tr("Asset"): item.asset_id,
                tr("Titel"): item.title,
                tr("Schwere"): label(INCIDENT_SEVERITY_LABELS, item.severity),
                tr("Status"): label(INCIDENT_STATUS_LABELS, item.status),
                tr("Erstellt"): fmt_datetime(item.created_at),
                tr("Geändert"): fmt_datetime(item.updated_at or item.created_at),
            }
            for item in visible
        ],
        width="stretch",
        hide_index=True,
    )
    if principal.can("incident:write"):
        _render_sap_handover(principal, repository, visible)
    st.subheader(tr("Incident bearbeiten"))
    by_id = {item.incident_id: item for item in visible}
    selected_id = st.selectbox(
        tr("Incident"),
        tuple(by_id),
        format_func=lambda option: _incident_option_label(by_id[option]),
        key="incident-selected",
    )
    _incident_detail(principal, repository, by_id[selected_id])


def _format_duration(value: timedelta | None) -> str:
    if value is None:
        return "–"
    hours = value / timedelta(hours=1)
    if hours < 1:
        text, unit = str(round(value / timedelta(minutes=1))), "min"
    elif hours < 48:
        text, unit = f"{hours:.1f}", "h"
    else:
        text, unit = f"{hours / 24:.1f}", "d"
    return f"{text.replace('.', ',') if _language() == 'de' else text} {unit}"


def _format_share(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{round(value * 100)} %" if _language() == "de" else f"{round(value * 100)}%"


def _kpi_window() -> tuple[int, datetime, datetime]:
    days = st.radio(
        tr("Zeitraum"),
        KPI_WINDOW_DAYS,
        index=KPI_WINDOW_DAYS.index(90),
        format_func=lambda option: tr("Letzte {n} Tage", n=option),
        horizontal=True,
        key="kpi-window",
    )
    now = datetime.now(UTC)
    return days, now - timedelta(days=days), now


def _render_kpi_tiles(kpis: MaintenanceKpis) -> None:
    tiles = (
        (tr("Incidents"), tr("{n} erfasst, {open} offen", n=kpis.incidents, open=kpis.open_incidents)),
        (
            tr("Reaktionszeit (MTTA)"),
            tr(
                "Ø {mean} · Median {median}",
                mean=_format_duration(kpis.mean_response),
                median=_format_duration(kpis.median_response),
            ),
        ),
        (
            tr("Behebungszeit (MTTR)"),
            tr(
                "Ø {mean} · Median {median}",
                mean=_format_duration(kpis.mean_restoration),
                median=_format_duration(kpis.median_restoration),
            ),
        ),
        (
            tr("Ohne Wiedereröffnung behoben"),
            tr(
                "{share} von {n} behobenen",
                share=_format_share(kpis.first_time_fix_rate),
                n=kpis.restored_incidents,
            ),
        ),
        (tr("Ältester offener Incident"), _format_duration(kpis.oldest_open)),
    )
    st.markdown(
        '<div class="hd-state hd-state-wide">'
        + "".join(f"<div><strong>{html.escape(title)}</strong>{html.escape(text)}</div>" for title, text in tiles)
        + "</div>",
        unsafe_allow_html=True,
    )


def _kpis(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.title(tr("Instandhaltungskennzahlen"))
    st.caption(
        tr(
            "Reaktions- und Behebungszeiten je Anlage aus dem dokumentierten Incident-Verlauf. Kennzahlen werden nur "
            "je Anlage gebildet, nie je Person; eine Leistungs- oder Verhaltenskontrolle ist nicht vorgesehen."
        )
    )
    days, window_start, now = _kpi_window()
    lifecycles = repository.list_incident_lifecycles(principal, since=window_start, limit=KPI_INCIDENT_LIMIT + 1)
    if len(lifecycles) > KPI_INCIDENT_LIMIT:
        st.warning(
            tr(
                "Im Zeitraum liegen mehr als {limit} Incidents. Ausgewertet werden die {limit} jüngsten; "
                "für einen vollständigen Überblick einen kürzeren Zeitraum wählen.",
                limit=KPI_INCIDENT_LIMIT,
            )
        )
        lifecycles = lifecycles[:KPI_INCIDENT_LIMIT]
    kpis = maintenance_kpis(lifecycles, repository.list_assets(principal), window_start=window_start, now=now)
    if not kpis.incidents:
        st.info(tr("Im gewählten Zeitraum wurden keine Incidents erfasst."))
        return
    _render_kpi_tiles(kpis)
    if repeat := kpis.repeat_failure_assets:
        st.markdown(
            '<div class="hd-notice hd-blocked">'
            + html.escape(
                tr_plural(
                    len(repeat),
                    "{n} Anlage mit Wiederholungsfehler (zwei Incidents innerhalb von {days} Tagen): {assets}. "
                    "Ursachenanalyse und Instandhaltungsstrategie prüfen.",
                    "{n} Anlagen mit Wiederholungsfehler (zwei Incidents innerhalb von {days} Tagen): {assets}. "
                    "Ursachenanalyse und Instandhaltungsstrategie prüfen.",
                    days=REPEAT_FAILURE_SPAN.days,
                    assets=", ".join(f"{item.name} ({item.asset_id})" for item in repeat),
                )
            )
            + "</div>",
            unsafe_allow_html=True,
        )
    st.subheader(tr("Je Anlage"))
    st.dataframe(
        [
            {
                tr("Asset"): item.asset_id,
                tr("Bezeichnung"): item.name,
                tr("Standort"): item.site,
                tr("Technischer Platz"): item.functional_location or "–",
                tr("Incidents"): item.incidents,
                tr("davon 8D"): item.eight_d_incidents,
                tr("Offen"): item.open_incidents,
                tr("Ø Reaktion"): _format_duration(item.mean_response),
                tr("Ø Behebung"): _format_duration(item.mean_restoration),
                tr("Wiedereröffnet"): item.reopened,
                tr("Ø Störungsabstand"): _format_duration(item.mean_interval),
                tr("Wiederholungsfehler"): tr("ja") if item.repeat_failure else "–",
                tr("Letzter Incident"): fmt_datetime(item.last_incident),
            }
            for item in kpis.assets
        ],
        width="stretch",
        hide_index=True,
    )
    if kpis.without_history:
        st.caption(
            tr_plural(
                kpis.without_history,
                "{n} Incident ohne Verlauf (vor Einführung der Verlaufserfassung angelegt) zählt mit, "
                "aber ohne Reaktions- und Behebungszeit.",
                "{n} Incidents ohne Verlauf (vor Einführung der Verlaufserfassung angelegt) zählen mit, "
                "aber ohne Reaktions- und Behebungszeit.",
            )
        )
    with st.expander(tr("Berechnungsgrundlage")):
        st.markdown(
            tr(
                "- **Reaktionszeit:** Anlage des Incidents bis zum ersten Bearbeitungsschritt (bestätigt oder in "
                "Bearbeitung).\n"
                "- **Behebungszeit:** Anlage bis zur letzten Meldung „Behoben“; ein wiedereröffneter Incident zählt "
                "erst mit der endgültigen Behebung.\n"
                "- **Störungsabstand:** mittlerer Abstand zwischen zwei Incidents derselben Anlage in Kalenderzeit, "
                "nicht in Betriebsstunden; daher kein MTBF im Sinne der Zuverlässigkeitstechnik.\n"
                "- **Grundlage** sind die Zeitpunkte der Dokumentation in HydraulikDoc, keine Maschinen- oder "
                "SAP-Daten. Gezählt werden Incidents, die im gewählten Zeitraum angelegt wurden."
            )
        )
    if principal.can("analysis:export"):
        rows = kpi_export_rows(kpis)
        exported = st.download_button(
            tr("Kennzahlen je Anlage als CSV herunterladen"),
            to_spreadsheet_csv(rows, KPI_EXPORT_COLUMNS),
            file_name=f"hydraulikdoc-kennzahlen-{days}d-{now:%Y%m%d-%H%M}.csv",
            mime="text/csv",
            key="kpi-export",
        )
        if exported:
            repository.emit_audit(
                principal,
                action="incident.kpi_export.generated",
                outcome=AuditOutcome.SUCCESS,
                resource_type="incident",
                metadata={"source_count": len(rows), "window_days": days},
            )


PRIVACY_REQUEST_LABELS = {
    "access": msg("Auskunft"),
    "rectification": msg("Berichtigung"),
    "restriction": msg("Einschränkung"),
    "erasure": msg("Löschung"),
    "objection": msg("Widerspruch"),
}
PRIVACY_DECISION_LABELS = {
    "fulfilled": msg("erfüllt"),
    "no_data": msg("keine Daten vorhanden"),
    "identity_not_verified": msg("Identität nicht nachgewiesen"),
    "legal_hold": msg("Legal Hold (Art. 17 Abs. 3 lit. e DSGVO)"),
    "retention_obligation": msg("gesetzliche Aufbewahrungspflicht (Art. 17 Abs. 3 lit. b DSGVO)"),
    "manifestly_unfounded": msg("offenkundig unbegründet oder exzessiv (Art. 12 Abs. 5 DSGVO)"),
}
PRIVACY_ACTION_LABELS = {
    "identity_verified": msg("Identität bestätigen"),
    "in_review": msg("In Prüfung nehmen"),
    "completed": msg("Abschließen"),
    "denied": msg("Ablehnen"),
}
PRIVACY_DECISION_ERRORS = {
    "PRIVACY_OWN_REQUEST": msg("Eigene Anträge bearbeitet eine andere berechtigte Person."),
    "PRIVACY_STALE_STATUS": msg("Der Antrag wurde zwischenzeitlich bearbeitet; Ansicht neu laden."),
    "PRIVACY_DECISION_REASON_REQUIRED": msg("Begründung auswählen."),
    "PRIVACY_EVIDENCE_REFERENCE_REQUIRED": msg(
        "Vorgangsnummer mit 3 bis 64 Zeichen aus Buchstaben, Ziffern und . _ / - angeben."
    ),
}
RECORD_CLASS_LABELS = {
    "ai_interaction": msg("KI-Anfragen und Reviews"),
    "incident": msg("Incidents und Verlauf"),
    "uploaded_content": msg("Dokumente"),
    "audit_event": msg("Auditereignisse"),
    "contract_acceptance": msg("Hinweisbestätigungen"),
    "data_subject_request": msg("Datenschutzanfragen"),
}
LEGAL_HOLD_REASON_LABELS = {
    "litigation": msg("Rechtsstreit"),
    "authority_request": msg("Behördenanfrage"),
    "internal_investigation": msg("Interne Untersuchung"),
    "warranty_claim": msg("Gewährleistung oder Produkthaftung"),
}
LEGAL_HOLD_ERRORS = {
    "LEGAL_HOLD_CASE_REFERENCE_INVALID": msg(
        "Aktenzeichen mit 3 bis 64 Zeichen aus Buchstaben, Ziffern und . _ / - angeben, ohne Personennamen."
    ),
    "LEGAL_HOLD_SCOPE_INVALID": msg("Mindestens eine Datenklasse auswählen."),
    "LEGAL_HOLD_REVIEW_DATE_INVALID": msg(
        "Die Wiedervorlage muss in der Zukunft und höchstens ein Jahr entfernt liegen."
    ),
}
PRIVACY_REQUEST_STATUS_LABELS = {
    "submitted": msg("eingereicht"),
    "identity_verified": msg("Identität geprüft"),
    "in_review": msg("in Prüfung"),
    "completed": msg("abgeschlossen"),
    "denied": msg("abgelehnt"),
}


def _governance(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.title(tr("Governance & Trust"))
    st.caption(tr("Technisch nachweisbare Kontrollen und klar benannte externe Freigaben."))
    _render_ai_acceptance(principal, repository, settings)
    _render_privacy_notice(principal, repository, settings)
    st.divider()
    st.subheader(tr("Kontrollstatus"))
    if settings.demo_mode:
        ai_status, ai_evidence = tr("Demo, kein Modellaufruf"), tr("Extraktion aus synthetischen Demodokumenten")
    else:
        ai_status = tr("konfiguriert") if settings.azure_ready else tr("gesperrt")
        ai_evidence = tr("Azure OpenAI, Document Intelligence, AI Search")
    rows = [
        (
            tr("Identität"),
            tr("verifiziert") if principal.authentication_method == "entra_proxy" else tr("lokale Entwicklung"),
            tr("Entra App-Rolle oder lokaler Argon2id-Adapter"),
        ),
        (
            tr("Tenant-Isolation"),
            tr("aktiv") if settings.persistence_backend.value == "postgres" else tr("Entwicklungsmodus"),
            tr("PostgreSQL FORCE RLS und Azure Search Filter"),
        ),
        (tr("KI-Pfad"), ai_status, ai_evidence),
        (
            tr("Region"),
            tr("konfiguriert") if settings.azure_region else tr("offen"),
            settings.azure_region or tr("Deployment-Nachweis fehlt"),
        ),
        (
            tr("Deployment-Evidenz"),
            tr("verknüpft") if settings.deployment_evidence_id else tr("offen"),
            settings.deployment_evidence_id or tr("Kein Evidence-ID gesetzt"),
        ),
        (
            tr("AI-Evaluation"),
            tr("verknüpft") if settings.ai_evaluation_evidence_id else tr("offen"),
            settings.ai_evaluation_evidence_id or tr("Kein freigegebener Eval-Report"),
        ),
        (
            tr("Löschkonzept"),
            tr("freigegeben") if settings.retention_policy_approved else tr("gesperrt"),
            settings.retention_policy_id or tr("Kein genehmigter Policy-Nachweis"),
        ),
        (tr("Produktionsfreigabe"), settings.release_state, tr("Technisches Gate, keine rechtliche Zertifizierung")),
    ]
    st.dataframe(
        [{tr("Kontrolle"): a, tr("Status"): b, tr("Evidenz"): c} for a, b, c in rows], width="stretch", hide_index=True
    )
    st.subheader(tr("Technische Nutzungsgrenzen"))
    st.write(tr("• Autonome Maschinensteuerung ist gesperrt."))
    st.write(tr("• Beschäftigtenüberwachung ist gesperrt."))
    st.write(tr("• Sicherheitsrelevante Diagnose erfordert qualifizierten Review."))
    st.write(tr("• Nur akzeptierte Reviews können als Nachweis exportiert werden."))
    st.info(
        tr(
            "DPA/AVV, DSFA/TIA, Betriebsrat, Rechtsgrundlagen, Löschfristen und regulatorische Einordnung müssen "
            "instanzbezogen freigegeben und regelmäßig revalidiert werden."
        )
    )
    st.divider()
    st.subheader(tr("Datenschutz-Self-Service"))
    st.caption(
        tr(
            "Der Export enthält nur Datensätze, die dem aktuell verifizierten Entra-Subjekt zugeordnet sind. "
            "Lösch- und Korrekturanträge werden zur Identitäts- und Ausnahmeprüfung eingereiht."
        )
    )
    if st.button(tr("Meine Daten für Export zusammenstellen")):
        st.session_state.subject_export = repository.subject_export(principal)
        repository.emit_audit(
            principal,
            action="privacy.subject_export.generated",
            outcome=AuditOutcome.SUCCESS,
            metadata={"request_type": "export"},
        )
    if export := st.session_state.get("subject_export"):
        st.download_button(
            tr("Personenbezogenen Export herunterladen"),
            json.dumps(export, default=str, ensure_ascii=False, indent=2),
            file_name="hydraulikdoc-meine-daten.json",
            mime="application/json",
        )
    request_type = st.selectbox(
        tr("Antragstyp"),
        tuple(PRIVACY_REQUEST_LABELS),
        format_func=lambda option: label(PRIVACY_REQUEST_LABELS, option),
        key="privacy-request-type",
    )
    if st.button(tr("Datenschutzantrag einreichen")):
        try:
            request = repository.create_privacy_request(principal, request_type)
            repository.emit_audit(
                principal,
                action="privacy.request.submitted",
                outcome=AuditOutcome.SUCCESS,
                resource_type="privacy_request",
                resource_id=request.request_id,
                metadata={"request_type": request.request_type},
            )
            st.success(tr("Antrag {id} wurde nachweisbar eingereiht.", id=request.request_id))
        except Exception:
            st.error(tr("Ein gleichartiger offener Antrag besteht bereits oder konnte nicht angelegt werden."))
    requests = repository.list_privacy_requests(principal)
    if requests:
        st.dataframe(
            [
                {
                    tr("ID"): item.request_id,
                    tr("Typ"): label(PRIVACY_REQUEST_LABELS, item.request_type),
                    tr("Status"): label(PRIVACY_REQUEST_STATUS_LABELS, item.status),
                    tr("Eingang"): fmt_datetime(item.requested_at),
                    tr("Interne Zielfrist"): fmt_datetime(item.due_at),
                }
                for item in requests
            ],
            width="stretch",
            hide_index=True,
        )
    _render_personal_data_inventory()
    if principal.can(PRIVACY_MANAGE_PERMISSION):
        _render_privacy_queue(principal, repository)
    if principal.can(LEGAL_HOLD_PERMISSION):
        _render_legal_holds(principal, repository)


def _render_privacy_queue(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.divider()
    st.subheader(tr("Datenschutzanträge bearbeiten"))
    st.caption(
        tr(
            "Anträge erscheinen nur mit Antrags-ID; die Person nennt diese ID bei der Identitätsprüfung. "
            "Die interne Zielfrist liegt bei 28 Tagen, die gesetzliche bei einem Monat (Art. 12 Abs. 3 DSGVO). "
            "Die Umsetzung, etwa Löschung oder Berichtigung, erfolgt nach Runbook; hier wird der Vorgang nachgewiesen."
        )
    )
    if notice := st.session_state.pop("privacy_notice", None):
        st.success(notice)
    queue = repository.list_privacy_queue(principal)
    if not queue:
        st.info(tr("Keine Datenschutzanträge im Mandanten."))
        return
    now = datetime.now(UTC)
    late = sum(1 for item in queue if item.overdue(now))
    if late:
        st.warning(
            tr_plural(
                late,
                "{n} offener Antrag hat die interne Frist überschritten.",
                "{n} offene Anträge haben die interne Frist überschritten.",
            )
        )
    st.dataframe(
        [
            {
                tr("ID"): item.request_id[:8],
                tr("Typ"): label(PRIVACY_REQUEST_LABELS, item.request_type),
                tr("Status"): label(PRIVACY_REQUEST_STATUS_LABELS, item.status),
                tr("Eingang"): fmt_datetime(item.requested_at),
                tr("Interne Zielfrist"): fmt_datetime(item.due_at)
                + (f" · {tr('überfällig')}" if item.overdue(now) else ""),
                tr("Begründung"): label(PRIVACY_DECISION_LABELS, item.decision_reason) if item.decision_reason else "–",
                tr("Vorgang"): item.evidence_reference or "–",
            }
            for item in queue
        ],
        width="stretch",
        hide_index=True,
    )
    open_requests = {item.request_id: item for item in queue if item.status in PRIVACY_OPEN_STATUSES}
    if not open_requests:
        return
    selected = st.selectbox(
        tr("Offenen Antrag bearbeiten"),
        tuple(open_requests),
        format_func=lambda option: (
            f"{option[:8]} · {label(PRIVACY_REQUEST_LABELS, open_requests[option].request_type)} · "
            f"{label(PRIVACY_REQUEST_STATUS_LABELS, open_requests[option].status)}"
        ),
        key="privacy-queue-selected",
    )
    _privacy_decision_form(principal, repository, open_requests[selected])


def _privacy_decision_form(
    principal: UserPrincipal, repository: EnterpriseRepository, request: PrivacyRequestRecord
) -> None:
    if request.request_type == "erasure" and any(
        item.released_at is None for item in repository.list_legal_holds(principal)
    ):
        st.warning(
            tr(
                "Für den Mandanten ist ein Legal Hold aktiv. Löschung der gehaltenen Daten nach Art. 17 Abs. 3 lit. e "
                "DSGVO zurückstellen und die Person darüber informieren."
            )
        )
    target = st.radio(
        tr("Nächster Schritt"),
        PRIVACY_REQUEST_TRANSITIONS[request.status],
        format_func=lambda option: label(PRIVACY_ACTION_LABELS, option),
        horizontal=True,
        key=f"privacy-target-{request.request_id}",
    )
    reason = reference = None
    if target in PRIVACY_DECISION_REASONS:
        reason = st.selectbox(
            tr("Begründung"),
            PRIVACY_DECISION_REASONS[target],
            format_func=lambda option: label(PRIVACY_DECISION_LABELS, option),
            key=f"privacy-reason-{request.request_id}-{target}",
        )
        reference = st.text_input(
            tr("Vorgangsnummer (Ticket oder Akte)"),
            max_chars=64,
            placeholder="DSR-2026-031",
            key=f"privacy-reference-{request.request_id}",
        )
    if st.button(label(PRIVACY_ACTION_LABELS, target), key=f"privacy-decide-{request.request_id}"):
        try:
            decided = repository.decide_privacy_request(
                principal,
                request.request_id,
                expected=request.status,
                target=target,
                decision_reason=reason,
                evidence_reference=reference,
            )
        except PrivacyTransitionRejected as error:
            st.error(label(PRIVACY_DECISION_ERRORS, str(error)))
            return
        repository.emit_audit(
            principal,
            action="privacy.request.status_changed",
            outcome=AuditOutcome.SUCCESS,
            resource_type="privacy_request",
            resource_id=decided.request_id,
            metadata={
                "request_type": decided.request_type,
                "previous_status": request.status,
                "reason_code": decided.decision_reason,
            },
        )
        st.session_state.privacy_notice = tr(
            "Antrag {id} steht jetzt auf „{status}“.",
            id=decided.request_id[:8],
            status=label(PRIVACY_REQUEST_STATUS_LABELS, decided.status),
        )
        st.rerun()


def _render_legal_holds(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.divider()
    st.subheader(tr("Legal Hold"))
    st.caption(
        tr(
            "Setzt die Löschfristen ganzer Datenklassen des Mandanten aus, etwa bei Rechtsstreit oder Behördenanfrage. "
            "Ein Hold endet nie automatisch: Er wird zur Wiedervorlage angemahnt und nur ausdrücklich aufgehoben."
        )
    )
    if notice := st.session_state.pop("legal_hold_notice", None):
        st.success(notice)
    holds = repository.list_legal_holds(principal)
    now = datetime.now(UTC)
    active = [item for item in holds if item.released_at is None]
    if holds:
        st.dataframe(
            [
                {
                    tr("Aktenzeichen"): item.case_reference,
                    tr("Grund"): label(LEGAL_HOLD_REASON_LABELS, item.reason_code),
                    tr("Datenklassen"): ", ".join(label(RECORD_CLASS_LABELS, value) for value in item.record_classes),
                    tr("Wiedervorlage"): fmt_datetime(item.review_at)
                    + (f" · {tr('fällig')}" if item.review_overdue(now) else ""),
                    tr("Gesetzt"): fmt_datetime(item.created_at),
                    tr("Aufgehoben"): fmt_datetime(item.released_at) if item.released_at else "–",
                }
                for item in holds
            ],
            width="stretch",
            hide_index=True,
        )
    with st.form("legal-hold-create", clear_on_submit=True):
        reference = st.text_input(tr("Aktenzeichen"), max_chars=64, placeholder="LH-2026-014")
        reason = st.selectbox(
            tr("Grund"), LEGAL_HOLD_REASONS, format_func=lambda option: label(LEGAL_HOLD_REASON_LABELS, option)
        )
        classes = st.multiselect(
            tr("Datenklassen"),
            tuple(RECORD_CLASS_LABELS),
            default=tuple(RECORD_CLASS_LABELS),
            format_func=lambda option: label(RECORD_CLASS_LABELS, option),
        )
        today = date.today()
        review = st.date_input(
            tr("Wiedervorlage"),
            value=today + timedelta(days=90),
            min_value=today + timedelta(days=1),
            max_value=today + timedelta(days=365),
        )
        submitted = st.form_submit_button(tr("Legal Hold setzen"))
    if submitted:
        try:
            hold = repository.create_legal_hold(
                principal,
                case_reference=reference,
                reason_code=reason,
                record_classes=tuple(classes),
                review_at=datetime(review.year, review.month, review.day, 8, tzinfo=UTC),
            )
        except ValueError as error:
            st.error(label(LEGAL_HOLD_ERRORS, str(error)))
        else:
            repository.emit_audit(
                principal,
                action="legal_hold.created",
                outcome=AuditOutcome.SUCCESS,
                resource_type="legal_hold",
                resource_id=hold.hold_id,
                metadata={"reason_code": hold.reason_code, "collection": ",".join(hold.record_classes)},
            )
            st.session_state.legal_hold_notice = tr(
                "Legal Hold {reference} ist aktiv; betroffene Daten werden nicht mehr gelöscht.",
                reference=hold.case_reference,
            )
            st.rerun()
    if not active:
        return
    by_id = {item.hold_id: item for item in active}
    selected = st.selectbox(
        tr("Aktiven Hold aufheben"),
        tuple(by_id),
        format_func=lambda option: by_id[option].case_reference,
        key="legal-hold-release-select",
    )
    confirmed = st.checkbox(tr("Aufhebung ist mit der Rechtsabteilung abgestimmt."), key="legal-hold-release-confirm")
    if st.button(tr("Legal Hold aufheben"), disabled=not confirmed, key="legal-hold-release"):
        released = repository.release_legal_hold(principal, selected)
        repository.emit_audit(
            principal,
            action="legal_hold.released",
            outcome=AuditOutcome.SUCCESS,
            resource_type="legal_hold",
            resource_id=released.hold_id,
            metadata={"reason_code": released.reason_code, "collection": ",".join(released.record_classes)},
        )
        st.session_state.legal_hold_notice = tr(
            "Legal Hold {reference} ist aufgehoben; die regulären Löschfristen gelten wieder.",
            reference=released.case_reference,
        )
        st.rerun()


def _render_personal_data_inventory() -> None:
    with st.expander(tr("Welche Daten über mich gespeichert werden")):
        st.caption(
            tr(
                "Personen erscheinen nur als nicht umkehrbares Pseudonym; Name und E-Mail werden nicht gespeichert. "
                "Diese Übersicht ist die technische Anlage für die Betriebsvereinbarung und wird gegen das "
                "Datenbankschema geprüft."
            )
        )
        days = RetentionPolicy.from_environment().days_by_class
        st.dataframe(
            [
                {
                    tr("Feld"): f"{item.table}.{item.column}",
                    tr("Inhalt"): tr(item.content),
                    tr("Zweck"): tr(item.purpose),
                    tr("Sichtbarkeit"): tr(item.visibility),
                    tr("Auswertung"): tr(item.evaluation),
                    tr("Löschfrist"): tr_plural(days[item.retention], "{n} Tag", "{n} Tage")
                    + (f"; {tr(item.retention_note)}" if item.retention_note else ""),
                    tr("Im Export"): tr("ja") if item.export_section else tr(item.export_note or ""),
                }
                for item in PERSONAL_DATA_FIELDS
            ],
            width="stretch",
            hide_index=True,
        )
        st.markdown(f"**{tr('Ausgeschlossene Auswertungen')}**")
        st.markdown("\n".join(f"- {tr(item)}" for item in EXCLUDED_EVALUATIONS))


def _system(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.title(tr("System Evidence"))
    st.caption(tr("Keine Secrets und keine Rohinhalte werden in dieser Ansicht ausgegeben."))
    policy = RetentionPolicy.from_environment()
    st.json(
        {
            "application_version": APP_VERSION,
            "environment": settings.environment.value,
            "release_state": settings.release_state,
            "auth_mode": settings.auth_mode.value,
            "persistence": settings.persistence_backend.value,
            "ai_backend": settings.ai_backend.value,
            "azure_ready": settings.azure_ready,
            "demo_mode": settings.demo_mode,
            "azure_region": settings.azure_region,
            "managed_identity": settings.azure_use_managed_identity,
            "search_semantic_ranker": settings.azure_search_semantic,
            "human_review_required": settings.require_human_review,
            "deployment_evidence_id": settings.deployment_evidence_id,
            "ai_evaluation_evidence_id": settings.ai_evaluation_evidence_id,
            "model_snapshot": settings.azure_model_snapshot,
            "retention_policy_approved": settings.retention_policy_approved,
            "retention_policy_id": settings.retention_policy_id,
            "retention_days": {record_class.value: days for record_class, days in policy.days_by_class.items()},
            "principal_role": principal.role,
        }
    )
    if principal.can(AUDIT_VERIFY_PERMISSION):
        _render_audit_chain_check(principal, repository)


def _render_audit_chain_check(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.subheader(tr("Auditkette"))
    st.caption(
        tr(
            "Berechnet jedes Auditereignis des Mandanten neu und prüft die Verkettung. Eine geänderte, entfernte "
            "oder umsortierte Eintragung fällt auf. Das Löschen der jüngsten Einträge erkennt nur der nächtliche "
            "Abgleich mit den außerhalb der Datenbank gespeicherten Ankern."
        )
    )
    if st.button(tr("Auditkette prüfen"), key="audit-chain-verify"):
        report = repository.verify_audit_chain(principal)
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
        st.session_state.audit_chain_report = report
    shown: AuditChainReport | None = st.session_state.get("audit_chain_report")
    if shown is None:
        return
    if shown.intact:
        st.success(
            tr_plural(shown.event_count, "Kette intakt: {n} Ereignis geprüft.", "Kette intakt: {n} Ereignisse geprüft.")
        )
    else:
        st.error(
            tr(
                "Kette unterbrochen bei Ereignis {sequence} ({reason}). Sicherheitsvorfall nach Runbook melden.",
                sequence=shown.broken_sequence if shown.broken_sequence is not None else "–",
                reason=shown.reason,
            )
        )
    if shown.head_hash:
        st.caption(
            tr(
                "Letztes Ereignis {sequence}, Hash {hash}. Diesen Anker außerhalb der Datenbank festhalten.",
                sequence=shown.head_sequence,
                hash=shown.head_hash,
            )
        )
    if shown.starts_after_purge:
        st.caption(
            tr(
                "Die Kette beginnt bei Ereignis {sequence}; ältere Einträge wurden nach Löschfrist entfernt.",
                sequence=shown.first_sequence,
            )
        )


def run() -> None:
    st.set_page_config(
        page_title="HydraulikDoc Enterprise",
        page_icon="⚙️",
        layout="wide",
        initial_sidebar_state="auto",
        menu_items={"Get help": "https://sbsdeutschland.com"},
    )
    _inject_css()
    try:
        settings = get_settings()
    except ConfigurationError as error:
        st.error(tr("Der Runtime-Start wurde wegen einer unsicheren Konfiguration blockiert."))
        st.code(str(error))
        st.stop()
    principal = _principal(settings)
    if not principal or not _enforce_session(principal, settings):
        st.stop()
    try:
        repository = get_repository(settings)
    except Exception as error:
        st.error(tr("Persistenz nicht verfügbar. Referenz {reference}", reference=public_error_code(error)))
        st.stop()

    selected = _sidebar(principal, settings)
    _render_shell(principal, settings, selected)
    try:
        if selected == "Leitstand":
            _overview(principal, repository, settings)
        elif selected == "Assets":
            _assets(principal, repository)
        elif selected == "Wissensbasis":
            _knowledge(principal, repository, settings)
        elif selected == "Condition Monitoring":
            _condition_monitoring(principal, repository, settings)
        elif selected == "Fluid":
            _fluid(principal, repository)
        elif selected == "Incidents":
            _incidents(principal, repository)
        elif selected == "Kennzahlen":
            _kpis(principal, repository)
        elif selected == "Governance":
            _governance(principal, repository, settings)
        else:
            _system(principal, repository, settings)
    except AuthenticationError:
        st.error(tr("Diese Funktion ist für Ihre App-Rolle nicht freigegeben."))
    except Exception as error:
        st.error(tr("Vorgang abgebrochen. Referenz {reference}", reference=public_error_code(error)))
