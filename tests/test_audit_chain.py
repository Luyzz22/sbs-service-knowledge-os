import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from compliance.audit import AuditEvent, AuditOutcome
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.repository import (
    InMemoryRepository,
    _audit_chain_key,
    _audit_chain_row,
    _event_hash,
    verify_audit_chain_rows,
)

KEY = _audit_chain_key("k" * 32)


def _chain(count: int, start: int = 1, previous: str | None = None) -> list[tuple[int, str | None, str, AuditEvent]]:
    rows = []
    for sequence in range(start, start + count):
        event = AuditEvent(
            action=f"test.event.{sequence}",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=datetime(2026, 11, 7, tzinfo=UTC) + timedelta(minutes=sequence),
            metadata={"source_count": sequence},
        )
        digest = _event_hash(KEY, previous, event)
        rows.append((sequence, previous, digest, event))
        previous = digest
    return rows


class ChainVerificationTests(unittest.TestCase):
    def test_untouched_chain_is_intact(self) -> None:
        rows = _chain(4)
        report = verify_audit_chain_rows(KEY, rows)
        self.assertTrue(report.intact)
        self.assertEqual((report.event_count, report.first_sequence, report.head_sequence), (4, 1, 4))
        self.assertEqual(report.head_hash, rows[-1][2])
        self.assertFalse(report.starts_after_purge)

    def test_changed_event_fails_with_its_sequence(self) -> None:
        rows = _chain(4)
        sequence, previous, digest, event = rows[2]
        rows[2] = (sequence, previous, digest, replace(event, metadata={"source_count": 999}))
        report = verify_audit_chain_rows(KEY, rows)
        self.assertFalse(report.intact)
        self.assertEqual((report.reason, report.broken_sequence, report.event_count), ("HASH_MISMATCH", 3, 2))

    def test_removed_event_breaks_the_link(self) -> None:
        rows = _chain(4)
        del rows[1]
        report = verify_audit_chain_rows(KEY, rows)
        self.assertEqual((report.intact, report.reason, report.broken_sequence), (False, "LINK_MISMATCH", 3))

    def test_wrong_key_fails(self) -> None:
        report = verify_audit_chain_rows(_audit_chain_key("x" * 32), _chain(2))
        self.assertEqual((report.intact, report.reason, report.broken_sequence), (False, "HASH_MISMATCH", 1))

    def test_truncated_tail_is_only_visible_through_an_anchor(self) -> None:
        rows = _chain(5)
        old_head = (rows[-1][0], rows[-1][2])
        truncated = rows[:3]
        self.assertTrue(verify_audit_chain_rows(KEY, truncated).intact)
        report = verify_audit_chain_rows(KEY, truncated, anchor=old_head)
        self.assertEqual((report.intact, report.anchor_status), (False, "ANCHOR_MISSING"))

    def test_anchor_matches_or_reports_a_rewrite(self) -> None:
        rows = _chain(5)
        self.assertEqual(verify_audit_chain_rows(KEY, rows, anchor=(3, rows[2][2])).anchor_status, "MATCH")
        report = verify_audit_chain_rows(KEY, rows, anchor=(3, "0" * 64))
        self.assertEqual((report.intact, report.anchor_status), (False, "ANCHOR_MISMATCH"))

    def test_chain_after_retention_purge_starts_at_a_kept_event(self) -> None:
        full = _chain(8)
        kept = full[4:]
        report = verify_audit_chain_rows(KEY, kept, anchor=(2, full[1][2]))
        self.assertTrue(report.intact)
        self.assertTrue(report.starts_after_purge)
        self.assertEqual((report.first_sequence, report.anchor_status), (5, "PURGED"))

    def test_empty_chain(self) -> None:
        report = verify_audit_chain_rows(KEY, [])
        self.assertEqual((report.intact, report.event_count, report.head_hash), (True, 0, None))

    def test_database_row_is_rebuilt_in_utc(self) -> None:
        event = AuditEvent(
            action="test.event",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=datetime(2026, 11, 7, 9, 30, tzinfo=UTC),
            expires_at=datetime(2028, 11, 6, 9, 30, tzinfo=UTC),
            metadata={"source_count": 1},
        )
        digest = _event_hash(KEY, None, event)
        berlin = timezone(timedelta(hours=1))
        # PostgreSQL returns timestamptz in the session time zone; the hash was computed in UTC.
        row = (
            1,
            None,
            digest,
            event.event_id,
            event.action,
            event.outcome.value,
            event.actor_token,
            event.resource_type,
            event.resource_token,
            dict(event.metadata),
            event.occurred_at.astimezone(berlin),
            event.expires_at.astimezone(berlin),
        )
        self.assertTrue(verify_audit_chain_rows(KEY, [_audit_chain_row(row)]).intact)


class RepositoryVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.admin = UserPrincipal("adm", "tenant-a", "Adm", "admin", permissions=ROLE_PERMISSIONS["admin"])

    def test_emitted_events_verify_and_tampering_is_found(self) -> None:
        for action in ("one", "two", "three"):
            self.repository.emit_audit(self.admin, action=f"test.{action}", outcome=AuditOutcome.SUCCESS)
        report = self.repository.verify_audit_chain(self.admin)
        self.assertEqual((report.intact, report.event_count), (True, 3))
        event, digest = self.repository._audit[1]
        self.repository._audit[1] = (replace(event, outcome=AuditOutcome.FAILURE), digest)
        broken = self.repository.verify_audit_chain(self.admin)
        self.assertEqual((broken.intact, broken.reason, broken.broken_sequence), (False, "HASH_MISMATCH", 2))

    def test_only_admins_may_verify(self) -> None:
        supervisor = UserPrincipal("sup", "tenant-a", "Sup", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"])
        with self.assertRaisesRegex(PermissionError, "AUDIT_VERIFY_REQUIRED"):
            self.repository.verify_audit_chain(supervisor)


class AnchorFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        script = Path(__file__).resolve().parents[1] / "ops" / "scripts" / "verify-audit-chain.py"
        spec = importlib.util.spec_from_file_location("verify_audit_chain", script)
        assert spec and spec.loader
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_previous_run_output_is_read_as_anchors(self) -> None:
        output = {
            "event": "audit_chain_verification_finished",
            "tenants": {
                "tenant-a": {"intact": True, "sequence": 41, "event_hash": "a" * 64},
                "tenant-empty": {"intact": True, "sequence": None, "event_hash": None},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchors.json"
            path.write_text(json.dumps(output), encoding="utf-8")
            self.assertEqual(self.module.load_anchors(str(path)), {"tenant-a": (41, "a" * 64)})
        self.assertEqual(self.module.load_anchors(None), {})


if __name__ == "__main__":
    unittest.main()
