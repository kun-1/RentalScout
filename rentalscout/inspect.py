"""HTML 侦察摘要。"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass(frozen=True)
class HtmlSummary:
    """入口页的轻量结构摘要。"""

    title: str | None
    link_count: int
    links: tuple[str, ...]
    body_size: int
    contains_next_data: bool


class _SummaryParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href:
            self.links.append(urljoin(self.base_url, href))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())


def summarize_html(body: str, base_url: str, *, max_links: int = 20) -> HtmlSummary:
    """从 HTML 中提取标题、链接数量和少量链接样本。"""

    parser = _SummaryParser(base_url)
    parser.feed(body)
    title = " ".join(part for part in parser.title_parts if part).strip() or None
    unique_links = tuple(dict.fromkeys(parser.links))

    return HtmlSummary(
        title=title,
        link_count=len(unique_links),
        links=unique_links[:max_links],
        body_size=len(body.encode("utf-8")),
        contains_next_data="__NEXT_DATA__" in body or "__NUXT__" in body,
    )
