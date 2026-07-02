"""下架检测: 全量抓取后, 标记消失的房源为 OUT_OF_WINDOW 或 OFFLINE。

判定规则:
  1. 调用方必须传入 ``seen_listing_ids`` (本次抓到的所有 listing_id) 和
     ``seen_total`` (API 返回的 total, 即当前口径下的实际在架总数)。
  2. 对每个 in-scope 历史房源:
       - 本次抓到         -> 忽略 (in_scope_active)
       - 本次没抓到 + seen_total == len(seen)  -> 标 OFFLINE (全量覆盖, 真的下架了)
       - 本次没抓到 + seen_total >  len(seen)  -> 标 OUT_OF_WINDOW (被 API 搜索上限挤出)
       - 已被标过同状态   -> already_X
  3. 同样只在当前筛选口径内做判定, 避免把不同口径的房源误判成下架。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rentalscout.schemas.normalized import (
    ListingAvailabilityStatus,
    NormalizedRentalListing,
)
from rentalscout.storage.sqlite import (
    DEFAULT_DB_PATH,
    ListingObservation,
    load_listings,
    load_observations,
    record_observations,
)


@dataclass(frozen=True)
class DelistedListing:
    """一条被判定为下架/出窗的房源(同结构, 仅 status 不同)。"""

    source: str
    source_listing_id: str
    title: str
    community_name: str | None
    district: str | None
    last_rent_price: int | None
    status: ListingAvailabilityStatus


@dataclass(frozen=True)
class ReconcileResult:
    """一次下架检测的结果汇总。"""

    scope_total: int
    in_scope_active: int
    newly_offline: int
    already_offline: int
    newly_out_of_window: int
    already_out_of_window: int
    saw_total: int
    saw_unique: int
    is_full_crawl: bool
    delisted: tuple[DelistedListing, ...]


def reconcile_availability(
    seen_listing_ids: Iterable[str],
    *,
    seen_total: int | None = None,
    source: str = "wellcee",
    district: str | None = "浦东",
    min_price: int = 3500,
    max_price: int = 6000,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
) -> ReconcileResult:
    """标记下架/出窗房源并写入观测。返回本次检测的汇总。

    full-crawl 判定 (可以判 OFFLINE 的条件):
      len(seen_listing_ids) >= seen_total  AND  in_scope 历史房源 <= seen_total
    否则视为部分覆盖, 缺席房源一律记 OUT_OF_WINDOW (被 API 搜索上限挤出)。
    """

    seen = {str(listing_id) for listing_id in seen_listing_ids}
    moment = now or datetime.now(UTC)

    latest_status = _latest_status_by_listing(load_observations(db_path=db_path))

    in_scope = [
        listing
        for listing in load_listings(db_path=db_path)
        if _in_scope(listing, source, district, min_price, max_price)
    ]
    saw_unique = len(seen)
    is_full_crawl = (
        seen_total is not None
        and saw_unique >= seen_total
        and len(in_scope) <= seen_total
    )

    new_observations: list[ListingObservation] = []
    newly_offline = 0
    newly_out_of_window = 0
    already_offline = 0
    already_out_of_window = 0
    delisted: list[DelistedListing] = []

    for listing in in_scope:
        if listing.source_listing_id in seen:
            continue
        key = (listing.source.value, listing.source_listing_id or "")
        previous = latest_status.get(key)
        target = (
            ListingAvailabilityStatus.OFFLINE
            if is_full_crawl
            else ListingAvailabilityStatus.OUT_OF_WINDOW
        )
        if previous == target:
            if target is ListingAvailabilityStatus.OFFLINE:
                already_offline += 1
            else:
                already_out_of_window += 1
            continue
        new_observations.append(_status_observation(listing, moment, target))
        if target is ListingAvailabilityStatus.OFFLINE:
            newly_offline += 1
        else:
            newly_out_of_window += 1
        delisted.append(_to_delisted(listing, target))

    record_observations(new_observations, db_path=db_path)

    return ReconcileResult(
        scope_total=len(in_scope),
        in_scope_active=sum(1 for listing in in_scope if listing.source_listing_id in seen),
        newly_offline=newly_offline,
        already_offline=already_offline,
        newly_out_of_window=newly_out_of_window,
        already_out_of_window=already_out_of_window,
        saw_total=seen_total or 0,
        saw_unique=saw_unique,
        is_full_crawl=is_full_crawl,
        delisted=tuple(delisted),
    )


def _in_scope(
    listing: NormalizedRentalListing,
    source: str,
    district: str | None,
    min_price: int,
    max_price: int,
) -> bool:
    if listing.source.value != source:
        return False
    if district is not None and listing.district != district:
        return False
    price = listing.rent_price
    if price is None:
        return False
    return min_price <= price <= max_price


def _latest_status_by_listing(
    observations: list[ListingObservation],
) -> dict[tuple[str, str], ListingAvailabilityStatus]:
    latest_time: dict[tuple[str, str], datetime] = {}
    latest_status: dict[tuple[str, str], ListingAvailabilityStatus] = {}
    for observation in observations:
        key = (observation.source, observation.source_listing_id)
        if key not in latest_time or observation.observed_at > latest_time[key]:
            latest_time[key] = observation.observed_at
            latest_status[key] = observation.availability_status
    return latest_status


def _status_observation(
    listing: NormalizedRentalListing,
    moment: datetime,
    status: ListingAvailabilityStatus,
) -> ListingObservation:
    return ListingObservation(
        source=listing.source.value,
        source_listing_id=listing.source_listing_id or "",
        observed_at=moment,
        crawl_run_id=None,
        rent_price=listing.rent_price,
        availability_status=status,
        days_on_market=(moment.date() - listing.first_seen_at.date()).days,
        title=listing.title,
        area_sqm=listing.area_sqm,
        district=listing.district,
        community_name=listing.community_name,
        host_last_login_at=listing.host_last_login_at,
    )


def _to_delisted(
    listing: NormalizedRentalListing,
    status: ListingAvailabilityStatus,
) -> DelistedListing:
    return DelistedListing(
        source=listing.source.value,
        source_listing_id=listing.source_listing_id or "",
        title=listing.title,
        community_name=listing.community_name,
        district=listing.district,
        last_rent_price=listing.rent_price,
        status=status,
    )
