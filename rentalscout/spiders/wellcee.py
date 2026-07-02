"""Scrapy spider for Wellcee listings via the public API.

Pipeline: API list → detail page → merge → yield enriched listing

Phase 1:
1. POST to Wellcee house API list endpoint per filter criteria
2. Save raw API response to data/raw/wellcee/api/
3. For each API item, yield detail page request with API meta data
4. Detail page callback:
   a. Parse JSON-LD (RealEstateListing) for structured fields
   b. Parse HTML detail module for supplementary fields
   c. Merge API + JSON-LD + HTML data
   d. Extract community_name, subdistrict
   e. Compute confidence scores
   f. Yield enriched NormalizedRentalListing
"""

from __future__ import annotations

import json
import math

import scrapy
from scrapy.http import Response

from rentalscout.parsers.wellcee import (
    canonical_wellcee_url,
    extract_subdistrict,
    parse_detail_html,
    parse_detail_jsonld,
)
from rentalscout.schemas.normalized import (
    LandlordType,
    ListingType,
    NormalizedRentalListing,
    SourceType,
)
from rentalscout.schemas.raw import SourceName
from rentalscout.wellcee_api import (
    WELLCEE_HOUSE_API_URL,
    _phase1_payload,
    api_item_to_partial,
    save_api_response,
)

API_PAGE_SIZE = 20


class WellceeSpider(scrapy.Spider):
    name = "wellcee"

    def __init__(self, max_pages: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.max_pages = max_pages

    async def start(self):
        self.logger.info("Starting Wellcee spider, max_pages=%s", self.max_pages)
        body = json.dumps(_phase1_payload(1), ensure_ascii=False).encode("utf-8")
        self.logger.info("Yielding POST request to %s (%d bytes)", WELLCEE_HOUSE_API_URL, len(body))
        yield scrapy.Request(
            url=WELLCEE_HOUSE_API_URL,
            method="POST",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            meta={"page": 1, "handle_httpstatus_list": [429, 500]},
            callback=self.parse_first,
        )

    def parse_first(self, response: Response) -> object:
        if response.status != 200:
            self.logger.error("Wellcee API page 1: HTTP %d", response.status)
            return

        data = json.loads(response.text)
        page_data = data.get("data") if isinstance(data, dict) else {}
        if not isinstance(page_data, dict):
            self.logger.error("Wellcee API: malformed response")
            return

        total = int(page_data.get("total") or 0)
        page_size = int(page_data.get("pageSize") or API_PAGE_SIZE)
        auto_max = math.ceil(total / page_size)

        effective_max = self.max_pages or auto_max
        self.logger.info(
            "Wellcee: total=%d, pageSize=%d, auto_pages=%d, effective_max=%s",
            total,
            page_size,
            auto_max,
            effective_max,
        )

        # Save raw response
        save_api_response(data, 1)

        # Yield detail page requests (not listings directly)
        detail_count = 0
        for item in page_data.get("list", []):
            if isinstance(item, dict):
                partial = api_item_to_partial(item)
                if partial is not None:
                    detail_url = canonical_wellcee_url(partial["listing_id"])
                    yield scrapy.Request(
                        url=detail_url,
                        meta={"partial": partial},
                        callback=self.parse_detail,
                    )
                    detail_count += 1

        # Schedule remaining API pages
        for page_num in range(2, min(effective_max, auto_max) + 1):
            body = json.dumps(_phase1_payload(page_num), ensure_ascii=False).encode("utf-8")
            yield scrapy.Request(
                url=WELLCEE_HOUSE_API_URL,
                method="POST",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                meta={"page": page_num},
                callback=self.parse_page,
            )

    def parse_page(self, response: Response) -> object:
        page = response.meta.get("page", 0)
        if response.status != 200:
            self.logger.warning("Wellcee page %d: HTTP %d", page, response.status)
            return

        data = json.loads(response.text)
        page_data = data.get("data") if isinstance(data, dict) else {}
        if not isinstance(page_data, dict):
            return

        page_num = response.meta.get("page", 0)
        save_api_response(data, page_num)

        detail_count = 0
        for item in page_data.get("list", []):
            if isinstance(item, dict):
                partial = api_item_to_partial(item)
                if partial is not None:
                    detail_url = canonical_wellcee_url(partial["listing_id"])
                    yield scrapy.Request(
                        url=detail_url,
                        meta={"partial": partial},
                        callback=self.parse_detail,
                    )
                    detail_count += 1

        self.logger.info(
            "Wellcee page %d: %d detail page requests scheduled",
            page_num,
            detail_count,
        )

    def parse_detail(self, response: Response) -> object:
        """Parse detail page HTML, merge with API partial data, yield enriched listing."""
        partial = response.meta.get("partial", {})
        if not partial:
            self.logger.warning("No partial data in meta for %s", response.url)
            return

        if response.status != 200:
            self.logger.warning("Detail page %s: HTTP %d", response.url, response.status)
            return

        # --- Parse JSON-LD (primary structured data) ---
        jsonld = parse_detail_jsonld(response.text) or {}
        html_data = parse_detail_html(response.text)

        # --- Merge strategy: JSON-LD > HTML > API partial ---
        listing_id = partial["listing_id"]
        title = jsonld.get("community_name") or partial["title"]
        rent_price = jsonld.get("rent_price") or partial["rent_price"]
        district = jsonld.get("district") or partial["district"]
        city = jsonld.get("city")
        community_name = jsonld.get("street_address") or jsonld.get("community_name")
        description = jsonld.get("description")
        area_sqm = jsonld.get("area_sqm")
        published_at = jsonld.get("published_at")
        longitude = jsonld.get("longitude") or partial.get("longitude")
        latitude = jsonld.get("latitude") or partial.get("latitude")
        currency = jsonld.get("currency", "CNY")
        features = jsonld.get("features", [])
        image_urls = jsonld.get("image_urls") or partial.get("api_imgs", [])
        room_count = jsonld.get("room_count")

        # From HTML detail module (fields not in JSON-LD)
        deposit = html_data.get("deposit")
        subway_info = html_data.get("subway_info")
        floor = html_data.get("floor")
        listing_type_detail = html_data.get("listing_type_detail", "")

        # Build layout string from JSON-LD + HTML room info
        layout = html_data.get("layout_detail")
        if not layout and room_count:
            bath_count = jsonld.get("bathroom_count", 1)
            layout = f"{room_count}室0厅{bath_count}卫" if bath_count else f"{room_count}室"

        # Determine listing_type from detail page
        listing_type = ListingType.WHOLE_RENT
        if listing_type_detail:
            lower = listing_type_detail.lower()
            if "合租" in lower:
                listing_type = ListingType.SHARED_RENT
            elif "转租" in lower:
                listing_type = ListingType.SUBLET

        # Extract subdistrict from community_name
        subdistrict, _ = extract_subdistrict(community_name or title)

        # --- Confidence scoring ---
        price_conf = 0.95 if rent_price is not None else 0.0
        area_conf = 0.90 if area_sqm is not None else 0.0
        layout_conf = 0.90 if layout else 0.0
        location_conf = (
            0.85 if (latitude is not None and longitude is not None and district) else 0.0
        )
        conf_scores = [c for c in [price_conf, area_conf, layout_conf, location_conf] if c > 0]
        overall_conf = round(sum(conf_scores) / len(conf_scores), 2) if conf_scores else 0.0

        enriched = NormalizedRentalListing(
            source=SourceName.WELLCEE,
            source_type=SourceType.UGC,
            source_listing_id=listing_id,
            source_url=f"https://www.wellcee.com/rent-apartment/{listing_id}",
            title=title,
            description=description,
            rent_price=rent_price,
            rent_price_unit="month",
            currency=currency,
            area_sqm=area_sqm,
            layout=layout,
            district=district,
            subdistrict=subdistrict,
            community_name=community_name,
            address_text=title,
            city=city,
            longitude=longitude,
            latitude=latitude,
            floor=floor,
            published_at=published_at,
            host_last_login_at=partial.get("host_last_login_at"),
            listing_type=listing_type,
            landlord_type=LandlordType.INDIVIDUAL,
            subway_info=subway_info,
            deposit=deposit,
            features=features,
            image_urls=image_urls,
            parse_confidence=overall_conf,
            price_confidence=price_conf,
            location_confidence=location_conf,
            area_confidence=area_conf,
            layout_confidence=layout_conf,
            overall_confidence=overall_conf,
        )
        yield enriched
