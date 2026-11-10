"""Operating limits per asset: proposed with a source, released by a second person, used read-only."""

import dataclasses
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.condition_monitoring import SensorReading, Severity, assess_condition
from hydraulikdoc.config import AppSettings
from hydraulikdoc.demo import DEMO_LIMITS, seed_demo_tenant
from hydraulikdoc.operating_limits import (
    LIMIT_FIELDS,
    LIMIT_REJECTION_REASONS,
    LimitValues,
    OperatingLimitSet,
    pending_limits,
    released_limits,
)
from hydraulikdoc.repository import InMemoryRepository
from hydraulikdoc.security import ValidatedUpload

ROOT = Path(__file__).resolve().parents[1]
TENANT = "tenant-a"
ASSET = "W1-PRESSE-04"
REFERENCE = "BA-HA-250 Rev. 1, Kapitel 4.2"


def _principal(subject: str, role: str, tenant: str = TENANT) -> UserPrincipal:
    return UserPrincipal(subject, tenant, subject.title(), role, permissions=ROLE_PERMISSIONS[role])


def _code(error: BaseException) -> str:
    return str(error.args[0])


class OperatingLimitsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.technician = _principal("tech", "technician")
        self.supervisor = _principal("sup", "supervisor")
        self.second_supervisor = _principal("sup-2", "supervisor")
        self.viewer = _principal("viewer", "viewer")
        self.repository.upsert_asset(
            self.supervisor,
            asset_id=ASSET,
            name="Presse 04",
            site="Werk 1",
            manufacturer="",
            model="HA-250",
            criticality="high",
        )

    def _propose(
        self, principal: UserPrincipal | None = None, values: LimitValues | None = None, **source: object
    ) -> OperatingLimitSet:
        return self.repository.propose_operating_limits(
            principal or self.technician,
            ASSET,
            values or LimitValues(pressure_warning_bar=230.0, pressure_critical_bar=250.0),
            source_reference=str(source.pop("source_reference", REFERENCE)),
            **source,  # type: ignore[arg-type]
        )

    def _released(self, values: LimitValues | None = None) -> OperatingLimitSet:
        proposal = self._propose(values=values)
        return self.repository.release_operating_limits(self.supervisor, proposal.limit_set_id).limits

    def _document(self, released: bool = True, pages: int = 20) -> str:
        record = self.repository.register_document(
            self.technician,
            ValidatedUpload(str(uuid.uuid4()), "Handbuch.pdf", uuid.uuid4().hex * 2, b"", "application/pdf"),
        )
        self.repository.mark_document_indexed(self.technician, record.document_id, pages)
        if released:
            self.repository.release_document(
                self.supervisor, record.document_id, review_due_at=datetime.now(UTC) + timedelta(days=180)
            )
        return record.document_id


class ValuesTests(unittest.TestCase):
    def test_defaults_match_the_previous_session_defaults(self) -> None:
        values = LimitValues()
        self.assertEqual(values.envelope().pressure_critical_bar, 300.0)
        self.assertEqual(values.fluid_limits().water_critical_pct, 0.1)

    def test_inconsistent_or_invalid_values_are_rejected_with_one_code(self) -> None:
        for values in (
            {"pressure_warning_bar": 300.0, "pressure_critical_bar": 300.0},
            {"temperature_warning_c": 90.0},
            {"water_warning_pct": 0.2, "water_critical_pct": 0.1},
            {"water_critical_pct": 101.0},
            {"particle_warning": -1.0},
            {"minimum_flow_l_min": float("nan")},
        ):
            with self.subTest(values), self.assertRaises(ValueError) as raised:
                LimitValues(**values)
            self.assertEqual(_code(raised.exception), "OPERATING_LIMITS_VALUES_INVALID")

    def test_released_values_drive_the_assessment(self) -> None:
        values = LimitValues(pressure_warning_bar=230.0, pressure_critical_bar=250.0)
        reading = SensorReading(datetime(2026, 11, 1, tzinfo=UTC), pressure_bar=255.0)
        self.assertIs(assess_condition((reading,), values.envelope()).severity, Severity.CRITICAL)
        self.assertIs(assess_condition((reading,), LimitValues().envelope()).severity, Severity.WARNING)


class ProposalTests(OperatingLimitsCase):
    def test_a_proposal_is_a_draft_that_no_assessment_uses(self) -> None:
        proposal = self._propose()
        self.assertEqual((proposal.status, proposal.version, proposal.is_own), ("draft", 1, True))
        sets = self.repository.list_operating_limits(self.supervisor, ASSET)
        self.assertIsNone(released_limits(sets, ASSET))
        self.assertEqual(pending_limits(sets, ASSET), dataclasses.replace(proposal, is_own=False))

    def test_proposal_rules(self) -> None:
        with self.assertRaises(PermissionError) as denied:
            self._propose(self.viewer)
        self.assertEqual(_code(denied.exception), "OPERATING_LIMITS_PROPOSE_REQUIRED")
        with self.assertRaises(ValueError) as unknown:
            self.repository.propose_operating_limits(
                self.technician, "UNBEKANNT", LimitValues(), source_reference=REFERENCE
            )
        self.assertEqual(_code(unknown.exception), "OPERATING_LIMITS_ASSET_UNKNOWN")
        for reference in ("", "  ab ", "x" * 161):
            with self.subTest(reference), self.assertRaises(ValueError) as invalid:
                self._propose(source_reference=reference)
            self.assertEqual(_code(invalid.exception), "OPERATING_LIMITS_SOURCE_REFERENCE_INVALID")
        self.assertEqual(self._propose(source_reference="  BA-HA-250   Rev. 1 ").source_reference, "BA-HA-250 Rev. 1")
        with self.assertRaises(ValueError) as pending:
            self._propose(self.supervisor)
        self.assertEqual(_code(pending.exception), "OPERATING_LIMITS_PENDING")

    def test_a_linked_document_must_be_released_and_contain_the_page(self) -> None:
        draft_document = self._document(released=False)
        with self.assertRaises(ValueError) as unreleased:
            self._propose(source_document_id=draft_document, source_page=1)
        self.assertEqual(_code(unreleased.exception), "OPERATING_LIMITS_SOURCE_NOT_RELEASED")
        document = self._document(pages=20)
        for page in (None, 0, 21):
            with self.subTest(page), self.assertRaises(ValueError) as wrong_page:
                self._propose(source_document_id=document, source_page=page)
            self.assertEqual(_code(wrong_page.exception), "OPERATING_LIMITS_SOURCE_PAGE_INVALID")
        with self.assertRaises(ValueError):
            self._propose(source_page=3)
        proposal = self._propose(source_document_id=document, source_page=12)
        self.assertEqual((proposal.source_document_name, proposal.source_page), ("Handbuch.pdf", 12))
        self.assertFalse(proposal.source_withdrawn)


class ReleaseTests(OperatingLimitsCase):
    def test_release_needs_a_second_person_with_the_release_role(self) -> None:
        own = self._propose(self.supervisor)
        with self.assertRaises(PermissionError) as four_eyes:
            self.repository.release_operating_limits(self.supervisor, own.limit_set_id)
        self.assertEqual(_code(four_eyes.exception), "FOUR_EYES_LIMITS_REQUIRED")
        admin = _principal("sup", "admin")
        with self.assertRaises(PermissionError):
            self.repository.release_operating_limits(admin, own.limit_set_id)
        with self.assertRaises(PermissionError) as role:
            self.repository.release_operating_limits(self.technician, own.limit_set_id)
        self.assertEqual(_code(role.exception), "OPERATING_LIMITS_RELEASE_REQUIRED")
        released = self.repository.release_operating_limits(self.second_supervisor, own.limit_set_id)
        self.assertEqual((released.limits.status, released.superseded), ("released", None))
        self.assertIsNotNone(released.limits.decided_at)
        with self.assertRaises(ValueError) as again:
            self.repository.release_operating_limits(self.second_supervisor, own.limit_set_id)
        self.assertEqual(_code(again.exception), "OPERATING_LIMITS_NOT_DRAFT")

    def test_a_new_version_stays_a_proposal_and_replaces_the_old_one_on_release(self) -> None:
        first = self._released()
        second = self._propose(values=LimitValues(pressure_warning_bar=220.0, pressure_critical_bar=240.0))
        self.assertEqual(second.version, 2)
        in_force = released_limits(self.repository.list_operating_limits(self.supervisor), ASSET)
        self.assertEqual(in_force.limit_set_id if in_force else None, first.limit_set_id)

        result = self.repository.release_operating_limits(self.supervisor, second.limit_set_id)
        self.assertEqual(result.superseded.limit_set_id if result.superseded else None, first.limit_set_id)
        sets = self.repository.list_operating_limits(self.technician, ASSET)
        self.assertEqual([(item.version, item.status) for item in sets], [(2, "released"), (1, "superseded")])
        self.assertEqual(sum(1 for item in sets if item.status == "released"), 1)
        self.assertIsNotNone(sets[1].superseded_at)
        self.assertEqual(sets[0].values.pressure_critical_bar, 240.0)

    def test_withdrawing_the_source_flags_the_limits_in_force_and_blocks_a_pending_release(self) -> None:
        document = self._document()
        proposal = self._propose(source_document_id=document, source_page=4)
        released = self.repository.release_operating_limits(self.supervisor, proposal.limit_set_id).limits
        self.assertFalse(released.source_withdrawn)
        follow_up = self._propose(source_document_id=document, source_page=5)
        self.repository.withdraw_document(self.supervisor, document, "safety_notice")

        sets = self.repository.list_operating_limits(self.supervisor, ASSET)
        current = released_limits(sets, ASSET)
        self.assertTrue(current is not None and current.source_withdrawn)
        with self.assertRaises(ValueError) as blocked:
            self.repository.release_operating_limits(self.supervisor, follow_up.limit_set_id)
        self.assertEqual(_code(blocked.exception), "OPERATING_LIMITS_SOURCE_NOT_RELEASED")
        self.repository.delete_document(self.supervisor, document)
        current = released_limits(self.repository.list_operating_limits(self.supervisor, ASSET), ASSET)
        self.assertTrue(current is not None and current.source_withdrawn and not current.source_document_name)

    def test_rejection_by_the_release_role_or_by_the_proposer(self) -> None:
        proposal = self._propose()
        with self.assertRaises(PermissionError):
            self.repository.reject_operating_limits(
                _principal("tech-2", "technician"), proposal.limit_set_id, "not_applicable"
            )
        with self.assertRaises(ValueError) as reason:
            self.repository.reject_operating_limits(self.supervisor, proposal.limit_set_id, "Tippfehler von Max")
        self.assertEqual(_code(reason.exception), "OPERATING_LIMITS_REASON_INVALID")
        rejected = self.repository.reject_operating_limits(self.technician, proposal.limit_set_id, "value_incorrect")
        self.assertEqual((rejected.status, rejected.decision_reason), ("rejected", "value_incorrect"))
        with self.assertRaises(ValueError):
            self.repository.release_operating_limits(self.supervisor, proposal.limit_set_id)
        self.assertEqual(self._propose().version, 2)

    def test_limits_stay_within_the_tenant(self) -> None:
        proposal = self._propose()
        outsider = _principal("sup-2", "supervisor", tenant="tenant-b")
        self.assertEqual(self.repository.list_operating_limits(outsider), ())
        with self.assertRaises(KeyError):
            self.repository.release_operating_limits(outsider, proposal.limit_set_id)


class PersonalDataTests(OperatingLimitsCase):
    def test_records_carry_no_person(self) -> None:
        fields = {item.name for item in dataclasses.fields(OperatingLimitSet)}
        self.assertFalse({name for name in fields if "token" in name or "actor" in name or "by" in name})

    def test_subject_export_lists_own_proposals_and_decisions(self) -> None:
        proposal = self._propose()
        self.repository.release_operating_limits(self.supervisor, proposal.limit_set_id)
        rejected = self._propose(self.supervisor)
        self.repository.reject_operating_limits(self.supervisor, rejected.limit_set_id, "replaced_by_proposal")

        def steps(principal: UserPrincipal) -> list[tuple[int, str]]:
            export = self.repository.subject_export(principal)
            return [(item["version"], item["step"]) for item in export["operating_limit_steps"]]

        self.assertEqual(steps(self.technician), [(1, "proposed")])
        self.assertEqual(steps(self.supervisor), [(1, "released"), (2, "proposed"), (2, "rejected")])
        self.assertEqual(steps(self.second_supervisor), [])


class DemoTests(unittest.TestCase):
    def test_demo_has_released_limits_and_a_proposal_for_the_person_loading_it(self) -> None:
        repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test", "AI_BACKEND": "demo"}))
        loader = _principal("demo-loader", "supervisor")
        seed_demo_tenant(loader, repository)
        sets = repository.list_operating_limits(loader)
        released = {item.asset_id for item in sets if item.status == "released"}
        drafts = [item for item in sets if item.status == "draft"]
        self.assertEqual(released, {item.asset_id for item in DEMO_LIMITS if item.released})
        self.assertEqual([item.is_own for item in drafts], [False])
        self.assertTrue(all(item.source_document_name.startswith("DEMO") for item in sets))

        # Releasing revision 2 of the manual withdraws revision 1, the source of both sets.
        revision_2 = next(
            item
            for item in repository.list_documents(loader)
            if item.release_status == "draft" and item.status == "ready"
        )
        repository.release_document(
            loader, revision_2.document_id, review_due_at=datetime.now(UTC) + timedelta(days=90)
        )
        after = repository.list_operating_limits(loader)
        self.assertTrue(all(item.source_withdrawn for item in after))
        with self.assertRaises(ValueError):
            repository.release_operating_limits(loader, drafts[0].limit_set_id)


class SchemaTests(unittest.TestCase):
    def test_table_is_tenant_isolated_and_released_values_are_not_updatable(self) -> None:
        migration = (ROOT / "db" / "migrations" / "001_enterprise.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE operating_limits FORCE ROW LEVEL SECURITY;", migration)
        self.assertIn("CREATE POLICY tenant_operating_limits ON operating_limits", migration)
        self.assertIn("operating_limits_released_idx", migration)
        self.assertIn("DELETE FROM public.operating_limits", migration)
        bootstrap = (ROOT / "ops" / "scripts" / "bootstrap-postgres.py").read_text(encoding="utf-8")
        # Join implicitly concatenated string literals so the grant reads as one statement.
        statements = re.sub(r'"\s*"', "", bootstrap)
        grant = re.search(r"GRANT UPDATE \(([^)]*)\) ON TABLE operating_limits", statements)
        self.assertIsNotNone(grant, "The runtime role needs a column-level UPDATE grant on operating_limits")
        assert grant is not None
        columns = {column.strip() for column in grant.group(1).split(",")}
        self.assertFalse(columns & set(LIMIT_FIELDS), "Limit values must not be updatable by the runtime role")
        self.assertLessEqual({"status", "decided_at", "retention_until"}, columns)

    def test_rejection_reasons_match_the_database_check(self) -> None:
        migration = (ROOT / "db" / "migrations" / "001_enterprise.sql").read_text(encoding="utf-8")
        for reason in LIMIT_REJECTION_REASONS:
            self.assertIn(f"'{reason}'", migration)


if __name__ == "__main__":
    unittest.main()
