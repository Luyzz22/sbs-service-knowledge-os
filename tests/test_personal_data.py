import re
import unittest
from pathlib import Path

from compliance.retention import RetentionPolicy
from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.governance import AIProvenance, GroundedAnswer, ReviewStatus, UseCase
from hydraulikdoc.personal_data import PERSONAL_DATA_FIELDS, is_person_column, render_annex
from hydraulikdoc.repository import SUBJECT_EXPORT_SCHEMA, InMemoryRepository
from hydraulikdoc.security import ValidatedUpload

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migrations" / "001_enterprise.sql"
ANNEX = ROOT / "docs" / "compliance" / "works-council-annex.md"
_CONSTRAINTS = {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}


def _schema_columns() -> set[tuple[str, str]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    columns: set[tuple[str, str]] = set()
    for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        for line in body.splitlines():
            name = line.strip().split(" ", 1)[0]
            if name and name.upper() not in _CONSTRAINTS:
                columns.add((table, name))
    columns |= set(re.findall(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", sql))
    return columns


class InventoryTests(unittest.TestCase):
    def test_every_person_column_in_the_schema_is_inventoried(self) -> None:
        in_schema = {item for item in _schema_columns() if is_person_column(item[1])}
        inventoried = {(item.table, item.column) for item in PERSONAL_DATA_FIELDS}
        self.assertEqual(
            sorted(in_schema - inventoried), [], "Person-related columns missing from hydraulikdoc/personal_data.py"
        )
        self.assertEqual(sorted(inventoried - _schema_columns()), [], "Inventory lists columns the schema lacks")

    def test_schema_parser_sees_the_known_tables(self) -> None:
        tables = {table for table, _ in _schema_columns()}
        self.assertLessEqual({"documents", "incidents", "incident_events", "audit_events"}, tables)

    def test_every_field_states_how_a_person_gets_access(self) -> None:
        for item in PERSONAL_DATA_FIELDS:
            with self.subTest(f"{item.table}.{item.column}"):
                self.assertTrue(item.export_section or item.export_note)

    def test_committed_annex_matches_the_inventory(self) -> None:
        self.assertEqual(
            ANNEX.read_text(encoding="utf-8"),
            render_annex(RetentionPolicy.from_environment({})),
            "Run: python ops/scripts/render-works-council-annex.py",
        )


class SubjectExportTests(unittest.TestCase):
    def test_export_contains_every_inventoried_section_with_the_persons_records(self) -> None:
        repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        person = UserPrincipal("sup", "tenant-a", "Sup", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"])
        colleague = UserPrincipal("tech", "tenant-a", "Tech", "technician", permissions=ROLE_PERMISSIONS["technician"])
        repository.register_document(person, ValidatedUpload("doc-1", "Handbuch.pdf", "a" * 64, b"", "application/pdf"))
        incident = repository.create_incident(person, asset_id="PU-1", title="Leckage", severity="p3", details="")
        repository.transition_incident(person, incident.incident_id, expected="new", target="acknowledged")
        answer = GroundedAnswer.create(
            text="Antwort [S1]",
            citations=(),
            provenance=AIProvenance("azure", "chat", "snapshot", "germanywestcentral"),
            use_case=UseCase.MAINTENANCE_ASSISTANCE,
        )
        repository.record_answer(colleague, "Frage", answer)
        repository.record_review(person, answer.answer_id, ReviewStatus.ACCEPTED)

        export = repository.subject_export(person)
        self.assertEqual(export["schema"], SUBJECT_EXPORT_SCHEMA)
        sections = {item.export_section for item in PERSONAL_DATA_FIELDS if item.export_section}
        self.assertLessEqual(sections, set(export))
        self.assertEqual([item["document_id"] for item in export["documents_uploaded"]], ["doc-1"])
        self.assertEqual([item["incident_id"] for item in export["incidents_created"]], [incident.incident_id])
        self.assertEqual([item["new_status"] for item in export["incident_steps"]], ["new", "acknowledged"])
        self.assertEqual([item["status"] for item in export["reviews_given"]], ["accepted"])
        # The colleague's own question belongs to the colleague, not to the reviewer.
        self.assertEqual(export["analysis_runs"], [])
        self.assertEqual(len(repository.subject_export(colleague)["analysis_runs"]), 1)
        self.assertEqual(repository.subject_export(colleague)["reviews_given"], [])


if __name__ == "__main__":
    unittest.main()
