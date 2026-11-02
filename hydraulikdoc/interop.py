"""File-based ERP interoperability: asset master import and SAP PM notification handover.

No live SAP connection is made. The handover file is a template whose field mapping must be
validated by the customer's SAP team before it is used for an upload (e.g. LSMW or a BTP flow).
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .repository import AssetRecord, IncidentRecord

MAX_ASSET_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ASSET_IMPORT_ROWS = 2_000
ASSET_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,119}")
# SAP field limits: TPLNR CHAR 40, EQUNR CHAR 18, QMTXT CHAR 40, QMART CHAR 2.
FUNCTIONAL_LOCATION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,39}")
EQUIPMENT_PATTERN = re.compile(r"[A-Za-z0-9]{1,18}")
NOTIFICATION_TYPE_PATTERN = re.compile(r"[A-Z0-9]{2}")
SAP_SHORT_TEXT_LENGTH = 40

ASSET_IMPORT_COLUMNS = (
    "asset_id",
    "name",
    "site",
    "manufacturer",
    "model",
    "criticality",
    "functional_location",
    "equipment_number",
)
_REQUIRED_IMPORT_COLUMNS = frozenset({"asset_id", "name", "site", "criticality"})
_CRITICALITY_ALIASES: Mapping[str, str] = {
    "low": "low",
    "niedrig": "low",
    "medium": "medium",
    "mittel": "medium",
    "high": "high",
    "hoch": "high",
    "safety_critical": "safety_critical",
    "sicherheitskritisch": "safety_critical",
}
# Severity -> SAP PM priority (PRIOK). Customer priority schemes differ; this is the documented default.
SAP_PRIORITY_BY_SEVERITY: Mapping[str, str] = {
    "critical": "1",
    "p1": "1",
    "p2": "2",
    "warning": "3",
    "p3": "3",
    "ok": "4",
    "p4": "4",
}
SAP_NOTIFICATION_COLUMNS = (
    "QMART",
    "QMTXT",
    "PRIOK",
    "TPLNR",
    "EQUNR",
    "LANGTEXT",
    "HD_INCIDENT_ID",
    "HD_ASSET_ID",
    "HD_STATUS",
    "HD_CREATED_AT",
)


@dataclass(frozen=True)
class AssetImportRow:
    asset_id: str
    name: str
    site: str
    manufacturer: str
    model: str
    criticality: str
    functional_location: str
    equipment_number: str


@dataclass(frozen=True)
class SapNotificationExport:
    rows: tuple[Mapping[str, str], ...]
    missing_reference: tuple[str, ...]


def _delimiter(header_line: str) -> str:
    # German Excel writes semicolon-separated CSV; plain exports use commas.
    return ";" if header_line.count(";") > header_line.count(",") else ","


def parse_asset_csv(content: bytes) -> tuple[AssetImportRow, ...]:
    """Validate an asset master file completely; any invalid row rejects the whole import."""
    if len(content) > MAX_ASSET_IMPORT_BYTES:
        raise ValueError("CSV überschreitet 2 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV muss UTF-8-kodiert sein") from error
    first_line = text.splitlines()[0] if text else ""
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(first_line))
    fieldnames = {name.strip() for name in reader.fieldnames or ()}
    if not _REQUIRED_IMPORT_COLUMNS.issubset(fieldnames):
        raise ValueError("CSV benötigt die Spalten asset_id, name, site und criticality")
    if not fieldnames.issubset(ASSET_IMPORT_COLUMNS):
        raise ValueError("CSV enthält nicht freigegebene Spalten")
    rows: list[AssetImportRow] = []
    seen: set[str] = set()
    errors: list[str] = []
    for line_number, raw in enumerate(reader, start=2):
        if len(rows) + len(errors) >= MAX_ASSET_IMPORT_ROWS:
            raise ValueError(f"CSV darf höchstens {MAX_ASSET_IMPORT_ROWS} Assets enthalten")
        row = {(key or "").strip(): (value or "").strip() for key, value in raw.items() if key is not None}
        if not any(row.values()):
            continue
        asset_id = row.get("asset_id", "")
        criticality = _CRITICALITY_ALIASES.get(row.get("criticality", "").lower())
        functional_location = row.get("functional_location", "")
        equipment_number = row.get("equipment_number", "")
        if not ASSET_ID_PATTERN.fullmatch(asset_id):
            errors.append(f"Zeile {line_number}: asset_id ungültig")
        elif asset_id in seen:
            errors.append(f"Zeile {line_number}: asset_id doppelt")
        elif not row.get("name") or not row.get("site"):
            errors.append(f"Zeile {line_number}: name und site sind erforderlich")
        elif criticality is None:
            errors.append(f"Zeile {line_number}: criticality unbekannt")
        elif functional_location and not FUNCTIONAL_LOCATION_PATTERN.fullmatch(functional_location):
            errors.append(f"Zeile {line_number}: functional_location ungültig (max. 40 Zeichen)")
        elif equipment_number and not EQUIPMENT_PATTERN.fullmatch(equipment_number):
            errors.append(f"Zeile {line_number}: equipment_number ungültig (max. 18 alphanumerische Zeichen)")
        else:
            seen.add(asset_id)
            rows.append(
                AssetImportRow(
                    asset_id=asset_id,
                    name=row["name"][:240],
                    site=row["site"][:240],
                    manufacturer=row.get("manufacturer", "")[:160],
                    model=row.get("model", "")[:160],
                    criticality=criticality,
                    functional_location=functional_location,
                    equipment_number=equipment_number,
                )
            )
    if errors:
        shown = "; ".join(errors[:5])
        more = f" (+{len(errors) - 5} weitere)" if len(errors) > 5 else ""
        raise ValueError(f"Import abgebrochen, keine Daten übernommen: {shown}{more}")
    if not rows:
        raise ValueError("CSV enthält keine Assets")
    return tuple(rows)


def asset_import_template() -> bytes:
    example = {
        "asset_id": "WERK1-PRESSE-04-HYD",
        "name": "Hydraulikaggregat Presse 04",
        "site": "Werk 1 · Halle 3",
        "manufacturer": "Hersteller",
        "model": "Baureihe",
        "criticality": "hoch",
        "functional_location": "1000-W1-H3-P04",
        "equipment_number": "10004711",
    }
    return to_spreadsheet_csv((example,), ASSET_IMPORT_COLUMNS)


def build_sap_notifications(
    incidents: Iterable[IncidentRecord],
    assets: Iterable[AssetRecord],
    notification_type: str,
) -> SapNotificationExport:
    if not NOTIFICATION_TYPE_PATTERN.fullmatch(notification_type):
        raise ValueError("Meldungsart muss aus zwei Großbuchstaben oder Ziffern bestehen")
    by_id = {asset.asset_id: asset for asset in assets}
    rows: list[Mapping[str, str]] = []
    missing: list[str] = []
    for incident in incidents:
        asset = by_id.get(incident.asset_id)
        functional_location = asset.functional_location if asset else ""
        equipment_number = asset.equipment_number if asset else ""
        if not functional_location and not equipment_number:
            missing.append(incident.incident_id)
        rows.append(
            {
                "QMART": notification_type,
                "QMTXT": incident.title[:SAP_SHORT_TEXT_LENGTH],
                "PRIOK": SAP_PRIORITY_BY_SEVERITY.get(incident.severity, "3"),
                "TPLNR": functional_location,
                "EQUNR": equipment_number,
                "LANGTEXT": _long_text(incident),
                "HD_INCIDENT_ID": incident.incident_id,
                "HD_ASSET_ID": incident.asset_id,
                "HD_STATUS": incident.status,
                "HD_CREATED_AT": incident.created_at.isoformat(),
            }
        )
    return SapNotificationExport(tuple(rows), tuple(missing))


_LONG_TEXT_SECTIONS = (
    ("containment_action", "Sofortmaßnahme"),
    ("root_cause", "Ursache"),
    ("corrective_action", "Abstellmaßnahme"),
    ("effectiveness_check", "Wirksamkeitsprüfung"),
)


def _long_text(incident: IncidentRecord) -> str:
    sections = [incident.details] if incident.details else []
    sections += [f"{label}: {value}" for field, label in _LONG_TEXT_SECTIONS if (value := getattr(incident, field))]
    return "\n".join(sections)


def _spreadsheet_safe(value: str) -> str:
    # Neutralise spreadsheet formula injection (CWE-1236) before a file is opened in Excel.
    return "'" + value if value[:1] in {"=", "+", "-", "@", "\t", "\r"} else value


def to_spreadsheet_csv(rows: Sequence[Mapping[str, str]], columns: Sequence[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _spreadsheet_safe(str(row.get(column, ""))) for column in columns})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
