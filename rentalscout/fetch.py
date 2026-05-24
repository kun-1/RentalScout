"""公开页面抓取与原始 HTML 保存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from rentalscout.schemas.raw import RawPage, SourceName
from rentalscout.settings import RAW_DATA_DIR

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
NO_PROXY_OPENER = build_opener(ProxyHandler({}))


@dataclass(frozen=True)
class FetchResult:
    """一次页面抓取的结果。"""

    raw_page: RawPage
    body: str | None


def fetch_public_page(
    source: SourceName,
    url: str,
    *,
    output_dir: Path = RAW_DATA_DIR,
    timeout_seconds: int = 20,
) -> FetchResult:
    """抓取公开页面并保存原始 HTML。"""

    fetched_at = datetime.now(UTC)
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )

    try:
        with NO_PROXY_OPENER.open(request, timeout=timeout_seconds) as response:
            raw_bytes = response.read()
            content_type = response.headers.get("content-type")
            status_code = response.status
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raw_page = _save_body(
            source=source,
            url=url,
            body=body,
            fetched_at=fetched_at,
            output_dir=output_dir,
            status_code=error.code,
            content_type=error.headers.get("content-type"),
            error_message=str(error),
        )
        return FetchResult(raw_page=raw_page, body=body)
    except URLError as error:
        raw_page = RawPage(
            source=source,
            url=url,
            fetched_at=fetched_at,
            error_message=str(error.reason),
        )
        return FetchResult(raw_page=raw_page, body=None)
    except (TimeoutError, OSError) as error:
        raw_page = RawPage(
            source=source,
            url=url,
            fetched_at=fetched_at,
            error_message=str(error),
        )
        return FetchResult(raw_page=raw_page, body=None)

    body = raw_bytes.decode("utf-8", errors="replace")
    raw_page = _save_body(
        source=source,
        url=url,
        body=body,
        fetched_at=fetched_at,
        output_dir=output_dir,
        status_code=status_code,
        content_type=content_type,
        error_message=None,
    )
    return FetchResult(raw_page=raw_page, body=body)


def _save_body(
    *,
    source: SourceName,
    url: str,
    body: str,
    fetched_at: datetime,
    output_dir: Path,
    status_code: int,
    content_type: str | None,
    error_message: str | None,
) -> RawPage:
    digest = sha256(body.encode("utf-8")).hexdigest()
    source_dir = output_dir / source.value
    source_dir.mkdir(parents=True, exist_ok=True)
    raw_path = source_dir / f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}-{digest[:12]}.html"
    raw_path.write_text(body, encoding="utf-8")

    return RawPage(
        source=source,
        url=url,
        fetched_at=fetched_at,
        status_code=status_code,
        content_type=content_type,
        content_hash=digest,
        raw_path=raw_path,
        error_message=error_message,
    )
