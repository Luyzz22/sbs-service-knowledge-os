import csv
import io
import unittest
from datetime import UTC, datetime

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.config import AppSettings
from hydraulikdoc.interop import (
    SAP_NOTIFICATION_COLUMNS,
    asset_import_template,
    build_sap_notifications,
    parse_asset_csv,
    to_spreadsheet_csv,
)
from hydraulikdoc.repository import AssetRecord, IncidentRecord, InMemoryRepository


def _asset(asset_id: str, functional_location: str = "", equipment_number: str = "") -> AssetRecord:
    return AssetRecord(
        asset_id,
        "tenant-a",
        "Aggregat",
        "Werk 1",
        "",
        "",
        "high",
        "active",
        datetime(2026, 11, 3, tzinfo=UTC),
        functional_location,
        equipment_number,
    )


def _incident(asset_id: str, severity: str, title: str = "Druck kritisch") -> IncidentRecord:
    return IncidentRecord(
        "11111111-2222-3333-4444-555555555555",
        "tenant-a",
        asset_id,
        title,
        severity,
        "new",
        datetime(2026, 11, 3, 8, 0, tzinfo=UTC),
        "P_HIGH: 312 bar",
    )


def _read_export(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8")
    assert text.startswith("\ufeff"), "Excel needs a UTF-8 BOM"
    return list(csv.DictReader(io.StringIO(text[1:]), delimiter=";"))


class AssetImportTests(unittest.TestCase):
    def test_semicolon_excel_export_with_german_criticality_is_accepted(self) -> None:
        content = (
            "\ufeffasset_id;name;site;criticality;functional_location;equipment_number\n"
            "WERK1-P04;Presse 04;Werk 1;hoch;1000-W1-H3-P04;10004711\n"
            "WERK1-P05;Presse 05;Werk 1;sicherheitskritisch;;\n"
        ).encode()
        rows = parse_asset_csv(content)
        self.assertEqual([row.criticality for row in rows], ["high", "safety_critical"])
        self.assertEqual(rows[0].functional_location, "1000-W1-H3-P04")
        self.assertEqual(rows[1].equipment_number, "")

    def test_template_round_trips_through_the_importer(self) -> None:
        rows = parse_asset_csv(asset_import_template())
        self.assertEqual(rows[0].asset_id, "WERK1-PRESSE-04-HYD")
        self.assertEqual(rows[0].criticality, "high")

    def test_any_invalid_row_rejects_the_whole_import(self) -> None:
        content = (
            b"asset_id,name,site,criticality,equipment_number\n"
            b"WERK1-P04,Presse 04,Werk 1,high,10004711\n"
            b"WERK1-P04,Duplikat,Werk 1,high,\n"
            b"WERK1-P06,Presse 06,Werk 1,extrem,\n"
            b"WERK1-P07,Presse 07,Werk 1,low,EQ-TOO-LONG-1234567890\n"
        )
        with self.assertRaises(ValueError) as raised:
            parse_asset_csv(content)
        message = str(raised.exception)
        self.assertIn("keine Daten übernommen", message)
        self.assertIn("Zeile 3: asset_id doppelt", message)
        self.assertIn("Zeile 4: criticality unbekannt", message)
        self.assertIn("Zeile 5: equipment_number", message)

    def test_unapproved_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "nicht freigegebene Spalten"):
            parse_asset_csv(b"asset_id,name,site,criticality,owner_email\nA1,X,Y,low,a@example.de\n")

    def test_repository_keeps_sap_references(self) -> None:
        repository = InMemoryRepository(AppSettings.from_environment({"APP_ENV": "test"}))
        principal = UserPrincipal("lead", "tenant-a", "Lead", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"])
        repository.upsert_asset(
            principal,
            asset_id="WERK1-P04",
            name="Presse 04",
            site="Werk 1",
            manufacturer="",
            model="",
            criticality="high",
            functional_location="1000-W1-H3-P04",
            equipment_number="10004711",
        )
        stored = repository.list_assets(principal)[0]
        self.assertEqual((stored.functional_location, stored.equipment_number), ("1000-W1-H3-P04", "10004711"))


class SapNotificationExportTests(unittest.TestCase):
    def test_incident_maps_to_sap_pm_fields(self) -> None:
        export = build_sap_notifications(
            [_incident("WERK1-P04", "critical", title="Druckspitze am Hauptzylinder über Prüfgrenze 300 bar")],
            [_asset("WERK1-P04", "1000-W1-H3-P04", "10004711")],
            "M2",
        )
        row = _read_export(to_spreadsheet_csv(export.rows, SAP_NOTIFICATION_COLUMNS))[0]
        self.assertEqual(row["QMART"], "M2")
        self.assertEqual(row["PRIOK"], "1")
        self.assertEqual(len(row["QMTXT"]), 40)
        self.assertEqual((row["TPLNR"], row["EQUNR"]), ("1000-W1-H3-P04", "10004711"))
        self.assertEqual(row["LANGTEXT"], "P_HIGH: 312 bar")
        self.assertEqual(export.missing_reference, ())

    def test_missing_technical_object_is_reported(self) -> None:
        export = build_sap_notifications([_incident("UNBEKANNT", "warning")], [], "M2")
        self.assertEqual(export.rows[0]["PRIOK"], "3")
        self.assertEqual(len(export.missing_reference), 1)

    def test_spreadsheet_formula_injection_is_neutralised(self) -> None:
        export = build_sap_notifications([_incident("A1", "p2", title='=HYPERLINK("x")')], [], "M2")
        row = _read_export(to_spreadsheet_csv(export.rows, SAP_NOTIFICATION_COLUMNS))[0]
        self.assertTrue(row["QMTXT"].startswith("'="))

    def test_notification_type_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            build_sap_notifications([], [], "m2;")


if __name__ == "__main__":
    unittest.main()
