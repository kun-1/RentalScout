from __future__ import annotations

from pathlib import Path

from rentalscout.analysis.commute import (
    AmapRouteClient,
    CommuteMode,
    DistanceBucket,
    RouteStatus,
    Workplace,
    analyze_listing_commute,
    distance_bucket,
    distance_row_for_listing,
    generate_commute_outputs,
    generate_distance_bucket_outputs,
    haversine_distance_meters,
    modes_for_bucket,
    parse_amap_geocode_payload,
    parse_amap_route_payload,
    route_status,
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


def test_modes_for_bucket() -> None:
    assert modes_for_bucket(DistanceBucket.WITHIN_4KM) == {
        CommuteMode.WALKING,
        CommuteMode.BICYCLING,
    }
    assert modes_for_bucket(DistanceBucket.KM_4_TO_8) == {CommuteMode.BICYCLING}
    assert modes_for_bucket(DistanceBucket.KM_8_TO_12) == {CommuteMode.BICYCLING}
    assert modes_for_bucket(DistanceBucket.OVER_12KM) == set()


def test_haversine_distance_is_reasonable_for_nearby_points() -> None:
    distance = haversine_distance_meters(121.52, 31.23, 121.53, 31.23)

    assert 900 <= distance <= 1_100


def test_parse_amap_walking_payload() -> None:
    result = parse_amap_route_payload(
        {
            "status": "1",
            "route": {
                "paths": [
                    {
                        "distance": "1350",
                        "duration": "901",
                    }
                ]
            },
        },
        mode=CommuteMode.WALKING,
        raw_path=Path("raw.json"),
    )

    assert result.distance_meters == 1350
    assert result.duration_minutes == 16
    assert result.raw_response_path == Path("raw.json")
    assert result.error_message is None


def test_parse_amap_error_payload() -> None:
    result = parse_amap_route_payload(
        {"status": "0", "info": "INVALID_USER_KEY"},
        mode=CommuteMode.BICYCLING,
    )

    assert result.distance_meters is None
    assert result.duration_minutes is None
    assert result.error_message == "INVALID_USER_KEY"


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


def test_route_status_marks_detour_as_caution() -> None:
    result = parse_amap_route_payload(
        {"status": "1", "route": {"paths": [{"distance": "9000", "duration": "1800"}]}},
        mode=CommuteMode.BICYCLING,
    )

    assert route_status(result, straight_distance_meters=2_000) == RouteStatus.CAUTION


def test_analyze_listing_commute_dry_run_skips_by_strategy() -> None:
    workplace = Workplace(
        workplace_id="work",
        name="工作地点",
        longitude=121.52,
        latitude=31.23,
    )
    listing = _listing(longitude=121.53, latitude=31.23)
    results = analyze_listing_commute(
        listing,
        workplace=workplace,
        client=AmapRouteClient(api_key=None),
        dry_run=True,
    )

    assert [result.mode for result in results] == [CommuteMode.WALKING, CommuteMode.BICYCLING]
    assert {result.route_status for result in results} == {RouteStatus.SKIPPED}
    assert {result.skip_reason for result in results} == {"dry_run"}


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


def test_generate_commute_outputs_from_sqlite_dry_run(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    csv_path = tmp_path / "commute_results.csv"
    summary_path = tmp_path / "commute_summary.json"
    raw_dir = tmp_path / "raw"
    workplace = Workplace(
        workplace_id="work",
        name="工作地点",
        longitude=121.52,
        latitude=31.23,
    )
    upsert_listings(
        [
            _listing(longitude=121.53, latitude=31.23),
            _listing(longitude=121.70, latitude=31.23),
        ],
        db_path=db_path,
    )

    rows, summary = generate_commute_outputs(
        workplace=workplace,
        db_path=db_path,
        csv_path=csv_path,
        summary_path=summary_path,
        raw_dir=raw_dir,
        dry_run=True,
    )

    assert len(rows) == 2
    assert summary["unique_listings"] == 1
    assert summary["statuses"]["skipped"] == 2
    assert csv_path.exists()
    assert summary_path.exists()


def _listing(*, longitude: float, latitude: float) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id="1",
        source_url="https://www.wellcee.com/rent-apartment/1",
        title="测试房源",
        rent_price=4500,
        district="浦东",
        community_name="测试小区",
        longitude=longitude,
        latitude=latitude,
    )
