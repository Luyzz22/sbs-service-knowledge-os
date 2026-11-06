import unittest
from dataclasses import fields
from datetime import UTC, datetime, timedelta

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.interop import to_spreadsheet_csv
from hydraulikdoc.maintenance_kpis import (
    KPI_EXPORT_COLUMNS,
    incident_times,
    kpi_export_rows,
    maintenance_kpis,
)
from hydraulikdoc.repository import AssetRecord, IncidentLifecycle, InMemoryRepository, StatusChange

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(days=90)


def _lifecycle(
    incident_id: str,
    asset_id: str,
    created_hours_ago: float,
    steps: tuple[tuple[str | None, str, float], ...],
    *,
    status: str,
    severity: str = "p3",
) -> IncidentLifecycle:
    """Steps are (previous, new, hours after creation)."""
    created = NOW - timedelta(hours=created_hours_ago)
    return IncidentLifecycle(
        incident_id,
        asset_id,
        severity,
        status,
        created,
        tuple(StatusChange(previous, new, created + timedelta(hours=offset)) for previous, new, offset in steps),
    )


def _asset(asset_id: str, name: str, functional_location: str = "") -> AssetRecord:
    return AssetRecord(asset_id, "tenant-a", name, "Werk 1", "", "", "high", "active", NOW, functional_location)


RESOLVED_STEPS = (
    (None, "new", 0),
    ("new", "acknowledged", 0.5),
    ("acknowledged", "in_progress", 1),
    ("in_progress", "resolved", 6),
)


class IncidentTimesTests(unittest.TestCase):
    def test_response_and_restoration_come_from_documented_steps(self) -> None:
        times = incident_times(_lifecycle("i1", "PU-1", 10, RESOLVED_STEPS, status="resolved"))
        self.assertEqual(times.response, timedelta(minutes=30))
        self.assertEqual(times.restoration, timedelta(hours=6))
        self.assertEqual(times.reopened, 0)

    def test_reopened_incident_is_restored_at_its_last_resolution(self) -> None:
        steps = (
            *RESOLVED_STEPS,
            ("resolved", "in_progress", 8),
            ("in_progress", "resolved", 20),
            ("resolved", "closed", 30),
        )
        times = incident_times(_lifecycle("i1", "PU-1", 40, steps, status="closed"))
        self.assertEqual(times.restoration, timedelta(hours=20))
        self.assertEqual(times.reopened, 1)

    def test_reopened_and_still_open_incident_has_no_restoration(self) -> None:
        steps = (*RESOLVED_STEPS, ("resolved", "in_progress", 8))
        self.assertIsNone(incident_times(_lifecycle("i1", "PU-1", 10, steps, status="in_progress")).restoration)

    def test_incident_without_history_keeps_unknown_times(self) -> None:
        times = incident_times(_lifecycle("legacy", "PU-1", 10, (), status="closed"))
        self.assertIsNone(times.response)
        self.assertIsNone(times.restoration)

    def test_direct_start_of_work_counts_as_response(self) -> None:
        steps = ((None, "new", 0), ("new", "in_progress", 2))
        self.assertEqual(
            incident_times(_lifecycle("i1", "PU-1", 5, steps, status="in_progress")).response, timedelta(hours=2)
        )


class MaintenanceKpiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lifecycles = (
            _lifecycle("a1", "PU-1", 24 * 40, RESOLVED_STEPS, status="resolved", severity="p1"),
            _lifecycle(
                "a2",
                "PU-1",
                24 * 20,
                (*RESOLVED_STEPS, ("resolved", "in_progress", 7), ("in_progress", "resolved", 10)),
                status="closed",
            ),
            _lifecycle("b1", "VA-2", 24 * 5, ((None, "new", 0),), status="new"),
            _lifecycle("legacy", "VA-2", 24 * 60, (), status="closed"),
            _lifecycle("old", "PU-1", 24 * 200, RESOLVED_STEPS, status="resolved"),
        )
        self.assets = (_asset("PU-1", "Hauptpumpe", "WERK1-PRESSE-01"), _asset("VA-2", "Ventilblock"))
        self.kpis = maintenance_kpis(self.lifecycles, self.assets, window_start=WINDOW_START, now=NOW)

    def test_window_excludes_older_incidents(self) -> None:
        self.assertEqual(self.kpis.incidents, 4)
        self.assertEqual(self.kpis.without_history, 1)

    def test_tenant_figures(self) -> None:
        self.assertEqual(self.kpis.open_incidents, 1)
        self.assertEqual(self.kpis.mean_response, timedelta(minutes=30))
        self.assertEqual(self.kpis.mean_restoration, timedelta(hours=8))
        self.assertEqual(self.kpis.median_restoration, timedelta(hours=8))
        self.assertEqual(self.kpis.oldest_open, timedelta(days=5))
        # Restored: a1 (no reopen), a2 (reopened), legacy (no recorded reopen).
        self.assertAlmostEqual(self.kpis.first_time_fix_rate or 0, 2 / 3)

    def test_asset_figures_and_repeat_failure(self) -> None:
        pump, valve = self.kpis.assets
        self.assertEqual(
            (pump.asset_id, pump.name, pump.functional_location), ("PU-1", "Hauptpumpe", "WERK1-PRESSE-01")
        )
        self.assertEqual((pump.incidents, pump.eight_d_incidents, pump.reopened), (2, 1, 1))
        self.assertEqual(pump.mean_interval, timedelta(days=20))
        self.assertTrue(pump.repeat_failure)
        self.assertEqual(self.kpis.repeat_failure_assets, (pump,))
        self.assertFalse(valve.repeat_failure)
        self.assertEqual(valve.mean_interval, timedelta(days=55))
        self.assertIsNone(valve.mean_restoration)

    def test_unknown_asset_falls_back_to_its_id(self) -> None:
        kpis = maintenance_kpis(self.lifecycles, (), window_start=WINDOW_START, now=NOW)
        self.assertEqual({item.name for item in kpis.assets}, {"PU-1", "VA-2"})

    def test_empty_window(self) -> None:
        kpis = maintenance_kpis((), self.assets, window_start=WINDOW_START, now=NOW)
        self.assertEqual((kpis.incidents, kpis.assets), (0, ()))
        self.assertIsNone(kpis.mean_restoration)
        self.assertIsNone(kpis.first_time_fix_rate)
        self.assertIsNone(kpis.oldest_open)

    def test_figures_carry_no_person_reference(self) -> None:
        names = {field.name for record in (IncidentLifecycle, StatusChange) for field in fields(record)}
        self.assertFalse(names & {"actor_token", "actor_role", "subject_id", "display_name", "is_own"})

    def test_export_rows_are_spreadsheet_safe(self) -> None:
        assets = (_asset("PU-1", "=SUM(A1)"),)
        kpis = maintenance_kpis(self.lifecycles, assets, window_start=WINDOW_START, now=NOW)
        rows = kpi_export_rows(kpis)
        self.assertEqual(set(rows[0]), set(KPI_EXPORT_COLUMNS))
        self.assertEqual(rows[0]["mean_restoration_hours"], "8,0")
        self.assertEqual(rows[0]["mean_interval_days"], "20,0")
        self.assertEqual(rows[0]["repeat_failure"], "1")
        self.assertEqual(rows[1]["mean_restoration_hours"], "")
        content = to_spreadsheet_csv(rows, KPI_EXPORT_COLUMNS).decode("utf-8")
        self.assertIn(";'=SUM(A1);", content)


class LifecycleRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        self.technician = UserPrincipal(
            "tech", "tenant-a", "Tech", "technician", permissions=ROLE_PERMISSIONS["technician"]
        )

    def test_lifecycles_follow_the_workflow_and_stay_in_the_tenant(self) -> None:
        incident = self.repository.create_incident(
            self.technician, asset_id="PU-1", title="Druckabfall", severity="p3", details=""
        )
        self.repository.transition_incident(self.technician, incident.incident_id, expected="new", target="in_progress")
        foreign = UserPrincipal("x", "tenant-b", "X", "admin", permissions=ROLE_PERMISSIONS["admin"])
        self.repository.create_incident(foreign, asset_id="PU-9", title="Fremd", severity="p3", details="")

        since = datetime.now(UTC) - timedelta(days=1)
        lifecycles = self.repository.list_incident_lifecycles(self.technician, since=since, limit=100)
        self.assertEqual([item.incident_id for item in lifecycles], [incident.incident_id])
        self.assertEqual(
            [(change.previous_status, change.new_status) for change in lifecycles[0].changes],
            [(None, "new"), ("new", "in_progress")],
        )
        self.assertEqual(lifecycles[0].status, "in_progress")

    def test_scripted_time_is_scoped_to_one_tenant_and_released(self) -> None:
        foreign = UserPrincipal("x", "tenant-b", "X", "admin", permissions=ROLE_PERMISSIONS["admin"])
        staged = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        with self.repository.scripted_time(self.technician, staged):
            own = self.repository.create_incident(
                self.technician, asset_id="PU-1", title="T", severity="p4", details=""
            )
            other = self.repository.create_incident(foreign, asset_id="PU-9", title="T", severity="p4", details="")
        later = self.repository.create_incident(self.technician, asset_id="PU-1", title="T", severity="p4", details="")
        self.assertEqual(own.created_at, staged)
        self.assertGreater(other.created_at, staged + timedelta(days=30))
        self.assertGreater(later.created_at, staged + timedelta(days=30))

    def test_window_and_limit(self) -> None:
        for index in range(3):
            self.repository.create_incident(
                self.technician, asset_id=f"PU-{index}", title="T", severity="p4", details=""
            )
        since = datetime.now(UTC) - timedelta(days=1)
        self.assertEqual(len(self.repository.list_incident_lifecycles(self.technician, since=since, limit=2)), 2)
        future = datetime.now(UTC) + timedelta(minutes=1)
        self.assertEqual(self.repository.list_incident_lifecycles(self.technician, since=future, limit=10), ())


if __name__ == "__main__":
    unittest.main()
