"""贝壳租房列表页解析。"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from rentalscout.parsers.common import clean_text, parse_area_sqm, parse_price_bounds
from rentalscout.schemas.normalized import (
    LandlordType,
    ListingType,
    NormalizedRentalListing,
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
IMAGE_RE = re.compile(r'(?:data-src|src)="(?P<image>https?://[^"]+)"')


def parse_beike_listings(body: str, base_url: str) -> list[NormalizedRentalListing]:
    """解析贝壳列表页中的房源卡片。"""

    listings: list[NormalizedRentalListing] = []
    for item in ITEM_RE.finditer(body):
        item_html = item.group("body")
        listing = _parse_item(item_html, base_url)
        if listing is not None:
            listings.append(listing)
    return listings


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
    image_urls = tuple(dict.fromkeys(IMAGE_RE.findall(item_html)))

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
        image_urls=list(image_urls),
        parse_confidence=0.75 if rent_max is not None else 0.55,
    )


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
