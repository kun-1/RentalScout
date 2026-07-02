"""Wellcee 公开列表 API 配置与共享工具。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from curl_cffi import requests as curl_requests

from rentalscout.parsers.common import parse_int, split_district_community
from rentalscout.parsers.wellcee import canonical_wellcee_url
from rentalscout.schemas.normalized import (
    LandlordType,
    ListingType,
    NormalizedRentalListing,
)
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import RAW_DATA_DIR

WELLCEE_HOUSE_API_URL = "https://www.wellcee.com/api/v3/frontend/house/get"
SHANGHAI_CITY_ID = "15102233103895305"
PUDONG_DISTRICT_ID = "15133101536753307"
WHOLE_RENT_ID = "15103931190241306"
LONG_RENT_ID = "15103937805971616"
DISTRICT_MAP = {
    "Pudong": "浦东",
    "Xuhui": "徐汇",
    "Putuo": "普陀",
    "Jing'An": "静安",
    "Changning": "长宁",
    "Huangpu": "黄浦",
    "Minhang": "闵行",
    "Hongkou": "虹口",
    "Yangpu": "杨浦",
    "Baoshan": "宝山",
    "Jiading": "嘉定",
    "Songjiang": "松江",
    "Qingpu": "青浦",
}


def _phase1_payload(page_num: int) -> dict[str, object]:
    return {
        "cityId": SHANGHAI_CITY_ID,
        "lang": 1,
        "pageNum": page_num,
        "districtIds": [PUDONG_DISTRICT_ID],
        "subways": [],
        "businessIds": [],
        "rentTypeIds": [WHOLE_RENT_ID],
        "timeTypeIds": [LONG_RENT_ID],
        "tagTypeIds": [],
        "bedroom": [1],
        "price": [{"minPrice": 3500, "maxPrice": 6000}],
    }


def save_api_response(
    data: dict[str, object],
    page_num: int,
    output_dir: Path = RAW_DATA_DIR,
) -> Path:
    """保存原始 API 响应到 JSON 文件。"""
    source_dir = output_dir / SourceName.WELLCEE.value / "api"
    source_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC)
    raw_path = source_dir / f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}-page{page_num}.json"
    raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_path


def api_item_to_partial(item: dict[str, object]) -> dict[str, object] | None:
    """从 API item 构建 partial data dict (通过 meta 传给详情页回调)."""
    listing_id = str(item.get("id") or "")
    if not listing_id.isdigit():
        return None
    title = str(item.get("address") or "").strip()
    if not title:
        return None

    images = [img for img in item.get("imgs", []) if isinstance(img, str)]
    tags = [str(t) for t in item.get("tags", []) if t]
    rent_price = parse_int(str(item.get("rent") or ""))
    raw_district = str(item.get("district") or "").strip()
    raw_district = raw_district.replace("\u2018", "'")
    district = DISTRICT_MAP.get(raw_district, raw_district) or None
    title = _normalize_address_title(title, raw_district, district)

    # typeTags contain hints: "NEW", "Renew" etc
    type_tags = [str(t) for t in item.get("typeTags", []) if t]
    is_renew = "Renew" in type_tags

    return {
        "listing_id": listing_id,
        "title": title,
        "rent_price": rent_price,
        "district": district,
        "api_imgs": images,
        "api_tags": tags,
        "api_type_tags": type_tags,
        "is_renew": is_renew,
        "latitude": (
            float(item["latitude"]) if isinstance(item.get("latitude"), int | float) else None
        ),
        "longitude": (
            float(item["longitude"]) if isinstance(item.get("longitude"), int | float) else None
        ),
        "host_last_login_at": _parse_login_time(item.get("loginTime")),
    }


def _normalize_address_title(title: str, raw_district: str, district: str | None) -> str:
    if district and raw_district and title.startswith(raw_district):
        return title.replace(raw_district, district, 1)
    return title


def _parse_login_time(value: object) -> datetime | None:
    """把 Wellcee API 返回的 loginTime (秒级 Unix timestamp) 转成 tz-aware datetime."""

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(int(value), tz=UTC)
    return None


# ── Legacy functions for batch.py compatibility ──────────────────────

_SESSION = curl_requests.Session()


@dataclass(frozen=True)
class WellceeApiPage:
    """Legacy: kept for batch.py compatibility."""

    page_num: int
    total: int
    page_size: int
    listings: tuple[NormalizedRentalListing, ...]
    raw_path: Path


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    retries: int = 3,
) -> dict[str, object]:
    """Legacy: kept for batch.py compatibility.

    curl_cffi + Chrome 指纹伪装, 与 spiders 统一。HTTP 错误和网络错误都会
    指数退避重试。
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = _SESSION.request(
                method="POST",
                url=url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0 Safari/537.36"
                    ),
                },
                impersonate="chrome",
                timeout=25,
            )
            response.raise_for_status()
            return json.loads(response.content.decode("utf-8"))
        except (curl_requests.RequestsError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"Wellcee API failed after {retries} retries") from last_error


def _listing_from_item(item: dict[str, object]) -> NormalizedRentalListing | None:
    """Legacy: kept for batch.py compatibility."""
    listing_id = str(item.get("id") or "")
    if not listing_id.isdigit():
        return None
    title = str(item.get("address") or "").strip()
    if not title:
        return None
    images = [image for image in item.get("imgs", []) if isinstance(image, str)]
    rent_price = parse_int(str(item.get("rent") or ""))
    raw_district = str(item.get("district") or "").strip()
    normalized_raw_district = raw_district.replace("\u2018", "'")
    district = DISTRICT_MAP.get(normalized_raw_district, raw_district) or None
    title = _normalize_address_title(title, raw_district, district)
    latitude = item.get("latitude")
    longitude = item.get("longitude")

    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=listing_id,
        source_url=canonical_wellcee_url(listing_id),
        title=title,
        description="; ".join(str(tag) for tag in item.get("tags", []) if tag),
        rent_price=rent_price,
        district=district,
        community_name=split_district_community(title)[1],
        address_text=title,
        longitude=float(longitude) if isinstance(longitude, int | float) else None,
        latitude=float(latitude) if isinstance(latitude, int | float) else None,
        host_last_login_at=_parse_login_time(item.get("loginTime")),
        listing_type=ListingType.WHOLE_RENT,
        landlord_type=LandlordType.INDIVIDUAL,
        image_urls=images,
        parse_confidence=0.85,
    )
