"""Schemas for manual and semi-automatic validation."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from rentalscout.schemas.raw import SourceName


class FieldReviewStatus(StrEnum):
    """Validation status for an individual field."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class OverallReviewStatus(StrEnum):
    """Validation status for an entire listing."""

    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"
    DOWN = "down"


class ValidationReview(BaseModel):
    """Human review record for a parsed listing."""

    listing_id: str
    source: SourceName
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reviewer: str | None = None
    title_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    price_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    area_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    location_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    image_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    availability_status: FieldReviewStatus = FieldReviewStatus.UNKNOWN
    overall_status: OverallReviewStatus = OverallReviewStatus.NEEDS_REVIEW
    notes: str | None = None
