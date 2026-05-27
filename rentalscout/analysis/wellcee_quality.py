"""Wellcee 数据质量分析。"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

DEFAULT_ANALYSIS_DIR = DATA_DIR / "analysis"
DEFAULT_WELLCEE_QUALITY_CSV = DEFAULT_ANALYSIS_DIR / "wellcee_quality.csv"
DEFAULT_WELLCEE_QUALITY_SUMMARY_JSON = DEFAULT_ANALYSIS_DIR / "wellcee_quality_summary.json"

MIN_PRICE = 3500
MAX_PRICE = 6000
MIN_REASONABLE_AREA_SQM = 10.0
MAX_REASONABLE_AREA_SQM = 120.0
MIN_REASONABLE_RENT_PER_SQM = 40.0
MAX_REASONABLE_RENT_PER_SQM = 300.0
SHANGHAI_LATITUDE_RANGE = (30.6, 31.9)
SHANGHAI_LONGITUDE_RANGE = (120.8, 122.2)

APARTMENT_PATTERN = re.compile(r"(公寓|自如|魔方|泊寓|冠寓|人才公寓|青年公寓|白领公寓|集中式)")
LOW_CONFIDENCE_SUBDISTRICT_PATTERN = re.compile(
    r"(地铁站|附近|^[一二三四五六七八九十\d]+号线|(?<!街)道$|路$|街$|线)"
)
SHANGHAI_LOCATION_HINT_PATTERN = re.compile(
    r"(上海|浦东|世纪大道|商城路|八佰伴|朱家滩|陆家嘴|张江|金桥|塘桥|花木|北蔡|周浦)"
)


class AnalysisTier(StrEnum):
    """单条房源的总体分析可用层级。"""

    READY = "ready"
    CAUTION = "caution"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WellceeQualityRow:
    """Wellcee 单条房源质量结果。"""

    source_listing_id: str
    source_url: str
    title: str
    rent_price: int | None
    area_sqm: float | None
    rent_per_sqm: float | None
    district: str | None
    subdistrict: str | None
    community_name: str | None
    has_price: bool
    has_area: bool
    has_location: bool
    has_region: bool
    has_layout: bool
    has_images: bool
    has_published_at: bool
    has_listing_type: bool
    has_duplicate_risk: bool
    can_analyze_price: bool
    can_analyze_area_price: bool
    can_analyze_map: bool
    can_analyze_commute: bool
    can_analyze_region: bool
    can_analyze_freshness: bool
    can_analyze_duplicates: bool
    area_outlier: bool
    subdistrict_low_confidence: bool
    apartment_like: bool
    possible_duplicate: bool
    missing_published_at: bool
    coordinate_suspicious: bool
    analysis_tier: AnalysisTier
    quality_notes: str


def generate_wellcee_quality_outputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_WELLCEE_QUALITY_CSV,
    summary_path: Path = DEFAULT_WELLCEE_QUALITY_SUMMARY_JSON,
) -> tuple[list[WellceeQualityRow], dict[str, object]]:
    """从 SQLite 生成 Wellcee 数据质量 CSV 和 JSON 摘要。"""

    listings = [
        listing for listing in load_listings(db_path) if listing.source == SourceName.WELLCEE
    ]
    rows = analyze_wellcee_quality(listings)
    summary = summarize_quality_rows(rows)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_quality_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def analyze_wellcee_quality(
    listings: Iterable[NormalizedRentalListing],
) -> list[WellceeQualityRow]:
    """计算 Wellcee 房源的分析准入标签。"""

    wellcee_listings = [listing for listing in listings if listing.source == SourceName.WELLCEE]
    duplicate_keys = _duplicate_keys(wellcee_listings)
    return [
        _quality_row(listing, duplicate_keys)
        for listing in sorted(wellcee_listings, key=lambda item: item.source_listing_id or "")
    ]


def summarize_quality_rows(rows: Iterable[WellceeQualityRow]) -> dict[str, object]:
    """汇总质量结果, 供工程和人工快速查看。"""

    row_list = list(rows)
    tier_counts = Counter(row.analysis_tier.value for row in row_list)
    capability_counts = {
        "can_analyze_price": sum(row.can_analyze_price for row in row_list),
        "can_analyze_area_price": sum(row.can_analyze_area_price for row in row_list),
        "can_analyze_map": sum(row.can_analyze_map for row in row_list),
        "can_analyze_commute": sum(row.can_analyze_commute for row in row_list),
        "can_analyze_region": sum(row.can_analyze_region for row in row_list),
        "can_analyze_freshness": sum(row.can_analyze_freshness for row in row_list),
        "can_analyze_duplicates": sum(row.can_analyze_duplicates for row in row_list),
    }
    risk_counts = {
        "area_outlier": sum(row.area_outlier for row in row_list),
        "subdistrict_low_confidence": sum(row.subdistrict_low_confidence for row in row_list),
        "apartment_like": sum(row.apartment_like for row in row_list),
        "possible_duplicate": sum(row.possible_duplicate for row in row_list),
        "missing_published_at": sum(row.missing_published_at for row in row_list),
        "coordinate_suspicious": sum(row.coordinate_suspicious for row in row_list),
    }
    return {
        "source": SourceName.WELLCEE.value,
        "total": len(row_list),
        "tiers": {
            AnalysisTier.READY.value: tier_counts[AnalysisTier.READY.value],
            AnalysisTier.CAUTION.value: tier_counts[AnalysisTier.CAUTION.value],
            AnalysisTier.BLOCKED.value: tier_counts[AnalysisTier.BLOCKED.value],
        },
        "capabilities": capability_counts,
        "risks": risk_counts,
    }


def _quality_row(
    listing: NormalizedRentalListing,
    duplicate_keys: set[tuple[str, int, str]],
) -> WellceeQualityRow:
    price_in_range = listing.rent_price is not None and MIN_PRICE <= listing.rent_price <= MAX_PRICE
    area_outlier = _area_outlier(listing)
    rent_per_sqm = _rent_per_sqm(listing)
    has_location = listing.latitude is not None and listing.longitude is not None
    coordinate_suspicious = has_location and not _coordinate_in_shanghai(listing)
    can_analyze_map = has_location and not coordinate_suspicious and listing.district == "浦东"
    duplicate_key = _duplicate_key(listing)
    possible_duplicate = duplicate_key in duplicate_keys if duplicate_key else False
    subdistrict_low_confidence = _subdistrict_low_confidence(listing.subdistrict)
    apartment_like = _apartment_like(listing)
    missing_published_at = listing.published_at is None
    can_analyze_price = price_in_range
    can_analyze_area_price = price_in_range and listing.area_sqm is not None and not area_outlier
    can_analyze_region = listing.district == "浦东" and bool(listing.community_name)
    can_analyze_freshness = listing.published_at is not None
    can_analyze_duplicates = bool(listing.source_listing_id and listing.community_name)

    notes = _quality_notes(
        listing=listing,
        price_in_range=price_in_range,
        has_area=listing.area_sqm is not None,
        area_outlier=area_outlier,
        coordinate_suspicious=coordinate_suspicious,
        can_analyze_map=can_analyze_map,
        subdistrict_low_confidence=subdistrict_low_confidence,
        apartment_like=apartment_like,
        possible_duplicate=possible_duplicate,
        missing_published_at=missing_published_at,
    )
    tier = _analysis_tier(
        can_analyze_price=can_analyze_price,
        can_analyze_map=can_analyze_map,
        area_outlier=area_outlier,
        coordinate_suspicious=coordinate_suspicious,
        subdistrict_low_confidence=subdistrict_low_confidence,
        possible_duplicate=possible_duplicate,
        missing_published_at=missing_published_at,
    )

    return WellceeQualityRow(
        source_listing_id=listing.source_listing_id or "",
        source_url=str(listing.source_url),
        title=listing.title,
        rent_price=listing.rent_price,
        area_sqm=listing.area_sqm,
        rent_per_sqm=rent_per_sqm,
        district=listing.district,
        subdistrict=listing.subdistrict,
        community_name=listing.community_name,
        has_price=listing.rent_price is not None,
        has_area=listing.area_sqm is not None,
        has_location=has_location,
        has_region=listing.district is not None,
        has_layout=listing.layout is not None,
        has_images=bool(listing.image_urls),
        has_published_at=listing.published_at is not None,
        has_listing_type=listing.listing_type.value != "unknown",
        has_duplicate_risk=possible_duplicate,
        can_analyze_price=can_analyze_price,
        can_analyze_area_price=can_analyze_area_price,
        can_analyze_map=can_analyze_map,
        can_analyze_commute=can_analyze_map,
        can_analyze_region=can_analyze_region,
        can_analyze_freshness=can_analyze_freshness,
        can_analyze_duplicates=can_analyze_duplicates,
        area_outlier=area_outlier,
        subdistrict_low_confidence=subdistrict_low_confidence,
        apartment_like=apartment_like,
        possible_duplicate=possible_duplicate,
        missing_published_at=missing_published_at,
        coordinate_suspicious=coordinate_suspicious,
        analysis_tier=tier,
        quality_notes="; ".join(notes) if notes else "核心字段可用于第一版分析",
    )


def _duplicate_keys(listings: list[NormalizedRentalListing]) -> set[tuple[str, int, str]]:
    counter: Counter[tuple[str, int, str]] = Counter()
    for listing in listings:
        key = _duplicate_key(listing)
        if key:
            counter[key] += 1
    return {key for key, count in counter.items() if count > 1}


def _duplicate_key(listing: NormalizedRentalListing) -> tuple[str, int, str] | None:
    if not listing.title or listing.rent_price is None or not listing.community_name:
        return None
    return (listing.title.strip(), listing.rent_price, listing.community_name.strip())


def _area_outlier(listing: NormalizedRentalListing) -> bool:
    if listing.area_sqm is None:
        return False
    if not MIN_REASONABLE_AREA_SQM <= listing.area_sqm <= MAX_REASONABLE_AREA_SQM:
        return True
    rent_per_sqm = _rent_per_sqm(listing)
    return rent_per_sqm is not None and not (
        MIN_REASONABLE_RENT_PER_SQM <= rent_per_sqm <= MAX_REASONABLE_RENT_PER_SQM
    )


def _rent_per_sqm(listing: NormalizedRentalListing) -> float | None:
    if listing.rent_price is None or listing.area_sqm is None or listing.area_sqm <= 0:
        return None
    return round(listing.rent_price / listing.area_sqm, 2)


def _coordinate_in_shanghai(listing: NormalizedRentalListing) -> bool:
    if listing.latitude is None or listing.longitude is None:
        return False
    return (
        SHANGHAI_LATITUDE_RANGE[0] <= listing.latitude <= SHANGHAI_LATITUDE_RANGE[1]
        and SHANGHAI_LONGITUDE_RANGE[0] <= listing.longitude <= SHANGHAI_LONGITUDE_RANGE[1]
    )


def _subdistrict_low_confidence(subdistrict: str | None) -> bool:
    if not subdistrict:
        return True
    stripped = subdistrict.strip()
    if len(stripped) < 3:
        return True
    return bool(LOW_CONFIDENCE_SUBDISTRICT_PATTERN.search(stripped))


def _apartment_like(listing: NormalizedRentalListing) -> bool:
    text = " ".join(
        value
        for value in [listing.title, listing.community_name, listing.description]
        if value
    )
    return bool(APARTMENT_PATTERN.search(text))


def _analysis_tier(
    *,
    can_analyze_price: bool,
    can_analyze_map: bool,
    area_outlier: bool,
    coordinate_suspicious: bool,
    subdistrict_low_confidence: bool,
    possible_duplicate: bool,
    missing_published_at: bool,
) -> AnalysisTier:
    if not can_analyze_price or not can_analyze_map or coordinate_suspicious:
        return AnalysisTier.BLOCKED
    if area_outlier or subdistrict_low_confidence or possible_duplicate or missing_published_at:
        return AnalysisTier.CAUTION
    return AnalysisTier.READY


def _quality_notes(
    *,
    listing: NormalizedRentalListing,
    price_in_range: bool,
    has_area: bool,
    area_outlier: bool,
    coordinate_suspicious: bool,
    can_analyze_map: bool,
    subdistrict_low_confidence: bool,
    apartment_like: bool,
    possible_duplicate: bool,
    missing_published_at: bool,
) -> list[str]:
    notes: list[str] = []
    if not price_in_range:
        notes.append("租金缺失或超出 3500-6000 元范围")
    if not has_area:
        notes.append("面积缺失, 不能做单位面积租金")
    elif area_outlier:
        notes.append("面积或单位面积租金异常, 不能做单位面积租金")
    if coordinate_suspicious:
        if _has_shanghai_location_hint(listing):
            notes.append("经纬度不在上海合理范围, 但正文含上海地址线索, 需要二次定位")
        else:
            notes.append("经纬度不在上海合理范围")
    elif not can_analyze_map:
        notes.append("缺少浦东坐标条件, 不能进入地图和通勤分析")
    if subdistrict_low_confidence:
        notes.append("街道/板块字段可信度低, 只能谨慎做区域聚合")
    if apartment_like:
        notes.append("疑似公寓类房源, 保留但后续可筛选排除")
    if possible_duplicate:
        notes.append("存在同标题、租金、小区的重复候选")
    if missing_published_at:
        notes.append("发布时间缺失, 不能做新鲜度分析")
    return notes


def _has_shanghai_location_hint(listing: NormalizedRentalListing) -> bool:
    text = " ".join(
        value
        for value in [
            listing.title,
            listing.address_text,
            listing.community_name,
            listing.subdistrict,
            listing.description,
        ]
        if value
    )
    return bool(SHANGHAI_LOCATION_HINT_PATTERN.search(text))


def _write_quality_csv(rows: list[WellceeQualityRow], path: Path) -> None:
    fieldnames = list(WellceeQualityRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            payload["analysis_tier"] = row.analysis_tier.value
            writer.writerow(payload)
