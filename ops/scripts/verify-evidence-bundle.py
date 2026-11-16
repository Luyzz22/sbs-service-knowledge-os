"""Verify a HydraulikDoc evidence bundle and print the result as JSON.

Without a secret the script checks every file against the SHA-256 in the manifest, which is what a
recipient can do. The operator sets AUDIT_HMAC_KEY to check the seal as well and thereby confirm that
this instance produced the bundle. Exits 1 when a file or the seal does not match.

    python ops/scripts/verify-evidence-bundle.py hydraulikdoc-nachweispaket-....zip
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from hydraulikdoc.evidence_bundle import verify_bundle


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("usage: verify-evidence-bundle.py <bundle.zip>", file=sys.stderr)
        return 2
    result = verify_bundle(Path(arguments[0]).read_bytes(), os.environ.get("AUDIT_HMAC_KEY") or None)
    manifest = result.manifest or {}
    print(
        json.dumps(
            {
                "level": "info" if result.intact else "error",
                "event": "evidence_bundle_verified",
                "intact": result.intact,
                "seal": result.seal,
                "problems": list(result.problems),
                "bundle_id": manifest.get("bundle_id"),
                "generated_at": manifest.get("generated_at"),
                "period": manifest.get("period"),
                "audit_chain": manifest.get("audit_chain"),
            },
            sort_keys=True,
        )
    )
    return 0 if result.intact else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
