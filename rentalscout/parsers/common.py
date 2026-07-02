"""解析器通用工具。"""

from __future__ import annotations

import re
from html import unescape

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    """去掉 HTML 标签并压缩空白。"""

    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value))).strip()


def parse_int(value: str | None) -> int | None:
    """从文本中解析整数。"""

    if not value:
        return None
    match = re.search(r"\d+", value.replace(",", ""))
    if not match:
        return None
    return int(match.group(0))


def parse_price_bounds(value: str | None) -> tuple[int | None, int | None]:
    """解析租金文本, 支持单值和区间。"""

    if not value:
        return None, None
    numbers = [int(item) for item in re.findall(r"\d+", value.replace(",", ""))]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers), max(numbers)


def parse_area_sqm(value: str) -> float | None:
    """从文本中解析面积。"""

    match = re.search(r"(\d+(?:\.\d+)?)\s*㎡", value)
    if not match:
        return None
    return float(match.group(1))


def split_district_community(title: str | None) -> tuple[str | None, str | None]:
    """从 "浦东 华泰金融大厦" 形式标题里拆出 (district, community)。

    Wellcee 老抓取路径把 community 信息直接写在 title 头, 没有独立字段。
    """

    if not title:
        return None, None
    parts = title.split(maxsplit=1)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]
