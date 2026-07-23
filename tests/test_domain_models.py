from datetime import datetime, timezone
import unittest

from fluid_advisor import FluidSample, assess_fluid
from incident_model import Incident, IncidentPriority, IncidentStatus


class FluidAdvisorTests(unittest.TestCase):
    def test_healthy_sample_remains_ok(self) -> None:
        sample = FluidSample(
            asset_id="asset-1",
            taken_at=datetime.now(timezone.utc),
            particle_count=200,
            water_content=0.02,
        )

        assessment = assess_fluid(sample)

        self.assertEqual(assessment.asset_id, "asset-1")
        self.assertEqual(assessment.score, 80)
        self.assertEqual(assessment.status, "OK")

    def test_combined_threshold_breaches_are_critical(self) -> None:
        sample = FluidSample(
            asset_id="asset-2",
            taken_at=datetime.now(timezone.utc),
            particle_count=1_500,
            water_content=0.2,
        )

        assessment = assess_fluid(sample)

        self.assertEqual(assessment.score, 20)
        self.assertEqual(assessment.status, "KRITISCH")
        self.assertTrue(any("Wassergehalt" in item for item in assessment.recommendations))


class IncidentTests(unittest.TestCase):
    def test_fluid_incident_links_assessment(self) -> None:
        incident = Incident.create_fluid_incident(
            asset_id="asset-3",
            summary="Critical water content",
            details="Lab result exceeded the configured threshold.",
            priority=IncidentPriority.P1,
            fluid_assessment_id="assessment-1",
            owner="operator@example.com",
        )

        self.assertTrue(incident.incident_id)
        self.assertEqual(incident.status, IncidentStatus.NEW)
        self.assertEqual(incident.related_fluid_assessment_ids, ["assessment-1"])
        self.assertEqual(incident.owner, "operator@example.com")


if __name__ == "__main__":
    unittest.main()
