from __future__ import annotations

from rentalscout.analysis.commute import (
    DistanceBucket,
    Workplace,
    analyze_distance_buckets,
    distance_bucket,
    distance_row_for_listing,
    generate_distance_bucket_outputs,
    haversine_distance_meters,
    parse_amap_geocode_payload,
)
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import upsert_listings


def test_distance_bucket_boundaries() -> None:
    assert distance_bucket(3_999) == DistanceBucket.WITHIN_4KM
    assert distance_bucket(4_000) == DistanceBucket.KM_4_TO_8
    assert distance_bucket(7_999) == DistanceBucket.KM_4_TO_8
    assert distance_bucket(8_000) == DistanceBucket.KM_8_TO_12
    assert distance_bucket(12_000) == DistanceBucket.KM_8_TO_12
    assert distance_bucket(12_001) == DistanceBucket.OVER_12KM


def test_haversine_distance_is_reasonable_for_nearby_points() -> None:
    distance = haversine_distance_meters(121.52, 31.23, 121.53, 31.23)

    assert 900 <= distance <= 1_100


def test_parse_amap_geocode_payload() -> None:
    workplace = parse_amap_geocode_payload(
        {
            "status": "1",
            "geocodes": [
                {
                    "formatted_address": "上海市浦东新区测试地址",
                    "location": "121.520000,31.230000",
                }
            ],
        },
        workplace_id="work",
        fallback_name="工作地点",
    )

    assert workplace.workplace_id == "work"
    assert workplace.name == "上海市浦东新区测试地址"
    assert workplace.longitude == 121.52
    assert workplace.latitude == 31.23


def test_parse_amap_geocode_payload_rejects_missing_location() -> None:
    try:
        parse_amap_geocode_payload(
            {"status": "1", "geocodes": []},
            workplace_id="work",
            fallback_name="错误地点",
        )
    except ValueError as error:
        assert str(error) == "invalid_workplace_location"
    else:
        raise AssertionError("expected invalid workplace location")


def test_analyze_distance_buckets_changes_when_workplace_changes() -> None:
    listing = _listing(longitude=121.53, latitude=31.23)
    near_workplace = Workplace(
        workplace_id="near",
        name="近工作地点",
        longitude=121.52,
        latitude=31.23,
    )
    far_workplace = Workplace(
        workplace_id="far",
        name="远工作地点",
        longitude=121.70,
        latitude=31.23,
    )

    near_rows = analyze_distance_buckets(listings=[listing], workplace=near_workplace)
    far_rows = analyze_distance_buckets(listings=[listing], workplace=far_workplace)

    assert near_rows[0].distance_bucket == DistanceBucket.WITHIN_4KM
    assert far_rows[0].distance_bucket == DistanceBucket.OVER_12KM
    assert near_rows[0].workplace_id == "near"
    assert far_rows[0].workplace_id == "far"


def test_distance_row_for_listing() -> None:
    workplace = Workplace(
        workplace_id="work",
        name="工作地点",
        longitude=121.52,
        latitude=31.23,
    )

    row = distance_row_for_listing(
        _listing(longitude=121.53, latitude=31.23),
        workplace=workplace,
    )

    assert row.distance_bucket == DistanceBucket.WITHIN_4KM
    assert 900 <= row.straight_distance_meters <= 1_100


def test_generate_distance_bucket_outputs_from_sqlite(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    csv_path = tmp_path / "commute_distance_buckets.csv"
    summary_path = tmp_path / "commute_distance_buckets_summary.json"
    workplace = Workplace(
        workplace_id="work",
        name="工作地点",
        longitude=121.52,
        latitude=31.23,
    )
    upsert_listings([_listing(longitude=121.53, latitude=31.23)], db_path=db_path)

    rows, summary = generate_distance_bucket_outputs(
        workplace=workplace,
        db_path=db_path,
        csv_path=csv_path,
        summary_path=summary_path,
    )

    assert len(rows) == 1
    assert summary["total_listings"] == 1
    assert summary["distance_buckets"]["within_4km"] == 1
    assert csv_path.exists()
    assert summary_path.exists()


def _listing(
    *,
    longitude: float,
    latitude: float,
    listing_id: str = "1",
) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/{listing_id}",
        title="测试房源",
        rent_price=4500,
        district="浦东",
        community_name="测试小区",
        longitude=longitude,
        latitude=latitude,
    )
