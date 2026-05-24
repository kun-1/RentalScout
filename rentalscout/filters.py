"""阶段 1 房源过滤规则。"""

from __future__ import annotations

from dataclasses import dataclass

from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName


@dataclass(frozen=True)
class ListingFilterResult:
    """房源过滤结果。"""

    listing: NormalizedRentalListing
    accepted: bool
    reasons: tuple[str, ...]


def apply_phase1_filters(
    listing: NormalizedRentalListing,
    *,
    detail_title: str | None = None,
) -> ListingFilterResult:
    """应用阶段 1 的基础过滤条件。"""

    reasons: list[str] = []
    text = " ".join(
        part
        for part in [
            listing.title,
            listing.description,
            listing.district,
            listing.subdistrict,
            listing.community_name,
            detail_title,
            str(listing.source_url),
        ]
        if part
    )

    min_price = 3500 if listing.source == SourceName.WELLCEE else 0
    max_price = 6000

    if listing.rent_price is None:
        reasons.append("缺少租金")
    elif listing.rent_price < min_price:
        reasons.append(f"租金低于 {min_price}")
    elif listing.rent_price > max_price:
        reasons.append(f"租金超过 {max_price}")

    if "浦东" not in text:
        reasons.append("不在浦东新区")

    if listing.source == SourceName.BEIKE:
        if "整租" not in text:
            reasons.append("贝壳房源不是整租")
        if "1室1厅" not in text and "一室一厅" not in text:
            reasons.append("未匹配一室一厅")
    elif listing.source == SourceName.WELLCEE:
        if any(keyword in text for keyword in ["合租", "找室友", "Seeking Flatmate"]):
            reasons.append("Wellcee 房源疑似合租或找室友")
        if "短租" in text:
            reasons.append("Wellcee 房源疑似短租")

    if listing.source == SourceName.BEIKE and any(
        keyword in text for keyword in ["公寓", "集中式", "/apartment/"]
    ):
        reasons.append("疑似公寓或集中式房源")

    return ListingFilterResult(
        listing=listing,
        accepted=not reasons,
        reasons=tuple(reasons),
    )
