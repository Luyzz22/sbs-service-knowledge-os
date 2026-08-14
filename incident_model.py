import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


class IncidentStatus:
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING = "WAITING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentPriority:
    P1 = "P1"  # Kritisch
    P2 = "P2"  # Hoch
    P3 = "P3"  # Mittel
    P4 = "P4"  # Niedrig


@dataclass
class Incident:
    incident_id: str
    asset_id: str
    type: str  # e.g. "FLUID_ALERT", "BREAKDOWN", "INSPECTION"
    priority: str
    status: str
    summary: str
    details: str
    opened_at: datetime
    resolved_at: datetime | None = None
    owner: str | None = None
    related_fluid_assessment_ids: list[str] = field(default_factory=list)
    related_video_analysis_ids: list[str] = field(default_factory=list)

    @staticmethod
    def create_fluid_incident(
        asset_id: str,
        summary: str,
        details: str,
        priority: str,
        fluid_assessment_id: str | None = None,
        owner: str | None = None,
    ) -> "Incident":
        incident_id = str(uuid.uuid4())
        related_fluid = [fluid_assessment_id] if fluid_assessment_id else []
        return Incident(
            incident_id=incident_id,
            asset_id=asset_id,
            type="FLUID_ALERT",
            priority=priority,
            status=IncidentStatus.NEW,
            summary=summary,
            details=details,
            opened_at=datetime.now(UTC),
            owner=owner,
            related_fluid_assessment_ids=related_fluid,
        )
