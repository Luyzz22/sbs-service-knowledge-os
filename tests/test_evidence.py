"""Evidence for audits: control tests re-performed from stored records, the auditor role and the bundle."""

import dataclasses
import hashlib
import importlib.util
import io
import json
import re
import unittest
import uuid
import zipfile
from base64 import b64encode
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from compliance.audit import AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal, principal_from_entra_header
from hydraulikdoc.config import AppSettings
from hydraulikdoc.demo import seed_demo_tenant
from hydraulikdoc.evidence import (
    CONTROLS,
    EVIDENCE_ROW_LIMIT,
    FINDING_LABELS,
    RESOURCE_LABELS,
    TIME_TOLERANCE,
    ControlKind,
    ControlResult,
    ControlStatus,
    EvidenceReport,
    evaluate_controls,
    window,
)
from hydraulikdoc.evidence_bundle import (
    BUNDLE_SCHEMA,
    CONTROL_CSV_COLUMNS,
    MANIFEST_NAME,
    build_bundle,
    verify_bundle,
)
from hydraulikdoc.evidence_data import (
    RETENTION_GRACE,
    AnswerEvidence,
    AuditTrailEntry,
    DeniedAttempts,
    DocumentEvidence,
    DocumentStep,
    EvidenceSnapshot,
    HoldEvidence,
    IncidentEvidence,
    IncidentStep,
    LimitEvidence,
    NoticeEvidence,
    PrivacyEvidence,
    RetentionEvidence,
    ReviewStep,
)
from hydraulikdoc.governance import AIProvenance, GroundedAnswer, ReviewStatus, SourceCitation, UseCase
from hydraulikdoc.operating_limits import LimitValues
from hydraulikdoc.repository import INCIDENT_ANALYSIS_FIELDS, AuditChainReport, InMemoryRepository
from hydraulikdoc.security import ValidatedUpload
from hydraulikdoc.ui import AUDITOR_PAGES, EVIDENCE_PAGE, NAV_PAGES, nav_pages

ROOT = Path(__file__).resolve().parents[1]
TENANT = "tenant-a"
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
SINCE = NOW - timedelta(days=30)
INTACT = AuditChainReport(12, True, 1, 12, "ab" * 32, False)
SECRET = "evidence-test-secret-" + "x" * 20
ALL_FIELDS = frozenset(INCIDENT_ANALYSIS_FIELDS)


def _principal(subject: str, role: str, tenant: str = TENANT) -> UserPrincipal:
    return UserPrincipal(subject, tenant, subject.title(), role, permissions=ROLE_PERMISSIONS[role])


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _snapshot(**datasets: object) -> EvidenceSnapshot:
    return EvidenceSnapshot(since=SINCE, until=NOW, **datasets)  # type: ignore[arg-type]


def _result(snapshot: EvidenceSnapshot, control_id: str, chain: AuditChainReport | None = INTACT) -> ControlResult:
    report = evaluate_controls(snapshot, chain)
    return next(item for item in report.results if item.definition.control_id == control_id)


def _codes(result: ControlResult) -> list[str]:
    return [item.code for item in result.findings]


def _doc(
    document_id: str = "doc-1",
    *,
    uploader: str = "psn_author",
    releaser: str = "psn_approver",
    uploaded: float = 20,
    released: float | None = 19,
    withdrawn: float | None = None,
    status: str = "ready",
    review_due: float = -200,
    legacy: bool = False,
    deleted_at: datetime | None = None,
) -> DocumentEvidence:
    steps = [] if legacy else [DocumentStep("uploaded", uploader, "technician", _ago(uploaded))]
    if released is not None:
        steps.append(DocumentStep("released", releaser, "supervisor", _ago(released)))
    in_force = released is not None or legacy
    return DocumentEvidence(
        document_id,
        uploader,
        status,
        "withdrawn" if withdrawn is not None else "released" if in_force else "draft",
        _ago(uploaded),
        _ago(released) if released is not None else None,
        _ago(review_due) if released is not None else None,
        _ago(withdrawn) if withdrawn is not None else None,
        deleted_at,
        tuple(steps),
    )


def _review(
    status: str, *, reviewer: str = "psn_reviewer", role: str = "supervisor", days: float = 4, reason: str | None = None
) -> ReviewStep:
    return ReviewStep(status, reason, reviewer, role, _ago(days))


def _answer(
    answer_id: str = "ans-1",
    *,
    asker: str = "psn_asker",
    risk: str = "limited",
    status: str = "draft",
    asked: float = 5,
    documents: tuple[str, ...] = ("doc-1",),
    reviews: tuple[ReviewStep, ...] = (),
) -> AnswerEvidence:
    return AnswerEvidence(answer_id, asker, risk, status, _ago(asked), documents, reviews)


def _incident(
    incident_id: str = "inc-1",
    *,
    severity: str = "p1",
    status: str = "closed",
    documented: frozenset[str] = ALL_FIELDS,
    closed_by: str | None = "supervisor",
    closed: float = 3,
) -> IncidentEvidence:
    steps = [IncidentStep("created", None, "new", "psn_reporter", "technician", _ago(10))]
    if closed_by is not None:
        steps.append(IncidentStep("status_changed", "resolved", "closed", "psn_closer", closed_by, _ago(closed)))
    return IncidentEvidence(incident_id, severity, status, _ago(10), documented, tuple(steps))


def _limit(
    limit_set_id: str = "lim-1",
    *,
    status: str = "released",
    proposer: str = "psn_tech",
    decider: str | None = "psn_sup",
    decided: float | None = 6,
    source: str | None = "doc-1",
) -> LimitEvidence:
    return LimitEvidence(
        limit_set_id, "PRESSE-04", 1, status, proposer, decider, _ago(8), _ago(decided) if decided else None, source
    )


class RoleTests(unittest.TestCase):
    def test_auditor_reads_evidence_and_nothing_else(self) -> None:
        auditor = _principal("aud", "auditor")
        self.assertEqual(ROLE_PERMISSIONS["auditor"], frozenset({"evidence:read", "audit:verify"}))
        for permission in ("knowledge:read", "asset:read", "review:write", "incident:write", "document:release"):
            self.assertFalse(auditor.can(permission), permission)
        self.assertEqual(nav_pages(auditor), AUDITOR_PAGES)
        self.assertEqual(set(AUDITOR_PAGES) - set(NAV_PAGES), set())
        for page in ("Leitstand", "Assets", "Wissensbasis", "Incidents", "Kennzahlen"):
            self.assertNotIn(page, nav_pages(auditor))

    def test_evidence_page_needs_its_own_permission(self) -> None:
        self.assertEqual(nav_pages(_principal("adm", "admin")), NAV_PAGES)
        for role in ("viewer", "technician", "supervisor"):
            pages = nav_pages(_principal("user", role))
            self.assertNotIn(EVIDENCE_PAGE, pages)
            self.assertEqual(pages, tuple(page for page in NAV_PAGES if page != EVIDENCE_PAGE))

    def test_entra_role_maps_to_auditor_and_an_operational_role_wins(self) -> None:
        def principal(*roles: str) -> UserPrincipal:
            claims = [{"typ": "oid", "val": "object-id"}, {"typ": "name", "val": "Erika Muster"}]
            claims += [{"typ": "roles", "val": role} for role in roles]
            payload = {"role_typ": "roles", "claims": claims}
            return principal_from_entra_header(b64encode(json.dumps(payload).encode()).decode(), "fallback")

        self.assertEqual(principal("HydraulikDoc.Auditor").role, "auditor")
        self.assertEqual(principal("HydraulikDoc.Auditor", "HydraulikDoc.Viewer").role, "auditor")
        self.assertEqual(principal("HydraulikDoc.Auditor", "HydraulikDoc.Technician").role, "technician")

    def test_entra_manifest_declares_every_role_once(self) -> None:
        manifest = json.loads((ROOT / "infra" / "azure" / "entra-app-roles.json").read_text(encoding="utf-8"))
        values = [item["value"] for item in manifest]
        self.assertEqual(sorted(value.split(".")[1].lower() for value in values), sorted(ROLE_PERMISSIONS))
        self.assertEqual(len({item["id"] for item in manifest}), len(manifest))
        for item in manifest:
            uuid.UUID(item["id"])


class ControlCatalogueTests(unittest.TestCase):
    def test_controls_are_unique_referenced_and_described(self) -> None:
        identifiers = [definition.control_id for definition, _ in CONTROLS]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for definition, _ in CONTROLS:
            with self.subTest(definition.control_id):
                self.assertTrue(definition.references)
                self.assertTrue(str(definition.title) and str(definition.objective) and str(definition.method))
                self.assertNotIn("{", str(definition.method) + str(definition.title))

    def test_every_finding_code_and_resource_has_a_label(self) -> None:
        source = (ROOT / "hydraulikdoc" / "evidence.py").read_text(encoding="utf-8")
        used = re.findall(r'ControlFinding\(\s*"([a-z_]+)",[^"]*"([A-Z_]+)"', source)
        self.assertGreater(len(used), 15)
        self.assertEqual({resource for resource, _ in used} - set(RESOURCE_LABELS), set())
        self.assertEqual({code for _, code in used} - set(FINDING_LABELS), set())

    def test_runbook_lists_exactly_the_implemented_controls(self) -> None:
        runbook = (ROOT / "docs" / "runbooks" / "audit-evidence.md").read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| ([A-Z]{2,4}-\d{2}) \| [^|]+ \| (erzwungen|überwacht) \|", runbook, re.MULTILINE))
        kinds = {ControlKind.ENFORCED: "erzwungen", ControlKind.MONITORED: "überwacht"}
        self.assertEqual(rows, {definition.control_id: kinds[definition.kind] for definition, _ in CONTROLS})
        for definition, _ in CONTROLS:
            self.assertIn(f"| {definition.control_id} | {definition.title} |", runbook)

    def test_empty_period_is_not_reported_as_effective(self) -> None:
        report = evaluate_controls(_snapshot(), AuditChainReport(0, True, None, None, None, False))
        self.assertEqual({item.status for item in report.results}, {ControlStatus.NOT_EXERCISED})
        self.assertEqual(report.count(ControlStatus.EFFECTIVE), 0)


class DocumentControlTests(unittest.TestCase):
    def test_release_by_the_uploader_is_a_deviation(self) -> None:
        clean = _result(_snapshot(documents=(_doc(),)), "DOC-01")
        self.assertEqual((clean.status, clean.population), (ControlStatus.EFFECTIVE, 1))
        bypassed = _result(_snapshot(documents=(_doc(), _doc("doc-2", releaser="psn_author"))), "DOC-01")
        self.assertEqual((bypassed.status, bypassed.population), (ControlStatus.DEVIATION, 2))
        self.assertEqual(
            [(item.resource_type, item.resource_id, item.code) for item in bypassed.findings],
            [("document", "doc-2", "SAME_PERSON")],
        )

    def test_release_outside_the_period_is_not_counted(self) -> None:
        old = _result(_snapshot(documents=(_doc(uploaded=50, released=45, releaser="psn_author"),)), "DOC-01")
        self.assertEqual((old.status, old.population), (ControlStatus.NOT_EXERCISED, 0))

    def test_answer_citing_a_draft_or_withdrawn_document_is_a_deviation(self) -> None:
        documents = (
            _doc("released"),
            _doc("draft", released=None),
            _doc("withdrawn", withdrawn=8),
            _doc("released-later", released=2),
        )
        answers = (
            _answer("ok", documents=("released",)),
            _answer("draft", documents=("released", "draft")),
            _answer("withdrawn", documents=("withdrawn",)),
            _answer("before-withdrawal", asked=9, documents=("withdrawn",)),
            _answer("too-early", documents=("released-later",)),
            _answer("no-source", documents=()),
            _answer("old", asked=40, documents=("draft",)),
        )
        result = _result(_snapshot(documents=documents, answers=answers), "DOC-02")
        self.assertEqual(result.population, 5)
        self.assertEqual({item.resource_id for item in result.findings}, {"draft", "withdrawn", "too-early"})
        self.assertEqual(set(_codes(result)), {"SOURCE_NOT_RELEASED"})

    def test_tolerance_covers_a_query_that_was_already_running(self) -> None:
        minutes = TIME_TOLERANCE / timedelta(days=1)
        document = _doc(withdrawn=5)
        inside = _answer("inside", asked=5 - minutes / 2)
        outside = _answer("outside", asked=5 - minutes * 2)
        result = _result(_snapshot(documents=(document,), answers=(inside, outside)), "DOC-02")
        self.assertEqual([item.resource_id for item in result.findings], ["outside"])

    def test_legacy_purged_and_undated_documents_are_handled_without_false_findings(self) -> None:
        documents = (
            # In use before document control, formally released only two days ago.
            _doc("legacy", legacy=True, uploaded=300, released=2),
            _doc("legacy-open", legacy=True, uploaded=300, released=None),
            _doc("undated", status="deleted"),
        )
        answers = (
            _answer("legacy", documents=("legacy",)),
            _answer("legacy-open", documents=("legacy-open",)),
            _answer("undated", documents=("undated",)),
            _answer("purged", documents=("gone",)),
        )
        result = _result(_snapshot(documents=documents, answers=answers), "DOC-02")
        self.assertEqual((result.status, result.population, result.untested), (ControlStatus.EFFECTIVE, 4, 2))

    def test_documents_in_use_need_a_recorded_release_and_a_current_review(self) -> None:
        documents = (
            _doc("ok"),
            _doc("overdue", review_due=1),
            _doc("legacy", legacy=True, released=None),
            _doc("draft", released=None),
            _doc("withdrawn", withdrawn=3, review_due=1),
            _doc("failed", status="failed", review_due=1),
        )
        result = _result(_snapshot(documents=documents), "DOC-03")
        self.assertEqual((result.status, result.population), (ControlStatus.OPEN_ITEMS, 3))
        self.assertEqual(
            sorted((item.resource_id, item.code) for item in result.findings),
            [("legacy", "NO_RECORDED_RELEASE"), ("overdue", "REVIEW_OVERDUE")],
        )


class AnswerControlTests(unittest.TestCase):
    def test_accepting_the_own_safety_relevant_answer_is_a_deviation(self) -> None:
        answers = (
            _answer("second", risk="heightened", status="accepted", reviews=(_review("accepted"),)),
            _answer("self", risk="heightened", status="accepted", reviews=(_review("accepted", reviewer="psn_asker"),)),
            # Ordinary answers may be accepted by the person who asked.
            _answer("limited", status="accepted", reviews=(_review("accepted", reviewer="psn_asker"),)),
            _answer(
                "rejected", risk="heightened", status="rejected", reviews=(_review("rejected", reviewer="psn_asker"),)
            ),
        )
        result = _result(_snapshot(answers=answers), "AI-01")
        self.assertEqual((result.status, result.population), (ControlStatus.DEVIATION, 2))
        self.assertEqual([(item.resource_id, item.code) for item in result.findings], [("self", "SAME_PERSON")])

    def test_decisions_are_single_reasoned_and_made_by_the_right_role(self) -> None:
        answers = (
            _answer("ok", status="rejected", reviews=(_review("rejected", reason="incomplete"),)),
            _answer(
                "escalated-ok",
                status="accepted",
                reviews=(_review("needs_expert", role="technician", days=6), _review("accepted", days=5)),
            ),
            _answer("no-reason", status="rejected", reviews=(_review("rejected", reason="TECHNICAL_REJECTION"),)),
            _answer(
                "twice",
                status="accepted",
                reviews=(_review("rejected", reason="incomplete", days=6), _review("accepted", days=5)),
            ),
            _answer(
                "not-expert",
                status="accepted",
                reviews=(
                    _review("needs_expert", role="technician", days=6),
                    _review("accepted", role="technician", days=5),
                ),
            ),
            _answer("mismatch", status="accepted", reviews=(_review("rejected", reason="incomplete"),)),
            _answer("without-review", status="accepted"),
            _answer("legacy", status="rejected", reviews=(_review("rejected", role="", reason="TECHNICAL_REJECTION"),)),
            _answer("open", reviews=(_review("needs_expert", role="technician"),)),
            _answer("old", status="accepted", asked=50, reviews=(_review("accepted", days=45, role="technician"),)),
        )
        result = _result(_snapshot(answers=answers), "AI-02")
        self.assertEqual((result.status, result.population, result.untested), (ControlStatus.DEVIATION, 7, 1))
        self.assertEqual(
            sorted((item.resource_id, item.code) for item in result.findings),
            [
                ("mismatch", "STATUS_MISMATCH"),
                ("no-reason", "REASON_MISSING"),
                ("not-expert", "NOT_EXPERT"),
                ("twice", "DECIDED_TWICE"),
                ("without-review", "DECISION_WITHOUT_REVIEW"),
            ],
        )

    def test_open_second_reviews_are_measured_against_the_target(self) -> None:
        answers = (
            _answer("fresh", risk="heightened", asked=1),
            _answer("late", risk="heightened", asked=4),
            # Waiting since before the period: still open, still counted.
            _answer("escalated", status="needs_expert", asked=45),
            _answer("own-draft", asked=20),
            _answer("done", risk="heightened", status="accepted", asked=20),
        )
        result = _result(_snapshot(answers=answers), "AI-03")
        self.assertEqual((result.status, result.population), (ControlStatus.OPEN_ITEMS, 3))
        self.assertEqual(sorted(item.resource_id for item in result.findings), ["escalated", "late"])

    def test_notice_has_to_be_confirmed_before_the_first_query(self) -> None:
        answers = (
            _answer("a-first", asker="psn_a", asked=9),
            _answer("a-second", asker="psn_a", asked=2),
            _answer("b-first", asker="psn_b", asked=8),
            _answer("c-first", asker="psn_c", asked=7),
            _answer("d-old", asker="psn_d", asked=60),
        )
        notices = (
            NoticeEvidence("psn_a", "ai_literacy", "2026-08-14", _ago(20)),
            NoticeEvidence("psn_a", "ai_literacy", "2026-11-01", _ago(1)),
            # Confirmed only after the first answer.
            NoticeEvidence("psn_b", "ai_literacy", "2026-08-14", _ago(3)),
            NoticeEvidence("psn_c", "privacy", "2026-08-14", _ago(30)),
        )
        result = _result(_snapshot(answers=answers, notices=notices), "AI-04")
        self.assertEqual((result.status, result.population), (ControlStatus.DEVIATION, 3))
        self.assertEqual(
            sorted((item.resource_type, item.resource_id, item.code) for item in result.findings),
            [("analysis", "b-first", "NOTICE_MISSING"), ("analysis", "c-first", "NOTICE_MISSING")],
        )


class WorkflowControlTests(unittest.TestCase):
    def test_limits_released_by_the_proposer_are_a_deviation(self) -> None:
        limits = (
            _limit("ok"),
            _limit("superseded", status="superseded"),
            _limit("self", decider="psn_tech"),
            _limit("no-decider", decider=None),
            # The proposer may reject their own proposal; an open draft has no decision.
            _limit("rejected", status="rejected", decider="psn_tech"),
            _limit("draft", status="draft", decider=None, decided=None),
            _limit("old", decider="psn_tech", decided=60),
        )
        result = _result(_snapshot(limits=limits), "LIM-01")
        self.assertEqual((result.status, result.population), (ControlStatus.DEVIATION, 4))
        self.assertEqual(
            sorted((item.resource_id, item.code) for item in result.findings),
            [("no-decider", "DECIDER_MISSING"), ("self", "SAME_PERSON")],
        )

    def test_limits_in_force_need_a_released_source(self) -> None:
        documents = (_doc("doc-1"), _doc("doc-withdrawn", withdrawn=2))
        limits = (
            _limit("ok"),
            _limit("withdrawn", source="doc-withdrawn"),
            _limit("purged", source="doc-gone"),
            _limit("text-only", source=None),
            _limit("superseded", status="superseded", source="doc-withdrawn"),
        )
        result = _result(_snapshot(documents=documents, limits=limits), "LIM-02")
        self.assertEqual((result.status, result.population), (ControlStatus.OPEN_ITEMS, 3))
        self.assertEqual(sorted(item.resource_id for item in result.findings), ["purged", "withdrawn"])

    def test_incident_sign_off_needs_the_role_and_the_analysis(self) -> None:
        incidents = (
            _incident("ok"),
            _incident("technician", closed_by="technician"),
            _incident("no-check", documented=ALL_FIELDS - {"effectiveness_check"}),
            # Below 8D severity only the corrective action is mandatory.
            _incident("p3", severity="p3", documented=frozenset({"corrective_action"})),
            _incident("p3-empty", severity="p3", documented=frozenset()),
            _incident("no-history", closed_by=None),
            _incident("open", status="in_progress", closed_by=None),
            _incident("old", closed_by="technician", closed=40),
        )
        result = _result(_snapshot(incidents=incidents), "INC-01")
        self.assertEqual((result.status, result.population, result.untested), (ControlStatus.DEVIATION, 5, 1))
        self.assertEqual(
            sorted((item.resource_id, item.code) for item in result.findings),
            [
                ("no-check", "ANALYSIS_INCOMPLETE"),
                ("p3-empty", "ANALYSIS_INCOMPLETE"),
                ("technician", "ROLE_NOT_AUTHORISED"),
            ],
        )

    def test_privacy_requests_are_measured_against_their_deadline(self) -> None:
        requests = (
            PrivacyEvidence("open", "in_review", _ago(10), _ago(-18), None),
            PrivacyEvidence("overdue", "submitted", _ago(40), _ago(12), None),
            PrivacyEvidence("late", "completed", _ago(35), _ago(7), _ago(5)),
            PrivacyEvidence("on-time", "denied", _ago(20), _ago(-8), _ago(15)),
            PrivacyEvidence("old", "completed", _ago(90), _ago(62), _ago(50)),
        )
        result = _result(_snapshot(privacy_requests=requests), "PRIV-01")
        self.assertEqual((result.status, result.population), (ControlStatus.OPEN_ITEMS, 4))
        self.assertEqual(
            sorted((item.resource_id, item.code) for item in result.findings),
            [("late", "DECIDED_LATE"), ("overdue", "DEADLINE_OVERDUE")],
        )

    def test_overdue_records_are_reported_unless_a_hold_covers_the_class(self) -> None:
        retention = (
            RetentionEvidence("ai_interaction", 4, _ago(6)),
            RetentionEvidence("incident", 2, _ago(9)),
            RetentionEvidence("audit_event", 1, _ago(3)),
            RetentionEvidence("uploaded_content", 0, None),
        )
        holds = (
            HoldEvidence("active", ("incident",), _ago(-30), _ago(20), None),
            HoldEvidence("released", ("audit_event",), _ago(-30), _ago(20), _ago(2)),
            HoldEvidence("overdue", ("uploaded_content",), _ago(1), _ago(200), None),
        )
        snapshot = _snapshot(retention=retention, legal_holds=holds)
        kept = _result(snapshot, "RET-01")
        self.assertEqual((kept.status, kept.population), (ControlStatus.OPEN_ITEMS, 4))
        self.assertEqual(
            sorted((item.resource_type, item.resource_id, item.code) for item in kept.findings),
            [
                ("record_class", "ai_interaction", "RETENTION_OVERDUE"),
                ("record_class", "audit_event", "RETENTION_OVERDUE"),
            ],
        )
        reviews = _result(snapshot, "RET-02")
        self.assertEqual((reviews.status, reviews.population), (ControlStatus.OPEN_ITEMS, 2))
        self.assertEqual([item.resource_id for item in reviews.findings], ["overdue"])

    def test_audit_chain_result_is_a_control(self) -> None:
        intact = _result(_snapshot(), "LOG-01")
        self.assertEqual((intact.status, intact.population), (ControlStatus.EFFECTIVE, 12))
        broken = AuditChainReport(7, False, 1, 7, "cd" * 32, False, broken_sequence=8, reason="HASH_MISMATCH")
        result = _result(_snapshot(), "LOG-01", broken)
        self.assertEqual(result.status, ControlStatus.DEVIATION)
        self.assertEqual(
            [(item.resource_type, item.resource_id, item.code) for item in result.findings],
            [("audit_event", "8", "HASH_MISMATCH")],
        )
        unverified = _result(_snapshot(), "LOG-01", None)
        self.assertEqual((unverified.status, _codes(unverified)), (ControlStatus.DEVIATION, ["NOT_VERIFIED"]))


class ReportTests(unittest.TestCase):
    def test_refused_attempts_are_attributed_to_their_control(self) -> None:
        denied = (
            DeniedAttempts("knowledge.document.release_denied", "FOUR_EYES_RELEASE_REQUIRED", 3),
            DeniedAttempts("knowledge.document.release_denied", "DOCUMENT_NOT_INDEXED", 5),
            DeniedAttempts("analysis.review.denied", "FOUR_EYES_REVIEW_REQUIRED", 2),
            DeniedAttempts("analysis.review.denied", "REVIEW_ALREADY_DECIDED", 1),
            DeniedAttempts("incident.status.denied", "INCIDENT_CLOSE_REQUIRED", 4),
        )
        report = evaluate_controls(_snapshot(denied=denied), INTACT)
        prevented = {item.definition.control_id: item.prevented for item in report.results if item.prevented}
        self.assertEqual(prevented, {"DOC-01": 3, "AI-01": 2, "AI-02": 1, "INC-01": 4})
        self.assertEqual(report.denied, denied)

    def test_truncated_dataset_marks_only_the_controls_that_read_it(self) -> None:
        report = evaluate_controls(_snapshot(truncated=frozenset({"answers"})), INTACT)
        incomplete = {item.definition.control_id for item in report.results if item.incomplete}
        self.assertEqual(incomplete, {"DOC-02", "AI-01", "AI-02", "AI-03", "AI-04"})

    def test_finding_kind_follows_the_control_kind(self) -> None:
        snapshot = _snapshot(documents=(_doc(releaser="psn_author", review_due=1),))
        report = evaluate_controls(snapshot, INTACT)
        by_id = {item.definition.control_id: item for item in report.results}
        self.assertIs(by_id["DOC-01"].definition.kind, ControlKind.ENFORCED)
        self.assertIs(by_id["DOC-01"].status, ControlStatus.DEVIATION)
        self.assertIs(by_id["DOC-03"].status, ControlStatus.OPEN_ITEMS)
        self.assertEqual([item.definition.control_id for item in report.deviations], ["DOC-01"])

    def test_no_finding_refers_to_a_person(self) -> None:
        snapshot = _snapshot(
            documents=(_doc(releaser="psn_author"), _doc("draft", released=None)),
            answers=(
                _answer(
                    "self", risk="heightened", status="accepted", reviews=(_review("accepted", reviewer="psn_asker"),)
                ),
                _answer("draft", documents=("draft",)),
            ),
            limits=(_limit(decider="psn_tech"),),
            incidents=(_incident(closed_by="technician"),),
        )
        report = evaluate_controls(snapshot, None)
        findings = [finding for item in report.results for finding in item.findings]
        self.assertGreater(len(findings), 5)
        for finding in findings:
            self.assertNotIn("psn_", finding.resource_id)
            self.assertNotIn(finding.resource_type, {"person", "actor", "user"})
        names = {field.name for field in dataclasses.fields(findings[0])}
        self.assertFalse({name for name in names if "token" in name or "actor" in name})


class RepositoryEvidenceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.technician = _principal("tech", "technician")
        self.colleague = _principal("tech-2", "technician")
        self.supervisor = _principal("sup", "supervisor")
        self.auditor = _principal("aud", "auditor")
        self.admin = _principal("adm", "admin")

    def _report(self, principal: UserPrincipal | None = None, limit: int = EVIDENCE_ROW_LIMIT) -> EvidenceReport:
        viewer = principal or self.auditor
        since, until = window(datetime.now(UTC), 30)
        snapshot = self.repository.evidence_snapshot(viewer, since=since, until=until, limit=limit)
        return evaluate_controls(snapshot, self.repository.verify_audit_chain(viewer))

    def _control(self, control_id: str, **options: object) -> ControlResult:
        report = self._report(**options)  # type: ignore[arg-type]
        return next(item for item in report.results if item.definition.control_id == control_id)

    def _released_document(self, name: str = "Handbuch.pdf") -> str:
        upload = ValidatedUpload(str(uuid.uuid4()), name, uuid.uuid4().hex * 2, b"", "application/pdf")
        record = self.repository.register_document(self.technician, upload)
        self.repository.mark_document_indexed(self.technician, record.document_id, 12)
        self.repository.release_document(
            self.supervisor, record.document_id, review_due_at=datetime.now(UTC) + timedelta(days=90)
        )
        return record.document_id

    def _ask(self, document_id: str, use_case: UseCase = UseCase.MAINTENANCE_ASSISTANCE) -> GroundedAnswer:
        answer = GroundedAnswer.create(
            text="Der Betriebsdruck beträgt 210 bar [S1].",
            citations=(SourceCitation(document_id, "Handbuch.pdf", 4, "chunk-4", 0.8, "1"),),
            provenance=AIProvenance("azure-openai", "chat", "2026-08-01", "germanywestcentral"),
            use_case=use_case,
        )
        self.repository.record_answer(self.technician, "Welcher Betriebsdruck gilt?", answer)
        return answer


class RepositoryEvidenceTests(RepositoryEvidenceCase):
    def test_evidence_needs_the_permission_and_stays_in_the_tenant(self) -> None:
        self._released_document()
        since, until = window(datetime.now(UTC), 30)
        for principal in (self.technician, self.supervisor, _principal("viewer", "viewer")):
            with self.assertRaisesRegex(PermissionError, "EVIDENCE_READ_REQUIRED"):
                self.repository.evidence_snapshot(principal, since=since, until=until, limit=10)
            with self.assertRaisesRegex(PermissionError, "EVIDENCE_READ_REQUIRED"):
                self.repository.list_audit_events(principal, since=since, until=until, limit=10)
        self.assertEqual(
            len(self.repository.evidence_snapshot(self.admin, since=since, until=until, limit=10).documents), 1
        )
        outsider = _principal("aud", "auditor", "tenant-b")
        foreign = self.repository.evidence_snapshot(outsider, since=since, until=until, limit=10)
        self.assertEqual((foreign.documents, foreign.answers, foreign.denied), ((), (), ()))

    def test_workflow_through_the_application_passes_every_enforced_control(self) -> None:
        document_id = self._released_document()
        self.repository.record_acceptance(self.technician, "ai_literacy", "2026-08-14", "d" * 64)
        safety = self._ask(document_id, UseCase.SAFETY_RELEVANT_DIAGNOSIS)
        ordinary = self._ask(document_id)
        self.repository.record_review(self.colleague, safety.answer_id, ReviewStatus.ACCEPTED)
        self.repository.record_review(self.technician, ordinary.answer_id, ReviewStatus.REJECTED, "incomplete")
        self.repository.upsert_asset(
            self.supervisor,
            asset_id="PRESSE-04",
            name="Presse 04",
            site="Werk 1",
            manufacturer="",
            model="",
            criticality="high",
        )
        proposal = self.repository.propose_operating_limits(
            self.technician,
            "PRESSE-04",
            LimitValues(),
            source_reference="BA-HA-250 Kapitel 4.2",
            source_document_id=document_id,
            source_page=4,
        )
        self.repository.release_operating_limits(self.supervisor, proposal.limit_set_id)
        incident = self.repository.create_incident(
            self.technician, asset_id="PRESSE-04", title="Druckabfall", severity="p1", details="Druck fällt ab"
        )
        incident = self.repository.transition_incident(
            self.technician, incident.incident_id, expected="new", target="in_progress"
        )
        incident = self.repository.update_incident_analysis(
            self.technician,
            incident.incident_id,
            expected_updated_at=incident.updated_at or incident.created_at,
            analysis={name: "Dokumentierte Analyse mit Messreihe" for name in INCIDENT_ANALYSIS_FIELDS},
        )
        self.repository.transition_incident(
            self.technician, incident.incident_id, expected="in_progress", target="resolved"
        )
        self.repository.transition_incident(self.supervisor, incident.incident_id, expected="resolved", target="closed")
        self.repository.create_privacy_request(self.technician, "access")
        self.repository.create_legal_hold(
            self.admin,
            case_reference="AZ-2026-17",
            reason_code="litigation",
            record_classes=("incident",),
            review_at=datetime.now(UTC) + timedelta(days=60),
        )
        report = self._report()
        statuses = {item.definition.control_id: (item.status, item.population) for item in report.results}
        self.assertEqual(
            statuses,
            {
                "DOC-01": (ControlStatus.EFFECTIVE, 1),
                "DOC-02": (ControlStatus.EFFECTIVE, 2),
                "DOC-03": (ControlStatus.EFFECTIVE, 1),
                "AI-01": (ControlStatus.EFFECTIVE, 1),
                "AI-02": (ControlStatus.EFFECTIVE, 2),
                "AI-03": (ControlStatus.NOT_EXERCISED, 0),
                "AI-04": (ControlStatus.EFFECTIVE, 1),
                "LIM-01": (ControlStatus.EFFECTIVE, 1),
                "LIM-02": (ControlStatus.EFFECTIVE, 1),
                "INC-01": (ControlStatus.EFFECTIVE, 1),
                "PRIV-01": (ControlStatus.EFFECTIVE, 1),
                "RET-01": (ControlStatus.EFFECTIVE, 6),
                "RET-02": (ControlStatus.EFFECTIVE, 1),
                # The repository workflow alone writes no audit event; the interface does that.
                "LOG-01": (ControlStatus.NOT_EXERCISED, 0),
            },
        )
        self.assertEqual(report.deviations, ())

    def test_a_change_behind_the_application_shows_up_as_a_deviation(self) -> None:
        document_id = self._released_document()
        self.assertIs(self._control("DOC-01").status, ControlStatus.EFFECTIVE)
        # What a direct write to the database would do: make the releasing person the uploader.
        releaser = next(actor for _, actor, event in self.repository._document_events if event.event_type == "released")
        self.repository._uploaders[(TENANT, document_id)] = releaser
        result = self._control("DOC-01")
        self.assertIs(result.status, ControlStatus.DEVIATION)
        self.assertEqual([(item.resource_id, item.code) for item in result.findings], [(document_id, "SAME_PERSON")])

        answer = self._ask(document_id)
        self.repository._reviews[(TENANT, answer.answer_id)] = ReviewStatus.ACCEPTED
        decisions = self._control("AI-02")
        self.assertEqual(
            [(item.resource_id, item.code) for item in decisions.findings],
            [(answer.answer_id, "DECISION_WITHOUT_REVIEW")],
        )
        # The asking person never confirmed the AI notice.
        self.assertEqual(_codes(self._control("AI-04")), ["NOTICE_MISSING"])

    def test_withdrawal_after_an_answer_is_no_finding_but_a_later_citation_would_be(self) -> None:
        document_id = self._released_document()
        answer = self._ask(document_id)
        self.repository.withdraw_document(self.supervisor, document_id, "incorrect")
        self.assertIs(self._control("DOC-02").status, ControlStatus.EFFECTIVE)
        late = dataclasses.replace(
            answer,
            answer_id=str(uuid.uuid4()),
            provenance=dataclasses.replace(answer.provenance, generated_at=datetime.now(UTC) + timedelta(minutes=30)),
        )
        self.repository.record_answer(self.technician, "Frage", late)
        since, _ = window(datetime.now(UTC), 30)
        until = datetime.now(UTC) + timedelta(hours=1)
        snapshot = self.repository.evidence_snapshot(self.auditor, since=since, until=until, limit=100)
        result = next(
            item for item in evaluate_controls(snapshot, None).results if item.definition.control_id == "DOC-02"
        )
        self.assertEqual([item.resource_id for item in result.findings], [late.answer_id])

    def test_refused_attempts_come_from_the_audit_trail_of_the_tenant(self) -> None:
        self._released_document()
        for principal in (self.technician, self.technician, _principal("tech", "technician", "tenant-b")):
            self.repository.emit_audit(
                principal,
                action="knowledge.document.release_denied",
                outcome=AuditOutcome.DENIED,
                resource_type="document",
                resource_id="doc",
                metadata={"reason_code": "FOUR_EYES_RELEASE_REQUIRED"},
            )
        result = self._control("DOC-01")
        self.assertEqual((result.status, result.prevented), (ControlStatus.EFFECTIVE, 2))

    def test_row_limit_marks_the_evidence_as_incomplete(self) -> None:
        self._released_document("A.pdf")
        self._released_document("B.pdf")
        report = self._report(limit=1)
        self.assertIn("documents", report.truncated)
        by_id = {item.definition.control_id: item for item in report.results}
        self.assertTrue(by_id["DOC-01"].incomplete and by_id["LIM-02"].incomplete)
        self.assertFalse(by_id["INC-01"].incomplete)

    def test_retention_evidence_counts_records_past_the_grace_period(self) -> None:
        document_id = self._released_document()
        self._ask(document_id)
        self.assertIs(self._control("RET-01").status, ControlStatus.EFFECTIVE)
        since, until = window(datetime.now(UTC) + timedelta(days=200), 30)
        snapshot = self.repository.evidence_snapshot(self.auditor, since=since, until=until, limit=100)
        overdue = {item.record_class: item.overdue for item in snapshot.retention}
        # AI interactions are kept 90 days, uploaded content 365 days.
        self.assertEqual((overdue["ai_interaction"], overdue["uploaded_content"]), (1, 0))
        self.assertLess(snapshot.retention[0].oldest_due or until, until - RETENTION_GRACE)

    def test_audit_trail_is_filtered_newest_first_and_per_tenant(self) -> None:
        actions = (
            ("knowledge.document.released", AuditOutcome.SUCCESS),
            ("knowledge.document.release_denied", AuditOutcome.DENIED),
            ("incident.status.changed", AuditOutcome.SUCCESS),
        )
        for action, outcome in actions:
            self.repository.emit_audit(
                self.supervisor, action=action, outcome=outcome, resource_type="x", resource_id="1"
            )
        self.repository.emit_audit(
            _principal("sup", "supervisor", "tenant-b"),
            action="knowledge.document.released",
            outcome=AuditOutcome.SUCCESS,
        )
        since, until = window(datetime.now(UTC), 1)

        def listed(**filters: object) -> list[str]:
            events = self.repository.list_audit_events(self.auditor, since=since, until=until, limit=10, **filters)  # type: ignore[arg-type]
            return [item.action for item in events]

        self.assertEqual(listed(), [action for action, _ in reversed(actions)])
        self.assertEqual(listed(outcome="denied"), ["knowledge.document.release_denied"])
        self.assertEqual(len(listed(action_prefix="knowledge.")), 2)
        self.assertEqual(listed(action_prefix="incident.", outcome="denied"), [])
        self.assertEqual(len(self.repository.list_audit_events(self.auditor, since=since, until=until, limit=2)), 2)
        earlier = self.repository.list_audit_events(
            self.auditor, since=since - timedelta(days=9), until=since, limit=10
        )
        self.assertEqual(earlier, ())
        entry = self.repository.list_audit_events(self.auditor, since=since, until=until, limit=1)[0]
        self.assertEqual((entry.sequence, len(entry.event_hash)), (3, 64))


class DemoEvidenceTests(unittest.TestCase):
    def test_seeded_demo_shows_effective_controls_and_the_open_reviews(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        repository = InMemoryRepository(settings)
        seed_demo_tenant(_principal("sup", "supervisor"), repository)
        auditor = _principal("aud", "auditor")
        since, until = window(datetime.now(UTC), 90)
        snapshot = repository.evidence_snapshot(auditor, since=since, until=until, limit=EVIDENCE_ROW_LIMIT)
        report = evaluate_controls(snapshot, repository.verify_audit_chain(auditor))
        self.assertEqual(report.deviations, ())
        by_id = {item.definition.control_id: item for item in report.results}
        self.assertEqual(by_id["AI-03"].status, ControlStatus.OPEN_ITEMS)
        self.assertEqual(_codes(by_id["AI-03"]), ["REVIEW_OVERDUE"])
        for control_id in ("DOC-01", "DOC-02", "DOC-03", "AI-02", "AI-04", "LIM-01", "INC-01", "RET-01", "LOG-01"):
            self.assertIs(by_id[control_id].status, ControlStatus.EFFECTIVE, control_id)
        self.assertEqual(by_id["DOC-02"].population, 7)


def _entry(sequence: int, action: str, actor: str, resource: str, outcome: str = "success") -> AuditTrailEntry:
    return AuditTrailEntry(
        sequence,
        str(uuid.UUID(int=sequence)),
        _ago(sequence),
        action,
        outcome,
        f"psn_v1_{actor * 8}",
        "document",
        f"psn_v1_{resource * 8}",
        {"reason_code": "=FORMULA", "source_count": sequence},
        f"{sequence:064x}",
    )


def _files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class BundleTests(unittest.TestCase):
    def setUp(self) -> None:
        snapshot = _snapshot(
            documents=(_doc(), _doc("doc-2", releaser="psn_author")),
            denied=(DeniedAttempts("knowledge.document.release_denied", "FOUR_EYES_RELEASE_REQUIRED", 2),),
        )
        self.report = evaluate_controls(snapshot, INTACT)
        self.events = (
            _entry(3, "knowledge.document.released", "b", "d"),
            _entry(1, "knowledge.document.indexed", "a", "d"),
            _entry(2, "knowledge.document.release_denied", "a", "d", "denied"),
        )

    def _bundle(self, **options: object):  # type: ignore[no-untyped-def]
        settings: dict[str, object] = {
            "report": self.report,
            "events": self.events,
            "events_truncated": False,
            "configuration": {"application_version": "5.0.0", "release_state": "demo"},
            "tenant_id": TENANT,
            "language": "de",
            "secret": SECRET,
            "bundle_id": "11111111-1111-4111-8111-111111111111",
            "generated_at": NOW,
        }
        return build_bundle(**(settings | options))  # type: ignore[arg-type]

    def test_bundle_verifies_and_is_reproducible(self) -> None:
        bundle = self._bundle()
        self.assertEqual(bundle.content, self._bundle().content)
        self.assertTrue(bundle.file_name.endswith("-11111111.zip"))
        files = _files(bundle.content)
        self.assertEqual(
            set(files),
            {"README.txt", "audit-events.jsonl", "configuration.json", "controls.csv", "controls.json", MANIFEST_NAME},
        )
        manifest = json.loads(files[MANIFEST_NAME])
        self.assertEqual((manifest["schema"], manifest["tenant_id"]), (BUNDLE_SCHEMA, TENANT))
        self.assertEqual(manifest["summary"]["deviation"], 1)
        self.assertEqual(manifest["audit_chain"]["head_hash"], INTACT.head_hash)
        self.assertEqual(manifest["audit_events"], {"count": 3, "truncated": False})
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256(files[item["name"]]).hexdigest(), item["sha256"])
        self.assertEqual(verify_bundle(bundle.content).problems, ())
        self.assertEqual(verify_bundle(bundle.content).seal, "not_checked")
        sealed = verify_bundle(bundle.content, SECRET)
        self.assertEqual((sealed.intact, sealed.seal), (True, "valid"))
        foreign = verify_bundle(bundle.content, "another-instance-secret-" + "y" * 20)
        self.assertEqual((foreign.intact, foreign.seal, foreign.problems), (False, "invalid", ("SEAL_INVALID",)))

    def test_changed_added_and_missing_files_are_detected(self) -> None:
        files = _files(self._bundle().content)
        changed = files | {"controls.json": files["controls.json"].replace(b'"deviation"', b'"effective"')}
        self.assertEqual(verify_bundle(_archive(changed), SECRET).problems, ("HASH_MISMATCH:controls.json",))
        added = files | {"extra.txt": b"x"}
        self.assertEqual(verify_bundle(_archive(added)).problems, ("UNLISTED_FILE:extra.txt",))
        missing = {name: content for name, content in files.items() if name != "audit-events.jsonl"}
        self.assertEqual(verify_bundle(_archive(missing)).problems, ("FILE_MISSING:audit-events.jsonl",))
        manifest = json.loads(files[MANIFEST_NAME])
        manifest["summary"]["deviation"] = 0
        edited = files | {MANIFEST_NAME: json.dumps(manifest).encode()}
        self.assertEqual(verify_bundle(_archive(edited)).intact, True)
        self.assertEqual(verify_bundle(_archive(edited), SECRET).problems, ("SEAL_INVALID",))
        self.assertEqual(verify_bundle(b"not a zip").problems, ("NOT_A_BUNDLE",))
        self.assertEqual(verify_bundle(_archive({"a.txt": b"x"})).problems, ("MANIFEST_MISSING",))
        self.assertEqual(verify_bundle(_archive({MANIFEST_NAME: b"{}"})).problems, ("MANIFEST_INVALID",))

    def test_persons_appear_only_as_an_alias_of_this_bundle(self) -> None:
        first = _files(self._bundle().content)
        second = _files(self._bundle(bundle_id="22222222-2222-4222-8222-222222222222").content)
        for files in (first, second):
            for name, content in files.items():
                self.assertNotIn(b"psn_v1_", content, name)
        events = [json.loads(line) for line in first["audit-events.jsonl"].decode().splitlines()]
        self.assertEqual([item["sequence"] for item in events], [1, 2, 3])
        # The same person keeps one alias inside a bundle, so segregation of duties can be re-performed.
        self.assertEqual(events[0]["actor"], events[1]["actor"])
        self.assertNotEqual(events[0]["actor"], events[2]["actor"])
        self.assertEqual(len({item["resource"] for item in events}), 1)
        self.assertRegex(events[0]["actor"], r"^akteur-[0-9a-f]{12}$")
        other = [json.loads(line) for line in second["audit-events.jsonl"].decode().splitlines()]
        self.assertNotEqual(events[0]["actor"], other[0]["actor"])
        self.assertEqual(events[0]["event_hash"], other[0]["event_hash"])

    def test_controls_are_exported_in_the_chosen_language_and_spreadsheet_safe(self) -> None:
        german = _files(self._bundle().content)
        english = _files(self._bundle(language="en").content)
        controls = {item["control_id"]: item for item in json.loads(german["controls.json"])}
        self.assertEqual(controls["DOC-01"]["status"], "deviation")
        self.assertEqual(controls["DOC-01"]["status_label"], "Abweichung")
        self.assertEqual(controls["DOC-01"]["prevented_attempts"], 2)
        self.assertEqual(
            [(item["resource_id"], item["code"]) for item in controls["DOC-01"]["findings"]], [("doc-2", "SAME_PERSON")]
        )
        translated = {item["control_id"]: item for item in json.loads(english["controls.json"])}
        self.assertEqual(translated["DOC-01"]["status_label"], "Deviation")
        self.assertEqual(translated["DOC-01"]["title"], "Documents are released by a second person")
        self.assertIn("evidence bundle", english["README.txt"].decode())
        rows = german["controls.csv"].decode("utf-8-sig").splitlines()
        self.assertEqual(rows[0].split(";"), list(CONTROL_CSV_COLUMNS))
        self.assertEqual(len(rows), len(CONTROLS) + 1)

    def test_verification_script_reports_the_result(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "verify_bundle_script", ROOT / "ops/scripts/verify-evidence-bundle.py"
        )
        assert spec is not None and spec.loader is not None
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        bundle = self._bundle()
        with mock.patch("pathlib.Path.read_bytes", return_value=bundle.content):
            for environment, expected in (({"AUDIT_HMAC_KEY": SECRET}, (0, "valid")), ({}, (0, "not_checked"))):
                output = io.StringIO()
                with mock.patch.dict("os.environ", environment, clear=True), redirect_stdout(output):
                    code = script.main(["bundle.zip"])
                result = json.loads(output.getvalue())
                self.assertEqual((code, result["seal"]), expected)
                self.assertEqual(result["bundle_id"], bundle.bundle_id)
        with mock.patch("pathlib.Path.read_bytes", return_value=b"broken"), redirect_stdout(io.StringIO()):
            self.assertEqual(script.main(["bundle.zip"]), 1)


if __name__ == "__main__":
    unittest.main()
