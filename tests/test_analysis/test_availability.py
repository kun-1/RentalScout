from datetime import UTC, datetime

from rentalscout.analysis.availability import reconcile_availability
from rentalscout.schemas.normalized import ListingAvailabilityStatus, NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import load_observations, upsert_listings


def _listing(
    listing_id: str, *, rent_price: int, district: str = "浦东"
) -> NormalizedRentalListing:
    seen = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/shanghai/{listing_id}",
        title=f"{district} 测试小区",
        rent_price=rent_price,
        district=district,
        first_seen_at=seen,
        last_seen_at=seen,
    )


def test_partial_crawl_marks_out_of_window_not_offline(tmp_path) -> None:
    db_path = tmp_path / "db.sqlite3"
    upsert_listings(
        [_listing("A", rent_price=4500), _listing("B", rent_price=4800)], db_path=db_path
    )

    # seen < total => not full => absent listings get OUT_OF_WINDOW
    result = reconcile_availability(
        ["A"], seen_total=10, db_path=db_path, now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    )

    assert result.is_full_crawl is False
    assert result.scope_total == 2
    assert result.in_scope_active == 1
    assert result.newly_offline == 0
    assert result.newly_out_of_window == 1
    assert {d.source_listing_id for d in result.delisted} == {"B"}
    assert result.delisted[0].status == ListingAvailabilityStatus.OUT_OF_WINDOW

    latest = {
        (o.source, o.source_listing_id): o.availability_status
        for o in load_observations(db_path=db_path)
        if o.observed_at == datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    }
    assert latest[("wellcee", "B")] == ListingAvailabilityStatus.OUT_OF_WINDOW


def test_full_crawl_marks_offline(tmp_path) -> None:
    db_path = tmp_path / "db.sqlite3"
    # 1 in-scope historical listing, no other historical in scope (small) =>
    # seen covers api_total and in_scope <= api_total, so full => OFFLINE
    upsert_listings([_listing("A", rent_price=4500)], db_path=db_path)

    result = reconcile_availability(
        ["A"], seen_total=1, db_path=db_path, now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    )

    # A is active (in seen), so no offline rows
    assert result.is_full_crawl is True
    assert result.newly_offline == 0
    assert result.newly_out_of_window == 0


def test_actually_absent_listing_under_full_crawl_gets_offline(tmp_path) -> None:
    """If historical in_scope is small AND api_total is small AND listing is absent: OFFLINE."""
    db_path = tmp_path / "db.sqlite3"
    upsert_listings([_listing("A", rent_price=4500)], db_path=db_path)

    result = reconcile_availability(
        [], seen_total=1, db_path=db_path, now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    )

    assert result.is_full_crawl is False  # len(seen)=0 < seen_total=1
    assert result.newly_out_of_window == 1
    assert result.delisted[0].status == ListingAvailabilityStatus.OUT_OF_WINDOW


def test_out_of_scope_listing_never_marked(tmp_path) -> None:
    db_path = tmp_path / "db.sqlite3"
    upsert_listings(
        [_listing("X", rent_price=9000), _listing("Y", rent_price=4500, district="徐汇")],
        db_path=db_path,
    )

    result = reconcile_availability(
        [], seen_total=0, db_path=db_path, now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    )

    assert result.scope_total == 0
    assert result.newly_offline == 0
    assert result.newly_out_of_window == 0


def test_already_marked_not_remarked(tmp_path) -> None:
    db_path = tmp_path / "db.sqlite3"
    upsert_listings([_listing("B", rent_price=4800)], db_path=db_path)

    first = reconcile_availability(
        ["A"], seen_total=10, db_path=db_path, now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    )
    second = reconcile_availability(
        ["A"], seen_total=10, db_path=db_path, now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    )

    assert first.newly_out_of_window == 1
    assert second.newly_out_of_window == 0
    assert second.already_out_of_window == 1
