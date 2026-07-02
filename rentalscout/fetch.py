"""公开页面抓取与原始 HTML 保存。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from curl_cffi import requests as curl_requests

from rentalscout.schemas.raw import RawPage, SourceName
from rentalscout.settings import RAW_DATA_DIR

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
_SESSION = curl_requests.Session()


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
    retries: int = 3,
) -> FetchResult:
    """抓取公开页面并保存原始 HTML。

    使用 curl_cffi + Chrome 指纹伪装, 与 spiders/beike.py 统一。网络级错误
    (连接/DNS/超时) 会指数退避重试; HTTP 4xx/5xx 视为已完成的抓取, 保存响应体
    并附带 error_message, 不重试。
    """

    fetched_at = datetime.now(UTC)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    }

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = _SESSION.request(
                method="GET",
                url=url,
                headers=headers,
                impersonate="chrome",
                timeout=timeout_seconds,
            )
        except curl_requests.RequestsError as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            break

        body = response.content.decode("utf-8", errors="replace")
        status_code = response.status_code
        raw_page = _save_body(
            source=source,
            url=url,
            body=body,
            fetched_at=fetched_at,
            output_dir=output_dir,
            status_code=status_code,
            content_type=response.headers.get("content-type"),
            error_message=None if status_code < 400 else f"HTTP {status_code}",
        )
        return FetchResult(raw_page=raw_page, body=body)

    raw_page = RawPage(
        source=source,
        url=url,
        fetched_at=fetched_at,
        error_message=str(last_error) if last_error else "fetch failed",
    )
    return FetchResult(raw_page=raw_page, body=None)


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
