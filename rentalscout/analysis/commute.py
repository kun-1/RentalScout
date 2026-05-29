"""工作地点解析与直线距离分析。"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from rentalscout.analysis.wellcee_quality import analyze_wellcee_quality
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR, RAW_DATA_DIR, load_dotenv
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

DEFAULT_DISTANCE_BUCKET_CSV = DATA_DIR / "analysis" / "commute_distance_buckets.csv"
DEFAULT_DISTANCE_BUCKET_SUMMARY_JSON = (
    DATA_DIR / "analysis" / "commute_distance_buckets_summary.json"
)
DEFAULT_AMAP_GEOCODE_RAW_DIR = RAW_DATA_DIR / "amap" / "geocode"
DEFAULT_WORKPLACE_ID = "default-workplace"
DEFAULT_WORKPLACE_NAME = "默认工作中心"

NO_PROXY_OPENER = build_opener(ProxyHandler({}))
DEFAULT_USER_AGENT = "RentalScout/0.1 (+https://localhost)"


class DistanceBucket(StrEnum):
    """按房源到工作地点的直线距离分桶。"""

    WITHIN_4KM = "within_4km"
    KM_4_TO_8 = "4_to_8km"
    KM_8_TO_12 = "8_to_12km"
    OVER_12KM = "over_12km"


@dataclass(frozen=True)
class Workplace:
    """工作目标点。"""

    workplace_id: str
    name: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class CommuteDistanceRow:
    """单条房源到工作地点的直线距离分桶。"""

    listing_id: str
    source_url: str
    title: str
    workplace_id: str
    workplace_name: str
    workplace_longitude: float
    workplace_latitude: float
    listing_longitude: float
    listing_latitude: float
    straight_distance_meters: int
    distance_bucket: DistanceBucket
    calculated_at: str


def resolve_workplace_from_amap(
    *,
    name: str = DEFAULT_WORKPLACE_NAME,
    workplace_id: str = DEFAULT_WORKPLACE_ID,
    city: str = "上海",
    api_key: str | None = None,
    raw_dir: Path = DEFAULT_AMAP_GEOCODE_RAW_DIR,
) -> Workplace:
    """用高德地理编码解析工作地点坐标。"""

    env_values = load_dotenv()
    key = api_key or os.environ.get("AMAP_API_KEY") or env_values.get("AMAP_API_KEY")
    if not key:
        msg = "missing_amap_api_key"
        raise ValueError(msg)

    url = "https://restapi.amap.com/v3/geocode/geo?" + urlencode(
        {
            "key": key,
            "address": name,
            "city": city,
            "output": "json",
        }
    )
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with NO_PROXY_OPENER.open(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        _save_amap_raw(raw_dir, f"{workplace_id}-geocode", body)
        raise ValueError(f"amap_geocode_http_{error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(str(error)) from error

    raw_path = _save_amap_raw(raw_dir, f"{workplace_id}-geocode", body)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_geocode_json:{raw_path}") from error
    return parse_amap_geocode_payload(
        payload,
        workplace_id=workplace_id,
        fallback_name=name,
    )


def parse_amap_geocode_payload(
    payload: dict[str, object],
    *,
    workplace_id: str,
    fallback_name: str,
) -> Workplace:
    """解析高德地理编码响应。"""

    if str(payload.get("status")) != "1":
        message = str(payload.get("info") or payload.get("infocode") or "amap_geocode_error")
        raise ValueError(message)
    geocodes = payload.get("geocodes")
    if not isinstance(geocodes, list) or not geocodes:
        raise ValueError("invalid_workplace_location")
    first = geocodes[0]
    if not isinstance(first, dict):
        raise ValueError("invalid_workplace_location")
    location = first.get("location")
    if not isinstance(location, str) or "," not in location:
        raise ValueError("invalid_workplace_location")
    lng_text, lat_text = location.split(",", 1)
    try:
        longitude = float(lng_text)
        latitude = float(lat_text)
    except ValueError as error:
        raise ValueError("invalid_workplace_location") from error
    formatted_address = first.get("formatted_address")
    name = str(formatted_address or fallback_name)
    return Workplace(
        workplace_id=workplace_id,
        name=name,
        longitude=longitude,
        latitude=latitude,
    )


def generate_distance_bucket_outputs(
    *,
    workplace: Workplace,
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_DISTANCE_BUCKET_CSV,
    summary_path: Path = DEFAULT_DISTANCE_BUCKET_SUMMARY_JSON,
) -> tuple[list[CommuteDistanceRow], dict[str, object]]:
    """生成房源到工作地点的直线距离分桶结果。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    rows = analyze_distance_buckets(listings=listings, workplace=workplace)
    summary = summarize_distance_rows(rows)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_distance_bucket_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def analyze_distance_buckets(
    *,
    listings: list[NormalizedRentalListing],
    workplace: Workplace,
) -> list[CommuteDistanceRow]:
    """按当前工作地点在内存中重算所有可分析房源的直线距离分桶。"""

    quality_by_id = {
        row.source_listing_id: row for row in analyze_wellcee_quality(listings)
    }
    candidates = [
        listing
        for listing in listings
        if listing.source_listing_id
        and listing.latitude is not None
        and listing.longitude is not None
        and quality_by_id.get(listing.source_listing_id)
        and quality_by_id[listing.source_listing_id].can_analyze_commute
    ]
    rows = [
        distance_row_for_listing(listing, workplace=workplace)
        for listing in sorted(candidates, key=lambda item: item.source_listing_id or "")
    ]
    return rows


def distance_row_for_listing(
    listing: NormalizedRentalListing,
    *,
    workplace: Workplace,
) -> CommuteDistanceRow:
    """生成单套房源的直线距离分桶结果。"""

    if not listing.source_listing_id or listing.latitude is None or listing.longitude is None:
        msg = "listing requires id and coordinates"
        raise ValueError(msg)
    straight_distance = haversine_distance_meters(
        listing.longitude,
        listing.latitude,
        workplace.longitude,
        workplace.latitude,
    )
    return CommuteDistanceRow(
        listing_id=listing.source_listing_id,
        source_url=str(listing.source_url),
        title=listing.title,
        workplace_id=workplace.workplace_id,
        workplace_name=workplace.name,
        workplace_longitude=workplace.longitude,
        workplace_latitude=workplace.latitude,
        listing_longitude=listing.longitude,
        listing_latitude=listing.latitude,
        straight_distance_meters=straight_distance,
        distance_bucket=distance_bucket(straight_distance),
        calculated_at=datetime.now(UTC).isoformat(),
    )


def summarize_distance_rows(rows: list[CommuteDistanceRow]) -> dict[str, object]:
    """汇总直线距离分桶结果。"""

    bucket_counts = Counter(row.distance_bucket.value for row in rows)
    return {
        "total_listings": len(rows),
        "distance_buckets": {
            DistanceBucket.WITHIN_4KM.value: bucket_counts[DistanceBucket.WITHIN_4KM.value],
            DistanceBucket.KM_4_TO_8.value: bucket_counts[DistanceBucket.KM_4_TO_8.value],
            DistanceBucket.KM_8_TO_12.value: bucket_counts[DistanceBucket.KM_8_TO_12.value],
            DistanceBucket.OVER_12KM.value: bucket_counts[DistanceBucket.OVER_12KM.value],
        },
    }


def haversine_distance_meters(
    origin_lng: float,
    origin_lat: float,
    destination_lng: float,
    destination_lat: float,
) -> int:
    """计算两点之间的球面直线距离。"""

    radius_meters = 6_371_000
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(destination_lat)
    delta_lat = math.radians(destination_lat - origin_lat)
    delta_lng = math.radians(destination_lng - origin_lng)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(radius_meters * c)


def distance_bucket(distance_meters: int) -> DistanceBucket:
    """按直线距离分桶。"""

    if distance_meters < 4_000:
        return DistanceBucket.WITHIN_4KM
    if distance_meters < 8_000:
        return DistanceBucket.KM_4_TO_8
    if distance_meters <= 12_000:
        return DistanceBucket.KM_8_TO_12
    return DistanceBucket.OVER_12KM


def _save_amap_raw(raw_dir: Path, stem: str, body: str) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"{timestamp}-{stem}.json"
    path.write_text(body, encoding="utf-8")
    return path


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _write_distance_bucket_csv(rows: list[CommuteDistanceRow], path: Path) -> None:
    fieldnames = list(CommuteDistanceRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            payload["distance_bucket"] = row.distance_bucket.value
            writer.writerow(payload)
