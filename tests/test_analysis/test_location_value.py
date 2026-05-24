from __future__ import annotations

import csv
import json

from rentalscout.analysis.location_value import (
    PriceAreaInputRow,
    analyze_location_value,
    generate_location_value_outputs,
    nearby_listing_ids,
)
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import upsert_listings


def test_nearby_listing_ids_uses_radius() -> None:
    listings = {
        "1": _listing("1", longitude=121.52, latitude=31.23, community_name="A"),
        "2": _listing("2", longitude=121.521, latitude=31.23, community_name="B"),
        "3": _listing("3", longitude=121.60, latitude=31.23, community_name="C"),
    }

    assert nearby_listing_ids("1", listings, radius_meters=300) == ["2"]


def test_analyze_location_value_marks_nearby_good_value_and_community_best() -> None:
    listings = [
        _listing("1", rent_price=4000, area_sqm=50, community_name="测试小区"),
        _listing("2", rent_price=4500, area_sqm=45, community_name="测试小区"),
        _listing("3", rent_price=5000, area_sqm=40, community_name="测试小区"),
        _listing("4", rent_price=5500, area_sqm=35, community_name="其他小区"),
        _listing("5", rent_price=6000, area_sqm=30, community_name="其他小区"),
        _listing("6", rent_price=5200, area_sqm=40, community_name="其他小区"),
    ]
    price_area_rows = {
        listing.source_listing_id: _price_row(listing)
        for listing in listings
        if listing.source_listing_id
    }

    rows = analyze_location_value(
        listings=listings,
        price_area_rows=price_area_rows,
        nearby_radius_meters=1_000,
    )
    first = rows[0]

    assert first.nearby_sample_size == 5
    assert first.below_nearby_median is True
    assert first.nearby_good_value is True
    assert first.below_community_median is True
    assert first.best_price_in_community is True
    assert first.best_area_price_in_community is True


def test_generate_location_value_outputs_from_sqlite(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    price_area_csv = tmp_path / "price_area_analysis.csv"
    output_csv = tmp_path / "location_value_analysis.csv"
    summary_json = tmp_path / "location_value_summary.json"
    listings = [
        _listing("1", rent_price=4000, area_sqm=50, community_name="测试小区"),
        _listing("2", rent_price=4500, area_sqm=45, community_name="测试小区"),
        _listing("3", rent_price=5000, area_sqm=40, community_name="测试小区"),
        _listing("4", rent_price=5500, area_sqm=35, community_name="其他小区"),
        _listing("5", rent_price=6000, area_sqm=30, community_name="其他小区"),
    ]
    upsert_listings(listings, db_path=db_path)
    with price_area_csv.open("w", encoding="utf-8", newline="") as file:
        fieldnames = [
            "listing_id",
            "rent_price",
            "area_sqm",
            "rent_per_sqm",
            "distance_bucket",
            "apartment_like",
            "possible_duplicate",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for listing in listings:
            row = _price_row(listing)
            writer.writerow(
                {
                    "listing_id": row.listing_id,
                    "rent_price": row.rent_price,
                    "area_sqm": row.area_sqm,
                    "rent_per_sqm": row.rent_per_sqm,
                    "distance_bucket": row.distance_bucket,
                    "apartment_like": row.apartment_like,
                    "possible_duplicate": row.possible_duplicate,
                }
            )

    rows, summary = generate_location_value_outputs(
        db_path=db_path,
        price_area_csv=price_area_csv,
        csv_path=output_csv,
        summary_path=summary_json,
        nearby_radius_meters=1_000,
    )

    assert len(rows) == 5
    assert summary["total_listings"] == 5
    assert output_csv.exists()
    assert json.loads(summary_json.read_text(encoding="utf-8"))["total_listings"] == 5


def _listing(
    source_listing_id: str,
    *,
    rent_price: int = 4000,
    area_sqm: float = 50,
    community_name: str = "测试小区",
    longitude: float = 121.52,
    latitude: float = 31.23,
) -> NormalizedRentalListing:
    offset = int(source_listing_id) * 0.0002
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=source_listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/{source_listing_id}",
        title=f"测试房源 {source_listing_id}",
        rent_price=rent_price,
        area_sqm=area_sqm,
        district="浦东",
        community_name=community_name,
        longitude=longitude + offset,
        latitude=latitude,
    )


def _price_row(listing: NormalizedRentalListing) -> PriceAreaInputRow:
    rent_price = int(listing.rent_price or 0)
    area_sqm = float(listing.area_sqm or 1)
    return PriceAreaInputRow(
        listing_id=listing.source_listing_id or "",
        rent_price=rent_price,
        area_sqm=area_sqm,
        rent_per_sqm=round(rent_price / area_sqm, 2),
        distance_bucket="within_4km",
        apartment_like=False,
        possible_duplicate=False,
    )
