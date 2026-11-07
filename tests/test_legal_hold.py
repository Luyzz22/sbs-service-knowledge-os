import unittest
from datetime import UTC, datetime, timedelta

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.repository import InMemoryRepository, LegalHoldRecord


def _principal(role: str, tenant: str = "tenant-a") -> UserPrincipal:
    return UserPrincipal(role, tenant, role.title(), role, permissions=ROLE_PERMISSIONS[role])


class LegalHoldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.admin = _principal("admin")
        self.review = datetime.now(UTC) + timedelta(days=90)

    def _hold(self, **overrides: object) -> LegalHoldRecord:
        values: dict[str, object] = {
            "case_reference": "LH-2026-014",
            "reason_code": "warranty_claim",
            "record_classes": ("incident", "audit_event", "incident"),
            "review_at": self.review,
        }
        values.update(overrides)
        return self.repository.create_legal_hold(self.admin, **values)  # type: ignore[arg-type]

    def test_hold_is_recorded_with_a_normalised_scope(self) -> None:
        hold = self._hold(case_reference="  LH-2026-014 ")
        self.assertEqual(hold.case_reference, "LH-2026-014")
        self.assertEqual(hold.record_classes, ("audit_event", "incident"))
        self.assertIsNone(hold.released_at)
        self.assertEqual(self.repository.list_legal_holds(self.admin), (hold,))

    def test_invalid_input_is_rejected(self) -> None:
        cases = {
            "LEGAL_HOLD_CASE_REFERENCE_INVALID": {"case_reference": "Max Mustermann"},
            "LEGAL_HOLD_REASON_INVALID": {"reason_code": "curiosity"},
            "LEGAL_HOLD_SCOPE_INVALID": {"record_classes": ()},
        }
        for code, override in cases.items():
            with self.subTest(code), self.assertRaisesRegex(ValueError, code):
                self._hold(**override)
        with self.assertRaisesRegex(ValueError, "LEGAL_HOLD_SCOPE_INVALID"):
            self._hold(record_classes=("assets",))

    def test_review_date_must_be_future_and_within_a_year(self) -> None:
        now = datetime.now(UTC)
        for review in (now - timedelta(minutes=1), now + timedelta(days=400), datetime(2027, 1, 1)):
            with self.subTest(review), self.assertRaisesRegex(ValueError, "LEGAL_HOLD_REVIEW_DATE_INVALID"):
                self._hold(review_at=review)

    def test_only_admins_manage_holds(self) -> None:
        for role in ("supervisor", "technician", "viewer"):
            with self.subTest(role), self.assertRaisesRegex(PermissionError, "LEGAL_HOLD_MANAGE_REQUIRED"):
                self.repository.create_legal_hold(
                    _principal(role),
                    case_reference="LH-1",
                    reason_code="litigation",
                    record_classes=("incident",),
                    review_at=self.review,
                )
        hold = self._hold()
        with self.assertRaises(PermissionError):
            self.repository.release_legal_hold(_principal("supervisor"), hold.hold_id)

    def test_release_is_final_and_tenant_scoped(self) -> None:
        hold = self._hold()
        with self.assertRaises(KeyError):
            self.repository.release_legal_hold(_principal("admin", "tenant-b"), hold.hold_id)
        released = self.repository.release_legal_hold(self.admin, hold.hold_id)
        self.assertIsNotNone(released.released_at)
        with self.assertRaises(KeyError):
            self.repository.release_legal_hold(self.admin, hold.hold_id)
        self.assertEqual(self.repository.list_legal_holds(_principal("admin", "tenant-b")), ())

    def test_overdue_review_is_flagged_but_never_releases(self) -> None:
        hold = self._hold()
        later = hold.review_at + timedelta(days=1)
        self.assertTrue(hold.review_overdue(later))
        self.assertFalse(hold.review_overdue(hold.review_at - timedelta(days=1)))
        self.assertIsNone(self.repository.list_legal_holds(self.admin)[0].released_at)
        released = self.repository.release_legal_hold(self.admin, hold.hold_id)
        self.assertFalse(released.review_overdue(later))


if __name__ == "__main__":
    unittest.main()
