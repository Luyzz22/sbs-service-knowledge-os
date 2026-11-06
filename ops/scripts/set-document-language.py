#!/usr/bin/env python3
"""Set the document language of the installed Streamlit frontend (WCAG 2.2 SC 3.1.1).

Streamlit ships ``<html lang="en">``. HydraulikDoc's interface is German, so screen readers would
otherwise apply English pronunciation rules. The image build runs this once; it fails loudly when
Streamlit changes its markup so the regression cannot ship unnoticed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HTML_TAG = re.compile(r'<html lang="[A-Za-z-]+">')
_LANGUAGE = re.compile(r"[a-z]{2}(-[A-Z]{2})?")


def set_document_language(document: str, language: str) -> str:
    if not _LANGUAGE.fullmatch(language):
        raise ValueError(f"Unsupported language tag: {language}")
    if len(_HTML_TAG.findall(document)) != 1:
        raise RuntimeError('Expected exactly one <html lang="..."> tag in the Streamlit index.html')
    return _HTML_TAG.sub(f'<html lang="{language}">', document)


def streamlit_index() -> Path:
    import streamlit

    return Path(streamlit.__file__).resolve().parent / "static" / "index.html"


def main(argv: list[str]) -> int:
    language = argv[1] if len(argv) > 1 else "de"
    index = streamlit_index()
    index.write_text(set_document_language(index.read_text(encoding="utf-8"), language), encoding="utf-8")
    print(f'{{"level":"info","event":"document_language_set","language":"{language}"}}')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
