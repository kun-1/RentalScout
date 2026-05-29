"""Price history analysis from listing observations."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rentalscout.schemas.normalized import ListingAvailabilityStatus
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, ListingObservation, load_observations

DEFAULT_PRICE_HISTORY_CSV = DATA_DIR / "analysis" / "price_history.csv"
DEFAULT_PRICE_HISTORY_SUMMARY_JSON = DATA_DIR / "analysis" / "price_history_summary.json"


@dataclass(frozen=True)
class PriceHistoryRow:
    """One observation annotated with price changes relative to prior history."""

    source: str
    source_listing_id: str
    observed_at: str
    crawl_run_id: int | None
    availability_status: str
    days_on_market: int | None
    title: str
    community_name: str | None
    rent_price: int | None
    previous_rent_price: int | None
    price_delta: int | None
    price_delta_pct: float | None
    first_rent_price: int | None
    price_delta_from_first: int | None
    lowest_rent_price_so_far: int | None
    price_delta_from_lowest: int | None
    price_change_direction: str


def generate_price_history_outputs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    csv_path: Path = DEFAULT_PRICE_HISTORY_CSV,
    summary_path: Path = DEFAULT_PRICE_HISTORY_SUMMARY_JSON,
) -> tuple[list[PriceHistoryRow], dict[str, object]]:
    """Generate price history CSV/JSON outputs from SQLite observations."""

    observations = load_observations(db_path=db_path)
    rows = analyze_price_history(observations)
    summary = summarize_price_history(rows)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_price_history_csv(rows, csv_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def analyze_price_history(observations: list[ListingObservation]) -> list[PriceHistoryRow]:
    """Compute price deltas for each listing's observation timeline."""

    grouped: dict[tuple[str, str], list[ListingObservation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.source, observation.source_listing_id)].append(observation)

    rows: list[PriceHistoryRow] = []
    for _, listing_observations in sorted(grouped.items()):
        previous_price: int | None = None
        first_price: int | None = None
        lowest_price: int | None = None
        for observation in sorted(listing_observations, key=lambda item: item.observed_at):
            current_price = observation.rent_price
            if first_price is None and current_price is not None:
                first_price = current_price
            if current_price is not None:
                lowest_price = (
                    current_price if lowest_price is None else min(lowest_price, current_price)
                )

            price_delta = _delta(current_price, previous_price)
            row = PriceHistoryRow(
                source=observation.source,
                source_listing_id=observation.source_listing_id,
                observed_at=observation.observed_at.isoformat(),
                crawl_run_id=observation.crawl_run_id,
                availability_status=observation.availability_status.value,
                days_on_market=observation.days_on_market,
                title=observation.title,
                community_name=observation.community_name,
                rent_price=current_price,
                previous_rent_price=previous_price,
                price_delta=price_delta,
                price_delta_pct=_delta_pct(price_delta, previous_price),
                first_rent_price=first_price,
                price_delta_from_first=_delta(current_price, first_price),
                lowest_rent_price_so_far=lowest_price,
                price_delta_from_lowest=_delta(current_price, lowest_price),
                price_change_direction=_direction(price_delta),
            )
            rows.append(row)
            if current_price is not None:
                previous_price = current_price
    return rows


def summarize_price_history(rows: list[PriceHistoryRow]) -> dict[str, object]:
    """Summarize price-history outputs."""

    listing_ids = {(row.source, row.source_listing_id) for row in rows}
    changed_rows = [row for row in rows if row.price_delta not in (None, 0)]
    latest_by_listing: dict[tuple[str, str], PriceHistoryRow] = {}
    for row in rows:
        latest_by_listing[(row.source, row.source_listing_id)] = row

    return {
        "total_observations": len(rows),
        "unique_listings": len(listing_ids),
        "price_changes": len(changed_rows),
        "price_drops": sum(row.price_delta is not None and row.price_delta < 0 for row in rows),
        "price_increases": sum(row.price_delta is not None and row.price_delta > 0 for row in rows),
        "inactive_latest": sum(
            row.availability_status != ListingAvailabilityStatus.ACTIVE.value
            for row in latest_by_listing.values()
        ),
    }


def _write_price_history_csv(rows: list[PriceHistoryRow], path: Path) -> None:
    fieldnames = list(PriceHistoryRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _delta_pct(delta: int | None, previous: int | None) -> float | None:
    if delta is None or previous in (None, 0):
        return None
    return round(delta / previous, 4)


def _direction(delta: int | None) -> str:
    if delta is None:
        return "first_or_unknown"
    if delta < 0:
        return "down"
    if delta > 0:
        return "up"
    return "unchanged"
