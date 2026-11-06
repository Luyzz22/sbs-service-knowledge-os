import unittest

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.azure_ai import has_valid_source_citations
from hydraulikdoc.condition_monitoring import OperatingEnvelope, Severity, assess_condition
from hydraulikdoc.config import AppSettings, ConfigurationError
from hydraulikdoc.demo import (
    DEMO_LIMITATION,
    DEMO_PROVIDER,
    DemoRAGService,
    demo_seed_blockers,
    demo_sensor_csv,
    seed_demo_tenant,
)
from hydraulikdoc.governance import ReviewStatus, UseCase
from hydraulikdoc.interop import build_sap_notifications
from hydraulikdoc.repository import InMemoryRepository, missing_analysis_fields
from hydraulikdoc.security import InputRejected
from hydraulikdoc.ui import _parse_sensor_csv
from tests.test_enterprise_core import _production_environment


def _principal(role: str, subject: str = "user", tenant: str = "demo-tenant") -> UserPrincipal:
    return UserPrincipal(subject, tenant, subject, role, permissions=ROLE_PERMISSIONS[role])


class DemoConfigurationTests(unittest.TestCase):
    def test_demo_backend_is_rejected_in_production(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "AI_BACKEND"):
            AppSettings.from_environment(_production_environment() | {"AI_BACKEND": "demo"})

    def test_demo_backend_is_rejected_behind_entra(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "local authentication"):
            AppSettings.from_environment({"APP_ENV": "test", "AI_BACKEND": "demo", "AUTH_MODE": "entra_proxy"})

    def test_demo_backend_is_reported_as_demo(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        self.assertTrue(settings.demo_mode)
        self.assertTrue(settings.ai_ready)
        self.assertFalse(settings.azure_ready)
        self.assertEqual(settings.release_state, "demo")


class DemoTenantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        self.repository = InMemoryRepository(self.settings)
        self.supervisor = _principal("supervisor")

    def test_seed_covers_every_workflow_state_with_labelled_data(self) -> None:
        result = seed_demo_tenant(self.supervisor, self.repository)
        self.assertEqual((result.assets, result.documents, result.incidents), (4, 2, 4))
        incidents = self.repository.list_incidents(self.supervisor)
        self.assertEqual(sorted(item.status for item in incidents), ["closed", "in_progress", "new", "resolved"])
        self.assertTrue(all(item.title.startswith("DEMO · ") for item in incidents))
        self.assertTrue(
            all(item.display_name.startswith("DEMO · ") for item in self.repository.list_documents(self.supervisor))
        )
        self.assertTrue(all("(Demo)" in item.name for item in self.repository.list_assets(self.supervisor)))
        awaiting = next(item for item in incidents if item.status == "resolved")
        self.assertEqual(missing_analysis_fields(awaiting, "closed"), ("effectiveness_check",))

    def test_seed_refuses_non_empty_tenant_and_insufficient_role(self) -> None:
        self.assertTrue(demo_seed_blockers(_principal("technician"), self.repository))
        with self.assertRaises(PermissionError):
            seed_demo_tenant(_principal("technician"), self.repository)
        self.repository.upsert_asset(
            self.supervisor, asset_id="REAL-01", name="Echt", site="Werk", manufacturer="", model="", criticality="low"
        )
        with self.assertRaisesRegex(PermissionError, "leeren Mandanten"):
            seed_demo_tenant(self.supervisor, self.repository)

    def test_demo_answers_are_extractive_cited_and_reviewable(self) -> None:
        seed_demo_tenant(self.supervisor, self.repository)
        service = DemoRAGService(self.settings, self.repository)
        answer = service.ask(self.supervisor, "Wie hoch darf der Wassergehalt sein?", UseCase.MAINTENANCE_ASSISTANCE)
        self.assertIn("Der Wassergehalt im Hydrauliköl darf 0,1 % nicht überschreiten. [S1]", answer.text)
        self.assertEqual([(item.page, item.display_name[:6]) for item in answer.citations], [(18, "DEMO ·")])
        self.assertTrue(has_valid_source_citations(answer.text, len(answer.citations)))
        self.assertEqual(answer.provenance.provider, DEMO_PROVIDER)
        self.assertEqual(answer.limitations[0], DEMO_LIMITATION)
        reviewer = _principal("supervisor", subject="reviewer")
        self.repository.record_review(reviewer, answer.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(self.repository.answer_review_status(reviewer, answer.answer_id), ReviewStatus.ACCEPTED)

    def test_two_part_question_gets_one_sentence_per_part(self) -> None:
        seed_demo_tenant(self.supervisor, self.repository)
        answer = DemoRAGService(self.settings, self.repository).ask(
            self.supervisor,
            "Welcher Betriebsdruck gilt für HA-250 und wann ist das Aggregat stillzusetzen?",
            UseCase.MAINTENANCE_ASSISTANCE,
        )
        self.assertIn("Bei Drücken über 250 bar im Betrieb ist das Aggregat stillzusetzen", answer.text)
        self.assertIn("Der zulässige Betriebsdruck beträgt 210 bar. [S2]", answer.text)
        self.assertEqual(len(answer.citations), 2)

    def test_demo_keeps_use_case_gates_and_has_no_upload(self) -> None:
        service = DemoRAGService(self.settings, self.repository)
        with self.assertRaisesRegex(PermissionError, "AUTONOMOUS_CONTROL_BLOCKED"):
            service.ask(self.supervisor, "Presse starten", UseCase.AUTOMATED_MACHINE_CONTROL)
        with self.assertRaises(InputRejected):
            service.ingest(self.supervisor, None)  # type: ignore[arg-type]

    def test_unrelated_question_returns_no_evidence(self) -> None:
        seed_demo_tenant(self.supervisor, self.repository)
        answer = DemoRAGService(self.settings, self.repository).ask(
            self.supervisor, "Was kostet ein Kaffee?", UseCase.OTHER
        )
        self.assertEqual(answer.citations, ())
        self.assertIn("keine passende Evidenz", answer.text)

    def test_demo_service_requires_demo_backend(self) -> None:
        with self.assertRaises(RuntimeError):
            DemoRAGService(AppSettings.from_environment({"APP_ENV": "test"}), self.repository)

    def test_sap_export_of_demo_incidents_is_marked(self) -> None:
        seed_demo_tenant(self.supervisor, self.repository)
        export = build_sap_notifications(
            self.repository.list_incidents(self.supervisor), self.repository.list_assets(self.supervisor), "M2"
        )
        self.assertTrue(all(row["QMTXT"].startswith("DEMO") for row in export.rows))
        self.assertEqual(len(export.missing_reference), 1)


class DemoSensorSeriesTests(unittest.TestCase):
    def test_sample_series_parses_and_crosses_default_warning_limits(self) -> None:
        readings = _parse_sensor_csv(demo_sensor_csv())
        self.assertEqual(len(readings), 48)
        assessment = assess_condition(readings, OperatingEnvelope(250, 300, 70, 85, 5, 1000))
        self.assertIs(assessment.severity, Severity.WARNING)
        self.assertEqual(
            sorted(signal.code for signal in assessment.signals),
            ["PARTICLE_WARNING", "PRESSURE_WARNING", "TEMPERATURE_WARNING"],
        )


if __name__ == "__main__":
    unittest.main()
