import unittest
from dataclasses import replace
from datetime import timedelta

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.repository import InMemoryRepository, PrivacyTransitionRejected


def _principal(role: str, subject: str | None = None, tenant: str = "tenant-a") -> UserPrincipal:
    return UserPrincipal(subject or role, tenant, role.title(), role, permissions=ROLE_PERMISSIONS[role])


class PrivacyQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.employee = _principal("technician", "employee")
        self.dpo = _principal("admin", "dpo")
        self.request = self.repository.create_privacy_request(self.employee, "erasure")

    def _decide(self, expected: str, target: str, **kwargs: str):  # type: ignore[no-untyped-def]
        return self.repository.decide_privacy_request(
            self.dpo, self.request.request_id, expected=expected, target=target, **kwargs
        )

    def test_full_case_is_recorded_and_visible_to_the_requester(self) -> None:
        self._decide("submitted", "identity_verified")
        self._decide("identity_verified", "in_review")
        done = self._decide("in_review", "completed", decision_reason="fulfilled", evidence_reference=" DSR-2026-031 ")
        self.assertEqual(
            (done.status, done.decision_reason, done.evidence_reference), ("completed", "fulfilled", "DSR-2026-031")
        )
        self.assertIsNotNone(done.completed_at)
        own = self.repository.list_privacy_requests(self.employee)
        self.assertEqual([(item.status, item.decision_reason) for item in own], [("completed", "fulfilled")])
        exported = self.repository.subject_export(self.employee)["privacy_requests"]
        self.assertEqual(exported[0]["decision_reason"], "fulfilled")

    def test_steps_follow_the_workflow(self) -> None:
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_TRANSITION_SUBMITTED_TO_COMPLETED"):
            self._decide("submitted", "completed", decision_reason="fulfilled", evidence_reference="DSR-1")
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_STALE_STATUS"):
            self._decide("in_review", "denied", decision_reason="legal_hold", evidence_reference="DSR-1")

    def test_closing_needs_a_matching_reason_and_a_case_number(self) -> None:
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_DECISION_REASON_REQUIRED"):
            self._decide("submitted", "denied", decision_reason="fulfilled", evidence_reference="DSR-1")
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_EVIDENCE_REFERENCE_REQUIRED"):
            self._decide("submitted", "denied", decision_reason="identity_not_verified", evidence_reference="")
        denied = self._decide(
            "submitted", "denied", decision_reason="identity_not_verified", evidence_reference="DSR-7"
        )
        self.assertEqual(denied.status, "denied")
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_TRANSITION_DENIED_TO_IN_REVIEW"):
            self._decide("denied", "in_review")

    def test_nobody_handles_their_own_request(self) -> None:
        own = self.repository.create_privacy_request(self.dpo, "access")
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_OWN_REQUEST"):
            self.repository.decide_privacy_request(
                self.dpo, own.request_id, expected="submitted", target="identity_verified"
            )

    def test_only_privacy_managers_see_and_handle_the_queue(self) -> None:
        for role in ("supervisor", "technician", "viewer"):
            with self.subTest(role):
                with self.assertRaisesRegex(PermissionError, "PRIVACY_MANAGE_REQUIRED"):
                    self.repository.list_privacy_queue(_principal(role, f"other-{role}"))
                with self.assertRaisesRegex(PermissionError, "PRIVACY_MANAGE_REQUIRED"):
                    self.repository.decide_privacy_request(
                        _principal(role, f"other-{role}"),
                        self.request.request_id,
                        expected="submitted",
                        target="identity_verified",
                    )

    def test_queue_is_tenant_scoped_and_puts_the_closest_open_deadline_first(self) -> None:
        later = self.repository.create_privacy_request(_principal("viewer", "colleague"), "access")
        self._decide("submitted", "denied", decision_reason="manifestly_unfounded", evidence_reference="DSR-9")
        queue = self.repository.list_privacy_queue(self.dpo)
        self.assertEqual([item.request_id for item in queue], [later.request_id, self.request.request_id])
        self.assertEqual(self.repository.list_privacy_queue(_principal("admin", "dpo", "tenant-b")), ())

    def test_overdue_applies_to_open_requests_only(self) -> None:
        after_deadline = self.request.due_at + timedelta(minutes=1)
        self.assertTrue(self.request.overdue(after_deadline))
        self.assertFalse(self.request.overdue(self.request.due_at - timedelta(days=1)))
        self.assertFalse(replace(self.request, status="completed").overdue(after_deadline))


if __name__ == "__main__":
    unittest.main()
