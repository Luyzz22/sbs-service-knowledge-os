"""Quality monitoring of AI answers from documented human reviews.

The figures answer one question for the operator of the AI system: do reviewers accept what a given
prompt and model release produces, and which documents keep producing rejected answers? They are
aggregated per release and per document and never per person. Who asked and who reviewed is not part
of the input, so the monitoring cannot be turned into a performance evaluation of employees
(BetrVG § 87 (1) no. 6).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hydraulikdoc.repository import REVIEW_REJECTION_REASONS, AnswerQualityRecord, DocumentRecord, StoredAnswer

# Answers are kept for the AI interaction retention period, so longer windows would silently shrink.
QUALITY_WINDOW_DAYS = (30, 90)
QUALITY_ANSWER_LIMIT = 10_000
# A share needs a minimum of decisions before it is treated as a signal rather than noise.
SIGNAL_MIN_DECISIONS = 5
SIGNAL_REJECTION_SHARE = 0.2
# Rejections for these reasons point at the source document rather than at the model.
SOURCE_REJECTION_REASONS = frozenset({"incorrect_value", "wrong_source", "outdated_source"})
DOCUMENT_SIGNAL_REJECTIONS = 2
# An answer waiting longer than this for its second reviewer is reported as overdue.
REVIEW_TARGET = timedelta(hours=72)
UNKNOWN_REASON = "unspecified"

QUALITY_EXPORT_COLUMNS = (
    "prompt_version",
    "model_snapshot",
    "deployment",
    "answers",
    "without_evidence",
    "decided",
    "accepted",
    "rejected",
    "escalated",
    "open",
    "rejection_share_percent",
    *(f"rejected_{reason}" for reason in REVIEW_REJECTION_REASONS),
    f"rejected_{UNKNOWN_REASON}",
)


@dataclass(frozen=True)
class ReleaseQuality:
    """Review outcome of one prompt version on one model snapshot and deployment."""

    prompt_version: str
    model_snapshot: str
    deployment: str
    answers: int
    without_evidence: int
    decided: int
    accepted: int
    rejected: int
    escalated: int
    open: int
    rejection_reasons: Mapping[str, int]

    @property
    def rejection_share(self) -> float | None:
        return self.rejected / self.decided if self.decided else None

    @property
    def signal(self) -> bool:
        share = self.rejection_share
        return self.decided >= SIGNAL_MIN_DECISIONS and share is not None and share >= SIGNAL_REJECTION_SHARE


@dataclass(frozen=True)
class DocumentQuality:
    document_id: str
    display_name: str
    revision: str
    # None when the document has been deleted since the answer was generated.
    release_status: str | None
    answers: int
    rejected: int
    source_rejections: int

    @property
    def signal(self) -> bool:
        return self.release_status == "released" and self.source_rejections >= DOCUMENT_SIGNAL_REJECTIONS


@dataclass(frozen=True)
class AnswerQuality:
    answers: int
    without_evidence: int
    decided: int
    accepted: int
    rejected: int
    escalated: int
    open: int
    open_second_person: int
    median_decision_time: timedelta | None
    rejection_reasons: Mapping[str, int]
    releases: tuple[ReleaseQuality, ...]
    documents: tuple[DocumentQuality, ...]

    @property
    def review_coverage(self) -> float | None:
        return self.decided / self.answers if self.answers else None

    @property
    def rejection_share(self) -> float | None:
        return self.rejected / self.decided if self.decided else None

    @property
    def release_signals(self) -> tuple[ReleaseQuality, ...]:
        return tuple(item for item in self.releases if item.signal)

    @property
    def document_signals(self) -> tuple[DocumentQuality, ...]:
        return tuple(item for item in self.documents if item.signal)


def _median(values: Sequence[timedelta]) -> timedelta | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _reason(record: AnswerQualityRecord) -> str:
    return record.rejection_reason if record.rejection_reason in REVIEW_REJECTION_REASONS else UNKNOWN_REASON


def _release(key: tuple[str, str, str], records: Sequence[AnswerQualityRecord]) -> ReleaseQuality:
    rejected = [item for item in records if item.review_status == "rejected"]
    accepted = sum(1 for item in records if item.review_status == "accepted")
    return ReleaseQuality(
        prompt_version=key[0],
        model_snapshot=key[1],
        deployment=key[2],
        answers=len(records),
        without_evidence=sum(1 for item in records if not item.document_ids),
        decided=accepted + len(rejected),
        accepted=accepted,
        rejected=len(rejected),
        escalated=sum(1 for item in records if item.escalated),
        open=sum(1 for item in records if item.review_status in ("draft", "needs_expert")),
        rejection_reasons=dict(Counter(_reason(item) for item in rejected)),
    )


def answer_quality(records: Iterable[AnswerQualityRecord], documents: Iterable[DocumentRecord]) -> AnswerQuality:
    items = tuple(records)
    register = {item.document_id: item for item in documents}
    by_release: dict[tuple[str, str, str], list[AnswerQualityRecord]] = defaultdict(list)
    by_document: dict[str, list[AnswerQualityRecord]] = defaultdict(list)
    for item in items:
        by_release[(item.prompt_version, item.model_snapshot, item.deployment)].append(item)
        for document_id in item.document_ids:
            by_document[document_id].append(item)
    releases = tuple(
        sorted(
            (_release(key, group) for key, group in by_release.items()),
            key=lambda item: (not item.signal, -item.answers, item.prompt_version, item.model_snapshot),
        )
    )
    document_rows = []
    for document_id, group in by_document.items():
        rejected = [item for item in group if item.review_status == "rejected"]
        known = register.get(document_id)
        document_rows.append(
            DocumentQuality(
                document_id=document_id,
                display_name=known.display_name if known else "",
                revision=known.revision if known else "",
                release_status=known.release_status if known else None,
                answers=len(group),
                rejected=len(rejected),
                source_rejections=sum(1 for item in rejected if item.rejection_reason in SOURCE_REJECTION_REASONS),
            )
        )
    document_rows.sort(key=lambda item: (not item.signal, -item.source_rejections, -item.answers, item.display_name))
    rejected_items = [item for item in items if item.review_status == "rejected"]
    accepted = sum(1 for item in items if item.review_status == "accepted")
    durations = [
        item.decided_at - item.generated_at
        for item in items
        if item.decided_at is not None and item.decided_at >= item.generated_at
    ]
    return AnswerQuality(
        answers=len(items),
        without_evidence=sum(1 for item in items if not item.document_ids),
        decided=accepted + len(rejected_items),
        accepted=accepted,
        rejected=len(rejected_items),
        escalated=sum(1 for item in items if item.escalated),
        open=sum(1 for item in items if item.review_status in ("draft", "needs_expert")),
        open_second_person=sum(
            1
            for item in items
            if item.review_status == "needs_expert"
            or (item.review_status == "draft" and item.risk_class == "heightened")
        ),
        median_decision_time=_median(durations),
        rejection_reasons=dict(Counter(_reason(item) for item in rejected_items)),
        releases=releases,
        documents=tuple(document_rows),
    )


def overdue_reviews(queue: Iterable[StoredAnswer], now: datetime) -> tuple[StoredAnswer, ...]:
    """Answers that have been waiting for a second person for longer than the review target."""
    return tuple(
        item for item in queue if item.needs_second_person and now - item.answer.provenance.generated_at > REVIEW_TARGET
    )


def quality_export_rows(quality: AnswerQuality) -> list[dict[str, str]]:
    rows = []
    for item in quality.releases:
        share = item.rejection_share
        row = {
            "prompt_version": item.prompt_version,
            "model_snapshot": item.model_snapshot,
            "deployment": item.deployment,
            "answers": str(item.answers),
            "without_evidence": str(item.without_evidence),
            "decided": str(item.decided),
            "accepted": str(item.accepted),
            "rejected": str(item.rejected),
            "escalated": str(item.escalated),
            "open": str(item.open),
            # Decimal comma to match the semicolon CSV that German spreadsheet defaults expect.
            "rejection_share_percent": f"{share * 100:.1f}".replace(".", ",") if share is not None else "",
        }
        for reason in (*REVIEW_REJECTION_REASONS, UNKNOWN_REASON):
            row[f"rejected_{reason}"] = str(item.rejection_reasons.get(reason, 0))
        rows.append(row)
    return rows


def window_start(now: datetime, days: int) -> datetime:
    return now.astimezone(UTC) - timedelta(days=days)
