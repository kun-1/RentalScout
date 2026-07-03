"""位置价值与同小区对比分析。"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rentalscout.analysis.commute import haversine_distance_meters
from rentalscout.analysis.price_area import (
    DEFAULT_PRICE_AREA_CSV,
    DistributionStats,
    distribution_stats,
)
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

DEFAULT_LOCATION_VALUE_CSV = DATA_DIR / "analysis" / "location_value_analysis.csv"
DEFAULT_LOCATION_VALUE_SUMMARY_JSON = DATA_DIR / "analysis" / "location_value_summary.json"
DEFAULT_NEARBY_RADIUS_METERS = 1_000
MIN_NEARBY_SAMPLE_SIZE = 5
MIN_COMMUNITY_SAMPLE_SIZE = 3


@dataclass(frozen=True)
class PriceAreaInputRow:
    """价格面积分析输入行。"""

    listing_id: str
    rent_price: int
    area_sqm: float
    rent_per_sqm: float
    distance_bucket: str
    apartment_like: bool
    possible_duplicate: bool


@dataclass(frozen=True)
class LocationValueRow:
    """单条房源的位置价值分析结果。"""

    listing_id: str
    source_url: str
    title: str
    community_name: str | None
    distance_bucket: str
    longitude: float
    latitude: float
    rent_price: int
    area_sqm: float
    rent_per_sqm: float
    nearby_radius_meters: int
    nearby_sample_size: int
    nearby_price_median: float | None
    nearby_rent_per_sqm_median: float | None
    price_delta_from_nearby_median: float | None
    rent_per_sqm_delta_from_nearby_median: float | None
    below_nearby_median: bool
    nearby_good_value: bool
    nearby_expensive: bool
    community_sample_size: int
    community_price_median: float | None
    community_rent_per_sqm_median: float | None
    below_community_median: bool
    above_community_median: bool
    best_price_in_community: bool
    best_area_price_in_community: bool
    apartment_like: bool
    possible_duplicate: bool
    analysis_notes: str


def generate_location_value_outputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    price_area_csv: Path = DEFAULT_PRICE_AREA_CSV,
    csv_path: Path = DEFAULT_LOCATION_VALUE_CSV,
    summary_path: Path = DEFAULT_LOCATION_VALUE_SUMMARY_JSON,
    nearby_radius_meters: int = DEFAULT_NEARBY_RADIUS_METERS,
) -> tuple[list[LocationValueRow], dict[str, object]]:
    """生成位置价值分析 CSV/JSON。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    price_area_rows = load_price_area_rows(price_area_csv)
    rows = analyze_location_value(
        listings=listings,
        price_area_rows=price_area_rows,
        nearby_radius_meters=nearby_radius_meters,
    )
    summary = summarize_location_value_rows(rows, nearby_radius_meters=nearby_radius_meters)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_location_value_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def load_price_area_rows(path: Path = DEFAULT_PRICE_AREA_CSV) -> dict[str, PriceAreaInputRow]:
    """读取价格面积分析输出。"""

    rows: dict[str, PriceAreaInputRow] = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            listing_id = row.get("listing_id")
            if not listing_id:
                continue
            rows[listing_id] = PriceAreaInputRow(
                listing_id=listing_id,
                rent_price=int(float(row["rent_price"])),
                area_sqm=float(row["area_sqm"]),
                rent_per_sqm=float(row["rent_per_sqm"]),
                distance_bucket=row["distance_bucket"],
                apartment_like=_bool_text(row.get("apartment_like")),
                possible_duplicate=_bool_text(row.get("possible_duplicate")),
            )
    return rows


def analyze_location_value(
    *,
    listings: list[NormalizedRentalListing],
    price_area_rows: dict[str, PriceAreaInputRow],
    nearby_radius_meters: int = DEFAULT_NEARBY_RADIUS_METERS,
) -> list[LocationValueRow]:
    """按附近房源和同小区房源比较价值。"""

    listing_by_id = {
        listing.source_listing_id: listing
        for listing in listings
        if listing.source_listing_id
        and listing.source_listing_id in price_area_rows
        and listing.longitude is not None
        and listing.latitude is not None
    }
    community_groups = _community_groups(listing_by_id, price_area_rows)

    # M2: 一次算全表 NxN haversine 距离矩阵, 每个 target 走 numpy 行切片
    dist_matrix_cache = _build_dist_matrix(listing_by_id)

    rows: list[LocationValueRow] = []
    for listing_id in sorted(listing_by_id):
        listing = listing_by_id[listing_id]
        price_row = price_area_rows[listing_id]
        nearby_ids = nearby_listing_ids(
            listing_id,
            listing_by_id,
            radius_meters=nearby_radius_meters,
            _dist_matrix_cache=dist_matrix_cache,
        )
        nearby_price_stats = _stats_for_ids(nearby_ids, price_area_rows, "price")
        nearby_rps_stats = _stats_for_ids(nearby_ids, price_area_rows, "rent_per_sqm")
        community_name = listing.community_name
        community_ids = community_groups.get(community_name or "", [])
        community_price_stat = _community_stats_for_ids(community_ids, price_area_rows, "price")
        community_rps_stat = _community_stats_for_ids(
            community_ids,
            price_area_rows,
            "rent_per_sqm",
        )

        row = LocationValueRow(
            listing_id=listing_id,
            source_url=str(listing.source_url),
            title=listing.title,
            community_name=community_name,
            distance_bucket=price_row.distance_bucket,
            longitude=float(listing.longitude),
            latitude=float(listing.latitude),
            rent_price=price_row.rent_price,
            area_sqm=price_row.area_sqm,
            rent_per_sqm=price_row.rent_per_sqm,
            nearby_radius_meters=nearby_radius_meters,
            nearby_sample_size=len(nearby_ids),
            nearby_price_median=nearby_price_stats.median if nearby_price_stats else None,
            nearby_rent_per_sqm_median=nearby_rps_stats.median if nearby_rps_stats else None,
            price_delta_from_nearby_median=_delta(price_row.rent_price, nearby_price_stats),
            rent_per_sqm_delta_from_nearby_median=_delta(
                price_row.rent_per_sqm,
                nearby_rps_stats,
            ),
            below_nearby_median=_below_median(price_row.rent_price, nearby_price_stats),
            nearby_good_value=_below_median(price_row.rent_per_sqm, nearby_rps_stats),
            nearby_expensive=_above_p75(price_row.rent_per_sqm, nearby_rps_stats),
            community_sample_size=len(community_ids),
            community_price_median=community_price_stat.median if community_price_stat else None,
            community_rent_per_sqm_median=(
                community_rps_stat.median if community_rps_stat else None
            ),
            below_community_median=_below_median(price_row.rent_price, community_price_stat),
            above_community_median=_above_median(price_row.rent_price, community_price_stat),
            best_price_in_community=_best_in_group(
                listing_id,
                community_ids,
                price_area_rows,
                "price",
            ),
            best_area_price_in_community=_best_in_group(
                listing_id,
                community_ids,
                price_area_rows,
                "rent_per_sqm",
            ),
            apartment_like=price_row.apartment_like,
            possible_duplicate=price_row.possible_duplicate,
            analysis_notes="",
        )
        rows.append(row_with_notes(row))
    return rows


def nearby_listing_ids(
    target_id: str,
    listing_by_id: dict[str, NormalizedRentalListing],
    *,
    radius_meters: int,
    _dist_matrix_cache: tuple | None = None,
) -> list[str]:
    """查找目标房源附近指定半径内的房源 ID。

    M2: 用预计算的 NxN 距离矩阵做行切片, O(N) 一次, 替代原 O(N) 循环 + Python
    haversine 调用。传 _dist_matrix_cache 以利用上游缓存; 没传时回退到旧路径。
    """

    target = listing_by_id[target_id]
    if target.longitude is None or target.latitude is None:
        return []
    if _dist_matrix_cache is None:
        # 慢路径: 原始实现, 单次调用
        nearby: list[str] = []
        for listing_id, listing in listing_by_id.items():
            if listing_id == target_id or listing.longitude is None or listing.latitude is None:
                continue
            distance = haversine_distance_meters(
                float(target.longitude),
                float(target.latitude),
                float(listing.longitude),
                float(listing.latitude),
            )
            if distance <= radius_meters:
                nearby.append(listing_id)
        return sorted(nearby)

    # 快路径: 用预计算的距离矩阵
    dist_matrix, id_to_idx = _dist_matrix_cache
    if target_id not in id_to_idx:
        return []
    i = id_to_idx[target_id]
    row = dist_matrix[i]
    return [lid for j, lid in enumerate(id_to_idx) if j != i and row[j] <= radius_meters]


def _build_dist_matrix(
    listing_by_id: dict[str, NormalizedRentalListing],
) -> tuple:
    """M2: 计算所有房源之间的 haversine 距离矩阵 (N x N), O(N^2) 一次。

    返回 (dist_matrix: np.ndarray, id_to_idx: dict[str, int]) 供 nearby_listing_ids 行切片。
    """
    import numpy as np

    ids = list(listing_by_id.keys())
    n = len(ids)
    if n == 0:
        return np.zeros((0, 0)), {}
    arr = np.empty((n, 2), dtype=np.float64)
    for i, lid in enumerate(ids):
        listing = listing_by_id[lid]
        arr[i, 0] = np.radians(float(listing.latitude))
        arr[i, 1] = np.radians(float(listing.longitude))
    lat = arr[:, 0:1]
    lon = arr[:, 1:2]
    dlat = lat.T - lat
    dlon = lon.T - lon
    a = np.sin(dlat / 2) ** 2 + np.cos(lat) * np.cos(lat.T) * np.sin(dlon / 2) ** 2
    dist_matrix = 2 * 6371008.8 * np.arcsin(np.sqrt(a))
    return dist_matrix, {lid: i for i, lid in enumerate(ids)}


def summarize_location_value_rows(
    rows: list[LocationValueRow],
    *,
    nearby_radius_meters: int = DEFAULT_NEARBY_RADIUS_METERS,
) -> dict[str, object]:
    """汇总位置价值分析结果。"""

    bucket_counts = Counter(row.distance_bucket for row in rows)
    return {
        "total_listings": len(rows),
        "distance_buckets": dict(sorted(bucket_counts.items())),
        "nearby_radius_meters": nearby_radius_meters,
        "labels": {
            "below_nearby_median": sum(row.below_nearby_median for row in rows),
            "nearby_good_value": sum(row.nearby_good_value for row in rows),
            "nearby_expensive": sum(row.nearby_expensive for row in rows),
            "below_community_median": sum(row.below_community_median for row in rows),
            "above_community_median": sum(row.above_community_median for row in rows),
            "best_price_in_community": sum(row.best_price_in_community for row in rows),
            "best_area_price_in_community": sum(row.best_area_price_in_community for row in rows),
        },
        "coverage": {
            "nearby_enabled": sum(row.nearby_sample_size >= MIN_NEARBY_SAMPLE_SIZE for row in rows),
            "community_enabled": sum(
                row.community_sample_size >= MIN_COMMUNITY_SAMPLE_SIZE for row in rows
            ),
        },
    }


def row_with_notes(row: LocationValueRow) -> LocationValueRow:
    """补充中文分析说明。"""

    notes: list[str] = []
    if row.nearby_sample_size < MIN_NEARBY_SAMPLE_SIZE:
        notes.append("附近样本不足, 暂不启用附近比较")
    else:
        if row.below_nearby_median:
            notes.append("租金低于附近中位数")
        if row.nearby_good_value:
            notes.append("单位面积租金低于附近中位数")
        if row.nearby_expensive:
            notes.append("单位面积租金高于附近 p75")
    if row.community_sample_size >= MIN_COMMUNITY_SAMPLE_SIZE:
        if row.below_community_median:
            notes.append("租金低于同小区中位数")
        if row.best_price_in_community:
            notes.append("同小区最低租金")
        if row.best_area_price_in_community:
            notes.append("同小区最低单位面积租金")
    if row.apartment_like:
        notes.append("疑似公寓类房源")
    if row.possible_duplicate:
        notes.append("存在重复候选")
    return row.__class__(**{**asdict(row), "analysis_notes": "; ".join(notes)})


def _community_groups(
    listing_by_id: dict[str, NormalizedRentalListing],
    price_area_rows: dict[str, PriceAreaInputRow],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for listing_id, listing in listing_by_id.items():
        if listing.community_name and listing_id in price_area_rows:
            groups[listing.community_name].append(listing_id)
    return groups


def _stats_for_ids(
    listing_ids: list[str],
    price_area_rows: dict[str, PriceAreaInputRow],
    value_name: str,
) -> DistributionStats | None:
    if len(listing_ids) < MIN_NEARBY_SAMPLE_SIZE:
        return None
    values = [_value(price_area_rows[listing_id], value_name) for listing_id in listing_ids]
    return distribution_stats(values)


def _community_stats_for_ids(
    listing_ids: list[str],
    price_area_rows: dict[str, PriceAreaInputRow],
    value_name: str,
) -> DistributionStats | None:
    if len(listing_ids) < MIN_COMMUNITY_SAMPLE_SIZE:
        return None
    values = [_value(price_area_rows[listing_id], value_name) for listing_id in listing_ids]
    return distribution_stats(values)


def _delta(value: float, stats: DistributionStats | None) -> float | None:
    if stats is None:
        return None
    return round(value - stats.median, 2)


def _below_median(value: float, stats: DistributionStats | None) -> bool:
    return bool(stats and value < stats.median)


def _above_median(value: float, stats: DistributionStats | None) -> bool:
    return bool(stats and value > stats.median)


def _above_p75(value: float, stats: DistributionStats | None) -> bool:
    return bool(stats and value >= stats.p75)


def _best_in_group(
    listing_id: str,
    group_ids: list[str],
    price_area_rows: dict[str, PriceAreaInputRow],
    value_name: str,
) -> bool:
    if len(group_ids) < MIN_COMMUNITY_SAMPLE_SIZE:
        return False
    own_value = _value(price_area_rows[listing_id], value_name)
    best_value = min(
        _value(price_area_rows[candidate_id], value_name) for candidate_id in group_ids
    )
    return own_value == best_value


def _value(row: PriceAreaInputRow, value_name: str) -> float:
    if value_name == "price":
        return float(row.rent_price)
    if value_name == "rent_per_sqm":
        return row.rent_per_sqm
    msg = f"unknown value name: {value_name}"
    raise ValueError(msg)


def _bool_text(value: str | None) -> bool:
    return value == "True"


def _write_location_value_csv(rows: list[LocationValueRow], path: Path) -> None:
    fieldnames = list(LocationValueRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
