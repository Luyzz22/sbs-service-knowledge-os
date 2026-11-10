"""Review queue and AI quality monitoring: a second person can decide, and nobody is evaluated."""

import dataclasses
import unittest
from datetime import UTC, datetime, timedelta

from hydraulikdoc.ai_quality import (
    QUALITY_EXPORT_COLUMNS,
    REVIEW_TARGET,
    SIGNAL_MIN_DECISIONS,
    UNKNOWN_REASON,
    answer_quality,
    overdue_reviews,
    quality_export_rows,
)
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.demo import DemoRAGService, seed_demo_tenant
from hydraulikdoc.governance import AIProvenance, GroundedAnswer, ReviewStatus, UseCase
from hydraulikdoc.interop import to_spreadsheet_csv
from hydraulikdoc.repository import (
    REVIEW_ESCALATION_REASON,
    REVIEW_REJECTION_REASONS,
    AnswerQualityRecord,
    DocumentRecord,
    InMemoryRepository,
    StoredAnswer,
)

TENANT = "tenant-a"
EPOCH = datetime.min.replace(tzinfo=UTC)
QUESTION = "Darf die Presse mit 260 bar weiterlaufen?"


def _principal(subject: str, role: str, tenant: str = TENANT) -> UserPrincipal:
    return UserPrincipal(subject, tenant, subject.title(), role, permissions=ROLE_PERMISSIONS[role])


def _answer(use_case: UseCase = UseCase.MAINTENANCE_ASSISTANCE) -> GroundedAnswer:
    return GroundedAnswer.create(
        text="Keine belastbare Evidenz.",
        citations=(),
        provenance=AIProvenance("azure-openai", "chat", "2026-08-01", "germanywestcentral"),
        use_case=use_case,
    )


class ReviewRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.asker = _principal("tech", "technician")
        self.colleague = _principal("tech-2", "technician")
        self.supervisor = _principal("sup", "supervisor")

    def _stored(self, use_case: UseCase = UseCase.MAINTENANCE_ASSISTANCE) -> GroundedAnswer:
        answer = _answer(use_case)
        self.repository.record_answer(self.asker, QUESTION, answer)
        return answer

    def _queued(self, principal: UserPrincipal, answer: GroundedAnswer) -> StoredAnswer:
        return next(
            item for item in self.repository.list_review_queue(principal) if item.answer.answer_id == answer.answer_id
        )

    def test_safety_relevant_answer_reaches_a_second_person_with_its_question(self) -> None:
        answer = self._stored(UseCase.SAFETY_RELEVANT_DIAGNOSIS)
        own = self._queued(self.asker, answer)
        self.assertTrue(own.is_own)
        self.assertFalse(own.acceptable_by(self.asker))
        with self.assertRaisesRegex(PermissionError, "FOUR_EYES_REVIEW_REQUIRED"):
            self.repository.record_review(self.asker, answer.answer_id, ReviewStatus.ACCEPTED)

        waiting = self._queued(self.colleague, answer)
        self.assertFalse(waiting.is_own)
        self.assertTrue(waiting.needs_second_person)
        self.assertEqual(waiting.question, QUESTION)
        self.assertTrue(waiting.acceptable_by(self.colleague))
        self.repository.record_review(self.colleague, answer.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(self.repository.answer_review_status(self.asker, answer.answer_id), ReviewStatus.ACCEPTED)
        # Decided answers leave the queue, and the question text goes with the decision.
        self.assertEqual(self.repository.list_review_queue(self.colleague), ())
        export = self.repository.subject_export(self.asker)
        self.assertIsNone(export["analysis_runs"][0]["review_question"])

    def test_ordinary_drafts_are_visible_to_their_author_only_and_keep_no_question(self) -> None:
        answer = self._stored()
        self.assertIsNone(self._queued(self.asker, answer).question)
        self.assertEqual(self.repository.list_review_queue(self.colleague), ())
        self.assertEqual(self.repository.list_review_queue(self.supervisor), ())
        self.assertEqual(self.repository.list_review_queue(_principal("other", "supervisor", "tenant-b")), ())

    def test_escalation_keeps_the_question_until_an_expert_decides(self) -> None:
        answer = self._stored()
        self.repository.record_review(self.asker, answer.answer_id, ReviewStatus.NEEDS_EXPERT, question=QUESTION)
        with self.assertRaisesRegex(ValueError, "REVIEW_ALREADY_ESCALATED"):
            self.repository.record_review(self.colleague, answer.answer_id, ReviewStatus.NEEDS_EXPERT)
        with self.assertRaisesRegex(PermissionError, "EXPERT_REVIEW_REQUIRED"):
            self.repository.record_review(self.colleague, answer.answer_id, ReviewStatus.REJECTED, "incomplete")

        waiting = self._queued(self.supervisor, answer)
        self.assertEqual(waiting.question, QUESTION)
        self.assertFalse(self._queued(self.colleague, answer).decidable_by(self.colleague))
        self.assertEqual(
            [(item.status, item.reason_code, item.reviewer_role, item.is_own) for item in waiting.reviews],
            [(ReviewStatus.NEEDS_EXPERT, REVIEW_ESCALATION_REASON, "technician", False)],
        )
        self.repository.record_review(self.supervisor, answer.answer_id, ReviewStatus.REJECTED, "incomplete")
        self.assertEqual(self.repository.list_review_queue(self.supervisor), ())
        self.assertIsNone(self.repository.subject_export(self.asker)["analysis_runs"][0]["review_question"])
        given = self.repository.subject_export(self.supervisor)["reviews_given"]
        self.assertEqual(
            [(item["status"], item["reason_code"], item["reviewer_role"]) for item in given],
            [("rejected", "incomplete", "supervisor")],
        )

    def test_a_decision_is_final_and_a_rejection_needs_a_fixed_reason(self) -> None:
        answer = self._stored()
        for reason in (None, "", "TECHNICAL_REJECTION", "Kollege Müller hat sich vertan"):
            with self.assertRaisesRegex(ValueError, "REVIEW_REASON_REQUIRED"):
                self.repository.record_review(self.asker, answer.answer_id, ReviewStatus.REJECTED, reason)
        with self.assertRaisesRegex(ValueError, "REVIEW_STATUS_INVALID"):
            self.repository.record_review(self.asker, answer.answer_id, ReviewStatus.DRAFT)
        with self.assertRaisesRegex(PermissionError, "REVIEW_PERMISSION_REQUIRED"):
            self.repository.record_review(_principal("viewer", "viewer"), answer.answer_id, ReviewStatus.ACCEPTED)
        with self.assertRaisesRegex(PermissionError, "REVIEW_PERMISSION_REQUIRED"):
            self.repository.list_review_queue(_principal("viewer", "viewer"))
        with self.assertRaises(KeyError):
            self.repository.record_review(
                _principal("other", "supervisor", "tenant-b"), answer.answer_id, ReviewStatus.ACCEPTED
            )
        self.repository.record_review(self.asker, answer.answer_id, ReviewStatus.REJECTED, REVIEW_REJECTION_REASONS[0])
        for status in (ReviewStatus.ACCEPTED, ReviewStatus.NEEDS_EXPERT, ReviewStatus.REJECTED):
            with self.assertRaisesRegex(ValueError, "REVIEW_ALREADY_DECIDED"):
                self.repository.record_review(self.supervisor, answer.answer_id, status, "incomplete")


class WithdrawnSourceTests(unittest.TestCase):
    def test_answer_with_a_withdrawn_source_can_only_be_rejected(self) -> None:
        settings = AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        repository = InMemoryRepository(settings)
        supervisor = _principal("sup", "supervisor")
        seed_demo_tenant(supervisor, repository)
        answer = DemoRAGService(settings, repository).ask(
            supervisor, "Wie hoch darf der Wassergehalt sein?", UseCase.MAINTENANCE_ASSISTANCE
        )
        repository.withdraw_document(supervisor, answer.citations[0].document_id, "incorrect")
        with self.assertRaisesRegex(ValueError, "REVIEW_SOURCE_NOT_RELEASED"):
            repository.record_review(supervisor, answer.answer_id, ReviewStatus.ACCEPTED)
        repository.record_review(supervisor, answer.answer_id, ReviewStatus.REJECTED, "outdated_source")


class DemoQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(
            AppSettings.from_environment({"APP_ENV": "development", "AI_BACKEND": "demo"})
        )
        self.supervisor = _principal("sup", "supervisor")
        seed_demo_tenant(self.supervisor, self.repository)

    def test_seed_leaves_two_answers_for_the_person_loading_the_demo(self) -> None:
        queue = self.repository.list_review_queue(self.supervisor)
        self.assertEqual(
            [(item.answer.review_status, item.is_own, item.acceptable_by(self.supervisor)) for item in queue],
            [(ReviewStatus.DRAFT, False, True), (ReviewStatus.NEEDS_EXPERT, False, True)],
        )
        self.assertTrue(all(item.question and item.answer.citations for item in queue))
        self.assertEqual(len(overdue_reviews(queue, datetime.now(UTC))), 1)
        # A technician sees both but may only decide the safety-relevant draft.
        technician = _principal("tech", "technician")
        self.assertEqual(
            [item.decidable_by(technician) for item in self.repository.list_review_queue(technician)], [True, False]
        )

    def test_seeded_reviews_point_at_the_outdated_revision(self) -> None:
        documents = self.repository.list_documents(self.supervisor)
        quality = answer_quality(
            self.repository.list_answer_quality(self.supervisor, since=EPOCH, limit=100), documents
        )
        self.assertEqual((quality.answers, quality.decided, quality.accepted, quality.rejected), (7, 5, 3, 2))
        self.assertEqual((quality.escalated, quality.open, quality.open_second_person), (1, 2, 2))
        self.assertEqual(quality.rejection_reasons, {"outdated_source": 2})
        self.assertEqual(quality.median_decision_time, timedelta(hours=2))
        (signal,) = quality.document_signals
        self.assertEqual((signal.revision, signal.source_rejections), ("1", 2))
        self.assertEqual(len(quality.release_signals), 1)
        # Withdrawing the document resolves the signal: the figures stay, the call to action goes.
        self.repository.withdraw_document(self.supervisor, signal.document_id, "obsolete")
        after = answer_quality(
            self.repository.list_answer_quality(self.supervisor, since=EPOCH, limit=100),
            self.repository.list_documents(self.supervisor),
        )
        self.assertEqual(after.document_signals, ())

    def test_window_and_tenant_limit_the_records(self) -> None:
        recent = self.repository.list_answer_quality(
            self.supervisor, since=datetime.now(UTC) - timedelta(days=7), limit=100
        )
        self.assertEqual(len(recent), 3)
        self.assertEqual(len(self.repository.list_answer_quality(self.supervisor, since=EPOCH, limit=2)), 2)
        other = _principal("other", "supervisor", "tenant-b")
        self.assertEqual(self.repository.list_answer_quality(other, since=EPOCH, limit=100), ())


def _record(index: int, status: str, reason: str | None = None, **changes: object) -> AnswerQualityRecord:
    generated = datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=index)
    record = AnswerQualityRecord(
        answer_id=f"answer-{index}",
        generated_at=generated,
        use_case="maintenance_assistance",
        risk_class="limited",
        review_status=status,
        prompt_version="2026-11-06.1",
        model_snapshot="2026-08-01",
        deployment="chat",
        document_ids=("doc-1",),
        decided_at=generated + timedelta(hours=index + 1) if status in ("accepted", "rejected") else None,
        rejection_reason=reason,
        escalated=False,
    )
    return dataclasses.replace(record, **changes)  # type: ignore[arg-type]


def _document(document_id: str, release_status: str = "released") -> DocumentRecord:
    now = datetime(2026, 11, 1, tzinfo=UTC)
    return DocumentRecord(
        document_id,
        TENANT,
        "Handbuch.pdf",
        "a" * 64,
        "ready",
        10,
        now,
        now,
        release_status=release_status,
        revision="4",
    )


class AnswerQualityTests(unittest.TestCase):
    def test_no_person_can_be_derived_from_the_monitoring_input(self) -> None:
        names = {field.name for field in dataclasses.fields(AnswerQualityRecord)}
        self.assertFalse({name for name in names if "token" in name or "actor" in name or "reviewer" in name})
        self.assertFalse({name for name in QUALITY_EXPORT_COLUMNS if "token" in name or "role" in name})

    def test_release_signal_needs_enough_decisions(self) -> None:
        few = [_record(0, "rejected", "incomplete"), _record(1, "accepted")]
        self.assertEqual(answer_quality(few, ()).release_signals, ())
        enough = [_record(index, "accepted") for index in range(SIGNAL_MIN_DECISIONS - 1)]
        enough.append(_record(9, "rejected", "incomplete"))
        quality = answer_quality(enough, ())
        (release,) = quality.release_signals
        self.assertEqual(release.rejection_share, 1 / SIGNAL_MIN_DECISIONS)
        clean = answer_quality([_record(index, "accepted") for index in range(10)], ())
        self.assertEqual(clean.release_signals, ())
        self.assertEqual(clean.rejection_share, 0)

    def test_releases_are_separated_and_open_answers_do_not_count_as_decided(self) -> None:
        records = [
            _record(0, "accepted"),
            _record(1, "draft", risk_class="heightened"),
            _record(2, "needs_expert", escalated=True),
            _record(3, "draft", document_ids=()),
            _record(4, "rejected", "wrong_source", prompt_version="2026-12-01.1", escalated=True),
        ]
        quality = answer_quality(records, ())
        self.assertEqual((quality.answers, quality.decided, quality.open, quality.open_second_person), (5, 2, 3, 2))
        self.assertEqual((quality.without_evidence, quality.escalated), (1, 2))
        self.assertEqual(quality.review_coverage, 0.4)
        self.assertEqual(
            [(item.prompt_version, item.answers) for item in quality.releases],
            [("2026-11-06.1", 4), ("2026-12-01.1", 1)],
        )
        self.assertEqual(quality.median_decision_time, timedelta(hours=3))
        self.assertIsNone(answer_quality((), ()).review_coverage)
        self.assertIsNone(answer_quality((), ()).median_decision_time)

    def test_document_signal_counts_source_reasons_on_released_documents_only(self) -> None:
        records = [
            _record(0, "rejected", "outdated_source"),
            _record(1, "rejected", "incorrect_value"),
            _record(2, "rejected", "incomplete", document_ids=("doc-2",)),
            _record(3, "rejected", "unsafe_recommendation", document_ids=("doc-2",)),
            _record(4, "rejected", "TECHNICAL_REJECTION", document_ids=("doc-gone",)),
        ]
        quality = answer_quality(records, (_document("doc-1"), _document("doc-2")))
        self.assertEqual([item.document_id for item in quality.document_signals], ["doc-1"])
        self.assertEqual(quality.rejection_reasons[UNKNOWN_REASON], 1)
        gone = next(item for item in quality.documents if item.document_id == "doc-gone")
        self.assertEqual((gone.display_name, gone.release_status), ("", None))
        withdrawn = answer_quality(records, (_document("doc-1", "withdrawn"),))
        self.assertEqual(withdrawn.document_signals, ())

    def test_export_has_one_row_per_release_and_is_spreadsheet_safe(self) -> None:
        records = [_record(0, "accepted"), _record(1, "rejected", "incomplete", deployment="=cmd|' /C calc'!A0")]
        rows = quality_export_rows(answer_quality(records, ()))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(set(row) == set(QUALITY_EXPORT_COLUMNS) for row in rows))
        rejected = next(row for row in rows if row["rejected"] == "1")
        self.assertEqual((rejected["rejection_share_percent"], rejected["rejected_incomplete"]), ("100,0", "1"))
        content = to_spreadsheet_csv(rows, QUALITY_EXPORT_COLUMNS).decode("utf-8-sig")
        self.assertNotIn(";=cmd", content)

    def test_overdue_only_counts_answers_waiting_for_a_second_person(self) -> None:
        now = datetime(2026, 11, 10, tzinfo=UTC)
        old = AIProvenance("azure-openai", "chat", "s", "r", generated_at=now - REVIEW_TARGET - timedelta(minutes=1))
        fresh = dataclasses.replace(old, generated_at=now - REVIEW_TARGET + timedelta(minutes=1))
        safety = dataclasses.replace(_answer(UseCase.SAFETY_RELEVANT_DIAGNOSIS), provenance=old)
        items = (
            StoredAnswer(safety, False),
            StoredAnswer(dataclasses.replace(safety, provenance=fresh), False),
            StoredAnswer(dataclasses.replace(_answer(), provenance=old), True),
        )
        self.assertEqual(overdue_reviews(items, now), (items[0],))


if __name__ == "__main__":
    unittest.main()
