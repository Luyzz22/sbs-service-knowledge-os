from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class FluidSample:
    asset_id: str
    taken_at: datetime
    particle_count: Optional[float] = None
    water_content: Optional[float] = None
    temperature: Optional[float] = None
    viscosity: Optional[float] = None
    source_document_id: Optional[str] = None


@dataclass
class FluidAssessment:
    asset_id: str
    sample_time: datetime
    score: int
    status: str
    summary: str
    recommendations: List[str]


def assess_fluid(sample: FluidSample) -> FluidAssessment:
    score = 80
    status = "OK"
    reasons: List[str] = []

    if sample.particle_count is not None and sample.particle_count > 1000:
        score -= 30
        status = "BEOBACHTEN"
        reasons.append("Erhöhte Partikelzahl – Filtration prüfen.")

    if sample.water_content is not None and sample.water_content > 0.1:
        score -= 30
        status = "KRITISCH"
        reasons.append("Erhöhter Wassergehalt – Gefahr von Korrosion und Kavitation.")

    if score < 50:
        status = "KRITISCH"

    if not reasons:
        reasons.append("Fluidzustand unauffällig im Rahmen der verfügbaren Daten.")

    summary = f"FluidScore {score}/100 – Status: {status}"
    recommendations: List[str] = ["Regelmäßige Kontrollmessung beibehalten."]
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
