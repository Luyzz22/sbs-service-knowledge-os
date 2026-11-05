"""Asset-level maintenance figures derived from the incident workflow.

Times are taken from when a workflow step was documented in HydraulikDoc, not from machine or SAP
data, so they describe the documented reaction and restoration process. Every figure is aggregated
per asset and never per person: monitoring employee performance would be subject to co-determination
(BetrVG § 87 (1) no. 6) and is deliberately out of scope.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean, median

from hydraulikdoc.repository import EIGHT_D_SEVERITIES, AssetRecord, IncidentLifecycle

OPEN_STATUSES = frozenset({"new", "acknowledged", "in_progress"})
RESTORED_STATUSES = frozenset({"resolved", "closed"})
# Two incidents on the same asset within this span count as a repeat failure that deserves a root-cause review.
REPEAT_FAILURE_SPAN = timedelta(days=30)
KPI_WINDOW_DAYS = (30, 90, 365)
KPI_INCIDENT_LIMIT = 10_000

KPI_EXPORT_COLUMNS = (
    "asset_id",
    "name",
    "site",
    "functional_location",
    "incidents",
    "eight_d_incidents",
    "open_incidents",
    "mean_response_hours",
    "mean_restoration_hours",
    "reopened",
    "mean_interval_days",
    "repeat_failure",
    "last_incident_utc",
)


@dataclass(frozen=True)
class IncidentTimes:
    incident_id: str
    asset_id: str
    severity: str
    status: str
    created_at: datetime
    response: timedelta | None
    restoration: timedelta | None
    reopened: int


@dataclass(frozen=True)
class AssetKpi:
    asset_id: str
    name: str
    site: str
    functional_location: str
    incidents: int
    eight_d_incidents: int
    open_incidents: int
    mean_response: timedelta | None
    mean_restoration: timedelta | None
    reopened: int
    mean_interval: timedelta | None
    repeat_failure: bool
    last_incident: datetime


@dataclass(frozen=True)
class MaintenanceKpis:
    window_start: datetime
    window_end: datetime
    incidents: int
    open_incidents: int
    restored_incidents: int
    without_history: int
    mean_response: timedelta | None
    median_response: timedelta | None
    mean_restoration: timedelta | None
    median_restoration: timedelta | None
    first_time_fix_rate: float | None
    oldest_open: timedelta | None
    assets: tuple[AssetKpi, ...]

    @property
    def repeat_failure_assets(self) -> tuple[AssetKpi, ...]:
        return tuple(item for item in self.assets if item.repeat_failure)


def _elapsed(start: datetime, end: datetime) -> timedelta:
    return max(end - start, timedelta(0))


def incident_times(lifecycle: IncidentLifecycle) -> IncidentTimes:
    """Reaction and restoration time of one incident from its documented status changes.

    Response ends with the first step out of "new". Restoration ends with the last report as resolved,
    because a reopened incident was not restored at its first report. Incidents created before the
    workflow history existed have no recorded steps; their times stay unknown instead of being guessed.
    """
    changes = sorted(lifecycle.changes, key=lambda change: change.occurred_at)
    responded = next((change.occurred_at for change in changes if change.previous_status == "new"), None)
    restored = None
    if lifecycle.status in RESTORED_STATUSES:
        restored = next(
            (change.occurred_at for change in reversed(changes) if change.new_status == "resolved"),
            None,
        )
    return IncidentTimes(
        incident_id=lifecycle.incident_id,
        asset_id=lifecycle.asset_id,
        severity=lifecycle.severity,
        status=lifecycle.status,
        created_at=lifecycle.created_at,
        response=_elapsed(lifecycle.created_at, responded) if responded else None,
        restoration=_elapsed(lifecycle.created_at, restored) if restored else None,
        reopened=sum(
            1 for change in changes if change.previous_status == "resolved" and change.new_status == "in_progress"
        ),
    )


def _mean(values: Sequence[timedelta]) -> timedelta | None:
    return timedelta(seconds=mean(value.total_seconds() for value in values)) if values else None


def _median(values: Sequence[timedelta]) -> timedelta | None:
    return timedelta(seconds=median(value.total_seconds() for value in values)) if values else None


def _known(values: Iterable[timedelta | None]) -> list[timedelta]:
    return [value for value in values if value is not None]


def _asset_kpi(asset_id: str, times: Sequence[IncidentTimes], asset: AssetRecord | None) -> AssetKpi:
    created = sorted(item.created_at for item in times)
    gaps = [later - earlier for earlier, later in zip(created, created[1:], strict=False)]
    return AssetKpi(
        asset_id=asset_id,
        name=asset.name if asset else asset_id,
        site=asset.site if asset else "",
        functional_location=asset.functional_location if asset else "",
        incidents=len(times),
        eight_d_incidents=sum(1 for item in times if item.severity in EIGHT_D_SEVERITIES),
        open_incidents=sum(1 for item in times if item.status in OPEN_STATUSES),
        mean_response=_mean(_known(item.response for item in times)),
        mean_restoration=_mean(_known(item.restoration for item in times)),
        reopened=sum(item.reopened for item in times),
        mean_interval=_mean(gaps),
        repeat_failure=any(gap <= REPEAT_FAILURE_SPAN for gap in gaps),
        last_incident=created[-1],
    )


def _asset_order(item: AssetKpi) -> tuple[bool, int, float, str]:
    restoration = item.mean_restoration.total_seconds() if item.mean_restoration else -1.0
    return (not item.repeat_failure, -item.incidents, -restoration, item.asset_id)


def maintenance_kpis(
    lifecycles: Iterable[IncidentLifecycle],
    assets: Iterable[AssetRecord],
    *,
    window_start: datetime,
    now: datetime,
) -> MaintenanceKpis:
    """Aggregate the incidents created in ``[window_start, now]`` into tenant and per-asset figures."""
    in_window = [item for item in lifecycles if window_start <= item.created_at <= now]
    times = [incident_times(item) for item in in_window]
    register: Mapping[str, AssetRecord] = {asset.asset_id: asset for asset in assets}
    by_asset: dict[str, list[IncidentTimes]] = defaultdict(list)
    for item in times:
        by_asset[item.asset_id].append(item)

    responses = _known(item.response for item in times)
    restorations = _known(item.restoration for item in times)
    restored = [item for item in times if item.status in RESTORED_STATUSES]
    still_open = [item for item in times if item.status in OPEN_STATUSES]
    return MaintenanceKpis(
        window_start=window_start,
        window_end=now,
        incidents=len(times),
        open_incidents=len(still_open),
        restored_incidents=len(restored),
        without_history=sum(1 for item in in_window if not item.changes),
        mean_response=_mean(responses),
        median_response=_median(responses),
        mean_restoration=_mean(restorations),
        median_restoration=_median(restorations),
        first_time_fix_rate=(sum(1 for item in restored if not item.reopened) / len(restored)) if restored else None,
        oldest_open=max((_elapsed(item.created_at, now) for item in still_open), default=None),
        assets=tuple(
            sorted(
                (_asset_kpi(asset_id, items, register.get(asset_id)) for asset_id, items in by_asset.items()),
                key=_asset_order,
            )
        ),
    )


def _decimal(value: timedelta | None, unit: timedelta) -> str:
    # Decimal comma to match the semicolon CSV that German spreadsheet defaults expect.
    return f"{value / unit:.1f}".replace(".", ",") if value is not None else ""


def kpi_export_rows(kpis: MaintenanceKpis) -> list[dict[str, str]]:
    return [
        {
            "asset_id": item.asset_id,
            "name": item.name,
            "site": item.site,
            "functional_location": item.functional_location,
            "incidents": str(item.incidents),
            "eight_d_incidents": str(item.eight_d_incidents),
            "open_incidents": str(item.open_incidents),
            "mean_response_hours": _decimal(item.mean_response, timedelta(hours=1)),
            "mean_restoration_hours": _decimal(item.mean_restoration, timedelta(hours=1)),
            "reopened": str(item.reopened),
            "mean_interval_days": _decimal(item.mean_interval, timedelta(days=1)),
            "repeat_failure": "1" if item.repeat_failure else "0",
            "last_incident_utc": item.last_incident.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for item in kpis.assets
    ]
