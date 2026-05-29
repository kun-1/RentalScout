from datetime import UTC, datetime, timedelta

from rentalscout.analysis.price_history import analyze_price_history, summarize_price_history
from rentalscout.schemas.normalized import ListingAvailabilityStatus
from rentalscout.storage.sqlite import ListingObservation


def test_analyze_price_history_computes_price_delta() -> None:
    observed_at = datetime(2026, 5, 1, tzinfo=UTC)
    rows = analyze_price_history(
        [
            _observation(observed_at=observed_at, rent_price=4500, days_on_market=0),
            _observation(
                observed_at=observed_at + timedelta(days=2),
                rent_price=4300,
                days_on_market=2,
            ),
            _observation(
                observed_at=observed_at + timedelta(days=5),
                rent_price=4600,
                days_on_market=5,
            ),
        ]
    )

    assert rows[0].price_delta is None
    assert rows[1].price_delta == -200
    assert rows[1].price_delta_pct == -0.0444
    assert rows[1].price_change_direction == "down"
    assert rows[2].price_delta == 300
    assert rows[2].price_delta_from_first == 100
    assert rows[2].price_delta_from_lowest == 300


def test_summarize_price_history_counts_inactive_latest() -> None:
    observed_at = datetime(2026, 5, 1, tzinfo=UTC)
    rows = analyze_price_history(
        [
            _observation(observed_at=observed_at, rent_price=4500),
            _observation(
                observed_at=observed_at + timedelta(days=1),
                rent_price=4500,
                availability_status=ListingAvailabilityStatus.OFFLINE,
            ),
        ]
    )

    summary = summarize_price_history(rows)

    assert summary["unique_listings"] == 1
    assert summary["inactive_latest"] == 1


def _observation(
    *,
    observed_at: datetime,
    rent_price: int,
    availability_status: ListingAvailabilityStatus = ListingAvailabilityStatus.ACTIVE,
    days_on_market: int | None = None,
) -> ListingObservation:
    return ListingObservation(
        source="wellcee",
        source_listing_id="1",
        observed_at=observed_at,
        crawl_run_id=1,
        rent_price=rent_price,
        availability_status=availability_status,
        days_on_market=days_on_market,
        title="浦东 测试小区",
        area_sqm=45.0,
        district="浦东",
        community_name="测试小区",
    )
