#!/usr/bin/env python3
"""Render the works-council annex from the personal-data inventory.

Run after changing hydraulikdoc/personal_data.py; tests/test_personal_data.py fails while the committed
document differs from the rendering.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hydraulikdoc.personal_data import render_annex  # noqa: E402

ANNEX = ROOT / "docs" / "compliance" / "works-council-annex.md"


def main() -> int:
    ANNEX.write_text(render_annex(), encoding="utf-8")
    print(f"written: {ANNEX.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
