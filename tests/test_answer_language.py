import re
import unittest
from collections.abc import Sequence

from compliance.audit import AuditEvent, AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.azure_ai import AzureRAGService, SearchHit
from hydraulikdoc.config import AppSettings
from hydraulikdoc.demo import DemoRAGService, seed_demo_tenant
from hydraulikdoc.evaluation import EvaluationCase, create_report, evaluate_case
from hydraulikdoc.governance import (
    NO_EVIDENCE_TEXT,
    PROMPT_KEY,
    PROMPT_VERSION,
    AIProvenance,
    GroundedAnswer,
    UseCase,
    system_prompt,
)
from hydraulikdoc.repository import InMemoryRepository


def _rules(prompt: str) -> dict[str, str]:
    return dict(re.findall(r"^(\d)\. (.+)$", prompt, re.M))


class _FakeModels:
    def __init__(self) -> None:
        self.languages: list[str] = []

    def embeddings(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.0,) for _ in texts)

    def answer(self, question: str, context: str, language: str) -> str:
        self.languages.append(language)
        return "The operating pressure is 210 bar (Betriebsdruck) [S1]."


class _FakeSearch:
    def __init__(self, hits: tuple[SearchHit, ...]) -> None:
        self._hits = hits

    def query(self, tenant_id: str, question: str, vector: Sequence[float]) -> tuple[SearchHit, ...]:
        return self._hits


def _last_query_event(repository: InMemoryRepository) -> AuditEvent:
    return next(event for event, _ in reversed(repository._audit) if event.action == "knowledge.query.completed")


class SystemPromptTests(unittest.TestCase):
    def test_only_the_language_rule_differs(self) -> None:
        german, english = _rules(system_prompt("de")), _rules(system_prompt("en"))
        self.assertEqual(set(german), set(english))
        self.assertEqual({key: german[key] for key in "123456"}, {key: english[key] for key in "123456"})
        self.assertTrue(german["7"].startswith("Antworte auf Deutsch"))
        self.assertTrue(english["7"].startswith("Antworte auf Englisch"))
        self.assertIn("wörtlich in Klammern", english["7"])

    def test_unknown_language_falls_back_to_german(self) -> None:
        self.assertEqual(system_prompt("fr"), system_prompt("de"))

    def test_prompt_carries_its_version(self) -> None:
        self.assertIn(f"Prompt: {PROMPT_KEY}@{PROMPT_VERSION}", system_prompt("en"))


class AzureAnswerLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.principal = UserPrincipal(
            "tech", "tenant-a", "Tech", "technician", permissions=ROLE_PERMISSIONS["technician"]
        )
        # Bypass the Azure clients; only the answer orchestration is under test.
        self.service = object.__new__(AzureRAGService)
        self.service._settings = AppSettings.from_environment({"APP_ENV": "test"})
        self.service._repository = self.repository
        self.models = _FakeModels()
        self.service._models = self.models

    def test_language_reaches_the_model_and_the_audit_trail(self) -> None:
        hit = SearchHit("c1", "d1", "Handbuch", 12, "Betriebsdruck 210 bar", 0.9)
        self.service._search = _FakeSearch((hit,))
        answer = self.service.ask(self.principal, "Operating pressure?", UseCase.MAINTENANCE_ASSISTANCE, "en")
        self.assertEqual(self.models.languages, ["en"])
        self.assertIn("[S1]", answer.text)
        self.assertEqual(answer.provenance.prompt_version, PROMPT_VERSION)
        self.assertEqual(_last_query_event(self.repository).metadata["answer_language"], "en")

    def test_no_evidence_text_follows_the_language(self) -> None:
        self.service._search = _FakeSearch(())
        english = self.service.ask(self.principal, "Operating pressure?", UseCase.MAINTENANCE_ASSISTANCE, "en")
        german = self.service.ask(self.principal, "Betriebsdruck?", UseCase.MAINTENANCE_ASSISTANCE)
        self.assertEqual(english.text, NO_EVIDENCE_TEXT["en"])
        self.assertEqual(german.text, NO_EVIDENCE_TEXT["de"])
        self.assertEqual(self.models.languages, [])


class DemoAnswerLanguageTests(unittest.TestCase):
    def test_english_frame_keeps_the_german_quotes_verbatim(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        repository = InMemoryRepository(settings)
        supervisor = UserPrincipal("sup", "tenant-a", "Sup", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"])
        seed_demo_tenant(supervisor, repository)
        answer = DemoRAGService(settings, repository).ask(
            supervisor, "Wie hoch darf der Wassergehalt sein?", UseCase.MAINTENANCE_ASSISTANCE, "en"
        )
        self.assertTrue(answer.text.startswith("**Demo answer without a language model.**"))
        self.assertIn("Der Wassergehalt im Hydrauliköl darf 0,1 % nicht überschreiten. [S1]", answer.text)
        self.assertEqual(_last_query_event(repository).metadata["answer_language"], "en")


class EvaluationLanguageTests(unittest.TestCase):
    def _no_evidence_case(self, language: str) -> EvaluationCase:
        return EvaluationCase.from_mapping(
            {
                "case_id": f"no-evidence-{language}",
                "tenant_id": "eval-tenant",
                "category": "no_evidence",
                "question": "Frage ohne Evidenz",
                "use_case": "maintenance_assistance",
                "expects_no_evidence": True,
                "answer_language": language,
            }
        )

    def _answer(self, text: str) -> GroundedAnswer:
        return GroundedAnswer.create(
            text=text,
            citations=(),
            provenance=AIProvenance("azure", "chat", "snapshot", "germanywestcentral"),
            use_case=UseCase.MAINTENANCE_ASSISTANCE,
        )

    def test_no_evidence_gate_uses_the_text_of_the_case_language(self) -> None:
        english = self._no_evidence_case("en")
        self.assertTrue(evaluate_case(english, self._answer(NO_EVIDENCE_TEXT["en"])).passed)
        self.assertFalse(evaluate_case(english, self._answer(NO_EVIDENCE_TEXT["de"])).passed)
        self.assertTrue(evaluate_case(self._no_evidence_case("de"), self._answer(NO_EVIDENCE_TEXT["de"])).passed)

    def test_unsupported_language_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "answer_language is not supported"):
            self._no_evidence_case("fr")

    def test_report_lists_the_exercised_languages(self) -> None:
        results = tuple(
            evaluate_case(self._no_evidence_case(language), self._answer(NO_EVIDENCE_TEXT[language]))
            for language in ("en", "de")
        )
        report = create_report(
            results=results,
            dataset_version="synthetic-v1",
            dataset_sha256="0" * 64,
            model_snapshot="snapshot",
            region="germanywestcentral",
        )
        self.assertEqual(report.answer_languages, ("de", "en"))
        self.assertIn('"answer_language": "en"', report.to_json())


class AuditMetadataTests(unittest.TestCase):
    def test_new_technical_keys_are_kept(self) -> None:
        event = AuditEvent(
            action="incident.kpi_export.generated",
            outcome=AuditOutcome.SUCCESS,
            metadata={"window_days": 90, "answer_language": "en", "free_text": "dropped"},
        )
        self.assertEqual(dict(event.metadata), {"window_days": 90, "answer_language": "en"})


if __name__ == "__main__":
    unittest.main()
