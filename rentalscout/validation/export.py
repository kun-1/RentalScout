"""阶段 2 人工验证样本导出。"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from rentalscout.filters import ListingFilterResult
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.settings import DATA_DIR

DEFAULT_VALIDATION_CSV = DATA_DIR / "validation" / "phase1_validation_sample.csv"
DEFAULT_FILTER_CSV = DATA_DIR / "validation" / "phase1_filter_candidates.csv"

VALIDATION_FIELDS = [
    "source",
    "source_type",
    "source_listing_id",
    "source_url",
    "title",
    "city",
    "district",
    "subdistrict",
    "community_name",
    "rent_price",
    "rent_unit",
    "currency",
    "area_sqm",
    "layout",
    "floor",
    "deposit",
    "subway_info",
    "published_at",
    "price_confidence",
    "location_confidence",
    "area_confidence",
    "layout_confidence",
    "overall_confidence",
    "人工验证状态",
    "人工备注",
]

FILTER_FIELDS = [
    "accepted",
    "reasons",
    "source",
    "source_listing_id",
    "source_url",
    "title",
    "district",
    "subdistrict",
    "community_name",
    "rent_price",
    "area_sqm",
    "layout",
    "description",
    "parse_confidence",
]


def export_validation_sample(
    listings: Iterable[NormalizedRentalListing],
    output_path: Path = DEFAULT_VALIDATION_CSV,
) -> int:
    """导出人工验证 CSV。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(listings)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=VALIDATION_FIELDS)
        writer.writeheader()
        for listing in rows:
            writer.writerow(_format_validation_row(listing))
    return len(rows)


def export_filter_candidates(
    results: Iterable[ListingFilterResult],
    output_path: Path = DEFAULT_FILTER_CSV,
) -> int:
    """导出候选房源和过滤原因 CSV。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(results)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FILTER_FIELDS)
        writer.writeheader()
        for result in rows:
            listing = result.listing
            writer.writerow(
                {
                    "accepted": "是" if result.accepted else "否",
                    "reasons": "; ".join(result.reasons),
                    "source": listing.source.value,
                    "source_listing_id": listing.source_listing_id,
                    "source_url": str(listing.source_url),
                    "title": listing.title,
                    "district": listing.district,
                    "subdistrict": listing.subdistrict,
                    "community_name": listing.community_name,
                    "rent_price": listing.rent_price,
                    "area_sqm": listing.area_sqm,
                    "layout": listing.layout,
                    "description": listing.description,
                    "parse_confidence": listing.parse_confidence,
                }
            )
    return len(rows)


def _format_validation_row(listing: NormalizedRentalListing) -> dict[str, object]:
    return {
        "source": listing.source.value,
        "source_type": listing.source_type.value,
        "source_listing_id": listing.source_listing_id,
        "source_url": str(listing.source_url),
        "title": listing.title,
        "city": listing.city or "",
        "district": listing.district or "",
        "subdistrict": listing.subdistrict or "",
        "community_name": listing.community_name or "",
        "rent_price": listing.rent_price,
        "rent_unit": listing.rent_price_unit.value,
        "currency": listing.currency,
        "area_sqm": listing.area_sqm,
        "layout": listing.layout or "",
        "floor": listing.floor or "",
        "deposit": listing.deposit or "",
        "subway_info": listing.subway_info or "",
        "published_at": listing.published_at.isoformat() if listing.published_at else "",
        "price_confidence": listing.price_confidence,
        "location_confidence": listing.location_confidence,
        "area_confidence": listing.area_confidence,
        "layout_confidence": listing.layout_confidence,
        "overall_confidence": listing.overall_confidence,
        "人工验证状态": "",
        "人工备注": "",
    }
