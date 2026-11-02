"""Evidence-led Streamlit interface for HydraulikDoc Enterprise."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from compliance.audit import AuditOutcome
from compliance.retention import RetentionPolicy
from fluid_advisor import FluidLimits, FluidSample, assess_fluid

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
from .governance import GroundedAnswer, ReviewStatus, UseCase, evaluate_use_case
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
from .repository import (
    EIGHT_D_SEVERITIES,
    INCIDENT_ANALYSIS_FIELDS,
    INCIDENT_ANALYSIS_MAX_CHARS,
    INCIDENT_ANALYSIS_MIN_CHARS,
    INCIDENT_CLOSE_PERMISSION,
    INCIDENT_STATUSES,
    INCIDENT_TRANSITIONS,
    AssetRecord,
    DocumentRecord,
    EnterpriseRepository,
    IncidentRecord,
    IncidentTransitionRejected,
    get_repository,
    missing_analysis_fields,
)
from .security import InputRejected, public_error_code, validate_pdf_upload

APP_VERSION = "5.0.0-enterprise"
AI_LITERACY_NOTICE = """HydraulikDoc erzeugt quellengebundene KI-Entwürfe. Ergebnisse können
unvollständig oder falsch sein. Vor Wartung, Freigabe, Ersatzteilbestellung oder einer
Maschinenhandlung muss eine qualifizierte Person die Originalquelle, Betriebsanweisung,
Gefährdungsbeurteilung und anwendbare LOTO-Regeln prüfen. HydraulikDoc steuert keine Maschine
und ersetzt weder Herstellerfreigaben noch Fachverantwortung."""
INCIDENT_STATUS_LABELS = {
    "new": "Neu",
    "acknowledged": "Bestätigt",
    "in_progress": "In Bearbeitung",
    "resolved": "Behoben",
    "closed": "Abgeschlossen",
}
INCIDENT_ACTION_LABELS = {
    "acknowledged": "Bestätigen",
    "in_progress": "Bearbeitung starten",
    "resolved": "Als behoben melden",
    "closed": "Abnehmen und abschließen",
}
INCIDENT_SEVERITY_LABELS = {
    "ok": "OK",
    "warning": "Warnung",
    "critical": "Kritisch",
    "p1": "P1 · kritisch",
    "p2": "P2 · hoch",
    "p3": "P3 · mittel",
    "p4": "P4 · niedrig",
}
OPEN_INCIDENT_STATUSES = ("new", "acknowledged", "in_progress")
ANALYSIS_LABELS = {
    "containment_action": "D3 Sofortmaßnahme",
    "root_cause": "D4 Ursache",
    "corrective_action": "D5/D6 Abstellmaßnahme",
    "effectiveness_check": "D7 Wirksamkeitsprüfung",
}
ANALYSIS_HELP = {
    "containment_action": "Wie wurde der Schaden begrenzt? Zum Beispiel Stillsetzung, Sperrung, Sortierung.",
    "root_cause": "Technische Ursache und, falls bekannt, warum sie nicht früher entdeckt wurde.",
    "corrective_action": "Dauerhafte Abstellung: Reparatur, Tausch, Einstellung, Prozessänderung.",
    "effectiveness_check": "Womit ist belegt, dass die Maßnahme wirkt? Messreihe, Folgeprobe, Zeitraum.",
}
ROLE_LABELS = {"viewer": "Leser", "technician": "Techniker", "supervisor": "Supervisor", "admin": "Admin"}
CRITICAL_SEVERITIES = frozenset({"critical", "p1"})
CRITICALITY_LABELS = {
    "low": "Niedrig",
    "medium": "Mittel",
    "high": "Hoch",
    "safety_critical": "Sicherheitskritisch",
}
ASSET_STATUS_LABELS = {
    "active": "Aktiv",
    "maintenance": "In Wartung",
    "out_of_service": "Außer Betrieb",
    "retired": "Stillgelegt",
}
NAV_PAGES = (
    "Leitstand",
    "Assets",
    "Wissensbasis",
    "Condition Monitoring",
    "Fluid",
    "Incidents",
    "Governance",
    "System",
)
# Resolved incidents stay visible by default because they still await supervisor sign-off.
DEFAULT_INCIDENT_FILTER = (*OPEN_INCIDENT_STATUSES, "resolved")
PRIVACY_NOTICE = """HydraulikDoc verarbeitet Ihre Entra-Kennung pseudonymisiert für Rollenprüfung,
Auditnachweise, KI-Interaktionen und von Ihnen ausgelöste Incidents. Freitextfragen werden nicht
protokolliert; in der Fachdatenbank wird nur ein Hash gespeichert. Die konkrete Rechtsgrundlage,
Verantwortlichenkontaktdaten, Empfänger und genehmigten Löschfristen werden in der
instanzbezogenen Datenschutzerklärung Ihres Unternehmens ausgewiesen."""


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


def _local_login(settings: AppSettings) -> UserPrincipal | None:
    if st.session_state.get("principal"):
        return st.session_state.principal
    st.title("HydraulikDoc Enterprise")
    st.caption(
        "Lokale Entwicklungsanmeldung mit Argon2id. In Produktion ist ausschließlich Microsoft Entra ID zulässig."
    )
    if not settings.local_users():
        st.warning("Keine lokalen Benutzer konfiguriert. Hinterlegen Sie LOCAL_USERS_JSON mit Argon2id-Hashes.")
        st.code(
            "python -c \"from argon2 import PasswordHasher; print(PasswordHasher().hash('change-me'))\"",
            language="bash",
        )
        return None
    with st.form("local-login", clear_on_submit=False):
        username = st.text_input("Benutzerkennung", autocomplete="username")
        password = st.text_input("Passwort", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Anmelden", type="primary", width="stretch")
    if submitted:
        principal = verify_local_user(username.strip(), password, settings)
        if principal:
            st.session_state.principal = principal
            st.session_state.last_activity = time.monotonic()
            st.rerun()
        st.error("Anmeldung fehlgeschlagen.")
    return None


def _principal(settings: AppSettings) -> UserPrincipal | None:
    if settings.auth_mode is AuthMode.ENTRA_PROXY:
        encoded = _header_value("X-MS-CLIENT-PRINCIPAL")
        if not encoded:
            st.error("Zugriff verweigert: Es liegt kein verifizierter Entra-Prinzipal vor.")
            return None
        try:
            return principal_from_entra_header(encoded, settings.default_tenant_id)
        except AuthenticationError:
            st.error("Zugriff verweigert: Identität oder App-Rolle ist unvollständig.")
            return None
    return _local_login(settings)


def _enforce_session(principal: UserPrincipal, settings: AppSettings) -> bool:
    now = time.monotonic()
    previous = st.session_state.get("last_activity", now)
    if now - previous > settings.session_idle_minutes * 60:
        st.session_state.clear()
        st.warning("Die Sitzung wurde wegen Inaktivität beendet.")
        return False
    st.session_state.last_activity = now
    st.session_state.principal = principal
    return True


def _rag(settings: AppSettings, repository: EnterpriseRepository) -> AzureRAGService:
    existing = st.session_state.get("azure_rag")
    if existing is None:
        existing = AzureRAGService(settings, repository)
        st.session_state.azure_rag = existing
    return existing


def _ai_notice_digest() -> str:
    return hashlib.sha256(AI_LITERACY_NOTICE.encode("utf-8")).hexdigest()


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
        st.success(f"KI-Nutzerhinweis {settings.ai_notice_version} bestätigt.")
        return True
    st.markdown(f'<div class="hd-notice">{AI_LITERACY_NOTICE}</div>', unsafe_allow_html=True)
    acknowledgement = st.checkbox(
        "Ich verstehe die Grenzen und bestätige die Pflicht zur fachlichen Prüfung.",
        key="ai-literacy-check",
    )
    if st.button(
        "Nutzerhinweis bestätigen",
        disabled=not acknowledgement,
        type="primary",
        key="ai-literacy-submit",
    ):
        repository.record_acceptance(
            principal,
            "ai_literacy",
            settings.ai_notice_version,
            _ai_notice_digest(),
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
    digest = hashlib.sha256(PRIVACY_NOTICE.encode("utf-8")).hexdigest()
    if repository.has_acceptance(principal, "privacy", settings.privacy_notice_version):
        st.caption(f"Datenschutzhinweis {settings.privacy_notice_version} zur Kenntnis genommen.")
        return
    st.markdown(f'<div class="hd-notice">{PRIVACY_NOTICE}</div>', unsafe_allow_html=True)
    if st.button("Datenschutzhinweis zur Kenntnis nehmen"):
        repository.record_acceptance(principal, "privacy", settings.privacy_notice_version, digest)
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
    if page != "Leitstand":
        # Working pages lead with the task; the context stays visible in one compact line.
        st.markdown(
            f"""
            <div class="hd-context">
              <span><strong>Mandant</strong> <code>{tenant}</code></span>
              <span><strong>Rolle</strong> <code>{role}</code></span>
              <span><strong>Releasezustand</strong> <code>{release}</code></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"""
        <section class="hd-hero">
          <div>
            <h1>Servicewissen wird zur überprüfbaren Entscheidung.</h1>
            <p>HydraulikDoc verbindet technische Dokumentation, Zustandsdaten und einen
            menschlich freizugebenden KI-Entwurf. Für Instandhaltungsteams, die Quellen,
            Grenzwerte und Verantwortung an einem Ort brauchen.</p>
          </div>
          <div class="hd-proof">
            <div><strong>Releasezustand</strong><code>{release}</code></div>
            <div><strong>Mandant</strong><code>{tenant}</code></div>
            <div><strong>Rolle</strong><code>{role}</code></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _go_to(page: str) -> None:
    st.session_state.nav = page


def _sidebar(principal: UserPrincipal, settings: AppSettings) -> str:
    with st.sidebar:
        st.markdown("## HydraulikDoc")
        st.caption(f"Enterprise {APP_VERSION}")
        st.divider()
        st.write(principal.display_name)
        st.caption(f"{principal.role} · {principal.authentication_method}")
        st.divider()
        selected = st.radio("Arbeitsbereich", NAV_PAGES, key="nav", label_visibility="collapsed")
        st.divider()
        st.caption(f"KI: {'Azure konfiguriert' if settings.azure_ready else 'nicht konfiguriert'}")
        st.caption(f"Region: {settings.azure_region or 'nicht attestiert'}")
        if settings.auth_mode is AuthMode.LOCAL and st.button("Abmelden", width="stretch"):
            st.session_state.clear()
            st.rerun()
        return selected


def _count_phrase(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _overview(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    documents = repository.list_documents(principal)
    assets = repository.list_assets(principal)
    incidents = repository.list_incidents(principal)
    open_incidents = [item for item in incidents if item.status in OPEN_INCIDENT_STATUSES]
    st.header("Leitstand")
    st.caption("Operativer Überblick ohne erfundene Verfügbarkeits- oder ROI-Kennzahlen.")
    st.markdown(
        f"""
        <div class="hd-state">
          <div><strong>Dokumente</strong>{len(documents)} aktive Dokumentdatensätze</div>
          <div><strong>Assets</strong>{len(assets)} aktive Anlagenobjekte</div>
          <div><strong>Offene Incidents</strong>{len(open_incidents)} im Workflow</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.subheader("Handlungsbedarf")
    critical = [item for item in open_incidents if item.severity in CRITICAL_SEVERITIES]
    unacknowledged = [item for item in incidents if item.status == "new"]
    awaiting_signoff = [item for item in incidents if item.status == "resolved"]
    actions: list[tuple[str, str]] = []
    if critical:
        actions.append(
            (
                "hd-notice hd-blocked",
                _count_phrase(len(critical), "kritischer Incident ist", "kritische Incidents sind")
                + " offen. Abschalt-, Sicherheits- und LOTO-Bewertung dokumentieren.",
            )
        )
    if unacknowledged:
        actions.append(
            (
                "hd-notice",
                _count_phrase(len(unacknowledged), "neuer Incident ist", "neue Incidents sind")
                + " noch nicht bestätigt.",
            )
        )
    if awaiting_signoff:
        responsible = (
            "Ihre Abnahme" if principal.can(INCIDENT_CLOSE_PERMISSION) else "die Abnahme durch einen Supervisor"
        )
        actions.append(
            (
                "hd-notice",
                _count_phrase(len(awaiting_signoff), "behobener Incident wartet", "behobene Incidents warten")
                + f" auf {responsible}.",
            )
        )
    if actions:
        for css_class, text in actions:
            st.markdown(f'<div class="{css_class}">{html.escape(text)}</div>', unsafe_allow_html=True)
        st.button("Zum Incident Workflow", on_click=_go_to, args=("Incidents",), key="overview-incidents")
    else:
        st.success("Kein offener Handlungsbedarf im Incident Workflow.")
    _render_setup_progress(principal, repository, settings, assets, documents)
    st.subheader("Freigabegrenzen")
    st.warning("Keine autonome Maschinensteuerung. Keine automatische Sicherheitsfreigabe.")
    if settings.release_state != "configured":
        st.info("Produktionsfreigabe bleibt offen, bis Deployment-Evidenz und Compliance-Gate bestätigt sind.")


def _render_setup_progress(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    settings: AppSettings,
    assets: tuple[AssetRecord, ...],
    documents: tuple[DocumentRecord, ...],
) -> None:
    st.subheader("Einrichtung")
    linked = sum(1 for item in assets if item.functional_location or item.equipment_number)
    ready_documents = sum(1 for item in documents if item.status == "ready")
    steps = (
        ("Assets erfasst", bool(assets), "Assets", _count_phrase(len(assets), "Anlagenobjekt", "Anlagenobjekte")),
        (
            "SAP-Referenz je Asset gepflegt",
            bool(assets) and linked == len(assets),
            "Assets",
            f"{linked} von {len(assets)} mit Technischem Platz oder Equipment",
        ),
        (
            "Herstellerunterlagen indexiert",
            ready_documents > 0,
            "Wissensbasis",
            _count_phrase(ready_documents, "Dokument bereit", "Dokumente bereit"),
        ),
        (
            "KI-Nutzerhinweis bestätigt",
            _has_ai_acceptance(principal, repository, settings),
            "Governance",
            f"Version {settings.ai_notice_version}",
        ),
        (
            "Datenschutzhinweis zur Kenntnis genommen",
            repository.has_acceptance(principal, "privacy", settings.privacy_notice_version),
            "Governance",
            f"Version {settings.privacy_notice_version}",
        ),
    )
    done = sum(1 for _, complete, _, _ in steps if complete)
    st.caption(f"{done} von {len(steps)} Schritten erledigt")
    items = "".join(
        f"""<li><span class="hd-status hd-status-{"resolved" if complete else "open"}">"""
        f"""{"Erledigt" if complete else "Offen"}</span>"""
        f"<div><strong>{html.escape(label)}</strong><small>{html.escape(detail)}</small></div></li>"
        for label, complete, _, detail in steps
    )
    st.markdown(f'<ul class="hd-checklist">{items}</ul>', unsafe_allow_html=True)
    next_step = next(((label, page) for label, complete, page, _ in steps if not complete), None)
    if next_step:
        st.button(
            f"Weiter: {next_step[0]}",
            on_click=_go_to,
            args=(next_step[1],),
            key="overview-next-setup",
            width="stretch",
        )


def _assets(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.header("Asset Register")
    st.caption("OEM-neutrale Anlagen- und Komponentenreferenz für Dokumente, Messwerte und Incidents.")
    if notice := st.session_state.pop("asset_import_notice", None):
        st.success(notice)
    assets = repository.list_assets(principal)
    if assets:
        st.dataframe(
            [
                {
                    "Asset-ID": item.asset_id,
                    "Name": item.name,
                    "Standort": item.site,
                    "Hersteller": item.manufacturer,
                    "Modell": item.model,
                    "Kritikalität": CRITICALITY_LABELS.get(item.criticality, item.criticality),
                    "Status": ASSET_STATUS_LABELS.get(item.status, item.status),
                    "Technischer Platz": item.functional_location,
                    "Equipment": item.equipment_number,
                }
                for item in assets
            ],
            width="stretch",
            hide_index=True,
        )
        unlinked = sum(1 for item in assets if not item.functional_location and not item.equipment_number)
        if unlinked:
            st.caption(
                _count_phrase(unlinked, "Asset hat", "Assets haben")
                + " noch keinen Technischen Platz oder Equipment. Ohne Referenz lassen sich Incidents"
                " in SAP PM keinem Technischen Objekt zuordnen."
            )
    else:
        st.info("Noch keine Assets erfasst. Einzelne Anlagen unten anlegen oder den Stammdatenimport nutzen.")
    if not principal.can("asset:write"):
        return
    with st.expander("Asset anlegen oder aktualisieren"):
        with st.form("asset-form"):
            asset_id = st.text_input("Asset-ID", placeholder="WERK1-PRESSE-04-HYD")
            name = st.text_input("Bezeichnung", placeholder="Hydraulikaggregat Presse 04")
            site = st.text_input("Standort", placeholder="Werk 1 · Halle 3")
            manufacturer = st.text_input("Hersteller")
            model = st.text_input("Modell / Baureihe")
            criticality = st.selectbox(
                "Kritikalität",
                tuple(CRITICALITY_LABELS),
                index=2,
                format_func=lambda option: CRITICALITY_LABELS[option],
            )
            sap_left, sap_right = st.columns(2)
            functional_location = sap_left.text_input(
                "Technischer Platz (SAP TPLNR)", max_chars=40, placeholder="1000-W1-H3-P04"
            )
            equipment_number = sap_right.text_input("Equipment (SAP EQUNR)", max_chars=18, placeholder="10004711")
            submitted = st.form_submit_button("Asset speichern", type="primary")
        if submitted:
            functional_location = functional_location.strip()
            equipment_number = equipment_number.strip()
            if not ASSET_ID_PATTERN.fullmatch(asset_id):
                st.error("Asset-ID enthält unzulässige Zeichen oder ist zu kurz.")
            elif not name.strip() or not site.strip():
                st.error("Bezeichnung und Standort sind erforderlich.")
            elif functional_location and not FUNCTIONAL_LOCATION_PATTERN.fullmatch(functional_location):
                st.error("Technischer Platz enthält unzulässige Zeichen.")
            elif equipment_number and not EQUIPMENT_PATTERN.fullmatch(equipment_number):
                st.error("Equipment darf nur Buchstaben und Ziffern enthalten (max. 18).")
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
    with st.expander("Stammdaten importieren (CSV, z. B. aus SAP PM)"):
        st.caption(
            "UTF-8-CSV mit Semikolon oder Komma. Pflichtspalten: asset_id, name, site, criticality "
            "(niedrig, mittel, hoch, sicherheitskritisch). Optional: manufacturer, model, "
            "functional_location (TPLNR), equipment_number (EQUNR). Der Import wird vollständig geprüft "
            "und nur übernommen, wenn alle Zeilen gültig sind; bestehende Asset-IDs werden aktualisiert."
        )
        st.download_button(
            "Importvorlage herunterladen",
            asset_import_template(),
            file_name="hydraulikdoc-asset-import-vorlage.csv",
            mime="text/csv",
            key="asset-import-template",
        )
        uploaded = st.file_uploader("Stammdaten-CSV", type=["csv"], key="asset-import-file")
        if uploaded and st.button("Prüfen und importieren", type="primary", key="asset-import-submit"):
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
                st.error(str(error))
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
                st.session_state.asset_import_notice = _count_phrase(len(rows), "Asset wurde", "Assets wurden") + (
                    " importiert."
                )
                st.rerun()


def _render_answer(
    answer: GroundedAnswer,
    principal: UserPrincipal,
    repository: EnterpriseRepository,
) -> None:
    st.markdown(
        '<div class="hd-notice"><strong>KI-Entwurf</strong><br>Vor jeder technischen Handlung fachlich prüfen.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(answer.text)
    st.subheader("Evidenz")
    if answer.citations:
        for index, citation in enumerate(answer.citations, start=1):
            st.markdown(
                f"**S{index}** · {citation.display_name} · Seite {citation.page} · Chunk `{citation.chunk_id[:12]}`"
            )
    else:
        st.warning("Keine Dokumentevidenz gefunden.")
    with st.expander("Provenienz und Grenzen"):
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
        st.write("Fachprüfung")
        accept, expert, reject = st.columns(3)
        if accept.button("Geprüft und akzeptiert", key=f"accept:{answer.answer_id}", width="stretch"):
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
                st.error("Für sicherheitsrelevante Analysen gilt das Vier-Augen-Prinzip.")
        if expert.button("Experte erforderlich", key=f"expert:{answer.answer_id}", width="stretch"):
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
        if reject.button("Ablehnen", key=f"reject:{answer.answer_id}", width="stretch"):
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
        st.info(f"Dokumentierter Reviewstatus: {review}")
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
            "Geprüften Nachweis exportieren",
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


def _knowledge(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.header("Wissensbasis")
    st.caption("Azure Document Intelligence, tenant-gefilterte Hybrid-Suche und quellengebundene Antworten.")
    documents = repository.list_documents(principal)
    if documents:
        for document in documents:
            columns = st.columns([5, 2, 1])
            columns[0].write(document.display_name)
            columns[1].caption(f"{document.page_count} Seiten · {document.status}")
            if principal.can("knowledge:write") and columns[2].button("Löschen", key=f"delete:{document.document_id}"):
                try:
                    _rag(settings, repository).delete_document(principal, document.document_id)
                    st.rerun()
                except Exception as error:
                    st.error(f"Löschung nicht abgeschlossen. Referenz {public_error_code(error)}")
    else:
        st.info("Für diesen Mandanten sind noch keine Dokumente indexiert.")

    if principal.can("knowledge:write"):
        uploaded = st.file_uploader("Technisches PDF hinzufügen", type=["pdf"], key="manual-upload")
        if uploaded and st.button("Validieren und indexieren", type="primary", disabled=not settings.azure_ready):
            try:
                validated = validate_pdf_upload(uploaded.name, uploaded.getvalue(), settings.max_upload_bytes)
                with st.spinner("Dokument wird sicher gespeichert, strukturiert und indexiert …"):
                    _rag(settings, repository).ingest(principal, validated)
                st.success("Dokument wurde indexiert.")
                st.rerun()
            except (InputRejected, ValueError) as error:
                st.error(str(error))
            except Exception as error:
                st.error(f"Indexierung fehlgeschlagen. Referenz {public_error_code(error)}")
        if not settings.azure_ready:
            st.caption("Upload ist gesperrt, bis alle Azure-Endpunkte und Deployments konfiguriert sind.")

    st.divider()
    st.subheader("Quellengebundene Abfrage")
    accepted = _has_ai_acceptance(principal, repository, settings)
    labels = {
        UseCase.MAINTENANCE_ASSISTANCE: "Instandhaltungsunterstützung",
        UseCase.SAFETY_RELEVANT_DIAGNOSIS: "Sicherheitsrelevante Diagnose mit Pflichtreview",
        UseCase.AUTOMATED_MACHINE_CONTROL: "Autonome Maschinensteuerung (gesperrt)",
        UseCase.EMPLOYEE_MONITORING: "Beschäftigtenüberwachung (gesperrt)",
        UseCase.OTHER: "Sonstige technische Recherche",
    }
    use_case = st.selectbox("Verwendungszweck", tuple(labels), format_func=lambda option: labels[option])
    decision = evaluate_use_case(use_case)
    if not decision.allowed:
        st.markdown(
            f'<div class="hd-notice hd-blocked">Dieser Zweck ist technisch gesperrt: {decision.reason_code}</div>',
            unsafe_allow_html=True,
        )
    question = st.text_area(
        "Technische Frage",
        max_chars=settings.max_question_chars,
        placeholder="Welcher Betriebsdruck gilt für die konfigurierte Pumpenbaureihe und welche Prüfhinweise nennt das Handbuch?",
    )
    disabled = not accepted or not settings.azure_ready or not decision.allowed
    if st.button("KI-Entwurf erzeugen", type="primary", disabled=disabled):
        try:
            with st.spinner("Hybrid Retrieval und Evidenzprüfung laufen …"):
                st.session_state.current_answer = _rag(settings, repository).ask(principal, question, use_case)
        except (InputRejected, PermissionError, AuthenticationError) as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"Abfrage fehlgeschlagen. Referenz {public_error_code(error)}")
    answer = st.session_state.get("current_answer")
    if answer:
        _render_answer(answer, principal, repository)
    if not accepted:
        st.info("Der KI-Nutzerhinweis muss im Bereich Governance bestätigt werden.")


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
        raise ValueError(f"{key} liegt außerhalb des zulässigen technischen Wertebereichs")
    return parsed


def _parse_sensor_csv(content: bytes) -> tuple[SensorReading, ...]:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("CSV überschreitet 5 MB")
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"timestamp"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV benötigt mindestens die Spalte timestamp")
    allowed = {"timestamp", "pressure_bar", "temperature_c", "flow_l_min", "particle_count", "water_content_pct"}
    if not set(reader.fieldnames).issubset(allowed):
        raise ValueError("CSV enthält nicht freigegebene Spalten")
    readings = []
    for index, row in enumerate(reader):
        if index >= 10_000:
            raise ValueError("CSV darf höchstens 10.000 Messzeilen enthalten")
        stamp = (row.get("timestamp") or "").replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(stamp)
        if timestamp.tzinfo is None:
            raise ValueError("Zeitstempel müssen eine Zeitzone enthalten")
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
        raise ValueError("CSV enthält keine Messwerte")
    return tuple(sorted(readings, key=lambda item: item.timestamp))


def _condition_monitoring(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.header("Condition Monitoring")
    st.caption(
        "Deterministische Grenzwertprüfung für Druck, Temperatur, Volumenstrom und Fluidzustand. Grenzwerte sind anlagenbezogen zu bestätigen."
    )
    assets = repository.list_assets(principal)
    asset_ids = [item.asset_id for item in assets]
    asset_id = st.selectbox("Asset", asset_ids) if asset_ids else st.text_input("Asset-ID")
    with st.expander("Betriebsgrenzen", expanded=True):
        c1, c2, c3 = st.columns(3)
        pressure_warning = c1.number_input("Druckwarnung (bar)", min_value=0.0, value=250.0)
        pressure_critical = c1.number_input("Druck-Prüfgrenze (bar)", min_value=0.0, value=300.0)
        temperature_warning = c2.number_input("Temperaturwarnung (°C)", min_value=0.0, value=70.0)
        temperature_critical = c2.number_input("Temperatur-Prüfgrenze (°C)", min_value=0.0, value=85.0)
        minimum_flow = c3.number_input("Mindestvolumenstrom (l/min)", min_value=0.0, value=5.0)
        particle_warning = c3.number_input("Partikelwarnung (#/ml)", min_value=0.0, value=1000.0)
    uploaded = st.file_uploader(
        "Messdaten-CSV",
        type=["csv"],
        help="Spalten: timestamp, pressure_bar, temperature_c, flow_l_min, particle_count, water_content_pct",
    )
    limits_confirmed = st.checkbox(
        "Ich bestätige, dass diese Betriebsgrenzen für das ausgewählte Asset fachlich freigegeben sind.",
        key="condition-limits-confirmed",
    )
    if uploaded and st.button("Messreihe prüfen", type="primary", disabled=not limits_confirmed):
        try:
            readings = _parse_sensor_csv(uploaded.getvalue())
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
            st.error(str(error))
    assessment: ConditionAssessment | None = st.session_state.get("condition_assessment")
    if not assessment:
        return
    st.metric("Zustand", assessment.severity.value.upper(), f"{assessment.sample_count} Messpunkte")
    if assessment.requires_shutdown_assessment:
        st.error("Kritische Prüfgrenze erreicht. Qualifizierte Abschalt- und Sicherheitsbewertung erforderlich.")
    if assessment.signals:
        st.dataframe(
            [
                {
                    "Code": signal.code,
                    "Stufe": signal.severity.value,
                    "Hinweis": signal.message,
                    "Wert": signal.value,
                    "Grenze": signal.threshold,
                    "Einheit": signal.unit,
                }
                for signal in assessment.signals
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.success("Keine konfigurierte Grenze wurde verletzt.")
    if principal.can("incident:write") and assessment.severity is not Severity.OK:
        if st.button("Incident aus Bewertung anlegen"):
            incident = repository.create_incident(
                principal,
                asset_id=st.session_state.get("condition_asset_id") or "unassigned",
                title=f"Condition-Monitoring {assessment.severity.value}",
                severity=assessment.severity.value,
                details="\n".join(f"{signal.code}: {signal.message}" for signal in assessment.signals),
            )
            st.success(f"Incident {incident.incident_id} wurde angelegt.")


def _fluid(principal: UserPrincipal, repository: EnterpriseRepository) -> None:
    st.header("Fluid & Service Advisor")
    st.caption("Regelbasierte Vorbewertung. ISO-/Herstellergrenzen müssen je Anlage freigegeben werden.")
    assets = repository.list_assets(principal)
    asset_id = (
        st.selectbox("Asset", [item.asset_id for item in assets], key="fluid-asset")
        if assets
        else st.text_input("Asset-ID", key="fluid-asset-text")
    )
    left, right = st.columns(2)
    particle_count = left.number_input("Partikelzahl (#/ml)", min_value=0.0, value=0.0)
    water_content = right.number_input("Wassergehalt (%)", min_value=0.0, max_value=100.0, value=0.0, step=0.01)
    particle_warning = left.number_input("Freigegebene Partikelwarngrenze (#/ml)", min_value=0.0, value=1000.0)
    water_critical = right.number_input(
        "Freigegebene Wasser-Prüfgrenze (%)", min_value=0.0, max_value=100.0, value=0.1, step=0.01
    )
    limits_confirmed = st.checkbox(
        "Ich bestätige, dass die Fluidgrenzen für dieses Asset fachlich freigegeben sind.",
        key="fluid-limits-confirmed",
    )
    if st.button("Fluidprobe bewerten", type="primary", disabled=not limits_confirmed):
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
        st.metric("Regelindikator (nicht normiert)", f"{assessment.score}/100", assessment.status)
        st.write(assessment.summary)
        for recommendation in assessment.recommendations:
            st.write(f"• {recommendation}")
        if principal.can("incident:write") and assessment.status != "OK" and st.button("Fluid-Incident anlegen"):
            incident = repository.create_incident(
                principal,
                asset_id=assessment.asset_id,
                title=assessment.summary,
                severity="critical" if assessment.status == "KRITISCH" else "warning",
                details="\n".join(assessment.recommendations),
            )
            st.success(f"Incident {incident.incident_id} wurde angelegt.")


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
            "Statuswechsel nicht durchgeführt. Der Incident wurde zwischenzeitlich geändert "
            f"oder Ihre Rolle ist dafür nicht freigegeben. Referenz {reason}"
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
    st.session_state.incident_notice = (
        f"Incident {updated.incident_id[:8]} steht jetzt auf „{INCIDENT_STATUS_LABELS[updated.status]}“."
    )
    st.rerun()


def _incident_detail(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    status_label = INCIDENT_STATUS_LABELS.get(incident.status, incident.status)
    severity_label = INCIDENT_SEVERITY_LABELS.get(incident.severity, incident.severity)
    critical = incident.severity in CRITICAL_SEVERITIES and incident.status in OPEN_INCIDENT_STATUSES
    st.markdown(
        f"""
        <div class="hd-incident{" hd-incident-critical" if critical else ""}">
          <div><strong>Status</strong><span class="hd-status hd-status-{html.escape(incident.status)}">{html.escape(status_label)}</span></div>
          <div><strong>Schwere</strong>{html.escape(severity_label)}</div>
          <div><strong>Asset</strong><code>{html.escape(incident.asset_id)}</code></div>
          <div><strong>Erstellt</strong>{incident.created_at:%d.%m.%Y %H:%M} UTC</div>
          <div><strong>Letzte Änderung</strong>{(incident.updated_at or incident.created_at):%d.%m.%Y %H:%M} UTC</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"**{incident.title}**")
    if incident.details:
        st.text(incident.details)
    else:
        st.caption("Keine Befunddetails hinterlegt.")
    if critical:
        st.warning(
            "Kritischer Befund: Abschalt-, Sicherheits- und LOTO-Bewertung durch eine qualifizierte Person dokumentieren."
        )
    _incident_analysis(principal, repository, incident)
    _incident_actions(principal, repository, incident)
    _incident_history(principal, repository, incident)


def _incident_analysis(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    st.markdown("#### Analyse und Maßnahmen (8D)")
    if incident.severity in EIGHT_D_SEVERITIES:
        st.caption(
            "8D-pflichtig: D3, D4 und D5/D6 sind vor „Als behoben melden“ zu dokumentieren, D7 vor der Abnahme. "
            f"Je Feld mindestens {INCIDENT_ANALYSIS_MIN_CHARS} Zeichen."
        )
    else:
        st.caption(
            "Vor „Als behoben melden“ ist mindestens die Abstellmaßnahme (D5/D6) zu dokumentieren. "
            "Die übrigen Felder sind empfohlen."
        )
    editable = principal.can("incident:write") and incident.status != "closed"
    if not editable:
        for field in INCIDENT_ANALYSIS_FIELDS:
            st.markdown(f"**{ANALYSIS_LABELS[field]}**")
            value = getattr(incident, field)
            if value:
                st.text(value)
            else:
                st.caption("Nicht dokumentiert.")
        return
    st.caption(
        "Ursachen technisch und prozessbezogen beschreiben. Keine Personennamen, Schuldzuweisungen oder "
        "Leistungsbewertungen eintragen; HydraulikDoc ist kein Werkzeug zur Beschäftigtenbewertung."
    )
    version = (incident.updated_at or incident.created_at).timestamp()
    with st.form(f"incident-analysis:{incident.incident_id}"):
        values = {
            field: st.text_area(
                ANALYSIS_LABELS[field],
                value=getattr(incident, field),
                max_chars=INCIDENT_ANALYSIS_MAX_CHARS,
                height=90,
                key=f"analysis:{incident.incident_id}:{field}:{version}",
                help=ANALYSIS_HELP[field],
            )
            for field in INCIDENT_ANALYSIS_FIELDS
        }
        submitted = st.form_submit_button("Analyse speichern")
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
            "Analyse nicht gespeichert. Der Incident wurde zwischenzeitlich geändert oder ist abgeschlossen; "
            f"bitte Ansicht neu laden. Referenz {reason}"
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
    st.session_state.incident_notice = f"Analyse für Incident {incident.incident_id[:8]} wurde gespeichert."
    st.rerun()


def _incident_actions(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    next_statuses = INCIDENT_TRANSITIONS.get(incident.status, ())
    if not next_statuses:
        st.caption("Abgeschlossen. Weitere Statuswechsel und Änderungen der Analyse sind nicht vorgesehen.")
        return
    if not principal.can("incident:write"):
        st.caption("Ihre Rolle darf Incidents einsehen, aber keinen Status ändern.")
        return
    st.write("Nächster Schritt")
    columns = st.columns(len(next_statuses))
    for column, target in zip(columns, next_statuses, strict=True):
        label = INCIDENT_ACTION_LABELS.get(target, INCIDENT_STATUS_LABELS[target])
        if target == "in_progress" and incident.status == "resolved":
            label = "Wieder öffnen"
        missing = missing_analysis_fields(incident, target)
        role_allowed = target != "closed" or principal.can(INCIDENT_CLOSE_PERMISSION)
        allowed = role_allowed and not missing
        if column.button(
            label,
            key=f"incident:{incident.incident_id}:{target}",
            type="primary" if target == next_statuses[0] and allowed else "secondary",
            disabled=not allowed,
            width="stretch",
        ):
            _transition_incident(principal, repository, incident, target)
        if not role_allowed:
            column.caption("Abnahme erfordert die Rolle Supervisor oder Admin.")
        elif missing:
            column.caption("Zuerst dokumentieren: " + ", ".join(ANALYSIS_LABELS[field] for field in missing) + ".")


def _incident_history(principal: UserPrincipal, repository: EnterpriseRepository, incident: IncidentRecord) -> None:
    st.markdown("#### Verlauf")
    events = repository.list_incident_events(principal, incident.incident_id)
    if not events:
        st.caption("Für diesen Incident liegt kein Verlauf vor (vor Einführung der Verlaufserfassung angelegt).")
        return
    entries = []
    for event in events:
        if event.event_type == "created":
            text = "Angelegt"
        elif event.event_type == "status_changed":
            previous = INCIDENT_STATUS_LABELS.get(event.previous_status or "", event.previous_status or "–")
            current = INCIDENT_STATUS_LABELS.get(event.new_status or "", event.new_status or "–")
            text = f"Status {previous} → {current}"
        else:
            text = "Analyse und Maßnahmen aktualisiert"
        actor = ROLE_LABELS.get(event.actor_role, event.actor_role) + (" (Sie)" if event.is_own else "")
        entries.append(
            f"<li><time>{event.occurred_at:%d.%m.%Y %H:%M} UTC</time>"
            f"<span>{html.escape(text)}</span><small>{html.escape(actor)}</small></li>"
        )
    st.markdown(f'<ol class="hd-timeline">{"".join(entries)}</ol>', unsafe_allow_html=True)
    st.caption("Personen werden nur mit Rolle angezeigt; die pseudonymisierte Kennung bleibt im Auditnachweis.")


def _render_sap_handover(
    principal: UserPrincipal,
    repository: EnterpriseRepository,
    incidents: list[IncidentRecord],
) -> None:
    with st.expander("Übergabe an SAP PM (Instandhaltungsmeldung)"):
        st.caption(
            "Erzeugt eine CSV-Übergabedatei für die gefilterten Incidents mit den SAP-PM-Feldern QMART, QMTXT "
            "(40 Zeichen), PRIOK, TPLNR und EQUNR sowie HydraulikDoc-Referenzen. Es besteht keine Live-Verbindung "
            "zu SAP; Feldmapping und Prioritätsschema sind vor dem Upload durch Ihr SAP-Team zu validieren."
        )
        notification_type = (
            st.text_input("Meldungsart (QMART)", value="M2", max_chars=2, key="sap-notification-type").strip().upper()
        )
        try:
            export = build_sap_notifications(incidents, repository.list_assets(principal), notification_type)
        except ValueError as error:
            st.error(str(error))
            return
        if export.missing_reference:
            st.warning(
                _count_phrase(len(export.missing_reference), "Incident hat", "Incidents haben")
                + " kein Asset mit Technischem Platz oder Equipment. Die Meldung ist dann keinem Technischen"
                " Objekt zugeordnet; Referenz im Asset Register ergänzen."
            )
        exported = st.download_button(
            _count_phrase(len(export.rows), "Meldung", "Meldungen") + " als SAP-PM-Übergabedatei herunterladen",
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
    st.header("Incident Workflow")
    st.caption(
        "Technische Auffälligkeiten werden nachvollziehbar erfasst; Meldepflichten bleiben organisatorisch zu bewerten."
    )
    if notice := st.session_state.pop("incident_notice", None):
        st.success(notice)
    incidents = repository.list_incidents(principal)
    if not incidents:
        st.info(
            "Keine Incidents vorhanden. Incidents entstehen aus einer Bewertung im Condition Monitoring oder im Fluid-Bereich."
        )
        return

    counts = {status: sum(1 for item in incidents if item.status == status) for status in INCIDENT_STATUSES}
    st.markdown(
        '<div class="hd-state hd-state-wide">'
        + "".join(
            f"<div><strong>{INCIDENT_STATUS_LABELS[status]}</strong>{counts[status]}</div>"
            for status in INCIDENT_STATUSES
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    status_filter, severity_filter, asset_filter = st.columns(3)
    selected_statuses = status_filter.multiselect(
        "Status",
        INCIDENT_STATUSES,
        default=DEFAULT_INCIDENT_FILTER,
        format_func=lambda option: INCIDENT_STATUS_LABELS[option],
        key="incident-status-filter",
    )
    severities = sorted(
        {item.severity for item in incidents},
        key=lambda option: tuple(INCIDENT_SEVERITY_LABELS).index(option) if option in INCIDENT_SEVERITY_LABELS else 99,
    )
    selected_severities = severity_filter.multiselect(
        "Schwere",
        severities,
        format_func=lambda option: INCIDENT_SEVERITY_LABELS.get(option, option),
        placeholder="Alle",
        key="incident-severity-filter",
    )
    asset_ids = sorted({item.asset_id for item in incidents})
    selected_asset = asset_filter.selectbox(
        "Asset", ("", *asset_ids), format_func=lambda option: option or "Alle", key="incident-asset-filter"
    )
    visible = [
        item
        for item in incidents
        if (not selected_statuses or item.status in selected_statuses)
        and (not selected_severities or item.severity in selected_severities)
        and (not selected_asset or item.asset_id == selected_asset)
    ]
    if not visible:
        st.info("Kein Incident entspricht den gewählten Filtern.")
        return
    st.dataframe(
        [
            {
                "ID": item.incident_id[:8],
                "Asset": item.asset_id,
                "Titel": item.title,
                "Schwere": INCIDENT_SEVERITY_LABELS.get(item.severity, item.severity),
                "Status": INCIDENT_STATUS_LABELS.get(item.status, item.status),
                "Erstellt": item.created_at.strftime("%d.%m.%Y %H:%M"),
                "Geändert": (item.updated_at or item.created_at).strftime("%d.%m.%Y %H:%M"),
            }
            for item in visible
        ],
        width="stretch",
        hide_index=True,
    )
    if principal.can("incident:write"):
        _render_sap_handover(principal, repository, visible)
    st.subheader("Incident bearbeiten")
    by_id = {item.incident_id: item for item in visible}
    selected_id = st.selectbox(
        "Incident",
        tuple(by_id),
        format_func=lambda option: _incident_option_label(by_id[option]),
        key="incident-selected",
    )
    _incident_detail(principal, repository, by_id[selected_id])


def _governance(principal: UserPrincipal, repository: EnterpriseRepository, settings: AppSettings) -> None:
    st.header("Governance & Trust")
    st.caption("Technisch nachweisbare Kontrollen und klar benannte externe Freigaben.")
    _render_ai_acceptance(principal, repository, settings)
    _render_privacy_notice(principal, repository, settings)
    st.divider()
    st.subheader("Kontrollstatus")
    rows = [
        (
            "Identität",
            "verifiziert" if principal.authentication_method == "entra_proxy" else "lokale Entwicklung",
            "Entra App-Rolle oder lokaler Argon2id-Adapter",
        ),
        (
            "Tenant-Isolation",
            "aktiv" if settings.persistence_backend.value == "postgres" else "Entwicklungsmodus",
            "PostgreSQL FORCE RLS und Azure Search Filter",
        ),
        (
            "KI-Pfad",
            "konfiguriert" if settings.azure_ready else "gesperrt",
            "Azure OpenAI, Document Intelligence, AI Search",
        ),
        (
            "Region",
            "konfiguriert" if settings.azure_region else "offen",
            settings.azure_region or "Deployment-Nachweis fehlt",
        ),
        (
            "Deployment-Evidenz",
            "verknüpft" if settings.deployment_evidence_id else "offen",
            settings.deployment_evidence_id or "Kein Evidence-ID gesetzt",
        ),
        (
            "AI-Evaluation",
            "verknüpft" if settings.ai_evaluation_evidence_id else "offen",
            settings.ai_evaluation_evidence_id or "Kein freigegebener Eval-Report",
        ),
        (
            "Löschkonzept",
            "freigegeben" if settings.retention_policy_approved else "gesperrt",
            settings.retention_policy_id or "Kein genehmigter Policy-Nachweis",
        ),
        ("Produktionsfreigabe", settings.release_state, "Technisches Gate, keine rechtliche Zertifizierung"),
    ]
    st.dataframe([{"Kontrolle": a, "Status": b, "Evidenz": c} for a, b, c in rows], width="stretch", hide_index=True)
    st.subheader("Technische Nutzungsgrenzen")
    st.write("• Autonome Maschinensteuerung ist gesperrt.")
    st.write("• Beschäftigtenüberwachung ist gesperrt.")
    st.write("• Sicherheitsrelevante Diagnose erfordert qualifizierten Review.")
    st.write("• Nur akzeptierte Reviews können als Nachweis exportiert werden.")
    st.info(
        "DPA/AVV, DSFA/TIA, Betriebsrat, Rechtsgrundlagen, Löschfristen und regulatorische Einordnung müssen instanzbezogen freigegeben und regelmäßig revalidiert werden."
    )
    st.divider()
    st.subheader("Datenschutz-Self-Service")
    st.caption(
        "Der Export enthält nur Datensätze, die dem aktuell verifizierten Entra-Subjekt zugeordnet sind. Lösch- und Korrekturanträge werden zur Identitäts- und Ausnahmeprüfung eingereiht."
    )
    if st.button("Meine Daten für Export zusammenstellen"):
        st.session_state.subject_export = repository.subject_export(principal)
        repository.emit_audit(
            principal,
            action="privacy.subject_export.generated",
            outcome=AuditOutcome.SUCCESS,
            metadata={"request_type": "export"},
        )
    if export := st.session_state.get("subject_export"):
        st.download_button(
            "Personenbezogenen Export herunterladen",
            json.dumps(export, default=str, ensure_ascii=False, indent=2),
            file_name="hydraulikdoc-meine-daten.json",
            mime="application/json",
        )
    request_labels = {
        "access": "Auskunft",
        "rectification": "Berichtigung",
        "restriction": "Einschränkung",
        "erasure": "Löschung",
        "objection": "Widerspruch",
    }
    request_type = st.selectbox(
        "Antragstyp",
        tuple(request_labels),
        format_func=lambda option: request_labels[option],
        key="privacy-request-type",
    )
    if st.button("Datenschutzantrag einreichen"):
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
            st.success(f"Antrag {request.request_id} wurde nachweisbar eingereiht.")
        except Exception:
            st.error("Ein gleichartiger offener Antrag besteht bereits oder konnte nicht angelegt werden.")
    requests = repository.list_privacy_requests(principal)
    if requests:
        st.dataframe(
            [
                {
                    "ID": item.request_id,
                    "Typ": request_labels.get(item.request_type, item.request_type),
                    "Status": item.status,
                    "Eingang": item.requested_at.isoformat(),
                    "Interne Zielfrist": item.due_at.isoformat(),
                }
                for item in requests
            ],
            width="stretch",
            hide_index=True,
        )


def _system(principal: UserPrincipal, settings: AppSettings) -> None:
    st.header("System Evidence")
    st.caption("Keine Secrets und keine Rohinhalte werden in dieser Ansicht ausgegeben.")
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
        st.error("Der Runtime-Start wurde wegen einer unsicheren Konfiguration blockiert.")
        st.code(str(error))
        st.stop()
    principal = _principal(settings)
    if not principal or not _enforce_session(principal, settings):
        st.stop()
    try:
        repository = get_repository(settings)
    except Exception as error:
        st.error(f"Persistenz nicht verfügbar. Referenz {public_error_code(error)}")
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
            _condition_monitoring(principal, repository)
        elif selected == "Fluid":
            _fluid(principal, repository)
        elif selected == "Incidents":
            _incidents(principal, repository)
        elif selected == "Governance":
            _governance(principal, repository, settings)
        else:
            _system(principal, settings)
    except AuthenticationError:
        st.error("Diese Funktion ist für Ihre App-Rolle nicht freigegeben.")
    except Exception as error:
        st.error(f"Vorgang abgebrochen. Referenz {public_error_code(error)}")
