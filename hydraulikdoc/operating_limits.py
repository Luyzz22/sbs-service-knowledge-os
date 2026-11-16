"""Operating limits per asset, released by a second person before an assessment relies on them.

Condition monitoring and the fluid advisor compare measurements against limits that only the plant
can confirm: the manufacturer's manual, a release letter or an engineering decision. A limit typed in
for one session leaves no evidence of where it came from. A limit set is therefore proposed with its
source, released by a second person and then used read-only. A new version stays a proposal until it
is released and replaces the previous one in the same step, so an asset never has two sets in force.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Protocol

from fluid_advisor import FluidLimits

from .auth import UserPrincipal
from .condition_monitoring import OperatingEnvelope


class SourceDocument(Protocol):
    """The part of a document record that decides whether it can back a limit set."""

    @property
    def usable_for_answers(self) -> bool: ...

    @property
    def page_count(self) -> int: ...


# A technician can transcribe limits from a manual; releasing them is a supervisor decision.
LIMITS_PROPOSE_PERMISSION = "diagnostic:run"
LIMITS_RELEASE_PERMISSION = "limits:release"
LIMIT_STATUSES = ("draft", "released", "superseded", "rejected")
# Fixed codes instead of free text, so a rejection never carries names or blame.
LIMIT_REJECTION_REASONS = ("value_incorrect", "source_insufficient", "not_applicable", "replaced_by_proposal")
LIMIT_SOURCE_REFERENCE_MIN = 3
LIMIT_SOURCE_REFERENCE_MAX = 160


@dataclass(frozen=True)
class LimitValues:
    pressure_warning_bar: float = 250.0
    pressure_critical_bar: float = 300.0
    temperature_warning_c: float = 70.0
    temperature_critical_c: float = 85.0
    minimum_flow_l_min: float = 5.0
    particle_warning: float = 1000.0
    water_warning_pct: float = 0.1
    water_critical_pct: float = 0.1

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in LIMIT_FIELDS)
        if any(not isinstance(value, int | float) or not isfinite(value) or value < 0 for value in values):
            raise ValueError("OPERATING_LIMITS_VALUES_INVALID")
        try:
            self.envelope()
            self.fluid_limits()
        except ValueError as error:
            raise ValueError("OPERATING_LIMITS_VALUES_INVALID") from error
        if self.water_warning_pct > self.water_critical_pct:
            raise ValueError("OPERATING_LIMITS_VALUES_INVALID")

    def envelope(self) -> OperatingEnvelope:
        return OperatingEnvelope(
            pressure_warning_bar=self.pressure_warning_bar,
            pressure_critical_bar=self.pressure_critical_bar,
            temperature_warning_c=self.temperature_warning_c,
            temperature_critical_c=self.temperature_critical_c,
            minimum_flow_l_min=self.minimum_flow_l_min,
            particle_warning=self.particle_warning,
            water_warning_pct=self.water_warning_pct,
        )

    def fluid_limits(self) -> FluidLimits:
        return FluidLimits(particle_warning=self.particle_warning, water_critical_pct=self.water_critical_pct)


LIMIT_FIELDS = (
    "pressure_warning_bar",
    "pressure_critical_bar",
    "temperature_warning_c",
    "temperature_critical_c",
    "minimum_flow_l_min",
    "particle_warning",
    "water_warning_pct",
    "water_critical_pct",
)


@dataclass(frozen=True)
class OperatingLimitSet:
    limit_set_id: str
    tenant_id: str
    asset_id: str
    version: int
    status: str
    values: LimitValues
    source_reference: str
    proposed_at: datetime
    source_document_id: str | None = None
    source_page: int | None = None
    decided_at: datetime | None = None
    decision_reason: str = ""
    superseded_at: datetime | None = None
    # True for the person who proposed the set; they cannot release it themselves.
    is_own: bool = False
    # Read from the linked document; empty when no document is linked or it no longer exists.
    source_document_name: str = ""
    source_revision: str = ""
    # The linked document is no longer a released source (withdrawn, superseded or deleted).
    source_withdrawn: bool = False


@dataclass(frozen=True)
class OperatingLimitRelease:
    limits: OperatingLimitSet
    # The set that this release took out of use.
    superseded: OperatingLimitSet | None = None


def released_limits(sets: Iterable[OperatingLimitSet], asset_id: str) -> OperatingLimitSet | None:
    return next((item for item in sets if item.asset_id == asset_id and item.status == "released"), None)


def pending_limits(sets: Iterable[OperatingLimitSet], asset_id: str) -> OperatingLimitSet | None:
    return next((item for item in sets if item.asset_id == asset_id and item.status == "draft"), None)


def check_limit_proposal(
    principal: UserPrincipal,
    *,
    asset_known: bool,
    pending: bool,
    source_reference: str,
    source_document: SourceDocument | None,
    source_document_id: str | None,
    source_page: int | None,
) -> str:
    """Fail closed unless the proposal may be recorded; returns the normalised source reference."""
    if not principal.can(LIMITS_PROPOSE_PERMISSION):
        raise PermissionError("OPERATING_LIMITS_PROPOSE_REQUIRED")
    if not asset_known:
        raise ValueError("OPERATING_LIMITS_ASSET_UNKNOWN")
    if pending:
        raise ValueError("OPERATING_LIMITS_PENDING")
    reference = " ".join(source_reference.split())
    if not LIMIT_SOURCE_REFERENCE_MIN <= len(reference) <= LIMIT_SOURCE_REFERENCE_MAX:
        raise ValueError("OPERATING_LIMITS_SOURCE_REFERENCE_INVALID")
    if source_document_id is None:
        if source_page is not None:
            raise ValueError("OPERATING_LIMITS_SOURCE_PAGE_INVALID")
        return reference
    if source_document is None or not source_document.usable_for_answers:
        raise ValueError("OPERATING_LIMITS_SOURCE_NOT_RELEASED")
    if source_page is None or not 1 <= source_page <= source_document.page_count:
        raise ValueError("OPERATING_LIMITS_SOURCE_PAGE_INVALID")
    return reference


def check_limit_release(principal: UserPrincipal, current: OperatingLimitSet) -> None:
    if not principal.can(LIMITS_RELEASE_PERMISSION):
        raise PermissionError("OPERATING_LIMITS_RELEASE_REQUIRED")
    if current.status != "draft":
        raise ValueError("OPERATING_LIMITS_NOT_DRAFT")
    if current.is_own:
        raise PermissionError("FOUR_EYES_LIMITS_REQUIRED")
    if current.source_withdrawn:
        raise ValueError("OPERATING_LIMITS_SOURCE_NOT_RELEASED")


def check_limit_rejection(principal: UserPrincipal, current: OperatingLimitSet, reason_code: str) -> None:
    # Stopping a proposal needs no second person: the proposer may discard their own.
    if not (principal.can(LIMITS_RELEASE_PERMISSION) or current.is_own):
        raise PermissionError("OPERATING_LIMITS_RELEASE_REQUIRED")
    if current.status != "draft":
        raise ValueError("OPERATING_LIMITS_NOT_DRAFT")
    if reason_code not in LIMIT_REJECTION_REASONS:
        raise ValueError("OPERATING_LIMITS_REASON_INVALID")
