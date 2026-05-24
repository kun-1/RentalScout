from __future__ import annotations

import csv
import json

from rentalscout.analysis.price_area import (
    analyze_price_area,
    distribution_stats,
    generate_price_area_outputs,
    percentile_rank,
)
from rentalscout.analysis.wellcee_quality import analyze_wellcee_quality
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import upsert_listings


def test_distribution_stats_uses_quartiles_and_iqr() -> None:
    stats = distribution_stats([4000, 4500, 5000, 6000])

    assert stats.count == 4
    assert stats.p25 == 4500
    assert stats.median == 4750
    assert stats.p75 == 5000
    assert stats.iqr == 500


def test_percentile_rank() -> None:
    assert percentile_rank([4000, 4500, 5000], 4000) == 0.0
    assert percentile_rank([4000, 4500, 5000], 4500) == 0.5
    assert percentile_rank([4000, 4500, 5000], 5000) == 1.0


def test_analyze_price_area_marks_good_and_expensive() -> None:
    listings = [
        _listing(source_listing_id="1", rent_price=4000, area_sqm=50),
        _listing(source_listing_id="2", rent_price=4500, area_sqm=45),
        _listing(source_listing_id="3", rent_price=5000, area_sqm=40),
        _listing(source_listing_id="4", rent_price=6000, area_sqm=30),
    ]
    distance_buckets = {listing.source_listing_id: "within_4km" for listing in listings}

    rows = analyze_price_area(
        listings=listings,
        quality_rows=analyze_wellcee_quality(listings),
        distance_buckets=distance_buckets,
    )

    first = rows[0]
    last = rows[-1]
    assert first.good_price is True
    assert first.good_area_price is True
    assert last.expensive is True
    assert last.area_price_expensive is True


def test_generate_price_area_outputs_from_sqlite(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    distance_csv = tmp_path / "commute_distance_buckets.csv"
    output_csv = tmp_path / "price_area_analysis.csv"
    summary_json = tmp_path / "price_area_summary.json"
    listings = [
        _listing(source_listing_id="1", rent_price=4000, area_sqm=50),
        _listing(source_listing_id="2", rent_price=4500, area_sqm=45),
        _listing(source_listing_id="3", rent_price=5000, area_sqm=40),
    ]
    upsert_listings(listings, db_path=db_path)
    with distance_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["listing_id", "distance_bucket"])
        writer.writeheader()
        for listing in listings:
            writer.writerow(
                {
                    "listing_id": listing.source_listing_id,
                    "distance_bucket": "4_to_8km",
                }
            )

    rows, summary = generate_price_area_outputs(
        db_path=db_path,
        distance_bucket_csv=distance_csv,
        csv_path=output_csv,
        summary_path=summary_json,
    )

    assert len(rows) == 3
    assert summary["total_listings"] == 3
    assert output_csv.exists()
    assert json.loads(summary_json.read_text(encoding="utf-8"))["total_listings"] == 3


def _listing(
    *,
    source_listing_id: str,
    rent_price: int,
    area_sqm: float,
) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=source_listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/{source_listing_id}",
        title=f"测试房源 {source_listing_id}",
        rent_price=rent_price,
        area_sqm=area_sqm,
        district="浦东",
        subdistrict="潍坊新村街道",
        community_name="测试小区",
        longitude=121.52,
        latitude=31.23,
    )
