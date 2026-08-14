import hashlib
import json
import unittest
from base64 import b64encode
from datetime import UTC, datetime

from compliance.audit import AuditEvent, AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal, principal_from_entra_header
from hydraulikdoc.azure_ai import ParsedPage, chunk_pages, has_valid_source_citations
from hydraulikdoc.condition_monitoring import (
    OperatingEnvelope,
    SensorReading,
    Severity,
    assess_condition,
)
from hydraulikdoc.config import AppSettings, ConfigurationError
from hydraulikdoc.evaluation import EvaluationCase, EvaluationCaseResult, create_report, evaluate_case
from hydraulikdoc.governance import (
    AIProvenance,
    GroundedAnswer,
    ReviewStatus,
    RiskClass,
    SourceCitation,
    UseCase,
    evaluate_use_case,
)
from hydraulikdoc.repository import InMemoryRepository, _audit_chain_key, _event_hash
from hydraulikdoc.security import InputRejected, odata_literal, validate_pdf_upload


def _production_environment() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "AUTH_MODE": "entra_proxy",
        "AI_BACKEND": "azure",
        "PERSISTENCE_BACKEND": "postgres",
        "DEFAULT_TENANT_ID": "tenant-fallback",
        "PUBLIC_BASE_URL": "https://knowledge.example.de",
        "DATABASE_URL": "postgresql://app:secret@database.example:5432/app?sslmode=require",
        "AUDIT_HMAC_KEY": "x" * 32,
        "AZURE_REGION": "germanywestcentral",
        "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "gpt-4.1",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "text-embedding-3-small",
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://example.cognitiveservices.azure.com",
        "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
        "AZURE_BLOB_ENDPOINT": "https://example.blob.core.windows.net",
        "AZURE_USE_MANAGED_IDENTITY": "true",
        "COMPLIANCE_RELEASE_APPROVED": "true",
        "DEPLOYMENT_EVIDENCE_ID": "REL-2026-08-001",
        "AI_EVALUATION_EVIDENCE_ID": "AI-EVAL-2026-08-001",
        "AZURE_OPENAI_MODEL_SNAPSHOT": "gpt-4.1-2026-04-14",
        "RETENTION_POLICY_APPROVED": "true",
        "RETENTION_POLICY_ID": "RET-2026-08-001",
        "REQUIRE_HUMAN_REVIEW": "true",
        "AUTO_MIGRATE_DATABASE": "false",
    }


class ConfigurationTests(unittest.TestCase):
    def test_production_profile_accepts_managed_identity_and_german_region(self) -> None:
        settings = AppSettings.from_environment(_production_environment())
        self.assertTrue(settings.is_production)
        self.assertTrue(settings.azure_ready)
        self.assertEqual(settings.release_state, "configured")

    def test_production_profile_fails_closed_for_local_auth(self) -> None:
        environment = _production_environment()
        environment["AUTH_MODE"] = "local"
        with self.assertRaisesRegex(ConfigurationError, "AUTH_MODE=entra_proxy"):
            AppSettings.from_environment(environment)

    def test_production_profile_rejects_static_azure_keys(self) -> None:
        environment = _production_environment()
        environment["AZURE_SEARCH_KEY"] = "not-allowed"
        with self.assertRaisesRegex(ConfigurationError, "forbids static Azure service keys"):
            AppSettings.from_environment(environment)

    def test_production_profile_rejects_runtime_migrations(self) -> None:
        environment = _production_environment()
        environment["AUTO_MIGRATE_DATABASE"] = "true"
        with self.assertRaisesRegex(ConfigurationError, "forbids AUTO_MIGRATE_DATABASE"):
            AppSettings.from_environment(environment)

    def test_production_profile_requires_ai_evaluation_evidence(self) -> None:
        environment = _production_environment()
        environment["AI_EVALUATION_EVIDENCE_ID"] = ""
        with self.assertRaisesRegex(ConfigurationError, "AI_EVALUATION_EVIDENCE_ID"):
            AppSettings.from_environment(environment)


class IdentityTests(unittest.TestCase):
    def test_entra_principal_requires_and_maps_application_role(self) -> None:
        payload = {
            "role_typ": "roles",
            "claims": [
                {"typ": "oid", "val": "user-object-id"},
                {"typ": "tid", "val": "customer-tenant-id"},
                {"typ": "name", "val": "Erika Muster"},
                {"typ": "roles", "val": "HydraulikDoc.Technician"},
            ],
        }
        encoded = b64encode(json.dumps(payload).encode()).decode()
        principal = principal_from_entra_header(encoded, "fallback")
        self.assertEqual(principal.tenant_id, "customer-tenant-id")
        self.assertEqual(principal.role, "technician")
        self.assertTrue(principal.can("diagnostic:run"))
        self.assertFalse(principal.can("asset:write"))


class AuditChainTests(unittest.TestCase):
    def test_chain_hash_is_stable_and_key_authenticated(self) -> None:
        event = AuditEvent(
            action="security.control.checked",
            outcome=AuditOutcome.SUCCESS,
            event_id="00000000-0000-0000-0000-000000000001",
            occurred_at=datetime(2026, 8, 15, tzinfo=UTC),
        )
        first_key = _audit_chain_key("a" * 32)
        second_key = _audit_chain_key("b" * 32)

        first = _event_hash(first_key, None, event)

        self.assertEqual(first, _event_hash(first_key, None, event))
        self.assertNotEqual(first, _event_hash(second_key, None, event))
        self.assertEqual(len(first), 64)


class InputSecurityTests(unittest.TestCase):
    def test_pdf_magic_bytes_and_active_content_are_checked(self) -> None:
        valid = validate_pdf_upload("../Betriebshandbuch ä.pdf", b"%PDF-1.7\nbody", 1024)
        self.assertEqual(valid.display_name, "Betriebshandbuch a.pdf")
        with self.assertRaises(InputRejected):
            validate_pdf_upload("fake.pdf", b"not a pdf", 1024)
        with self.assertRaises(InputRejected):
            validate_pdf_upload("active.pdf", b"%PDF-1.7 /JavaScript", 1024)

    def test_odata_literals_escape_quotes(self) -> None:
        self.assertEqual(odata_literal("tenant' or true"), "tenant'' or true")


class GovernanceTests(unittest.TestCase):
    def test_autonomous_control_is_blocked(self) -> None:
        decision = evaluate_use_case(UseCase.AUTOMATED_MACHINE_CONTROL)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk_class, RiskClass.PROHIBITED_BY_PRODUCT_POLICY)

    def test_safety_diagnosis_requires_human_review(self) -> None:
        decision = evaluate_use_case(UseCase.SAFETY_RELEVANT_DIAGNOSIS)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_human_review)

    def test_safety_diagnosis_requires_a_second_person_for_acceptance(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "test"})
        repository = InMemoryRepository(settings)
        author = UserPrincipal(
            "author",
            "tenant-a",
            "Author",
            "technician",
            permissions=ROLE_PERMISSIONS["technician"],
        )
        reviewer = UserPrincipal(
            "reviewer",
            "tenant-a",
            "Reviewer",
            "technician",
            permissions=ROLE_PERMISSIONS["technician"],
        )
        answer = GroundedAnswer.create(
            text="Prüfung erforderlich [S1].",
            citations=(),
            provenance=AIProvenance("test", "test", "test", "test"),
            use_case=UseCase.SAFETY_RELEVANT_DIAGNOSIS,
        )
        repository.record_answer(author, "Frage", answer)
        with self.assertRaisesRegex(PermissionError, "FOUR_EYES"):
            repository.record_review(author, answer.answer_id, ReviewStatus.ACCEPTED)
        repository.record_review(reviewer, answer.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(repository.answer_review_status(author, answer.answer_id), ReviewStatus.ACCEPTED)


class RetrievalTests(unittest.TestCase):
    def test_chunk_ids_are_stable_and_tenant_scoped(self) -> None:
        pages = (ParsedPage(1, "# Druckgrenzen\n" + "A" * 6000),)
        first = chunk_pages(
            pages,
            tenant_id="tenant-a",
            document_id="document-a",
            display_name="manual.pdf",
        )
        second = chunk_pages(
            pages,
            tenant_id="tenant-b",
            document_id="document-a",
            display_name="manual.pdf",
        )
        self.assertGreater(len(first), 1)
        self.assertNotEqual(first[0][0], second[0][0])

    def test_model_output_requires_in_range_source_markers(self) -> None:
        self.assertTrue(has_valid_source_citations("Grenzwert 250 bar [S1].", 2))
        self.assertFalse(has_valid_source_citations("Grenzwert 250 bar.", 2))
        self.assertFalse(has_valid_source_citations("Grenzwert 250 bar [S9].", 2))
        self.assertTrue(has_valid_source_citations("Keine Evidenz gefunden.", 0))


class EvaluationTests(unittest.TestCase):
    def test_gold_set_result_scores_grounding_and_drops_raw_content(self) -> None:
        case = EvaluationCase.from_mapping(
            {
                "case_id": "grounding-pressure-001",
                "tenant_id": "tenant-a",
                "category": "grounding",
                "question": "Geheime Goldset-Frage zum Betriebsdruck?",
                "use_case": "maintenance_assistance",
                "expected_terms": ["250 bar"],
                "forbidden_terms": ["300 bar"],
                "allowed_document_ids": ["manual-a"],
            }
        )
        answer = GroundedAnswer.create(
            text="Der Betriebsdruck beträgt 250 bar [S1].",
            citations=(SourceCitation("manual-a", "Handbuch", 4, "chunk-1"),),
            provenance=AIProvenance("azure", "chat", "snapshot", "germanywestcentral"),
            use_case=case.use_case,
        )
        result = evaluate_case(case, answer)
        self.assertTrue(result.passed)
        serialized = json.dumps(result.__dict__)
        self.assertNotIn(case.question, serialized)
        self.assertNotIn(answer.text, serialized)

    def test_release_report_requires_all_critical_categories(self) -> None:
        results = tuple(
            EvaluationCaseResult(
                case_id=f"critical-{index:03d}",
                category=category,
                passed=True,
                citation_gate=True,
                expected_terms_gate=True,
                forbidden_terms_gate=True,
                tenant_document_gate=True,
                oversight_gate=True,
                denial_gate=category == "policy",
            )
            for index, category in enumerate(("policy", "prompt_injection", "tenant_isolation", "safety"), start=1)
        )
        report = create_report(
            results=results,
            dataset_version="synthetic-v1",
            dataset_sha256=hashlib.sha256(b"synthetic").hexdigest(),
            model_snapshot="gpt-4.1-test",
            region="germanywestcentral",
            minimum_cases=4,
            now=datetime(2026, 8, 15, tzinfo=UTC),
        )
        self.assertTrue(report.release_eligible)
        self.assertTrue(report.evidence_id.startswith("AI-EVAL-20260815-"))


class ConditionMonitoringTests(unittest.TestCase):
    def test_critical_pressure_is_aggregated_and_requires_assessment(self) -> None:
        readings = (
            SensorReading(datetime(2026, 8, 14, 10, tzinfo=UTC), pressure_bar=310),
            SensorReading(datetime(2026, 8, 14, 11, tzinfo=UTC), pressure_bar=320),
        )
        result = assess_condition(readings, OperatingEnvelope())
        self.assertEqual(result.severity, Severity.CRITICAL)
        self.assertTrue(result.requires_shutdown_assessment)
        self.assertEqual(len(result.signals), 1)
        self.assertEqual(result.signals[0].value, 320)

    def test_unordered_series_is_rejected(self) -> None:
        readings = (
            SensorReading(datetime(2026, 8, 14, 11, tzinfo=UTC)),
            SensorReading(datetime(2026, 8, 14, 10, tzinfo=UTC)),
        )
        with self.assertRaisesRegex(ValueError, "ordered"):
            assess_condition(readings, OperatingEnvelope())

    def test_non_finite_sensor_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            SensorReading(datetime(2026, 8, 14, 10, tzinfo=UTC), pressure_bar=float("nan"))


if __name__ == "__main__":
    unittest.main()
