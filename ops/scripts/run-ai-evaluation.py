#!/usr/bin/env python3
"""Run a confidential live gold set against the configured Azure RAG stack."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
from hydraulikdoc.azure_ai import AzureRAGService
from hydraulikdoc.config import AppSettings
from hydraulikdoc.evaluation import EvaluationCase, create_report, evaluate_case
from hydraulikdoc.repository import InMemoryRepository


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def main() -> int:
    dataset_path = Path(os.environ["EVAL_DATASET_PATH"]).resolve(strict=True)
    output_path = Path(os.environ.get("EVAL_OUTPUT_PATH", "ai-evaluation-evidence.json")).resolve()
    dataset_version = os.environ["EVAL_DATASET_VERSION"].strip()
    if not dataset_version:
        raise ValueError("EVAL_DATASET_VERSION is required")
    raw_dataset = dataset_path.read_bytes()
    cases = tuple(
        EvaluationCase.from_mapping(json.loads(line))
        for line in raw_dataset.decode("utf-8").splitlines()
        if line.strip()
    )

    settings = AppSettings.from_environment()
    if not settings.azure_ready:
        raise RuntimeError("The Azure evaluation profile is incomplete")
    repository = InMemoryRepository(settings)
    rag = AzureRAGService(settings, repository)
    results = []
    for case in cases:
        principal = UserPrincipal(
            subject_id="ai-release-evaluator",
            tenant_id=case.tenant_id,
            display_name="AI Release Evaluator",
            role="supervisor",
            permissions=ROLE_PERMISSIONS["supervisor"],
            authentication_method="evaluation_job",
        )
        answer = None
        denied_reason = None
        try:
            answer = rag.ask(principal, case.question, case.use_case)
        except PermissionError as error:
            denied_reason = str(error)
        results.append(evaluate_case(case, answer, denied_reason))

    report = create_report(
        results=tuple(results),
        dataset_version=dataset_version,
        dataset_sha256=hashlib.sha256(raw_dataset).hexdigest(),
        model_snapshot=settings.azure_model_snapshot,
        region=settings.azure_region or "unverified",
        minimum_cases=_positive_int("EVAL_MINIMUM_CASES", 20),
        minimum_pass_rate=float(os.environ.get("EVAL_MINIMUM_PASS_RATE", "0.95")),
    )
    output_path.write_text(report.to_json(), encoding="utf-8")
    print(
        json.dumps(
            {
                "event": "ai_evaluation_completed",
                "evidence_id": report.evidence_id,
                "case_count": report.case_count,
                "pass_rate": report.pass_rate,
                "release_eligible": report.release_eligible,
            },
            separators=(",", ":"),
        )
    )
    return 0 if report.release_eligible else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"event": "ai_evaluation_failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from error
