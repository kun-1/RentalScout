"""Batch scraping with retry, anti-detection delays, and Chrome lifecycle management."""

from __future__ import annotations

import logging
import math
import random
import re
import subprocess
import time
from collections.abc import Generator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from rentalscout.crawl_control import BeikeCrawlControl
from rentalscout.parsers.beike import parse_beike_detail
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.settings import RAW_DATA_DIR
from rentalscout.wellcee_api import (
    WELLCEE_HOUSE_API_URL,
    WellceeApiPage,
    _listing_from_item,
    _phase1_payload,
    _post_json,
    save_api_response,
)

logger = logging.getLogger(__name__)

BROWSER_TOOLS_DIR = Path.home() / ".claude" / "skills" / "browser-tools"
BEIKE_SCRAPE_JS = str(BROWSER_TOOLS_DIR / "beike-scrape.js")
BROWSER_START_JS = str(BROWSER_TOOLS_DIR / "browser-start.js")
BROWSER_NAV_JS = str(BROWSER_TOOLS_DIR / "browser-nav.js")
BEIKE_PHASE1_BASE = "https://sh.zu.ke.com/zufang/pudong"
BEIKE_PHASE1_SUFFIX = "rt200600000001l0brp3500erp6000"


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def _build_beike_url(page_num: int) -> str:
    if page_num == 1:
        return f"{BEIKE_PHASE1_BASE}/{BEIKE_PHASE1_SUFFIX}/"
    return f"{BEIKE_PHASE1_BASE}/pg{page_num}{BEIKE_PHASE1_SUFFIX}/"


def _detect_beike_start_page(output_dir: Path = RAW_DATA_DIR) -> int:
    """Detect the first page to scrape by finding gaps in saved raw files.

    Scans ``data/raw/beike/*.html`` for filenames with ``-page<N>-`` patterns
    and returns the **first missing page number** (1 if none saved).
    """
    beike_dir = output_dir / "beike"
    if not beike_dir.is_dir():
        return 1
    saved: set[int] = set()
    for path in beike_dir.glob("*.html"):
        m = re.search(r"-page(\d+)-", path.name)
        if m:
            saved.add(int(m.group(1)))
    page = 1
    while page in saved:
        page += 1
    return page


def _latest_raw_page(page_num: int, output_dir: Path = RAW_DATA_DIR) -> Path | None:
    beike_dir = output_dir / "beike"
    if not beike_dir.is_dir():
        return None
    matches = sorted(beike_dir.glob(f"*-page{page_num}-*.html"))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Chrome lifecycle
# ---------------------------------------------------------------------------


def _ensure_chrome_running() -> None:
    proc = subprocess.run(
        [BROWSER_START_JS, "--profile"],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8").strip()
        raise RuntimeError(f"Chrome start failed (exit {proc.returncode}): {stderr}")


def _chrome_restart() -> None:
    try:
        pid_result = subprocess.run(
            ["lsof", "-ti", ":9222"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        pid = pid_result.stdout.strip()
        if pid:
            subprocess.run(["kill", pid], timeout=5)
            time.sleep(2)
    except Exception:
        pass
    _ensure_chrome_running()
    time.sleep(3)


def _notify_manual_intervention(message: str) -> None:
    logger.error("%s", message)
    print("\a", end="", flush=True)
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "RentalScout captcha"',
            ],
            timeout=5,
            check=False,
        )
    except Exception:
        logger.info("macOS notification failed; relying on terminal message")


def _open_url_for_manual_intervention(url: str) -> None:
    try:
        subprocess.run(
            [BROWSER_NAV_JS, url, "--new"],
            timeout=15,
            check=False,
        )
    except Exception:
        logger.info("Failed to open captcha URL in browser: %s", url)


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------


def _looks_like_listings(html: str) -> bool:
    if not html or len(html) < 1000:
        return False
    if "content__list--item" not in html:
        return False
    return "content__list--item-price" in html


def _is_captcha_page(html: str) -> bool:
    return len(html) < 50000  # real page ~230KB, captcha ~19KB


# ---------------------------------------------------------------------------
# Storage helper
# ---------------------------------------------------------------------------


def _save_raw_page(
    body: str,
    source: str,
    page_num: int,
    output_dir: Path = RAW_DATA_DIR,
) -> Path:
    digest = sha256(body.encode("utf-8")).hexdigest()
    source_dir = output_dir / source
    source_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC)
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = source_dir / f"{ts}-page{page_num}-{digest[:12]}.html"
    raw_path.write_text(body, encoding="utf-8")
    return raw_path


def _save_raw_detail(
    body: str,
    source_listing_id: str,
    output_dir: Path = RAW_DATA_DIR,
) -> Path:
    digest = sha256(body.encode("utf-8")).hexdigest()
    source_dir = output_dir / "beike" / "detail"
    source_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC)
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    raw_path = source_dir / f"{ts}-{source_listing_id}-{digest[:12]}.html"
    raw_path.write_text(body, encoding="utf-8")
    return raw_path


def _latest_raw_detail(
    source_listing_id: str | None,
    output_dir: Path = RAW_DATA_DIR,
) -> Path | None:
    if not source_listing_id:
        return None
    detail_dir = output_dir / "beike" / "detail"
    if not detail_dir.is_dir():
        return None
    matches = sorted(detail_dir.glob(f"*-{source_listing_id}-*.html"))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Beike batch scraper
# ---------------------------------------------------------------------------


def scrape_beike_pages(
    *,
    start_page: int | None = None,
    max_pages: int = 75,
    retry_attempts: int = 3,
    delay_range: tuple[float, float] = (10.0, 15.0),
    human_break_every: int = 7,
    human_break_range: tuple[float, float] = (60.0, 120.0),
    crawl_control: BeikeCrawlControl | None = None,
) -> Generator[tuple[int, str]]:
    """Yield (page_num, html_body) for each successfully scraped Beike page.

    If ``start_page`` is None, auto-detects from saved raw files in
    ``data/raw/beike/`` (resume from last saved page + 1).

    Anti-detection features:
    - 10-15s random delay between pages with micro-jitter
    - 60-120s "human break" pause every ~7 pages
    - Random scroll before extraction (in beike-scrape.js)
    - Per-page retry: captcha wait 120s, browser disconnect restarts Chrome
    - Sanity check on extracted HTML before yielding
    """
    _ensure_chrome_running()
    control = crawl_control or BeikeCrawlControl(
        delay_range=delay_range,
        human_break_every=human_break_every,
        human_break_range=human_break_range,
    )

    explicit_start_page = start_page is not None
    if start_page is None:
        start_page = 1
    if start_page > max_pages:
        logger.info(
            "All pages already scraped (start=%d > max=%d)",
            start_page,
            max_pages,
        )
        return

    logger.info(
        "Beike batch: pages %d-%d, delay=%.0f-%.0fs, breaks every %d pages",
        start_page,
        max_pages,
        delay_range[0],
        delay_range[1],
        human_break_every,
    )

    succeeded = 0
    failed_pages: list[int] = []

    for page_num in range(start_page, max_pages + 1):
        url = _build_beike_url(page_num)
        cached_path = None if explicit_start_page else _latest_raw_page(page_num)
        if cached_path is not None:
            logger.info("Page %d/%d: reuse cached %s", page_num, max_pages, cached_path.name)
            control.log_event(
                "cache_reuse",
                kind="list",
                page=page_num,
                raw_path=str(cached_path),
            )
            yield (page_num, cached_path.read_text(encoding="utf-8", errors="replace"))
            continue

        html: str | None = None
        captcha_seen = False

        tmp_html = Path(f"/tmp/beike_batch_page{page_num}.html")
        for attempt in range(1, retry_attempts + 1):
            started_at = time.monotonic()
            try:
                tmp_html.parent.mkdir(parents=True, exist_ok=True)
                with tmp_html.open("wb") as stdout_file:
                    proc = subprocess.run(
                        [BEIKE_SCRAPE_JS, url],
                        stdout=stdout_file,
                        timeout=35,
                    )

                page_html = tmp_html.read_text(encoding="utf-8", errors="replace")
                tmp_html.unlink(missing_ok=True)

                if proc.returncode == 0:
                    if _looks_like_listings(page_html):
                        html = page_html
                        raw_path = _save_raw_page(html, source="beike", page_num=page_num)
                        control.log_event(
                            "request",
                            kind="list",
                            status="ok",
                            page=page_num,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                            raw_path=str(raw_path),
                        )
                        control.record_success(kind="list", label=page_num)
                        succeeded += 1
                        logger.info(
                            "Page %d/%d: OK (%d bytes) → %s",
                            page_num,
                            max_pages,
                            len(html),
                            raw_path.name,
                        )
                        break
                    if _is_captcha_page(page_html):
                        captcha_seen = True
                        control.log_event(
                            "request",
                            kind="list",
                            status="captcha",
                            page=page_num,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                        )
                        logger.warning(
                            "Page %d: captcha (%d bytes, attempt %d/%d), stopping",
                            page_num,
                            len(page_html),
                            attempt,
                            retry_attempts,
                        )
                        break
                    else:
                        control.log_event(
                            "request",
                            kind="list",
                            status="unexpected",
                            page=page_num,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                        )
                        logger.warning(
                            "Page %d: no listing cards (%d bytes, attempt %d/%d)",
                            page_num,
                            len(page_html),
                            attempt,
                            retry_attempts,
                        )
                        _chrome_restart()
                elif proc.returncode == 2:
                    control.log_event(
                        "request",
                        kind="list",
                        status="browser_disconnected",
                        page=page_num,
                        attempt=attempt,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    logger.warning(
                        "Page %d: browser disconnected (attempt %d/%d)",
                        page_num,
                        attempt,
                        retry_attempts,
                    )
                    _chrome_restart()
                else:
                    control.log_event(
                        "request",
                        kind="list",
                        status="exit",
                        page=page_num,
                        attempt=attempt,
                        exit_code=proc.returncode,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    logger.warning(
                        "Page %d: exit %d (attempt %d/%d)",
                        page_num,
                        proc.returncode,
                        attempt,
                        retry_attempts,
                    )
            except subprocess.TimeoutExpired:
                tmp_html.unlink(missing_ok=True)
                control.log_event(
                    "request",
                    kind="list",
                    status="timeout",
                    page=page_num,
                    attempt=attempt,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                )
                logger.warning(
                    "Page %d: timeout (attempt %d/%d)",
                    page_num,
                    attempt,
                    retry_attempts,
                )

        if html is None:
            failed_pages.append(page_num)
            logger.error("Page %d: ALL %d attempts failed, skipping", page_num, retry_attempts)
            if captcha_seen:
                next_profile = control.record_captcha(kind="list", label=page_num)
                _open_url_for_manual_intervention(url)
                _notify_manual_intervention(
                    f"Page {page_num}: captcha persisted; next suggested profile={next_profile}"
                )
                break
        else:
            yield (page_num, html)

        control.sleep_between_requests(kind="list", label=page_num)
        break_time = control.maybe_human_break(page_num, max_pages)
        if break_time is not None:
            logger.info("Human break %d: %.0fs pause", page_num, break_time)

    logger.info(
        "Beike batch done: %d/%d succeeded, failed=%s",
        succeeded,
        max_pages,
        failed_pages or "none",
    )


def scrape_beike_detail_listings(
    listings: list[NormalizedRentalListing],
    *,
    retry_attempts: int = 3,
    delay_range: tuple[float, float] = (8.0, 12.0),
    output_dir: Path = RAW_DATA_DIR,
    crawl_control: BeikeCrawlControl | None = None,
) -> Generator[NormalizedRentalListing]:
    """Fetch Beike detail pages and yield detail-enriched listings."""
    if not listings:
        return

    _ensure_chrome_running()
    control = crawl_control or BeikeCrawlControl(delay_range=delay_range)

    seen_urls: set[str] = set()
    failed_urls: list[str] = []

    for index, listing in enumerate(listings, start=1):
        url = str(listing.source_url)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        cached_path = _latest_raw_detail(listing.source_listing_id, output_dir)
        if cached_path is not None:
            cached_html = cached_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_beike_detail(cached_html, url, fallback=listing)
            if parsed is not None:
                control.log_event(
                    "cache_reuse",
                    kind="detail",
                    source_listing_id=listing.source_listing_id,
                    raw_path=str(cached_path),
                )
                logger.info(
                    "Detail %d/%d: reuse cached %s",
                    index,
                    len(listings),
                    cached_path.name,
                )
                yield parsed
                continue

        html: str | None = None
        captcha_seen = False
        tmp_html = Path(f"/tmp/beike_detail_{listing.source_listing_id or index}.html")
        for attempt in range(1, retry_attempts + 1):
            started_at = time.monotonic()
            try:
                tmp_html.parent.mkdir(parents=True, exist_ok=True)
                with tmp_html.open("wb") as stdout_file:
                    proc = subprocess.run(
                        [BEIKE_SCRAPE_JS, url],
                        stdout=stdout_file,
                        timeout=35,
                    )

                page_html = tmp_html.read_text(encoding="utf-8", errors="replace")
                tmp_html.unlink(missing_ok=True)

                if proc.returncode == 0:
                    if _looks_like_beike_detail(page_html):
                        html = page_html
                        raw_path = _save_raw_detail(
                            page_html,
                            listing.source_listing_id or f"detail{index}",
                            output_dir,
                        )
                        control.log_event(
                            "request",
                            kind="detail",
                            status="ok",
                            source_listing_id=listing.source_listing_id,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                            raw_path=str(raw_path),
                        )
                        control.record_success(
                            kind="detail",
                            label=listing.source_listing_id,
                        )
                        logger.info(
                            "Detail %d/%d: OK %s (%d bytes) -> %s",
                            index,
                            len(listings),
                            listing.source_listing_id,
                            len(page_html),
                            raw_path.name,
                        )
                        break
                    if _is_captcha_page(page_html):
                        captcha_seen = True
                        control.log_event(
                            "request",
                            kind="detail",
                            status="captcha",
                            source_listing_id=listing.source_listing_id,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                        )
                        logger.warning(
                            "Detail %s: captcha (%d bytes, attempt %d/%d), stopping",
                            listing.source_listing_id,
                            len(page_html),
                            attempt,
                            retry_attempts,
                        )
                        break
                    else:
                        control.log_event(
                            "request",
                            kind="detail",
                            status="unexpected",
                            source_listing_id=listing.source_listing_id,
                            attempt=attempt,
                            elapsed_seconds=round(time.monotonic() - started_at, 3),
                            html_bytes=len(page_html),
                        )
                        logger.warning(
                            "Detail %s: unexpected page (%d bytes, attempt %d/%d)",
                            listing.source_listing_id,
                            len(page_html),
                            attempt,
                            retry_attempts,
                        )
                        _chrome_restart()
                elif proc.returncode == 2:
                    control.log_event(
                        "request",
                        kind="detail",
                        status="browser_disconnected",
                        source_listing_id=listing.source_listing_id,
                        attempt=attempt,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    logger.warning(
                        "Detail %s: browser disconnected (attempt %d/%d)",
                        listing.source_listing_id,
                        attempt,
                        retry_attempts,
                    )
                    _chrome_restart()
                else:
                    control.log_event(
                        "request",
                        kind="detail",
                        status="exit",
                        source_listing_id=listing.source_listing_id,
                        attempt=attempt,
                        exit_code=proc.returncode,
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                    )
                    logger.warning(
                        "Detail %s: exit %d (attempt %d/%d)",
                        listing.source_listing_id,
                        proc.returncode,
                        attempt,
                        retry_attempts,
                    )
            except subprocess.TimeoutExpired:
                tmp_html.unlink(missing_ok=True)
                control.log_event(
                    "request",
                    kind="detail",
                    status="timeout",
                    source_listing_id=listing.source_listing_id,
                    attempt=attempt,
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                )
                logger.warning(
                    "Detail %s: timeout (attempt %d/%d)",
                    listing.source_listing_id,
                    attempt,
                    retry_attempts,
                )

        if html is None:
            failed_urls.append(url)
            if captcha_seen:
                next_profile = control.record_captcha(
                    kind="detail",
                    label=listing.source_listing_id,
                )
                _open_url_for_manual_intervention(url)
                _notify_manual_intervention(
                    f"Detail {listing.source_listing_id}: captcha persisted, "
                    f"next suggested profile={next_profile}"
                )
                break
        else:
            parsed = parse_beike_detail(html, url, fallback=listing)
            if parsed is not None:
                yield parsed

        if index < len(listings):
            control.sleep_between_requests(kind="detail", label=listing.source_listing_id)

    logger.info(
        "Beike detail batch done: %d/%d succeeded, failed=%d",
        len(seen_urls) - len(failed_urls),
        len(seen_urls),
        len(failed_urls),
    )


def _looks_like_beike_detail(html: str) -> bool:
    if not html or len(html) < 1000:
        return False
    return "content__article__info" in html and "g_conf.houseCode" in html


# ---------------------------------------------------------------------------
# Wellcee batch scraper
# ---------------------------------------------------------------------------


def scrape_wellcee_pages(
    *,
    max_pages: int | None = None,
    retry_attempts: int = 3,
    delay_range: tuple[float, float] = (2.0, 3.0),
    output_dir: Path = RAW_DATA_DIR,
) -> list[WellceeApiPage]:
    """Fetch all Wellcee API pages with retry and anti-detection delays.

    If max_pages is None, auto-detects total pages from the first API response.
    """
    pages: list[WellceeApiPage] = []
    max_bound = max_pages if max_pages is not None else 100

    for page_num in range(1, max_bound + 1):
        page = _fetch_one_wellcee_page(page_num, retry_attempts, output_dir)
        if page is None:
            logger.error("Wellcee page %d: ALL attempts failed, stopping", page_num)
            break

        pages.append(page)

        total_label = max_bound if max_pages else "auto"
        logger.info(
            "Wellcee page %d/%s: %d listings (total=%d)",
            page_num,
            total_label,
            len(page.listings),
            page.total,
        )

        # Auto-detect total pages on first response
        if page_num == 1 and max_pages is None:
            total = page.total
            page_size = page.page_size or 20
            auto_max = math.ceil(total / page_size)
            if auto_max < max_bound:
                logger.info(
                    "Wellcee auto-detected %d pages (%d items, %d/page)",
                    auto_max,
                    total,
                    page_size,
                )

        # Stop if fewer listings than page size (end of results)
        if len(page.listings) < (page.page_size or 20):
            logger.info("Wellcee: last page (fewer listings than page size)")
            break

        # Respect explicit max_pages
        if max_pages is not None and page_num >= max_pages:
            break

        # Anti-ban delay
        time.sleep(random.uniform(*delay_range))

    total_listings = sum(len(p.listings) for p in pages)
    logger.info("Wellcee batch done: %d pages, %d total listings", len(pages), total_listings)
    return pages


def _fetch_one_wellcee_page(
    page_num: int,
    retry_attempts: int = 3,
    output_dir: Path = RAW_DATA_DIR,
) -> WellceeApiPage | None:
    """Fetch and parse a single Wellcee API page with retry."""
    last_error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            payload = _phase1_payload(page_num)
            data = _post_json(WELLCEE_HOUSE_API_URL, payload)
            raw_path = save_api_response(data, page_num, output_dir)
            page_data = data.get("data") if isinstance(data, dict) else {}
            if not isinstance(page_data, dict):
                raise ValueError(
                    f"Malformed Wellcee response: 'data' is {type(page_data).__name__}"
                )

            listings = tuple(
                listing
                for item in page_data.get("list", [])
                if isinstance(item, dict)
                for listing in [_listing_from_item(item)]
                if listing is not None
            )
            return WellceeApiPage(
                page_num=page_num,
                total=int(page_data.get("total") or 0),
                page_size=int(page_data.get("pageSize") or 20),
                listings=listings,
                raw_path=raw_path,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Wellcee page %d: attempt %d/%d failed: %s",
                page_num,
                attempt,
                retry_attempts,
                exc,
            )
            if attempt < retry_attempts:
                time.sleep(2 ** (attempt - 1))

    logger.error(
        "Wellcee page %d: ALL %d attempts failed: %s",
        page_num,
        retry_attempts,
        last_error,
    )
    return None
