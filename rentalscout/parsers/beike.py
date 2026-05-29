"""贝壳租房列表页解析。"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from rentalscout.parsers.common import clean_text, parse_area_sqm, parse_int, parse_price_bounds
from rentalscout.schemas.normalized import (
    LandlordType,
    ListingType,
    NormalizedRentalListing,
    SourceType,
)
from rentalscout.schemas.raw import SourceName

ITEM_RE = re.compile(
    (
        r'<div\s+class="content__list--item"(?P<body>.*?)'
        r'(?=<div\s+class="content__list--item"|<div class="content__pg")'
    ),
    re.DOTALL,
)
HOUSE_CODE_RE = re.compile(r'data-house_code="([^"]+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
TITLE_RE = re.compile(r'<a class="twoline"[^>]*>(?P<title>.*?)</a>', re.DOTALL)
DESC_RE = re.compile(
    r'<p class="content__list--item--des">(?P<description>.*?)</p>',
    re.DOTALL,
)
PRICE_RE = re.compile(r'content__list--item-price"><em>(?P<price>.*?)</em>', re.DOTALL)
TITLE_DETAIL_RE = re.compile(r'<p class="content__title">\s*(?P<title>.*?)\s*</p>', re.DOTALL)
META_DESC_RE = re.compile(r'<meta name="description" content="(?P<description>[^"]*)"', re.DOTALL)
DETAIL_PRICE_RE = re.compile(
    r'<div class="content__aside--title">\s*<span>(?P<price>[\d,]+)</span>元/月',
    re.DOTALL,
)
DETAIL_FIELD_RE = re.compile(
    r"<li[^>]*>\s*(?P<label>[^\uff1a<]+)\uff1a(?P<value>.*?)</li>",
    re.DOTALL,
)
ASIDE_FIELD_RE = re.compile(
    r'<li[^>]*>\s*<span class="label">(?P<label>[^\uff1a<]+)\uff1a</span>'
    r"(?P<value>.*?)</li>",
    re.DOTALL,
)
HOUSE_CODE_DETAIL_RE = re.compile(r"g_conf\.houseCode\s*=\s*'(?P<code>[^']+)'")
COORD_RE = re.compile(
    r"g_conf\.coord\s*=\s*\{\s*longitude:\s*'(?P<longitude>[^']+)'\s*,\s*"
    r"latitude:\s*'(?P<latitude>[^']+)'",
    re.DOTALL,
)
G_CONF_NAME_RE = re.compile(r"g_conf\.name\s*=\s*'(?P<name>[^']*)'")
G_CONF_SUBDISTRICT_RE = re.compile(r"g_conf\.houseConditionName\s*=\s*'(?P<name>[^']*)'")
G_CONF_SUBWAY_RE = re.compile(r"g_conf\.subway\s*=\s*(?P<subway>\[.*?\]);", re.DOTALL)
DETAIL_URL_ID_RE = re.compile(r"/(?:zufang|apartment)/(?P<id>[^/.]+)")
DETAIL_LOCATION_RE = re.compile(r"此房源位于上海(?P<location>[^,\uff0c]+)")
SHANGHAI_DISTRICTS = (
    "浦东",
    "徐汇",
    "普陀",
    "静安",
    "长宁",
    "黄浦",
    "闵行",
    "虹口",
    "杨浦",
    "宝山",
    "嘉定",
    "松江",
    "青浦",
)


def parse_beike_listings(body: str, base_url: str) -> list[NormalizedRentalListing]:
    """解析贝壳列表页中的房源卡片。"""

    listings: list[NormalizedRentalListing] = []
    for item in ITEM_RE.finditer(body):
        item_html = item.group("body")
        listing = _parse_item(item_html, base_url)
        if listing is not None:
            listings.append(listing)
    return listings


def parse_beike_detail(
    body: str,
    source_url: str,
    *,
    fallback: NormalizedRentalListing | None = None,
) -> NormalizedRentalListing | None:
    """解析贝壳详情页 HTML, 返回字段更完整的标准化房源。"""

    title = _detail_title(body) or (fallback.title if fallback else None)
    if not title:
        return None

    description = _meta_description(body)
    detail_fields = _detail_fields(body)
    aside_fields = _aside_fields(body)
    house_type = aside_fields.get("房屋类型")
    rent_type = aside_fields.get("租赁方式")
    orientation_floor = aside_fields.get("朝向楼层")
    layout = _layout(title, house_type or (fallback.description if fallback else None))
    area_sqm = parse_area_sqm(detail_fields.get("面积", "") or house_type or "")
    orientation, floor = _orientation_floor(
        orientation_floor=orientation_floor,
        orientation=detail_fields.get("朝向"),
        floor=detail_fields.get("楼层"),
    )
    district, subdistrict, community = _detail_location(body, description)
    longitude, latitude = _detail_coordinates(body)
    source_listing_id = _detail_listing_id(body, source_url) or (
        fallback.source_listing_id if fallback else None
    )
    tags = _detail_tags(body)

    rent_price = parse_int(_detail_price_text(body))
    if rent_price is None and fallback is not None:
        rent_price = fallback.rent_price

    listing_type = ListingType.UNKNOWN
    type_text = " ".join(part for part in [rent_type, title] if part)
    if "整租" in type_text:
        listing_type = ListingType.WHOLE_RENT
    elif "合租" in type_text:
        listing_type = ListingType.SHARED_RENT

    price_conf = 0.95 if rent_price is not None else 0.0
    area_conf = 0.9 if area_sqm is not None else 0.0
    layout_conf = 0.9 if layout else 0.0
    location_conf = 0.9 if longitude is not None and latitude is not None else 0.0
    confidence_values = [price_conf, area_conf, layout_conf, location_conf]
    non_zero = [value for value in confidence_values if value > 0]
    overall_conf = round(sum(non_zero) / len(non_zero), 2) if non_zero else 0.0

    return NormalizedRentalListing(
        source=SourceName.BEIKE,
        source_type=SourceType.PLATFORM,
        source_listing_id=source_listing_id,
        source_url=source_url,
        title=title,
        description=description,
        rent_price=rent_price,
        area_sqm=area_sqm,
        layout=layout,
        district=district or (fallback.district if fallback else None),
        subdistrict=subdistrict or (fallback.subdistrict if fallback else None),
        community_name=community or (fallback.community_name if fallback else None),
        address_text=title,
        city="上海",
        longitude=longitude,
        latitude=latitude,
        floor=floor,
        orientation=orientation,
        available_from=detail_fields.get("入住"),
        listing_type=listing_type,
        landlord_type=LandlordType.AGENCY,
        subway_info=_subway_info(body),
        features=tags,
        image_urls=[],
        parse_confidence=overall_conf,
        price_confidence=price_conf,
        location_confidence=location_conf,
        area_confidence=area_conf,
        layout_confidence=layout_conf,
        overall_confidence=overall_conf,
    )


def _parse_item(item_html: str, base_url: str) -> NormalizedRentalListing | None:
    href_match = HREF_RE.search(item_html)
    title_match = TITLE_RE.search(item_html)
    price_match = PRICE_RE.search(item_html)
    if not href_match or not title_match:
        return None

    url = urljoin(base_url, href_match.group(1))
    title = clean_text(title_match.group("title"))
    description = _description(item_html)
    price_text = clean_text(price_match.group("price")) if price_match else None
    rent_min, rent_max = parse_price_bounds(price_text)
    source_listing_id = _source_listing_id(item_html, url)
    layout = _layout(title, description)

    return NormalizedRentalListing(
        source=SourceName.BEIKE,
        source_listing_id=source_listing_id,
        source_url=url,
        title=title,
        description=description,
        rent_price=rent_min,
        area_sqm=parse_area_sqm(description),
        layout=layout,
        district=_district(description),
        subdistrict=_subdistrict(description),
        community_name=_community_name(description),
        listing_type=ListingType.WHOLE_RENT if title.startswith("整租") else ListingType.UNKNOWN,
        landlord_type=LandlordType.AGENCY,
        image_urls=[],
        parse_confidence=0.75 if rent_max is not None else 0.55,
    )


def _detail_title(body: str) -> str | None:
    match = TITLE_DETAIL_RE.search(body)
    if match:
        return clean_text(match.group("title"))
    title_match = re.search(r"<title>(?P<title>.*?)</title>", body, re.DOTALL)
    if not title_match:
        return None
    return clean_text(title_match.group("title").split("-")[0])


def _meta_description(body: str) -> str | None:
    match = META_DESC_RE.search(body)
    return clean_text(match.group("description")) if match else None


def _detail_price_text(body: str) -> str | None:
    match = DETAIL_PRICE_RE.search(body)
    return match.group("price") if match else None


def _detail_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in DETAIL_FIELD_RE.finditer(body):
        label = clean_text(match.group("label"))
        value = clean_text(match.group("value"))
        if label and value and label not in {"基本信息"}:
            fields[label] = value
    return fields


def _aside_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in ASIDE_FIELD_RE.finditer(body):
        label = clean_text(match.group("label"))
        value = clean_text(match.group("value"))
        if label and value:
            fields[label] = value
    return fields


def _orientation_floor(
    *,
    orientation_floor: str | None,
    orientation: str | None,
    floor: str | None,
) -> tuple[str | None, str | None]:
    if orientation and floor:
        return orientation, floor
    if not orientation_floor:
        return orientation, floor
    parts = orientation_floor.split(maxsplit=1)
    if len(parts) == 2:
        return orientation or parts[0], floor or parts[1]
    return orientation or orientation_floor, floor


def _detail_location(
    body: str,
    description: str | None,
) -> tuple[str | None, str | None, str | None]:
    community_match = G_CONF_NAME_RE.search(body)
    subdistrict_match = G_CONF_SUBDISTRICT_RE.search(body)
    community = clean_text(community_match.group("name")) if community_match else None
    subdistrict = clean_text(subdistrict_match.group("name")) if subdistrict_match else None
    district = None
    if description:
        location_match = DETAIL_LOCATION_RE.search(description)
        if location_match:
            location_text = location_match.group("location")
            parsed_district, parsed_subdistrict, parsed_community = _split_detail_location(
                location_text
            )
            district = parsed_district
            subdistrict = subdistrict or parsed_subdistrict
            community = community or parsed_community
    return district, subdistrict, community


def _split_detail_location(location_text: str) -> tuple[str | None, str | None, str | None]:
    for district in SHANGHAI_DISTRICTS:
        if not location_text.startswith(district):
            continue
        tail = location_text.removeprefix(district)
        if "的" not in tail:
            return district, tail or None, None
        subdistrict, community = tail.split("的", maxsplit=1)
        return district, subdistrict or None, community or None
    return None, None, None


def _detail_coordinates(body: str) -> tuple[float | None, float | None]:
    match = COORD_RE.search(body)
    if not match:
        return None, None
    return float(match.group("longitude")), float(match.group("latitude"))


def _detail_listing_id(body: str, source_url: str) -> str | None:
    match = HOUSE_CODE_DETAIL_RE.search(body)
    if match:
        return match.group("code")
    url_match = DETAIL_URL_ID_RE.search(source_url)
    return url_match.group("id") if url_match else None


def _detail_tags(body: str) -> list[str]:
    tag_block = re.search(r'<p class="content__aside--tags">(?P<body>.*?)</p>', body, re.DOTALL)
    if not tag_block:
        return []
    return [
        clean_text(match)
        for match in re.findall(r"<i[^>]*>(.*?)</i>", tag_block.group("body"), re.DOTALL)
        if clean_text(match)
    ]


def _subway_info(body: str) -> str | None:
    match = G_CONF_SUBWAY_RE.search(body)
    if not match:
        return "近地铁" if "近地铁" in body else None
    try:
        stations = json.loads(match.group("subway"))
    except json.JSONDecodeError:
        return "近地铁"
    parts = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        name = station.get("name")
        distance = station.get("distance")
        lines = station.get("lines") or []
        line_text = "/".join(str(line) for line in lines)
        if name and distance is not None:
            station_text = (
                f"{name}({line_text}, {distance}m)" if line_text else f"{name}({distance}m)"
            )
            parts.append(station_text)
    return "; ".join(parts) or None


def _description(item_html: str) -> str | None:
    match = DESC_RE.search(item_html)
    if not match:
        return None
    return clean_text(match.group("description"))


def _source_listing_id(item_html: str, url: str) -> str | None:
    code_match = HOUSE_CODE_RE.search(item_html)
    if code_match:
        return code_match.group(1)
    url_match = re.search(r"/(?:zufang|apartment)/([^/.]+)", url)
    if url_match:
        return url_match.group(1)
    return None


def _layout(title: str, description: str | None) -> str | None:
    text = f"{title} {description or ''}"
    match = re.search(r"\d室\d厅(?:\d卫)?", text)
    if match:
        return match.group(0)
    if "一居" in text:
        return "一居"
    return None


def _district(description: str | None) -> str | None:
    if not description:
        return None
    first = description.split("-", maxsplit=1)[0].strip()
    return first or None


def _subdistrict(description: str | None) -> str | None:
    if not description or "-" not in description:
        return None
    parts = [part.strip() for part in description.split("-")]
    return parts[1] if len(parts) > 1 and parts[1] else None


def _community_name(description: str | None) -> str | None:
    if not description:
        return None
    parts = [part.strip() for part in description.split("-")]
    if len(parts) < 3:
        return None
    community = parts[2].split("/", maxsplit=1)[0].strip()
    return community or None
