"""基于经纬度的房源空间聚类分析。"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rentalscout.analysis.commute import haversine_distance_meters
from rentalscout.analysis.wellcee_quality import analyze_wellcee_quality
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

DEFAULT_GEO_CLUSTER_CSV = DATA_DIR / "analysis" / "geo_clusters.csv"
DEFAULT_GEO_CLUSTER_SUMMARY_JSON = DATA_DIR / "analysis" / "geo_clusters_summary.json"
DEFAULT_CLUSTER_EPS_METERS = 800
DEFAULT_CLUSTER_MIN_SAMPLES = 5
NOISE_CLUSTER_ID = "noise"


@dataclass(frozen=True)
class GeoClusterPoint:
    """可参与空间聚类的房源点。"""

    listing_id: str
    source_url: str
    title: str
    longitude: float
    latitude: float
    rent_price: int | None
    area_sqm: float | None


@dataclass(frozen=True)
class GeoClusterRow:
    """单套房源的空间聚类结果。"""

    listing_id: str
    source_url: str
    title: str
    longitude: float
    latitude: float
    rent_price: int | None
    area_sqm: float | None
    eps_meters: int
    min_samples: int
    geo_cluster_id: str
    geo_cluster_size: int
    is_geo_noise: bool
    is_core_point: bool
    neighbor_count: int
    cluster_centroid_longitude: float | None
    cluster_centroid_latitude: float | None
    distance_to_cluster_centroid_meters: int | None
    analysis_notes: str


def generate_geo_cluster_outputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_GEO_CLUSTER_CSV,
    summary_path: Path = DEFAULT_GEO_CLUSTER_SUMMARY_JSON,
    eps_meters: int = DEFAULT_CLUSTER_EPS_METERS,
    min_samples: int = DEFAULT_CLUSTER_MIN_SAMPLES,
) -> tuple[list[GeoClusterRow], dict[str, object]]:
    """生成经纬度聚类 CSV/JSON。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    rows = analyze_geo_clusters(
        listings,
        eps_meters=eps_meters,
        min_samples=min_samples,
    )
    summary = summarize_geo_cluster_rows(
        rows,
        eps_meters=eps_meters,
        min_samples=min_samples,
    )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_geo_cluster_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def analyze_geo_clusters(
    listings: list[NormalizedRentalListing],
    *,
    eps_meters: int = DEFAULT_CLUSTER_EPS_METERS,
    min_samples: int = DEFAULT_CLUSTER_MIN_SAMPLES,
) -> list[GeoClusterRow]:
    """对 Wellcee 房源坐标执行 DBSCAN 风格聚类。"""

    if eps_meters <= 0:
        msg = "eps_meters must be positive"
        raise ValueError(msg)
    if min_samples <= 0:
        msg = "min_samples must be positive"
        raise ValueError(msg)

    points = _cluster_points(listings)
    neighborhoods = _neighborhoods(points, eps_meters=eps_meters)
    cluster_ids = _dbscan_cluster_ids(
        points,
        neighborhoods=neighborhoods,
        min_samples=min_samples,
    )
    cluster_sizes = Counter(cluster_ids.values())
    centroids = _cluster_centroids(points, cluster_ids)

    rows: list[GeoClusterRow] = []
    for point in points:
        cluster_id = cluster_ids[point.listing_id]
        is_noise = cluster_id == NOISE_CLUSTER_ID
        centroid = centroids.get(cluster_id)
        distance_to_centroid = (
            None
            if centroid is None
            else haversine_distance_meters(
                point.longitude,
                point.latitude,
                centroid[0],
                centroid[1],
            )
        )
        row = GeoClusterRow(
            listing_id=point.listing_id,
            source_url=point.source_url,
            title=point.title,
            longitude=point.longitude,
            latitude=point.latitude,
            rent_price=point.rent_price,
            area_sqm=point.area_sqm,
            eps_meters=eps_meters,
            min_samples=min_samples,
            geo_cluster_id=cluster_id,
            geo_cluster_size=0 if is_noise else cluster_sizes[cluster_id],
            is_geo_noise=is_noise,
            is_core_point=len(neighborhoods[point.listing_id]) >= min_samples,
            neighbor_count=len(neighborhoods[point.listing_id]) - 1,
            cluster_centroid_longitude=None if centroid is None else centroid[0],
            cluster_centroid_latitude=None if centroid is None else centroid[1],
            distance_to_cluster_centroid_meters=distance_to_centroid,
            analysis_notes="",
        )
        rows.append(_row_with_notes(row))
    return rows


def summarize_geo_cluster_rows(
    rows: list[GeoClusterRow],
    *,
    eps_meters: int = DEFAULT_CLUSTER_EPS_METERS,
    min_samples: int = DEFAULT_CLUSTER_MIN_SAMPLES,
) -> dict[str, object]:
    """汇总空间聚类结果。"""

    cluster_counts = Counter(
        row.geo_cluster_id for row in rows if row.geo_cluster_id != NOISE_CLUSTER_ID
    )
    sizes = sorted(cluster_counts.values(), reverse=True)
    largest_clusters = [
        {"geo_cluster_id": cluster_id, "size": size}
        for cluster_id, size in cluster_counts.most_common(10)
    ]
    return {
        "total_listings": len(rows),
        "parameters": {
            "eps_meters": eps_meters,
            "min_samples": min_samples,
        },
        "cluster_count": len(cluster_counts),
        "clustered_listings": sum(sizes),
        "noise_listings": sum(row.is_geo_noise for row in rows),
        "core_points": sum(row.is_core_point for row in rows),
        "cluster_size": {
            "largest": sizes[0] if sizes else 0,
            "smallest": sizes[-1] if sizes else 0,
            "median": _median(sizes),
        },
        "largest_clusters": largest_clusters,
    }


def _cluster_points(listings: list[NormalizedRentalListing]) -> list[GeoClusterPoint]:
    quality_by_id = {
        row.source_listing_id: row for row in analyze_wellcee_quality(listings)
    }
    points: list[GeoClusterPoint] = []
    for listing in listings:
        listing_id = listing.source_listing_id
        if (
            not listing_id
            or listing.longitude is None
            or listing.latitude is None
            or listing.source != SourceName.WELLCEE
        ):
            continue
        quality = quality_by_id.get(listing_id)
        if not quality or not quality.can_analyze_map:
            continue
        points.append(
            GeoClusterPoint(
                listing_id=listing_id,
                source_url=str(listing.source_url),
                title=listing.title,
                longitude=float(listing.longitude),
                latitude=float(listing.latitude),
                rent_price=listing.rent_price,
                area_sqm=listing.area_sqm,
            )
        )
    return sorted(points, key=lambda point: point.listing_id)


def _neighborhoods(
    points: list[GeoClusterPoint],
    *,
    eps_meters: int,
) -> dict[str, list[str]]:
    """M3: 向量化 haversine。N^2 一次矩阵算, 比 Python 双循环快 30-100x。"""
    import numpy as np
    n = len(points)
    if n == 0:
        return {}
    # radians (lat, lon) 顺序给 haversine 公式
    arr = np.array(
        [(np.radians(p.latitude), np.radians(p.longitude)) for p in points],
        dtype=np.float64,
    )
    lat1 = arr[:, 0:1]
    lon1 = arr[:, 1:2]
    lat2 = arr[:, 0:1].T
    lon2 = arr[:, 1:2].T
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    dist_matrix = 2 * 6371008.8 * np.arcsin(np.sqrt(a))  # 地球半径米

    # 上三角掩码: 排除对角线, 留 (i<j) 部分做邻接
    within = dist_matrix <= eps_meters
    np.fill_diagonal(within, False)  # 自己也算邻居(稍后手动加)

    neighborhoods: dict[str, list[str]] = {}
    for i in range(n):
        lid = points[i].listing_id
        # 同行/列的 (i, j) 满足 within 的全部塞进 i
        neighbors = [points[j].listing_id for j in range(n) if within[i, j] or j == i]
        neighborhoods[lid] = sorted(neighbors)
    return neighborhoods


def _dbscan_cluster_ids(
    points: list[GeoClusterPoint],
    *,
    neighborhoods: dict[str, list[str]],
    min_samples: int,
) -> dict[str, str]:
    point_ids = [point.listing_id for point in points]
    labels: dict[str, str] = {}
    visited: set[str] = set()
    cluster_index = 0

    for point_id in point_ids:
        if point_id in visited:
            continue
        visited.add(point_id)
        neighbors = neighborhoods[point_id]
        if len(neighbors) < min_samples:
            labels[point_id] = NOISE_CLUSTER_ID
            continue

        cluster_index += 1
        cluster_id = f"geo_c{cluster_index:03d}"
        labels[point_id] = cluster_id
        seeds = [neighbor_id for neighbor_id in neighbors if neighbor_id != point_id]
        seed_index = 0
        while seed_index < len(seeds):
            neighbor_id = seeds[seed_index]
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                neighbor_neighbors = neighborhoods[neighbor_id]
                if len(neighbor_neighbors) >= min_samples:
                    for candidate_id in neighbor_neighbors:
                        if candidate_id not in seeds:
                            seeds.append(candidate_id)
            if labels.get(neighbor_id, NOISE_CLUSTER_ID) == NOISE_CLUSTER_ID:
                labels[neighbor_id] = cluster_id
            seed_index += 1

    for point_id in point_ids:
        labels.setdefault(point_id, NOISE_CLUSTER_ID)
    return labels


def _cluster_centroids(
    points: list[GeoClusterPoint],
    cluster_ids: dict[str, str],
) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[GeoClusterPoint]] = defaultdict(list)
    for point in points:
        cluster_id = cluster_ids[point.listing_id]
        if cluster_id != NOISE_CLUSTER_ID:
            grouped[cluster_id].append(point)
    return {
        cluster_id: (
            round(sum(point.longitude for point in cluster_points) / len(cluster_points), 6),
            round(sum(point.latitude for point in cluster_points) / len(cluster_points), 6),
        )
        for cluster_id, cluster_points in grouped.items()
    }


def _row_with_notes(row: GeoClusterRow) -> GeoClusterRow:
    notes: list[str] = []
    if row.is_geo_noise:
        notes.append("未进入任何空间簇, 可视为离群点")
    elif row.is_core_point:
        notes.append("空间簇核心点")
    else:
        notes.append("空间簇边界点")
    if row.geo_cluster_size >= 20:
        notes.append("所在区域房源密集")
    elif row.geo_cluster_size and row.geo_cluster_size < row.min_samples * 2:
        notes.append("所在空间簇样本较少")
    return row.__class__(**{**asdict(row), "analysis_notes": "; ".join(notes)})


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return float(sorted_values[middle])
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def _write_geo_cluster_csv(rows: list[GeoClusterRow], path: Path) -> None:
    fieldnames = list(GeoClusterRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
