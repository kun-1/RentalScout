from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from rentalscout.analysis.wellcee_quality import (
    AnalysisTier,
    analyze_wellcee_quality,
    generate_wellcee_quality_outputs,
)
from rentalscout.schemas.normalized import ListingType, NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import upsert_listings


def test_area_one_sqm_is_outlier_and_not_area_price_ready() -> None:
    rows = analyze_wellcee_quality([_listing(area_sqm=1.0)])

    assert rows[0].area_outlier is True
    assert rows[0].can_analyze_area_price is False
    assert rows[0].can_analyze_price is True
    assert rows[0].can_analyze_map is True


def test_complete_listing_is_ready() -> None:
    rows = analyze_wellcee_quality([_listing()])

    assert rows[0].analysis_tier == AnalysisTier.READY
    assert rows[0].can_analyze_price is True
    assert rows[0].can_analyze_area_price is True
    assert rows[0].can_analyze_commute is True
    assert rows[0].can_analyze_region is True


def test_apartment_like_is_marked_but_not_removed() -> None:
    rows = analyze_wellcee_quality([
        _listing(title="唐镇唐城人才公寓", community_name="唐镇唐城人才公寓")
    ])

    assert rows[0].apartment_like is True
    assert rows[0].can_analyze_price is True
    assert rows[0].can_analyze_map is True


def test_duplicate_title_price_community_is_marked() -> None:
    rows = analyze_wellcee_quality([
        _listing(source_listing_id="1"),
        _listing(source_listing_id="2"),
    ])

    assert [row.possible_duplicate for row in rows] == [True, True]
    assert [row.has_duplicate_risk for row in rows] == [True, True]


def test_missing_coordinates_blocks_map_and_commute() -> None:
    rows = analyze_wellcee_quality([_listing(latitude=None, longitude=None)])

    assert rows[0].can_analyze_map is False
    assert rows[0].can_analyze_commute is False
    assert rows[0].analysis_tier == AnalysisTier.BLOCKED


def test_generate_outputs_from_sqlite(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    csv_path = tmp_path / "wellcee_quality.csv"
    summary_path = tmp_path / "wellcee_quality_summary.json"
    listings = [
        _listing(source_listing_id="1"),
        _listing(source_listing_id="2", area_sqm=1.0),
        _listing(source_listing_id="3", source=SourceName.BEIKE),
    ]
    upsert_listings(listings, db_path=db_path)

    rows, summary = generate_wellcee_quality_outputs(
        db_path=db_path,
        csv_path=csv_path,
        summary_path=summary_path,
    )

    assert len(rows) == 2
    assert summary["total"] == 2
    assert set(summary["tiers"]) == {"ready", "caution", "blocked"}
    assert summary["capabilities"]["can_analyze_price"] == 2
    assert summary["risks"]["area_outlier"] == 1

    with csv_path.open(encoding="utf-8", newline="") as file:
        csv_rows = list(csv.DictReader(file))
    assert len(csv_rows) == 2

    loaded_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert loaded_summary["source"] == "wellcee"


def _listing(
    *,
    source: SourceName = SourceName.WELLCEE,
    source_listing_id: str = "1",
    title: str = "潍坊九村社区",
    rent_price: int = 4500,
    area_sqm: float = 45.0,
    district: str = "浦东",
    subdistrict: str = "潍坊新村街道",
    community_name: str = "潍坊九村社区",
    latitude: float | None = 31.23,
    longitude: float | None = 121.52,
) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=source,
        source_listing_id=source_listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/{source_listing_id}",
        title=title,
        rent_price=rent_price,
        area_sqm=area_sqm,
        district=district,
        subdistrict=subdistrict,
        community_name=community_name,
        city="上海",
        latitude=latitude,
        longitude=longitude,
        layout="1卧室/1洗手间",
        listing_type=ListingType.WHOLE_RENT,
        image_urls=["https://example.com/image.jpg"],
        published_at=datetime(2026, 5, 24, tzinfo=UTC),
    )
