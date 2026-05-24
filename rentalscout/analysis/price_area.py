"""价格与面积分析。"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rentalscout.analysis.commute import DEFAULT_DISTANCE_BUCKET_CSV
from rentalscout.analysis.wellcee_quality import (
    AnalysisTier,
    WellceeQualityRow,
    analyze_wellcee_quality,
)
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

DEFAULT_PRICE_AREA_CSV = DATA_DIR / "analysis" / "price_area_analysis.csv"
DEFAULT_PRICE_AREA_SUMMARY_JSON = DATA_DIR / "analysis" / "price_area_summary.json"
MIN_COMMUNITY_SAMPLE_SIZE = 3


@dataclass(frozen=True)
class DistributionStats:
    """一组价格或单价分布统计。"""

    count: int
    min: float
    p25: float
    median: float
    p75: float
    max: float
    iqr: float


@dataclass(frozen=True)
class PriceAreaRow:
    """单条房源价格与面积分析结果。"""

    listing_id: str
    source_url: str
    title: str
    community_name: str | None
    distance_bucket: str
    rent_price: int
    area_sqm: float
    rent_per_sqm: float
    bucket_price_median: float
    bucket_rent_per_sqm_median: float
    price_percentile_in_bucket: float
    rent_per_sqm_percentile_in_bucket: float
    price_delta_from_bucket_median: float
    rent_per_sqm_delta_from_bucket_median: float
    community_sample_size: int
    community_price_median: float | None
    community_rent_per_sqm_median: float | None
    good_price: bool
    good_area_price: bool
    expensive: bool
    area_price_expensive: bool
    low_price_outlier: bool
    high_price_outlier: bool
    low_area_price_outlier: bool
    high_area_price_outlier: bool
    apartment_like: bool
    possible_duplicate: bool
    analysis_notes: str


def generate_price_area_outputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    distance_bucket_csv: Path = DEFAULT_DISTANCE_BUCKET_CSV,
    csv_path: Path = DEFAULT_PRICE_AREA_CSV,
    summary_path: Path = DEFAULT_PRICE_AREA_SUMMARY_JSON,
) -> tuple[list[PriceAreaRow], dict[str, object]]:
    """生成价格与面积分析 CSV/JSON。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    quality_rows = analyze_wellcee_quality(listings)
    distance_buckets = load_distance_buckets(distance_bucket_csv)
    rows = analyze_price_area(
        listings=listings,
        quality_rows=quality_rows,
        distance_buckets=distance_buckets,
    )
    summary = summarize_price_area_rows(rows)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_price_area_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def load_distance_buckets(path: Path = DEFAULT_DISTANCE_BUCKET_CSV) -> dict[str, str]:
    """读取直线距离分桶结果。"""

    with path.open(encoding="utf-8", newline="") as file:
        return {
            row["listing_id"]: row["distance_bucket"]
            for row in csv.DictReader(file)
            if row.get("listing_id") and row.get("distance_bucket")
        }


def analyze_price_area(
    *,
    listings: list[NormalizedRentalListing],
    quality_rows: list[WellceeQualityRow],
    distance_buckets: dict[str, str],
) -> list[PriceAreaRow]:
    """计算每条房源在距离桶内的价格和面积位置。"""

    quality_by_id = {row.source_listing_id: row for row in quality_rows}
    candidates = [
        listing
        for listing in listings
        if _is_price_area_candidate(listing, quality_by_id, distance_buckets)
    ]
    bucket_price_values = _values_by_group(candidates, distance_buckets, value_name="price")
    bucket_rps_values = _values_by_group(candidates, distance_buckets, value_name="rent_per_sqm")
    community_price_values = _community_values(candidates, value_name="price")
    community_rps_values = _community_values(candidates, value_name="rent_per_sqm")
    bucket_price_stats = {
        key: distribution_stats(values) for key, values in bucket_price_values.items()
    }
    bucket_rps_stats = {
        key: distribution_stats(values) for key, values in bucket_rps_values.items()
    }
    community_price_stats = _stats_for_large_communities(community_price_values)
    community_rps_stats = _stats_for_large_communities(community_rps_values)

    rows: list[PriceAreaRow] = []
    for listing in sorted(candidates, key=lambda item: item.source_listing_id or ""):
        listing_id = listing.source_listing_id or ""
        bucket = distance_buckets[listing_id]
        quality = quality_by_id[listing_id]
        rent_price = int(listing.rent_price or 0)
        area_sqm = float(listing.area_sqm or 0)
        rent_per_sqm = round(rent_price / area_sqm, 2)
        price_stats = bucket_price_stats[bucket]
        rps_stats = bucket_rps_stats[bucket]
        community_name = listing.community_name
        community_price_stat = (
            community_price_stats.get(community_name or "") if community_name else None
        )
        community_rps_stat = (
            community_rps_stats.get(community_name or "") if community_name else None
        )
        row = PriceAreaRow(
            listing_id=listing_id,
            source_url=str(listing.source_url),
            title=listing.title,
            community_name=community_name,
            distance_bucket=bucket,
            rent_price=rent_price,
            area_sqm=area_sqm,
            rent_per_sqm=rent_per_sqm,
            bucket_price_median=price_stats.median,
            bucket_rent_per_sqm_median=rps_stats.median,
            price_percentile_in_bucket=percentile_rank(bucket_price_values[bucket], rent_price),
            rent_per_sqm_percentile_in_bucket=percentile_rank(
                bucket_rps_values[bucket],
                rent_per_sqm,
            ),
            price_delta_from_bucket_median=round(rent_price - price_stats.median, 2),
            rent_per_sqm_delta_from_bucket_median=round(rent_per_sqm - rps_stats.median, 2),
            community_sample_size=len(community_price_values.get(community_name or "", [])),
            community_price_median=community_price_stat.median if community_price_stat else None,
            community_rent_per_sqm_median=community_rps_stat.median if community_rps_stat else None,
            good_price=rent_price <= price_stats.p25,
            good_area_price=rent_per_sqm <= rps_stats.p25,
            expensive=rent_price >= price_stats.p75,
            area_price_expensive=rent_per_sqm >= rps_stats.p75,
            low_price_outlier=rent_price < price_stats.p25 - 1.5 * price_stats.iqr,
            high_price_outlier=rent_price > price_stats.p75 + 1.5 * price_stats.iqr,
            low_area_price_outlier=rent_per_sqm < rps_stats.p25 - 1.5 * rps_stats.iqr,
            high_area_price_outlier=rent_per_sqm > rps_stats.p75 + 1.5 * rps_stats.iqr,
            apartment_like=quality.apartment_like,
            possible_duplicate=quality.possible_duplicate,
            analysis_notes="",
        )
        rows.append(row_with_notes(row))
    return rows


def summarize_price_area_rows(rows: list[PriceAreaRow]) -> dict[str, object]:
    """汇总价格与面积分析结果。"""

    bucket_counts = Counter(row.distance_bucket for row in rows)
    return {
        "total_listings": len(rows),
        "distance_buckets": dict(sorted(bucket_counts.items())),
        "labels": {
            "good_price": sum(row.good_price for row in rows),
            "good_area_price": sum(row.good_area_price for row in rows),
            "expensive": sum(row.expensive for row in rows),
            "area_price_expensive": sum(row.area_price_expensive for row in rows),
            "low_price_outlier": sum(row.low_price_outlier for row in rows),
            "high_price_outlier": sum(row.high_price_outlier for row in rows),
            "low_area_price_outlier": sum(row.low_area_price_outlier for row in rows),
            "high_area_price_outlier": sum(row.high_area_price_outlier for row in rows),
        },
        "risks": {
            "apartment_like": sum(row.apartment_like for row in rows),
            "possible_duplicate": sum(row.possible_duplicate for row in rows),
        },
    }


def distribution_stats(values: list[float]) -> DistributionStats:
    """用分位数和 IQR 描述一组分布。"""

    sorted_values = sorted(values)
    if not sorted_values:
        msg = "distribution requires at least one value"
        raise ValueError(msg)
    p25 = percentile_value(sorted_values, 0.25)
    p75 = percentile_value(sorted_values, 0.75)
    return DistributionStats(
        count=len(sorted_values),
        min=round(sorted_values[0], 2),
        p25=round(p25, 2),
        median=round(statistics.median(sorted_values), 2),
        p75=round(p75, 2),
        max=round(sorted_values[-1], 2),
        iqr=round(p75 - p25, 2),
    )


def percentile_value(sorted_values: list[float], percentile: float) -> float:
    """返回最近秩分位数。"""

    index = round((len(sorted_values) - 1) * percentile)
    return sorted_values[index]


def percentile_rank(values: list[float], value: float) -> float:
    """返回 value 在 values 中的百分位位置, 范围 0-1。"""

    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return 0.0
    less_or_equal = sum(candidate <= value for candidate in sorted_values)
    return round((less_or_equal - 1) / (len(sorted_values) - 1), 4)


def row_with_notes(row: PriceAreaRow) -> PriceAreaRow:
    """补充中文分析说明。"""

    notes: list[str] = []
    if row.good_price:
        notes.append("租金低于同距离桶 p25")
    if row.good_area_price:
        notes.append("单位面积租金低于同距离桶 p25")
    if row.expensive:
        notes.append("租金高于同距离桶 p75")
    if row.area_price_expensive:
        notes.append("单位面积租金高于同距离桶 p75")
    if row.low_price_outlier or row.low_area_price_outlier:
        notes.append("疑似低价异常, 需要人工复核")
    if row.high_price_outlier or row.high_area_price_outlier:
        notes.append("疑似高价异常")
    if row.apartment_like:
        notes.append("疑似公寓类房源")
    if row.possible_duplicate:
        notes.append("存在重复候选")
    if row.community_sample_size >= MIN_COMMUNITY_SAMPLE_SIZE:
        notes.append("已启用同小区辅助比较")
    return row.__class__(**{**asdict(row), "analysis_notes": "; ".join(notes)})


def _is_price_area_candidate(
    listing: NormalizedRentalListing,
    quality_by_id: dict[str, WellceeQualityRow],
    distance_buckets: dict[str, str],
) -> bool:
    listing_id = listing.source_listing_id
    if not listing_id or listing_id not in distance_buckets:
        return False
    quality = quality_by_id.get(listing_id)
    return bool(
        quality
        and quality.analysis_tier != AnalysisTier.BLOCKED
        and quality.can_analyze_price
        and quality.can_analyze_area_price
        and listing.rent_price is not None
        and listing.area_sqm is not None
        and listing.area_sqm > 0
    )


def _values_by_group(
    listings: list[NormalizedRentalListing],
    distance_buckets: dict[str, str],
    *,
    value_name: str,
) -> dict[str, list[float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for listing in listings:
        listing_id = listing.source_listing_id or ""
        bucket = distance_buckets[listing_id]
        values[bucket].append(_value_for_listing(listing, value_name))
    return values


def _community_values(
    listings: list[NormalizedRentalListing],
    *,
    value_name: str,
) -> dict[str, list[float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for listing in listings:
        if listing.community_name:
            values[listing.community_name].append(_value_for_listing(listing, value_name))
    return values


def _stats_for_large_communities(
    grouped_values: dict[str, list[float]],
) -> dict[str, DistributionStats]:
    return {
        community: distribution_stats(values)
        for community, values in grouped_values.items()
        if len(values) >= MIN_COMMUNITY_SAMPLE_SIZE
    }


def _value_for_listing(listing: NormalizedRentalListing, value_name: str) -> float:
    if value_name == "price":
        return float(listing.rent_price or 0)
    if value_name == "rent_per_sqm":
        return round(float(listing.rent_price or 0) / float(listing.area_sqm or 1), 2)
    msg = f"unknown value name: {value_name}"
    raise ValueError(msg)


def _write_price_area_csv(rows: list[PriceAreaRow], path: Path) -> None:
    fieldnames = list(PriceAreaRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
