"""Input validation and data-minimisation controls."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass


class InputRejected(ValueError):
    """Raised when untrusted input violates a security policy."""


_ACTIVE_PDF_MARKERS = (
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/EmbeddedFile",
    b"/OpenAction",
    b"/RichMedia",
)


@dataclass(frozen=True)
class ValidatedUpload:
    document_id: str
    display_name: str
    sha256: str
    content: bytes
    content_type: str = "application/pdf"


def normalise_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").split("/")[-1]
    normalised = unicodedata.normalize("NFKD", leaf).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", normalised).strip(" ._")
    if not cleaned:
        cleaned = "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    stem, extension = cleaned[:-4], ".pdf"
    return f"{stem[:116]}{extension}"


def validate_pdf_upload(filename: str, content: bytes, max_bytes: int) -> ValidatedUpload:
    if not content:
        raise InputRejected("Die Datei ist leer.")
    if len(content) > max_bytes:
        raise InputRejected(f"Die PDF-Datei überschreitet das Limit von {max_bytes // 1024 // 1024} MB.")
    if not content.startswith(b"%PDF-"):
        raise InputRejected("Dateiinhalt und PDF-Dateityp stimmen nicht überein.")
    head = content[: min(len(content), 2 * 1024 * 1024)]
    if any(marker in head for marker in _ACTIVE_PDF_MARKERS):
        raise InputRejected("Aktive oder eingebettete PDF-Inhalte sind nicht zugelassen.")
    return ValidatedUpload(
        document_id=str(uuid.uuid4()),
        display_name=normalise_filename(filename),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def validate_question(question: str, max_chars: int) -> str:
    cleaned = question.strip()
    if not cleaned:
        raise InputRejected("Bitte geben Sie eine technische Frage ein.")
    if len(cleaned) > max_chars:
        raise InputRejected(f"Die Frage darf höchstens {max_chars} Zeichen enthalten.")
    if any(ord(character) < 32 and character not in "\n\t" for character in cleaned):
        raise InputRejected("Die Frage enthält unzulässige Steuerzeichen.")
    return cleaned


def bounded_untrusted_text(value: str, max_chars: int = 16000) -> str:
    """Bound retrieved content and neutralise framing delimiters."""
    return value.replace("\x00", "").replace("</source>", "&lt;/source&gt;")[:max_chars]


def odata_literal(value: str) -> str:
    """Escape one OData string literal; callers still choose the field allowlist."""
    return value.replace("'", "''")


def public_error_code(error: BaseException) -> str:
    return f"ERR-{hashlib.sha256(type(error).__name__.encode()).hexdigest()[:10].upper()}"
