"""Document control (ISO 9001 7.5.3): only released documents are evidence, and release needs a second person."""

import unittest
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from compliance.audit import AuditEvent, AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.azure_ai import AzureHybridSearch, AzureRAGService, SearchHit
from hydraulikdoc.config import AppSettings
from hydraulikdoc.demo import DemoRAGService, seed_demo_tenant
from hydraulikdoc.governance import NO_EVIDENCE_TEXT, UseCase
from hydraulikdoc.repository import (
    DOCUMENT_MAX_REVIEW,
    DOCUMENT_WITHDRAWAL_REASONS,
    DocumentControl,
    DocumentRecord,
    InMemoryRepository,
    require_document_deletion,
)
from hydraulikdoc.security import ValidatedUpload

TENANT = "tenant-a"


def _principal(subject: str, role: str, tenant: str = TENANT) -> UserPrincipal:
    return UserPrincipal(subject, tenant, subject.title(), role, permissions=ROLE_PERMISSIONS[role])


def _upload(name: str = "Handbuch.pdf") -> ValidatedUpload:
    return ValidatedUpload(str(uuid.uuid4()), name, uuid.uuid4().hex * 2, b"", "application/pdf")


def _review(days: int = 180) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


class DocumentControlCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.technician = _principal("tech", "technician")
        self.supervisor = _principal("sup", "supervisor")
        self.second_supervisor = _principal("sup-2", "supervisor")

    def _indexed(
        self, principal: UserPrincipal, control: DocumentControl | None = None, name: str = "Handbuch.pdf"
    ) -> DocumentRecord:
        record = self.repository.register_document(principal, _upload(name), control)
        self.repository.mark_document_indexed(principal, record.document_id, 12)
        return self._document(principal, record.document_id)

    def _released(self, control: DocumentControl | None = None, name: str = "Handbuch.pdf") -> DocumentRecord:
        record = self._indexed(self.technician, control, name)
        return self.repository.release_document(self.supervisor, record.document_id, review_due_at=_review()).document

    def _document(self, principal: UserPrincipal, document_id: str) -> DocumentRecord:
        return next(item for item in self.repository.list_documents(principal) if item.document_id == document_id)

    def _code(self, error: type[Exception], call: Any, *args: Any, **kwargs: Any) -> str:
        with self.assertRaises(error) as raised:
            call(*args, **kwargs)
        return str(raised.exception.args[0])


class RegistrationTests(DocumentControlCase):
    def test_upload_starts_as_draft_and_is_no_evidence(self) -> None:
        record = self._indexed(self.technician)
        self.assertEqual((record.release_status, record.revision, record.status), ("draft", "1", "ready"))
        self.assertFalse(record.usable_for_answers)
        self.assertTrue(record.is_own)
        self.assertFalse(self._document(self.supervisor, record.document_id).is_own)

    def test_revision_and_document_number_are_validated(self) -> None:
        register = self.repository.register_document
        for revision in ("", "2 b", "x" * 17, "-1"):
            with self.subTest(revision=revision):
                code = self._code(ValueError, register, self.technician, _upload(), DocumentControl(revision))
                self.assertEqual(code, "DOCUMENT_REVISION_INVALID")
        for number in ("A", "BA 250", "x" * 65, "/BA"):
            with self.subTest(number=number):
                code = self._code(ValueError, register, self.technician, _upload(), DocumentControl("1", number))
                self.assertEqual(code, "DOCUMENT_NUMBER_INVALID")
        self.assertEqual(self.repository.list_documents(self.technician), ())

    def test_only_a_released_document_of_the_tenant_can_be_superseded(self) -> None:
        draft = self._indexed(self.technician)
        register = self.repository.register_document
        for target in (draft.document_id, str(uuid.uuid4()), "not-a-uuid"):
            with self.subTest(target=target):
                control = DocumentControl("2", supersedes_document_id=target)
                self.assertEqual(
                    self._code(ValueError, register, self.technician, _upload(), control),
                    "DOCUMENT_SUPERSEDES_INVALID",
                )
        released = self._released(DocumentControl("1", "BA-HA-250"))
        foreign = _principal("other", "technician", "tenant-b")
        control = DocumentControl("2", supersedes_document_id=released.document_id)
        self.assertEqual(self._code(ValueError, register, foreign, _upload(), control), "DOCUMENT_SUPERSEDES_INVALID")

    def test_new_revision_inherits_the_number_and_must_differ(self) -> None:
        released = self._released(DocumentControl("1", "BA-HA-250"))
        register = self.repository.register_document
        same = DocumentControl("1", supersedes_document_id=released.document_id)
        self.assertEqual(
            self._code(ValueError, register, self.technician, _upload(), same), "DOCUMENT_REVISION_UNCHANGED"
        )
        successor = register(self.technician, _upload(), DocumentControl("2", "", released.document_id))
        self.assertEqual(successor.document_number, "BA-HA-250")
        self.assertEqual(successor.supersedes_document_id, released.document_id)
        third = DocumentControl("3", supersedes_document_id=released.document_id)
        self.assertEqual(
            self._code(ValueError, register, self.technician, _upload(), third), "DOCUMENT_SUPERSEDES_PENDING"
        )


class ReleaseTests(DocumentControlCase):
    def test_release_needs_the_permission(self) -> None:
        record = self._indexed(self.technician)
        other = _principal("tech-2", "technician")
        with self.assertRaises(PermissionError):
            self.repository.release_document(other, record.document_id, review_due_at=_review())
        self.assertEqual(self._document(other, record.document_id).release_status, "draft")

    def test_uploader_cannot_release_their_own_document(self) -> None:
        record = self._indexed(self.supervisor)
        code = self._code(
            PermissionError,
            self.repository.release_document,
            self.supervisor,
            record.document_id,
            review_due_at=_review(),
        )
        self.assertEqual(code, "FOUR_EYES_RELEASE_REQUIRED")
        released = self.repository.release_document(
            self.second_supervisor, record.document_id, review_due_at=_review()
        ).document
        self.assertTrue(released.usable_for_answers)
        self.assertTrue(released.release_recorded)

    def test_admin_is_bound_by_four_eyes_as_well(self) -> None:
        admin = _principal("root", "admin")
        record = self._indexed(admin)
        code = self._code(
            PermissionError, self.repository.release_document, admin, record.document_id, review_due_at=_review()
        )
        self.assertEqual(code, "FOUR_EYES_RELEASE_REQUIRED")

    def test_document_must_be_indexed(self) -> None:
        record = self.repository.register_document(self.technician, _upload())
        release = self.repository.release_document
        code = self._code(ValueError, release, self.supervisor, record.document_id, review_due_at=_review())
        self.assertEqual(code, "DOCUMENT_NOT_INDEXED")
        self.repository.mark_document_failed(self.technician, record.document_id)
        code = self._code(ValueError, release, self.supervisor, record.document_id, review_due_at=_review())
        self.assertEqual(code, "DOCUMENT_NOT_INDEXED")

    def test_review_date_must_be_within_a_year_and_timezone_aware(self) -> None:
        record = self._indexed(self.technician)
        now = datetime.now(UTC)
        invalid = (
            now - timedelta(minutes=1),
            now + DOCUMENT_MAX_REVIEW + timedelta(days=1),
            (now + timedelta(days=30)).replace(tzinfo=None),
        )
        for due in invalid:
            with self.subTest(due=due):
                code = self._code(
                    ValueError, self.repository.release_document, self.supervisor, record.document_id, review_due_at=due
                )
                self.assertEqual(code, "DOCUMENT_REVIEW_DATE_INVALID")
        self.assertEqual(self._document(self.supervisor, record.document_id).release_status, "draft")

    def test_second_release_and_unknown_document_are_rejected(self) -> None:
        released = self._released()
        release = self.repository.release_document
        code = self._code(ValueError, release, self.second_supervisor, released.document_id, review_due_at=_review())
        self.assertEqual(code, "DOCUMENT_ALREADY_RELEASED")
        with self.assertRaises(KeyError):
            release(self.supervisor, str(uuid.uuid4()), review_due_at=_review())
        foreign = _principal("sup-b", "supervisor", "tenant-b")
        draft = self._indexed(self.technician)
        with self.assertRaises(KeyError):
            release(foreign, draft.document_id, review_due_at=_review())

    def test_releasing_a_revision_withdraws_its_predecessor(self) -> None:
        first = self._released(DocumentControl("1", "BA-HA-250"))
        second = self._indexed(self.technician, DocumentControl("2", supersedes_document_id=first.document_id))
        self.assertTrue(self._document(self.supervisor, first.document_id).usable_for_answers)
        result = self.repository.release_document(self.supervisor, second.document_id, review_due_at=_review())
        assert result.superseded is not None
        self.assertEqual(result.superseded.document_id, first.document_id)
        self.assertEqual(
            (result.superseded.release_status, result.superseded.withdrawal_reason), ("withdrawn", "superseded")
        )
        self.assertFalse(self._document(self.supervisor, first.document_id).usable_for_answers)
        self.assertTrue(self._document(self.supervisor, second.document_id).usable_for_answers)
        events = self.repository.list_document_events(self.supervisor, first.document_id)
        self.assertEqual(
            [(event.event_type, event.reason_code) for event in events],
            [("uploaded", None), ("released", None), ("withdrawn", "superseded")],
        )

    def test_predecessor_withdrawn_in_the_meantime_is_left_alone(self) -> None:
        first = self._released(DocumentControl("1", "BA-HA-250"))
        second = self._indexed(self.technician, DocumentControl("2", supersedes_document_id=first.document_id))
        self.repository.withdraw_document(self.supervisor, first.document_id, "incorrect")
        result = self.repository.release_document(self.supervisor, second.document_id, review_due_at=_review())
        self.assertIsNone(result.superseded)
        self.assertEqual(self._document(self.supervisor, first.document_id).withdrawal_reason, "incorrect")


class WithdrawalAndReviewTests(DocumentControlCase):
    def test_withdrawal_is_immediate_final_and_needs_a_listed_reason(self) -> None:
        released = self._released()
        withdraw = self.repository.withdraw_document
        with self.assertRaises(PermissionError):
            withdraw(self.technician, released.document_id, "obsolete")
        for reason in ("", "superseded", "other"):
            with self.subTest(reason=reason):
                code = self._code(ValueError, withdraw, self.supervisor, released.document_id, reason)
                self.assertEqual(code, "DOCUMENT_WITHDRAWAL_REASON_INVALID")
        # One person is enough to take a document out of use, including the person who released it.
        result = withdraw(self.supervisor, released.document_id, "safety_notice")
        self.assertEqual((result.document.release_status, result.cited_answer_count), ("withdrawn", 0))
        self.assertIsNotNone(result.document.withdrawn_at)
        self.assertFalse(result.document.usable_for_answers)
        code = self._code(ValueError, withdraw, self.supervisor, released.document_id, "obsolete")
        self.assertEqual(code, "DOCUMENT_NOT_RELEASED")
        code = self._code(
            ValueError,
            self.repository.release_document,
            self.second_supervisor,
            released.document_id,
            review_due_at=_review(),
        )
        self.assertEqual(code, "DOCUMENT_WITHDRAWN")

    def test_every_listed_reason_is_accepted(self) -> None:
        for reason in DOCUMENT_WITHDRAWAL_REASONS:
            with self.subTest(reason=reason):
                released = self._released(name=f"{reason}.pdf")
                result = self.repository.withdraw_document(self.supervisor, released.document_id, reason)
                self.assertEqual(result.document.withdrawal_reason, reason)

    def test_draft_cannot_be_withdrawn(self) -> None:
        draft = self._indexed(self.technician)
        code = self._code(ValueError, self.repository.withdraw_document, self.supervisor, draft.document_id, "obsolete")
        self.assertEqual(code, "DOCUMENT_NOT_RELEASED")

    def test_review_confirmation_moves_the_due_date(self) -> None:
        released = self._released()
        confirm = self.repository.confirm_document_review
        with self.assertRaises(PermissionError):
            confirm(self.technician, released.document_id, review_due_at=_review(300))
        code = self._code(ValueError, confirm, self.supervisor, released.document_id, review_due_at=_review(-1))
        self.assertEqual(code, "DOCUMENT_REVIEW_DATE_INVALID")
        due = _review(300)
        updated = confirm(self.supervisor, released.document_id, review_due_at=due)
        self.assertEqual(updated.review_due_at, due)
        self.assertEqual(updated.released_at, released.released_at)
        draft = self._indexed(self.technician, name="Entwurf.pdf")
        code = self._code(ValueError, confirm, self.supervisor, draft.document_id, review_due_at=due)
        self.assertEqual(code, "DOCUMENT_NOT_RELEASED")
        types = [
            event.event_type for event in self.repository.list_document_events(self.supervisor, released.document_id)
        ]
        self.assertEqual(types, ["uploaded", "released", "review_confirmed"])

    def test_overdue_review_is_flagged_but_keeps_the_document_usable(self) -> None:
        released = self._released()
        assert released.review_due_at is not None
        self.assertFalse(released.review_overdue(datetime.now(UTC)))
        self.assertTrue(released.review_overdue(released.review_due_at + timedelta(seconds=1)))
        self.assertTrue(released.usable_for_answers)
        self.assertFalse(replace(released, release_status="withdrawn").review_overdue(released.review_due_at))


class LegacyDocumentTests(DocumentControlCase):
    """Documents that were in use before document control: released without a recorded release."""

    def _legacy(self, uploader: UserPrincipal) -> DocumentRecord:
        record = self._indexed(uploader)
        key = (TENANT, record.document_id)
        self.repository._documents[key] = replace(self.repository._documents[key], release_status="released")
        self.repository._document_events.clear()
        return self._document(uploader, record.document_id)

    def test_legacy_document_stays_usable_and_is_marked(self) -> None:
        legacy = self._legacy(self.technician)
        self.assertTrue(legacy.usable_for_answers)
        self.assertFalse(legacy.release_recorded)
        self.assertEqual(self.repository.list_document_events(self.supervisor, legacy.document_id), ())

    def test_legacy_document_can_be_released_formally_by_a_second_person(self) -> None:
        legacy = self._legacy(self.supervisor)
        release = self.repository.release_document
        code = self._code(PermissionError, release, self.supervisor, legacy.document_id, review_due_at=_review())
        self.assertEqual(code, "FOUR_EYES_RELEASE_REQUIRED")
        released = release(self.second_supervisor, legacy.document_id, review_due_at=_review()).document
        self.assertTrue(released.release_recorded)
        self.assertIsNotNone(released.review_due_at)

    def test_review_needs_a_recorded_release_but_withdrawal_does_not(self) -> None:
        legacy = self._legacy(self.technician)
        code = self._code(
            ValueError,
            self.repository.confirm_document_review,
            self.supervisor,
            legacy.document_id,
            review_due_at=_review(),
        )
        self.assertEqual(code, "DOCUMENT_RELEASE_NOT_RECORDED")
        result = self.repository.withdraw_document(self.supervisor, legacy.document_id, "obsolete")
        self.assertEqual(result.document.release_status, "withdrawn")


class DeletionAndEvidenceTests(DocumentControlCase):
    def test_released_documents_are_deleted_by_release_holders_only(self) -> None:
        released = self._released()
        draft = self._indexed(self.technician, name="Entwurf.pdf")
        with self.assertRaises(PermissionError) as raised:
            require_document_deletion(self.technician, self.repository, released.document_id)
        self.assertEqual(str(raised.exception), "DOCUMENT_RELEASE_REQUIRED")
        require_document_deletion(self.technician, self.repository, draft.document_id)
        require_document_deletion(self.supervisor, self.repository, released.document_id)
        require_document_deletion(self.technician, self.repository, str(uuid.uuid4()))
        self.repository.withdraw_document(self.supervisor, released.document_id, "obsolete")
        require_document_deletion(self.technician, self.repository, released.document_id)

    def test_history_shows_roles_and_marks_only_own_steps(self) -> None:
        released = self._released()
        seen_by_uploader = self.repository.list_document_events(self.technician, released.document_id)
        seen_by_releaser = self.repository.list_document_events(self.supervisor, released.document_id)
        self.assertEqual([event.actor_role for event in seen_by_uploader], ["technician", "supervisor"])
        self.assertEqual([event.is_own for event in seen_by_uploader], [True, False])
        self.assertEqual([event.is_own for event in seen_by_releaser], [False, True])
        foreign = _principal("sup-b", "supervisor", "tenant-b")
        self.assertEqual(self.repository.list_document_events(foreign, released.document_id), ())

    def test_subject_export_contains_only_the_own_document_steps(self) -> None:
        released = self._released()
        own = self.repository.subject_export(self.supervisor)["document_steps"]
        self.assertEqual(
            [(step["document_id"], step["event_type"]) for step in own], [(released.document_id, "released")]
        )
        uploaded = self.repository.subject_export(self.technician)["document_steps"]
        self.assertEqual([step["event_type"] for step in uploaded], ["uploaded"])

    def test_new_audit_metadata_key_is_kept(self) -> None:
        event = AuditEvent(
            action="knowledge.document.withdrawn",
            outcome=AuditOutcome.SUCCESS,
            metadata={"reason_code": "obsolete", "answer_count": 3, "display_name": "dropped"},
        )
        self.assertEqual(dict(event.metadata), {"reason_code": "obsolete", "answer_count": 3})


class DemoRevisionTests(unittest.TestCase):
    """The demo tenant shows the point of the control: a draft revision changes nothing until released."""

    QUESTION = "Nach wie vielen Betriebsstunden ist ein Ölwechsel erforderlich?"

    def setUp(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        self.repository = InMemoryRepository(settings)
        self.supervisor = _principal("sup", "supervisor")
        seed_demo_tenant(self.supervisor, self.repository)
        self.service = DemoRAGService(settings, self.repository)
        documents = self.repository.list_documents(self.supervisor)
        self.draft = next(item for item in documents if item.release_status == "draft")
        self.first = next(item for item in documents if item.document_id == self.draft.supersedes_document_id)

    def test_answers_follow_the_released_revision(self) -> None:
        before = self.service.ask(self.supervisor, self.QUESTION, UseCase.MAINTENANCE_ASSISTANCE)
        self.assertIn("4000 Betriebsstunden", before.text)
        self.assertNotIn("3000 Betriebsstunden", before.text)
        self.assertEqual({citation.revision for citation in before.citations}, {"1"})
        self.assertEqual({citation.document_id for citation in before.citations}, {self.first.document_id})

        result = self.repository.release_document(self.supervisor, self.draft.document_id, review_due_at=_review())
        assert result.superseded is not None
        self.assertEqual(result.superseded.document_id, self.first.document_id)
        self.assertEqual(result.superseded_answer_count, 1)

        after = self.service.ask(self.supervisor, self.QUESTION, UseCase.MAINTENANCE_ASSISTANCE)
        self.assertIn("3000 Betriebsstunden", after.text)
        self.assertNotIn("4000 Betriebsstunden", after.text)
        self.assertEqual({citation.revision for citation in after.citations}, {"2"})

    def test_withdrawn_document_is_no_longer_cited(self) -> None:
        self.service.ask(self.supervisor, self.QUESTION, UseCase.MAINTENANCE_ASSISTANCE)
        result = self.repository.withdraw_document(self.supervisor, self.first.document_id, "incorrect")
        self.assertEqual(result.cited_answer_count, 1)
        answer = self.service.ask(self.supervisor, self.QUESTION, UseCase.MAINTENANCE_ASSISTANCE)
        self.assertNotIn(self.first.document_id, {citation.document_id for citation in answer.citations})
        self.assertNotIn("4000 Betriebsstunden", answer.text)

    def test_demo_revision_is_releasable_by_the_seeding_supervisor(self) -> None:
        self.assertFalse(self.draft.is_own)
        self.assertEqual(self.draft.document_number, self.first.document_number)
        with self.assertRaises(PermissionError):
            DemoRAGService.delete_document(self.service, _principal("tech", "technician"), self.first.document_id)


class _FakeModels:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def embeddings(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.0,) for _ in texts)

    def answer(self, question: str, context: str, language: str) -> str:
        self.contexts.append(context)
        return "Der Betriebsdruck beträgt 210 bar [S1]."


class _FakeSearch:
    """Returns every stored hit, as a stale or manipulated index would."""

    def __init__(self, hits: tuple[SearchHit, ...]) -> None:
        self.hits = hits
        self.requested: list[tuple[str, ...]] = []

    def query(
        self, tenant_id: str, question: str, vector: Sequence[float], document_ids: Sequence[str]
    ) -> tuple[SearchHit, ...]:
        self.requested.append(tuple(document_ids))
        return self.hits


class AzureAnswerGateTests(DocumentControlCase):
    def setUp(self) -> None:
        super().setUp()
        # Bypass the Azure clients; only the answer orchestration is under test.
        self.service = object.__new__(AzureRAGService)
        self.service._settings = AppSettings.from_environment({"APP_ENV": "test"})
        self.service._repository = self.repository
        self.models = _FakeModels()
        self.service._models = self.models

    def _hit(self, document: DocumentRecord, content: str) -> SearchHit:
        return SearchHit(f"chunk-{document.document_id}", document.document_id, document.display_name, 12, content, 0.9)

    def _ask(self) -> Any:
        return self.service.ask(self.technician, "Betriebsdruck?", UseCase.MAINTENANCE_ASSISTANCE)

    def test_without_a_released_document_the_index_is_not_even_queried(self) -> None:
        draft = self._indexed(self.technician)
        search = _FakeSearch((self._hit(draft, "Betriebsdruck 999 bar"),))
        self.service._search = search
        answer = self._ask()
        self.assertEqual(answer.text, NO_EVIDENCE_TEXT["de"])
        self.assertEqual((search.requested, self.models.contexts), ([], []))

    def test_hits_from_unreleased_documents_never_reach_the_model(self) -> None:
        released = self._released(DocumentControl("4", "BA-1"), "Freigegeben.pdf")
        draft = self._indexed(self.technician, name="Entwurf.pdf")
        withdrawn = self._released(name="Zurückgezogen.pdf")
        self.repository.withdraw_document(self.supervisor, withdrawn.document_id, "incorrect")
        search = _FakeSearch(
            (
                self._hit(draft, "ENTWURF 999 bar"),
                self._hit(released, "Betriebsdruck 210 bar"),
                self._hit(withdrawn, "ZURÜCKGEZOGEN 500 bar"),
            )
        )
        self.service._search = search
        answer = self._ask()
        self.assertEqual(search.requested, [(released.document_id,)])
        self.assertEqual(len(self.models.contexts), 1)
        self.assertIn("Betriebsdruck 210 bar", self.models.contexts[0])
        self.assertNotIn("ENTWURF", self.models.contexts[0])
        self.assertNotIn("ZURÜCKGEZOGEN", self.models.contexts[0])
        self.assertEqual(
            [(citation.document_id, citation.revision) for citation in answer.citations],
            [(released.document_id, "4")],
        )

    def test_withdrawal_takes_effect_for_the_next_question(self) -> None:
        released = self._released()
        self.service._search = _FakeSearch((self._hit(released, "Betriebsdruck 210 bar"),))
        self.assertEqual(len(self._ask().citations), 1)
        result = self.repository.withdraw_document(self.supervisor, released.document_id, "obsolete")
        self.assertEqual(result.cited_answer_count, 1)
        self.assertEqual(self._ask().text, NO_EVIDENCE_TEXT["de"])


class _Response:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {"value": []}


class _RecordingClient:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> _Response:
        self.payloads.append(json)
        return _Response()


class SearchFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.search = object.__new__(AzureHybridSearch)
        self.search._settings = AppSettings.from_environment({"APP_ENV": "test"})
        self.search._endpoint = "https://search.invalid"
        self.search._index = "hydraulikdoc"
        self.search._headers = lambda: {}  # type: ignore[method-assign]
        self.client = _RecordingClient()
        self.search._client = self.client

    def test_filter_is_limited_to_the_tenant_and_the_released_documents(self) -> None:
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        self.search.query("tenant-a", "Betriebsdruck?", (0.0,), (first, second))
        self.assertEqual(
            self.client.payloads[0]["filter"],
            f"tenant_id eq 'tenant-a' and search.in(document_id, '{first},{second}', ',')",
        )

    def test_empty_release_set_skips_the_request(self) -> None:
        self.assertEqual(self.search.query("tenant-a", "Betriebsdruck?", (0.0,), ()), ())
        self.assertEqual(self.client.payloads, [])

    def test_only_canonical_uuids_reach_the_filter(self) -> None:
        with self.assertRaises(ValueError):
            self.search.query("tenant-a", "Betriebsdruck?", (0.0,), ("x') or tenant_id ne ('tenant-a",))
        self.assertEqual(self.client.payloads, [])


if __name__ == "__main__":
    unittest.main()
