from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True)
class FluidSample:
    asset_id: str
    taken_at: datetime
    particle_count: float | None = None
    water_content: float | None = None
    temperature: float | None = None
    viscosity: float | None = None
    source_document_id: str | None = None

    def __post_init__(self) -> None:
        if self.taken_at.tzinfo is None:
            raise ValueError("sample time must be timezone-aware")
        for name in ("particle_count", "water_content", "temperature", "viscosity"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.particle_count is not None and self.particle_count < 0:
            raise ValueError("particle_count must be non-negative")
        if self.water_content is not None and not 0 <= self.water_content <= 100:
            raise ValueError("water_content must be between 0 and 100 percent")
        if self.viscosity is not None and self.viscosity < 0:
            raise ValueError("viscosity must be non-negative")


@dataclass(frozen=True)
class FluidLimits:
    particle_warning: float = 1000.0
    water_critical_pct: float = 0.1

    def __post_init__(self) -> None:
        if not isfinite(self.particle_warning) or self.particle_warning < 0:
            raise ValueError("particle warning must be finite and non-negative")
        if not isfinite(self.water_critical_pct) or not 0 <= self.water_critical_pct <= 100:
            raise ValueError("water limit must be between 0 and 100 percent")


@dataclass(frozen=True)
class FluidAssessment:
    asset_id: str
    sample_time: datetime
    score: int
    status: str
    summary: str
    recommendations: list[str]


def assess_fluid(sample: FluidSample, limits: FluidLimits | None = None) -> FluidAssessment:
    limits = limits or FluidLimits()
    score = 80
    status = "OK"
    reasons: list[str] = []

    if sample.particle_count is not None and sample.particle_count > limits.particle_warning:
        score -= 30
        status = "BEOBACHTEN"
        reasons.append("Erhöhte Partikelzahl – Filtration prüfen.")

    if sample.water_content is not None and sample.water_content > limits.water_critical_pct:
        score -= 30
        status = "KRITISCH"
        reasons.append("Erhöhter Wassergehalt – Gefahr von Korrosion und Kavitation.")

    if score < 50:
        status = "KRITISCH"

    if not reasons:
        reasons.append("Fluidzustand unauffällig im Rahmen der verfügbaren Daten.")

    summary = f"FluidScore {score}/100 – Status: {status}"
    recommendations: list[str] = ["Regelmäßige Kontrollmessung beibehalten."]
    if status != "OK":
        recommendations.append("Zeitnahe Analyse durch Fluidservice einplanen.")

    return FluidAssessment(
        asset_id=sample.asset_id,
        sample_time=sample.taken_at,
        score=max(0, min(100, score)),
        status=status,
        summary=summary,
        recommendations=reasons + recommendations,
    )
