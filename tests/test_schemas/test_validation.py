from rentalscout.schemas.raw import SourceName
from rentalscout.schemas.validation import OverallReviewStatus, ValidationReview


def test_validation_review_defaults_to_needs_review() -> None:
    review = ValidationReview(listing_id="listing-1", source=SourceName.BEIKE)

    assert review.overall_status == OverallReviewStatus.NEEDS_REVIEW
