"""Wellcee 列表页与详情页解析。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import parsel

from rentalscout.inspect import summarize_html
from rentalscout.parsers.common import parse_int
from rentalscout.schemas.normalized import (
    LandlordType,
    ListingType,
    NormalizedRentalListing,
)
from rentalscout.schemas.raw import SourceName

SUBDISTRICT_TABLE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "subdistricts" / "shanghai_pudong.json"
)

JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">(?P<payload>.*?)</script>',
    re.DOTALL,
)


def parse_wellcee_listings(body: str) -> list[NormalizedRentalListing]:
    """从 Wellcee 列表页 JSON-LD 中解析房源。"""

    listings: list[NormalizedRentalListing] = []
    for payload_match in JSON_LD_RE.finditer(body):
        payload = unescape(payload_match.group("payload"))
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "ItemList":
            continue
        for element in data.get("itemListElement", []):
            listing = _parse_list_item(element)
            if listing is not None:
                listings.append(listing)
    return listings


def parse_wellcee_detail_title(body: str, url: str) -> str | None:
    """解析 Wellcee 详情页标题, 用于识别整租、转租或合租。"""

    return summarize_html(body, url).title


def parse_detail_jsonld(html: str) -> dict[str, object] | None:
    """从 Wellcee 详情页 JSON-LD 中提取结构化数据.

    返回 dict 或者 None, 字段:
      - community_name, description, published_at, rent_price, currency
      - city, district, street_address
      - room_count, bathroom_count
      - area_sqm (int), latitude, longitude
      - features (list[str]), image_urls (list[str])
    """

    for payload_match in JSON_LD_RE.finditer(html):
        payload = unescape(payload_match.group("payload"))
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "RealEstateListing":
            continue

        result: dict[str, object] = {}

        result["community_name"] = data.get("name")
        result["description"] = data.get("description")

        if date_posted := data.get("datePosted"):
            result["published_at"] = _parse_iso_datetime(str(date_posted))

        offers = data.get("offers")
        if isinstance(offers, dict):
            price = offers.get("price")
            if price is not None:
                result["rent_price"] = parse_int(str(price))
            if currency := offers.get("priceCurrency"):
                result["currency"] = str(currency).upper()

        address = data.get("address")
        if isinstance(address, dict):
            if locality := address.get("addressLocality"):
                result["city"] = str(locality)
            if region := address.get("addressRegion"):
                result["district"] = str(region)
            if street := address.get("streetAddress"):
                result["street_address"] = str(street)

        if (rooms := data.get("numberOfRooms")) is not None:
            result["room_count"] = int(rooms)
        if (bathrooms := data.get("numberOfBathroomsTotal")) is not None:
            result["bathroom_count"] = int(bathrooms)

        floor_size = data.get("floorSize")
        if isinstance(floor_size, dict):
            area_value = floor_size.get("value")
            if area_value is not None:
                result["area_sqm"] = float(area_value)

        geo = data.get("geo")
        if isinstance(geo, dict):
            if (lat := geo.get("latitude")) is not None:
                result["latitude"] = float(lat)
            if (lng := geo.get("longitude")) is not None:
                result["longitude"] = float(lng)

        amenities = data.get("amenityFeature")
        if isinstance(amenities, list):
            result["features"] = [
                a.get("name") for a in amenities if isinstance(a, dict) and a.get("name")
            ]

        images = data.get("image")
        if isinstance(images, list):
            result["image_urls"] = [str(img) for img in images if isinstance(img, str)]
        elif isinstance(images, str):
            result["image_urls"] = [images]

        return result

    return None


def parse_detail_html(html: str) -> dict[str, str]:
    """从详情页 HTML 详情模块提取字段.

    提取: 押金, 类型, 房间, 楼层, 面积, 地铁
    JSON-LD 已有面积和房间, 此函数主要提取 JSON-LD 没有的字段:
    押金 (deposit), 地铁 (subway), 楼层 (floor), 类型详情 (listing_type_detail)

    schema.org JSON-LD 的 RealEstateListing 不包含: deposit, subway, floor
    这些只能从 HTML 详情模块提取.
    """

    selector = parsel.Selector(html)
    result: dict[str, str] = {}

    labels = ["押金", "类型", "房间", "楼层", "面积", "地铁"]
    for label in labels:
        value = _extract_label_value(selector, label)
        if value:
            result[_label_to_key(label)] = value

    return result


def _extract_label_value(selector: parsel.Selector, label: str) -> str | None:
    """根据 label 文本在详情模块中找到对应的 value。"""

    # 策略: 在 bg-[#fbfbfb] 卡片中找到 label 的 span
    # 然后取其后的 sibling span 的文本
    xpath = (
        '//div[contains(@class, "rounded-[8px]")]'
        f'[.//span[normalize-space(text())="{label}"]]'
        "//span[last()]"
    )
    result = selector.xpath(f"{xpath}/text()").get()
    if result:
        text = result.strip()
        return text if text else None

    # fallback: 直接找包含 label 文本的 span 的下一个 span
    result = selector.xpath(
        f'//span[normalize-space(text())="{label}"]/following-sibling::span[1]/text()'
    ).get()
    if result:
        text = result.strip()
        return text if text else None

    return None


LABEL_KEY_MAP: dict[str, str] = {
    "押金": "deposit",
    "类型": "listing_type_detail",
    "房间": "layout_detail",
    "楼层": "floor",
    "面积": "area_text",
    "地铁": "subway_info",
}


def _label_to_key(label: str) -> str:
    return LABEL_KEY_MAP.get(label, label)


@lru_cache(maxsize=1)
def _load_subdistrict_table() -> list[dict[str, str]]:
    """Load the Shanghai Pudong subdistrict lookup table (cached)."""
    try:
        data = json.loads(SUBDISTRICT_TABLE_PATH.read_text(encoding="utf-8"))
        return data.get("known_prefixes", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _lookup_subdistrict(name: str, prefixes: list[dict[str, str]]) -> str | None:
    """Try to find a matching subdistrict by prefix in the lookup table.

    Longest prefix wins (prefixes are sorted by length descending).
    """
    for entry in prefixes:
        prefix = entry["prefix"]
        if name.startswith(prefix):
            return entry["name"]
    return None


def extract_subdistrict(community_name: str | None) -> tuple[str | None, float]:
    """从社区名称中提取 subdistrict.

    先用 lookup table 做精确前缀匹配:
      - "潍坊九村社区" -> 查表: prefix "潍坊" -> "潍坊新村街道" (0.90)
      - "上南三村" -> 查表: prefix "上南" -> "周家渡街道" (0.90)

    查表失败后回退到启发式:
      - "晶耀名邸3期" -> "晶耀" (0.50)
      - "金桥路2346弄" -> "金桥" (0.30)

    Returns (subdistrict_name | None, confidence).
    """

    if not community_name or not community_name.strip():
        return None, 0.0

    name = community_name.strip()

    if re.match(r"^[\d]+", name):
        return None, 0.0

    # Skip non-community names like metro stations
    if "\u0028" in name or "\uff08" in name:
        return name, 0.10

    # Phase 1: try lookup table (longest prefix match)
    prefixes = _load_subdistrict_table()
    table_result = _lookup_subdistrict(name, prefixes)
    if table_result:
        return table_result, 0.90

    # Phase 2: heuristic fallback
    cand = name
    cand = re.sub(
        r"[0-9一二三四五六七八九十]+(?:弄|幢|号|栋|楼|期|村|区|座|组)",
        "",
        cand,
    )
    stripped_multichar = False

    for suffix in ["社区", "小区", "新村", "公寓", "大厦", "大楼", "名邸", "花园", "中心", "广场"]:
        if cand.endswith(suffix):
            cand = cand[: -len(suffix)]
            stripped_multichar = True
            break

    while True:
        match = re.search(
            r"(弄|幢|号|栋|楼|期|村|区|座|组|苑|园|庄|阁|轩|庭|城|都|汇|路|街|道|里)$",
            cand,
        )
        if not match:
            break
        remaining = cand[: match.start()]
        if len(remaining.strip(" -")) < 3:
            break
        cand = remaining

    cand = cand.strip(" -")

    if not cand or len(cand) < 2:
        return None, 0.0

    if re.search(r"(?:村|社区|小区)", name):
        conf = 0.70
    elif re.search(r"(?:苑|园|庄|名邸)", name):
        conf = 0.50
    elif stripped_multichar:
        conf = 0.40
    else:
        conf = 0.30

    return cand, conf


def _parse_iso_datetime(value: str) -> datetime | None:
    """解析 ISO 8601 或 YYYY-MM-DD 格式时间。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed
    except (ValueError, TypeError):
        pass
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        return parsed
    except (ValueError, TypeError):
        pass
    return None


def _parse_list_item(element: dict[str, object]) -> NormalizedRentalListing | None:
    item = element.get("item")
    if not isinstance(item, dict):
        return None
    offers = item.get("offers")
    if not isinstance(offers, dict):
        offers = {}

    url = item.get("url")
    title = item.get("name")
    if not isinstance(url, str) or not isinstance(title, str):
        return None

    price = offers.get("price")
    rent_price = int(price) if isinstance(price, str) and price.isdigit() else None
    image = item.get("image")
    date_posted = _date_posted(item.get("datePosted"))
    source_listing_id = extract_wellcee_listing_id(url)
    if source_listing_id is None:
        return None
    canonical_url = canonical_wellcee_url(source_listing_id)

    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=source_listing_id,
        source_url=canonical_url,
        title=title,
        rent_price=rent_price,
        district=_district_from_title(title),
        published_at=date_posted,
        listing_type=ListingType.UNKNOWN,
        landlord_type=LandlordType.INDIVIDUAL,
        image_urls=[image] if isinstance(image, str) else [],
        parse_confidence=0.55,
    )


def _date_posted(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    return parsed


def _district_from_title(title: str) -> str | None:
    parts = title.split(maxsplit=1)
    if parts:
        return parts[0]
    return None


def extract_wellcee_listing_id(url: str) -> str | None:
    """从 Wellcee URL 中提取数字房源 ID。"""

    path = urlparse(url).path.rstrip("/")
    listing_id = path.split("/")[-1]
    if listing_id.isdigit():
        return listing_id
    return None


def canonical_wellcee_url(listing_id: str) -> str:
    """生成 Wellcee 详情页 canonical URL。"""

    return f"https://www.wellcee.com/rent-apartment/{listing_id}"
