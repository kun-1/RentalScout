"""步行与骑行通勤分析。"""

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

DEFAULT_COMMUTE_CSV = DATA_DIR / "analysis" / "commute_results.csv"
DEFAULT_COMMUTE_SUMMARY_JSON = DATA_DIR / "analysis" / "commute_summary.json"
DEFAULT_DISTANCE_BUCKET_CSV = DATA_DIR / "analysis" / "commute_distance_buckets.csv"
DEFAULT_DISTANCE_BUCKET_SUMMARY_JSON = (
    DATA_DIR / "analysis" / "commute_distance_buckets_summary.json"
)
DEFAULT_AMAP_RAW_DIR = RAW_DATA_DIR / "amap" / "routes"
DEFAULT_AMAP_GEOCODE_RAW_DIR = RAW_DATA_DIR / "amap" / "geocode"
DEFAULT_WORKPLACE_ID = "ben-guan-medical-beauty"
DEFAULT_WORKPLACE_NAME = "上海本冠医疗美容门诊部"

NO_PROXY_OPENER = build_opener(ProxyHandler({}))
DEFAULT_USER_AGENT = "RentalScout/0.1 (+https://localhost)"


class CommuteMode(StrEnum):
    """第一版通勤方式。"""

    WALKING = "walking"
    BICYCLING = "bicycling"


class DistanceBucket(StrEnum):
    """按房源到工作地点的直线距离分桶。"""

    WITHIN_4KM = "within_4km"
    KM_4_TO_8 = "4_to_8km"
    KM_8_TO_12 = "8_to_12km"
    OVER_12KM = "over_12km"


class RouteStatus(StrEnum):
    """路线计算状态。"""

    READY = "ready"
    CAUTION = "caution"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class Workplace:
    """通勤目标点。"""

    workplace_id: str
    name: str
    longitude: float
    latitude: float


@dataclass(frozen=True)
class CommuteResult:
    """单条房源、单种方式的通勤结果。"""

    listing_id: str
    source_url: str
    title: str
    workplace_id: str
    workplace_name: str
    mode: CommuteMode
    straight_distance_meters: int
    distance_bucket: DistanceBucket
    route_distance_meters: int | None
    duration_minutes: int | None
    route_status: RouteStatus
    skip_reason: str | None
    raw_response_path: str | None
    calculated_at: str


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
        raise ValueError("missing_geocode")
    first = geocodes[0]
    if not isinstance(first, dict):
        raise ValueError("invalid_geocode")
    location = first.get("location")
    if not isinstance(location, str) or "," not in location:
        raise ValueError("missing_geocode_location")
    lng_text, lat_text = location.split(",", 1)
    try:
        longitude = float(lng_text)
        latitude = float(lat_text)
    except ValueError as error:
        raise ValueError("invalid_geocode_location") from error
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
    summary = summarize_distance_rows(rows)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_distance_bucket_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


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


def generate_commute_outputs(
    *,
    workplace: Workplace,
    db_path: Path = DEFAULT_DB_PATH,
    api_key: str | None = None,
    csv_path: Path = DEFAULT_COMMUTE_CSV,
    summary_path: Path = DEFAULT_COMMUTE_SUMMARY_JSON,
    raw_dir: Path = DEFAULT_AMAP_RAW_DIR,
    dry_run: bool = False,
) -> tuple[list[CommuteResult], dict[str, object]]:
    """生成步行和骑行通勤结果。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    quality_by_id = {
        row.source_listing_id: row for row in analyze_wellcee_quality(listings)
    }
    candidates = [
        listing
        for listing in listings
        if listing.source_listing_id
        and quality_by_id.get(listing.source_listing_id)
        and quality_by_id[listing.source_listing_id].can_analyze_commute
    ]

    env_values = load_dotenv()
    key = api_key or os.environ.get("AMAP_API_KEY") or env_values.get("AMAP_API_KEY")
    client = AmapRouteClient(api_key=key, raw_dir=raw_dir)
    results = [
        result
        for listing in sorted(candidates, key=lambda item: item.source_listing_id or "")
        for result in analyze_listing_commute(
            listing,
            workplace=workplace,
            client=client,
            dry_run=dry_run,
        )
    ]
    summary = summarize_commute_results(results)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_commute_csv(results, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return results, summary


def analyze_listing_commute(
    listing: NormalizedRentalListing,
    *,
    workplace: Workplace,
    client: AmapRouteClient,
    dry_run: bool = False,
) -> list[CommuteResult]:
    """计算单套房源的步行与骑行通勤结果。"""

    if not listing.source_listing_id or listing.latitude is None or listing.longitude is None:
        return []

    straight_distance = haversine_distance_meters(
        listing.longitude,
        listing.latitude,
        workplace.longitude,
        workplace.latitude,
    )
    bucket = distance_bucket(straight_distance)
    calculated_at = datetime.now(UTC).isoformat()
    modes = modes_for_bucket(bucket)
    results: list[CommuteResult] = []

    for mode in [CommuteMode.WALKING, CommuteMode.BICYCLING]:
        if mode not in modes:
            results.append(
                _base_result(
                    listing,
                    workplace=workplace,
                    mode=mode,
                    straight_distance=straight_distance,
                    bucket=bucket,
                    route_status=RouteStatus.SKIPPED,
                    skip_reason=skip_reason_for_bucket(bucket, mode),
                    calculated_at=calculated_at,
                )
            )
            continue

        if dry_run:
            results.append(
                _base_result(
                    listing,
                    workplace=workplace,
                    mode=mode,
                    straight_distance=straight_distance,
                    bucket=bucket,
                    route_status=RouteStatus.SKIPPED,
                    skip_reason="dry_run",
                    calculated_at=calculated_at,
                )
            )
            continue

        route = client.fetch_route(
            origin_lng=listing.longitude,
            origin_lat=listing.latitude,
            destination_lng=workplace.longitude,
            destination_lat=workplace.latitude,
            mode=mode,
            listing_id=listing.source_listing_id,
            workplace_id=workplace.workplace_id,
        )
        status = route_status(route, straight_distance)
        results.append(
            _base_result(
                listing,
                workplace=workplace,
                mode=mode,
                straight_distance=straight_distance,
                bucket=bucket,
                route_distance_meters=route.distance_meters,
                duration_minutes=route.duration_minutes,
                route_status=status,
                skip_reason=route.error_message,
                raw_response_path=str(route.raw_response_path) if route.raw_response_path else None,
                calculated_at=calculated_at,
            )
        )

    return results


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


def modes_for_bucket(bucket: DistanceBucket) -> set[CommuteMode]:
    """根据距离分桶决定需要精算的通勤方式。"""

    if bucket == DistanceBucket.WITHIN_4KM:
        return {CommuteMode.WALKING, CommuteMode.BICYCLING}
    if bucket in {DistanceBucket.KM_4_TO_8, DistanceBucket.KM_8_TO_12}:
        return {CommuteMode.BICYCLING}
    return set()


def skip_reason_for_bucket(bucket: DistanceBucket, mode: CommuteMode) -> str:
    """返回按策略跳过计算的原因。"""

    if bucket == DistanceBucket.OVER_12KM:
        return "straight_distance_over_12km"
    if mode == CommuteMode.WALKING:
        return "walking_only_calculated_within_4km"
    return "mode_not_enabled_for_bucket"


def route_status(route: AmapRouteResult, straight_distance_meters: int) -> RouteStatus:
    """把高德返回结果分层。"""

    if route.error_message or route.distance_meters is None or route.duration_minutes is None:
        return RouteStatus.FAILED
    max_reasonable_distance = max(straight_distance_meters * 2.5, straight_distance_meters + 3_000)
    if route.distance_meters > max_reasonable_distance:
        return RouteStatus.CAUTION
    return RouteStatus.READY


def summarize_commute_results(results: list[CommuteResult]) -> dict[str, object]:
    """汇总通勤分析结果。"""

    status_counts = Counter(result.route_status.value for result in results)
    bucket_counts = Counter(result.distance_bucket.value for result in results)
    mode_counts = Counter(result.mode.value for result in results)
    return {
        "total_results": len(results),
        "unique_listings": len({result.listing_id for result in results}),
        "statuses": {
            RouteStatus.READY.value: status_counts[RouteStatus.READY.value],
            RouteStatus.CAUTION.value: status_counts[RouteStatus.CAUTION.value],
            RouteStatus.SKIPPED.value: status_counts[RouteStatus.SKIPPED.value],
            RouteStatus.FAILED.value: status_counts[RouteStatus.FAILED.value],
        },
        "distance_buckets": {
            DistanceBucket.WITHIN_4KM.value: bucket_counts[DistanceBucket.WITHIN_4KM.value],
            DistanceBucket.KM_4_TO_8.value: bucket_counts[DistanceBucket.KM_4_TO_8.value],
            DistanceBucket.KM_8_TO_12.value: bucket_counts[DistanceBucket.KM_8_TO_12.value],
            DistanceBucket.OVER_12KM.value: bucket_counts[DistanceBucket.OVER_12KM.value],
        },
        "modes": {
            CommuteMode.WALKING.value: mode_counts[CommuteMode.WALKING.value],
            CommuteMode.BICYCLING.value: mode_counts[CommuteMode.BICYCLING.value],
        },
    }


@dataclass(frozen=True)
class AmapRouteResult:
    """高德路线结果。"""

    distance_meters: int | None
    duration_minutes: int | None
    raw_response_path: Path | None
    error_message: str | None = None


class AmapRouteClient:
    """高德步行与骑行路线 API 客户端。"""

    def __init__(self, *, api_key: str | None, raw_dir: Path = DEFAULT_AMAP_RAW_DIR) -> None:
        self.api_key = api_key
        self.raw_dir = raw_dir

    def fetch_route(
        self,
        *,
        origin_lng: float,
        origin_lat: float,
        destination_lng: float,
        destination_lat: float,
        mode: CommuteMode,
        listing_id: str,
        workplace_id: str,
    ) -> AmapRouteResult:
        """调用高德路线 API 并保存原始响应。"""

        if not self.api_key:
            return AmapRouteResult(
                distance_meters=None,
                duration_minutes=None,
                raw_response_path=None,
                error_message="missing_amap_api_key",
            )

        url = _amap_route_url(
            api_key=self.api_key,
            origin_lng=origin_lng,
            origin_lat=origin_lat,
            destination_lng=destination_lng,
            destination_lat=destination_lat,
            mode=mode,
        )
        request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        try:
            with NO_PROXY_OPENER.open(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raw_path = self._save_raw(body, listing_id, workplace_id, mode)
            return AmapRouteResult(None, None, raw_path, f"http_{error.code}")
        except (URLError, TimeoutError, OSError) as error:
            return AmapRouteResult(None, None, None, str(error))

        raw_path = self._save_raw(body, listing_id, workplace_id, mode)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return AmapRouteResult(None, None, raw_path, "invalid_json")
        return parse_amap_route_payload(payload, mode=mode, raw_path=raw_path)

    def _save_raw(
        self,
        body: str,
        listing_id: str,
        workplace_id: str,
        mode: CommuteMode,
    ) -> Path:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.raw_dir / f"{timestamp}-{listing_id}-{workplace_id}-{mode.value}.json"
        path.write_text(body, encoding="utf-8")
        return path


def _save_amap_raw(raw_dir: Path, stem: str, body: str) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / f"{timestamp}-{stem}.json"
    path.write_text(body, encoding="utf-8")
    return path


def parse_amap_route_payload(
    payload: dict[str, object],
    *,
    mode: CommuteMode,
    raw_path: Path | None = None,
) -> AmapRouteResult:
    """解析高德步行或骑行路线响应。"""

    if str(payload.get("status")) != "1":
        message = str(payload.get("info") or payload.get("infocode") or "amap_error")
        return AmapRouteResult(None, None, raw_path, message)

    route = payload.get("route")
    if not isinstance(route, dict):
        return AmapRouteResult(None, None, raw_path, "missing_route")

    paths = route.get("paths")
    if not isinstance(paths, list) or not paths:
        return AmapRouteResult(None, None, raw_path, "missing_paths")

    first_path = paths[0]
    if not isinstance(first_path, dict):
        return AmapRouteResult(None, None, raw_path, "invalid_path")

    if mode == CommuteMode.WALKING:
        distance = _parse_int(first_path.get("distance"))
        duration = _parse_int(first_path.get("duration"))
    else:
        distance = _parse_int(first_path.get("distance"))
        duration = _parse_int(first_path.get("duration"))

    if distance is None or duration is None:
        return AmapRouteResult(None, None, raw_path, "missing_distance_or_duration")
    return AmapRouteResult(
        distance_meters=distance,
        duration_minutes=math.ceil(duration / 60),
        raw_response_path=raw_path,
    )


def _amap_route_url(
    *,
    api_key: str,
    origin_lng: float,
    origin_lat: float,
    destination_lng: float,
    destination_lat: float,
    mode: CommuteMode,
) -> str:
    origin = f"{origin_lng:.6f},{origin_lat:.6f}"
    destination = f"{destination_lng:.6f},{destination_lat:.6f}"
    if mode == CommuteMode.WALKING:
        endpoint = "https://restapi.amap.com/v3/direction/walking"
    else:
        endpoint = "https://restapi.amap.com/v4/direction/bicycling"
    query = urlencode(
        {
            "key": api_key,
            "origin": origin,
            "destination": destination,
            "output": "json",
        }
    )
    return f"{endpoint}?{query}"


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _base_result(
    listing: NormalizedRentalListing,
    *,
    workplace: Workplace,
    mode: CommuteMode,
    straight_distance: int,
    bucket: DistanceBucket,
    route_status: RouteStatus,
    calculated_at: str,
    route_distance_meters: int | None = None,
    duration_minutes: int | None = None,
    skip_reason: str | None = None,
    raw_response_path: str | None = None,
) -> CommuteResult:
    return CommuteResult(
        listing_id=listing.source_listing_id or "",
        source_url=str(listing.source_url),
        title=listing.title,
        workplace_id=workplace.workplace_id,
        workplace_name=workplace.name,
        mode=mode,
        straight_distance_meters=straight_distance,
        distance_bucket=bucket,
        route_distance_meters=route_distance_meters,
        duration_minutes=duration_minutes,
        route_status=route_status,
        skip_reason=skip_reason,
        raw_response_path=raw_response_path,
        calculated_at=calculated_at,
    )


def _write_commute_csv(results: list[CommuteResult], path: Path) -> None:
    fieldnames = list(CommuteResult.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            payload = asdict(result)
            payload["mode"] = result.mode.value
            payload["distance_bucket"] = result.distance_bucket.value
            payload["route_status"] = result.route_status.value
            writer.writerow(payload)


def _write_distance_bucket_csv(rows: list[CommuteDistanceRow], path: Path) -> None:
    fieldnames = list(CommuteDistanceRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            payload["distance_bucket"] = row.distance_bucket.value
            writer.writerow(payload)
