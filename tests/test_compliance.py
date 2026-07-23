from datetime import datetime, timezone
import json
import logging
import unittest

from compliance.audit import AuditLogger, AuditOutcome, SubjectPseudonymizer
from compliance.retention import RecordClass, RetentionPolicy


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pseudonymizer = SubjectPseudonymizer(b"x" * 32)

    def test_pseudonyms_are_stable_and_do_not_expose_identifier(self) -> None:
        first = self.pseudonymizer.token("operator@example.com")
        second = self.pseudonymizer.token("operator@example.com")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("psn_v1_"))
        self.assertNotIn("operator", first)

    def test_audit_logger_drops_unapproved_personal_metadata(self) -> None:
        capture = _CaptureHandler()
        logger = logging.getLogger("test.compliance.audit")
        logger.handlers = [capture]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        audit = AuditLogger(self.pseudonymizer, logger)

        event = audit.emit(
            action="knowledge.query.completed",
            outcome=AuditOutcome.SUCCESS,
            actor_id="operator@example.com",
            resource_type="knowledge_base",
            resource_id="customer-manual.pdf",
            metadata={
                "duration_ms": 42,
                "model": "gpt-4o",
                "question": "personal free text must not be logged",
                "email": "operator@example.com",
            },
        )

        self.assertEqual(event.metadata, {"duration_ms": 42, "model": "gpt-4o"})
        payload = json.loads(capture.messages[0])
        serialized = json.dumps(payload)
        self.assertNotIn("operator@example.com", serialized)
        self.assertNotIn("customer-manual.pdf", serialized)
        self.assertNotIn("personal free text", serialized)


class RetentionTests(unittest.TestCase):
    def test_environment_policy_calculates_timezone_safe_expiry(self) -> None:
        policy = RetentionPolicy.from_environment(
            {
                "AI_INTERACTION_RETENTION_DAYS": "7",
                "AUDIT_EVENT_RETENTION_DAYS": "90",
                "CONTRACT_ACCEPTANCE_RETENTION_DAYS": "365",
                "DATA_SUBJECT_REQUEST_RETENTION_DAYS": "180",
                "UPLOADED_CONTENT_RETENTION_DAYS": "1",
            }
        )
        created_at = datetime(2026, 7, 23, tzinfo=timezone.utc)

        expires_at = policy.expires_at(RecordClass.AI_INTERACTION, created_at)

        self.assertEqual(expires_at, datetime(2026, 7, 30, tzinfo=timezone.utc))

    def test_naive_timestamps_are_rejected(self) -> None:
        policy = RetentionPolicy.from_environment({})

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            policy.expires_at(RecordClass.AUDIT_EVENT, datetime(2026, 7, 23))
