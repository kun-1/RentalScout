"""Scrapy spider for Beike 贝壳找房 listing pages.

Uses curl_cffi directly for Chrome-identical TLS fingerprint, bypassing
Scrapy's download handler (which has complex integration issues with curl_cffi).
Requires cookies extracted from a logged-in Chrome session
(``uv run python scripts/extract_cookies.py`` first).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import scrapy
from curl_cffi import requests as curl_requests

from rentalscout.parsers.beike import parse_beike_detail, parse_beike_listings
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.settings import RAW_DATA_DIR

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
COOKIE_PATH = DATA_DIR / "beike_cookies.json"
BEIKE_BASE = "https://sh.zu.ke.com/zufang/pudong"
BEIKE_SUFFIX = "rt200600000001l0brp3500erp6000"
MAX_PAGES = 75


def _build_beike_url(page_num: int) -> str:
    if page_num == 1:
        return f"{BEIKE_BASE}/{BEIKE_SUFFIX}/"
    return f"{BEIKE_BASE}/pg{page_num}{BEIKE_SUFFIX}/"


class BeikeSpider(scrapy.Spider):
    name = "beike"

    def __init__(self, start_page: int = 1, max_pages: int = MAX_PAGES, **kwargs):
        super().__init__(**kwargs)
        self.start_page = start_page
        self.max_pages = max_pages
        self.beike_cookies: dict[str, str] = {}
        if COOKIE_PATH.exists():
            self.beike_cookies = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
            self.logger.info("Loaded %d Beike cookies", len(self.beike_cookies))
        else:
            self.logger.warning(
                "No cookies at %s — run scripts/extract_cookies.py first",
                COOKIE_PATH,
            )

    async def start(self):
        session = curl_requests.Session()
        try:
            for page_num in range(self.start_page, self.max_pages + 1):
                url = _build_beike_url(page_num)
                self.logger.info("Fetching page %d/%d: %s", page_num, self.max_pages, url)

                resp = await asyncio.to_thread(
                    session.request,
                    method="GET",
                    url=url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/148.0.7778.179 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
                    },
                    cookies=self.beike_cookies,
                    impersonate="chrome",
                    timeout=30,
                )

                if resp.status_code != 200:
                    self.logger.warning("Page %d: HTTP %d", page_num, resp.status_code)
                    continue

                html = resp.text
                if "content__list--item" not in html:
                    self.logger.warning(
                        "Page %d: no listing cards (%d bytes)%s",
                        page_num,
                        len(html),
                        " likely captcha" if len(html) < 50000 else "",
                    )
                    if len(html) < 50000:
                        self.logger.warning("Captcha/block detected, stopping")
                        break
                    continue

                listings = parse_beike_listings(html, "https://sh.zu.ke.com")
                self.logger.info(
                    "Page %d: %d listings (%d bytes)",
                    page_num,
                    len(listings),
                    len(html),
                )
                for listing in listings:
                    detail_listing = await self._fetch_detail(session, listing)
                    yield detail_listing or listing

                # Anti-ban delay
                if page_num < self.max_pages:
                    await asyncio.sleep(12 + hash(str(page_num)) % 6)

        finally:
            session.close()

    async def _fetch_detail(
        self,
        session: curl_requests.Session,
        listing: NormalizedRentalListing,
    ) -> NormalizedRentalListing | None:
        url = str(listing.source_url)
        resp = await asyncio.to_thread(
            session.request,
            method="GET",
            url=url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.7778.179 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            },
            cookies=self.beike_cookies,
            impersonate="chrome",
            timeout=30,
        )
        if resp.status_code != 200:
            self.logger.warning("Detail %s: HTTP %d", listing.source_listing_id, resp.status_code)
            return None
        raw_path = _save_raw_detail(resp.text, listing.source_listing_id or "unknown")
        self.logger.info("Detail %s: saved %s", listing.source_listing_id, raw_path.name)
        detail = parse_beike_detail(resp.text, url, fallback=listing)
        if detail is None:
            self.logger.warning("Detail %s: parse failed", listing.source_listing_id)
            return None
        await asyncio.sleep(3 + hash(url) % 3)
        return detail


def _save_raw_detail(body: str, source_listing_id: str) -> Path:
    digest = sha256(body.encode("utf-8")).hexdigest()
    source_dir = RAW_DATA_DIR / "beike" / "detail"
    source_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC)
    raw_path = (
        source_dir
        / f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}-{source_listing_id}-{digest[:12]}.html"
    )
    raw_path.write_text(body, encoding="utf-8")
    return raw_path
