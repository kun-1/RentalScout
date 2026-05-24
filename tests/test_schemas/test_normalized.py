from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName


def test_normalized_listing_strips_title() -> None:
    listing = NormalizedRentalListing(
        source=SourceName.BEIKE,
        source_url="https://example.com/listing",
        title="  Nice apartment  ",
        rent_price=4500,
    )

    assert listing.title == "Nice apartment"
    assert listing.rent_price == 4500


def test_normalized_listing_rejects_invalid_seen_range() -> None:
    now = datetime.now(UTC)

    try:
        NormalizedRentalListing(
            source=SourceName.WELLCEE,
            source_url="https://example.com/listing",
            title="Sublet",
            first_seen_at=now,
            last_seen_at=now - timedelta(days=1),
        )
    except ValidationError as error:
        assert "last_seen_at cannot be earlier" in str(error)
    else:
        raise AssertionError("expected validation error")
