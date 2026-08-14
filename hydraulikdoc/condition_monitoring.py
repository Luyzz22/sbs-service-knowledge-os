"""Deterministic hydraulic condition-monitoring rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from statistics import fmean


class Severity(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SensorReading:
    timestamp: datetime
    pressure_bar: float | None = None
    temperature_c: float | None = None
    flow_l_min: float | None = None
    particle_count: float | None = None
    water_content_pct: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("sensor timestamps must be timezone-aware")
        for name in ("pressure_bar", "temperature_c", "flow_l_min", "particle_count", "water_content_pct"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.water_content_pct is not None and self.water_content_pct > 100:
            raise ValueError("water_content_pct must not exceed 100")


@dataclass(frozen=True)
class OperatingEnvelope:
    pressure_warning_bar: float = 250.0
    pressure_critical_bar: float = 300.0
    temperature_warning_c: float = 70.0
    temperature_critical_c: float = 85.0
    minimum_flow_l_min: float = 5.0
    particle_warning: float = 1000.0
    water_warning_pct: float = 0.1

    def __post_init__(self) -> None:
        if self.pressure_warning_bar >= self.pressure_critical_bar:
            raise ValueError("pressure warning must be below the critical threshold")
        if self.temperature_warning_c >= self.temperature_critical_c:
            raise ValueError("temperature warning must be below the critical threshold")
        values = (
            self.pressure_warning_bar,
            self.pressure_critical_bar,
            self.temperature_warning_c,
            self.temperature_critical_c,
            self.minimum_flow_l_min,
            self.particle_warning,
            self.water_warning_pct,
        )
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("operating thresholds must be finite and non-negative")
        if self.water_warning_pct > 100:
            raise ValueError("water warning must not exceed 100 percent")


@dataclass(frozen=True)
class ConditionSignal:
    code: str
    severity: Severity
    message: str
    value: float
    threshold: float
    unit: str


@dataclass(frozen=True)
class ConditionAssessment:
    severity: Severity
    signals: tuple[ConditionSignal, ...]
    sample_count: int
    pressure_mean: float | None
    temperature_mean: float | None
    requires_shutdown_assessment: bool


def _mean(readings: Iterable[SensorReading], attribute: str) -> float | None:
    values = [getattr(reading, attribute) for reading in readings]
    bounded = [float(value) for value in values if value is not None]
    return fmean(bounded) if bounded else None


def assess_condition(
    readings: Iterable[SensorReading],
    envelope: OperatingEnvelope,
) -> ConditionAssessment:
    samples = tuple(readings)
    if not samples:
        raise ValueError("at least one sensor reading is required")
    if any(samples[index].timestamp > samples[index + 1].timestamp for index in range(len(samples) - 1)):
        raise ValueError("sensor readings must be ordered by timestamp")

    signals_by_code: dict[str, ConditionSignal] = {}

    def add_signal(signal: ConditionSignal) -> None:
        existing = signals_by_code.get(signal.code)
        if existing is None or signal.value > existing.value:
            signals_by_code[signal.code] = signal

    for reading in samples:
        if reading.pressure_bar is not None:
            if reading.pressure_bar >= envelope.pressure_critical_bar:
                add_signal(
                    ConditionSignal(
                        "PRESSURE_CRITICAL",
                        Severity.CRITICAL,
                        "Druck überschreitet die Abschaltprüfgrenze.",
                        reading.pressure_bar,
                        envelope.pressure_critical_bar,
                        "bar",
                    )
                )
            elif reading.pressure_bar >= envelope.pressure_warning_bar:
                add_signal(
                    ConditionSignal(
                        "PRESSURE_WARNING",
                        Severity.WARNING,
                        "Druck überschreitet die Warngrenze.",
                        reading.pressure_bar,
                        envelope.pressure_warning_bar,
                        "bar",
                    )
                )
        if reading.temperature_c is not None:
            if reading.temperature_c >= envelope.temperature_critical_c:
                add_signal(
                    ConditionSignal(
                        "TEMPERATURE_CRITICAL",
                        Severity.CRITICAL,
                        "Temperatur überschreitet die Abschaltprüfgrenze.",
                        reading.temperature_c,
                        envelope.temperature_critical_c,
                        "°C",
                    )
                )
            elif reading.temperature_c >= envelope.temperature_warning_c:
                add_signal(
                    ConditionSignal(
                        "TEMPERATURE_WARNING",
                        Severity.WARNING,
                        "Temperatur überschreitet die Warngrenze.",
                        reading.temperature_c,
                        envelope.temperature_warning_c,
                        "°C",
                    )
                )
        if reading.flow_l_min is not None and reading.flow_l_min < envelope.minimum_flow_l_min:
            signal = ConditionSignal(
                "FLOW_LOW",
                Severity.WARNING,
                "Volumenstrom unterschreitet die konfigurierte Mindestgrenze.",
                reading.flow_l_min,
                envelope.minimum_flow_l_min,
                "l/min",
            )
            existing = signals_by_code.get(signal.code)
            if existing is None or signal.value < existing.value:
                signals_by_code[signal.code] = signal
        if reading.particle_count is not None and reading.particle_count >= envelope.particle_warning:
            add_signal(
                ConditionSignal(
                    "PARTICLE_WARNING",
                    Severity.WARNING,
                    "Partikelbelastung überschreitet die Warngrenze.",
                    reading.particle_count,
                    envelope.particle_warning,
                    "#/ml",
                )
            )
        if reading.water_content_pct is not None and reading.water_content_pct >= envelope.water_warning_pct:
            add_signal(
                ConditionSignal(
                    "WATER_WARNING",
                    Severity.WARNING,
                    "Wassergehalt überschreitet die Warngrenze.",
                    reading.water_content_pct,
                    envelope.water_warning_pct,
                    "%",
                )
            )

    signals = tuple(signals_by_code.values())

    severity = Severity.OK
    if any(signal.severity is Severity.CRITICAL for signal in signals):
        severity = Severity.CRITICAL
    elif signals:
        severity = Severity.WARNING
    return ConditionAssessment(
        severity=severity,
        signals=signals,
        sample_count=len(samples),
        pressure_mean=_mean(samples, "pressure_bar"),
        temperature_mean=_mean(samples, "temperature_c"),
        requires_shutdown_assessment=severity is Severity.CRITICAL,
    )
