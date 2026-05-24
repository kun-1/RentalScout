from __future__ import annotations

import json

import pytest

from rentalscout.analysis.geo_clusters import (
    NOISE_CLUSTER_ID,
    analyze_geo_clusters,
    generate_geo_cluster_outputs,
)
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import upsert_listings


def test_analyze_geo_clusters_marks_cluster_and_noise() -> None:
    listings = [
        _listing("1", longitude=121.5200, latitude=31.2300),
        _listing("2", longitude=121.5204, latitude=31.2300),
        _listing("3", longitude=121.5208, latitude=31.2300),
        _listing("4", longitude=121.5212, latitude=31.2300),
        _listing("5", longitude=121.5216, latitude=31.2300),
        _listing("6", longitude=121.6000, latitude=31.2300),
    ]

    rows = analyze_geo_clusters(listings, eps_meters=120, min_samples=3)
    row_by_id = {row.listing_id: row for row in rows}

    assert row_by_id["1"].geo_cluster_id == "geo_c001"
    assert row_by_id["5"].geo_cluster_id == "geo_c001"
    assert row_by_id["1"].geo_cluster_size == 5
    assert row_by_id["3"].is_core_point is True
    assert row_by_id["6"].geo_cluster_id == NOISE_CLUSTER_ID
    assert row_by_id["6"].is_geo_noise is True
    assert row_by_id["6"].geo_cluster_size == 0


def test_analyze_geo_clusters_accepts_parameter_changes() -> None:
    listings = [
        _listing("1", longitude=121.5200, latitude=31.2300),
        _listing("2", longitude=121.5207, latitude=31.2300),
        _listing("3", longitude=121.5214, latitude=31.2300),
    ]

    tight_rows = analyze_geo_clusters(listings, eps_meters=30, min_samples=2)
    loose_rows = analyze_geo_clusters(listings, eps_meters=100, min_samples=2)

    assert all(row.is_geo_noise for row in tight_rows)
    assert all(not row.is_geo_noise for row in loose_rows)


def test_analyze_geo_clusters_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError, match="eps_meters"):
        analyze_geo_clusters([], eps_meters=0, min_samples=2)

    with pytest.raises(ValueError, match="min_samples"):
        analyze_geo_clusters([], eps_meters=100, min_samples=0)


def test_generate_geo_cluster_outputs_from_sqlite(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    output_csv = tmp_path / "geo_clusters.csv"
    summary_json = tmp_path / "geo_clusters_summary.json"
    listings = [
        _listing("1", longitude=121.5200, latitude=31.2300),
        _listing("2", longitude=121.5204, latitude=31.2300),
        _listing("3", longitude=121.5208, latitude=31.2300),
        _listing("4", longitude=121.6000, latitude=31.2300),
    ]
    upsert_listings(listings, db_path=db_path)

    rows, summary = generate_geo_cluster_outputs(
        db_path=db_path,
        csv_path=output_csv,
        summary_path=summary_json,
        eps_meters=120,
        min_samples=3,
    )

    assert len(rows) == 4
    assert summary["parameters"] == {"eps_meters": 120, "min_samples": 3}
    assert summary["cluster_count"] == 1
    assert summary["clustered_listings"] == 3
    assert summary["noise_listings"] == 1
    assert output_csv.exists()
    assert json.loads(summary_json.read_text(encoding="utf-8"))["cluster_count"] == 1


def _listing(
    source_listing_id: str,
    *,
    longitude: float,
    latitude: float,
) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=source_listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/{source_listing_id}",
        title=f"测试房源 {source_listing_id}",
        rent_price=4500,
        area_sqm=45,
        district="浦东",
        longitude=longitude,
        latitude=latitude,
    )
