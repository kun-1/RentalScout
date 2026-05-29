"""SQLite 本地存储。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from rentalscout.schemas.normalized import ListingAvailabilityStatus, NormalizedRentalListing
from rentalscout.settings import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "rentalscout.sqlite3"
LISTING_ADAPTER = TypeAdapter(NormalizedRentalListing)


@dataclass(frozen=True)
class ListingObservation:
    """A point-in-time listing observation for price history analysis."""

    source: str
    source_listing_id: str
    observed_at: datetime
    crawl_run_id: int | None
    rent_price: int | None
    availability_status: ListingAvailabilityStatus
    days_on_market: int | None
    title: str
    area_sqm: float | None
    district: str | None
    community_name: str | None


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化本地 SQLite 数据库。"""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rental_listings (
                source TEXT NOT NULL,
                source_listing_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT NOT NULL,
                rent_price INTEGER,
                district TEXT,
                community_name TEXT,
                payload_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (source, source_listing_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS listing_observations (
                source TEXT NOT NULL,
                source_listing_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                crawl_run_id INTEGER,
                rent_price INTEGER,
                availability_status TEXT NOT NULL DEFAULT 'active',
                days_on_market INTEGER,
                title TEXT NOT NULL,
                area_sqm REAL,
                district TEXT,
                community_name TEXT,
                PRIMARY KEY (source, source_listing_id, observed_at)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                raw_path TEXT,
                status_code INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def upsert_listings(
    listings: Iterable[NormalizedRentalListing],
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """写入或更新标准化房源。"""

    init_db(db_path)
    rows = [_row_for_listing(listing) for listing in listings if listing.source_listing_id]
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO rental_listings (
                source,
                source_listing_id,
                source_url,
                title,
                rent_price,
                district,
                community_name,
                payload_json,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_listing_id) DO UPDATE SET
                source_url = excluded.source_url,
                title = excluded.title,
                rent_price = excluded.rent_price,
                district = excluded.district,
                community_name = excluded.community_name,
                payload_json = excluded.payload_json,
                last_seen_at = excluded.last_seen_at
            """,
            rows,
        )
    return len(rows)


def load_listings(db_path: Path = DEFAULT_DB_PATH) -> list[NormalizedRentalListing]:
    """读取所有标准化房源。"""

    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM rental_listings ORDER BY source, source_listing_id"
        ).fetchall()
    return [LISTING_ADAPTER.validate_json(row[0]) for row in rows]


def load_observations(db_path: Path = DEFAULT_DB_PATH) -> list[ListingObservation]:
    """Read point-in-time listing observations, falling back to current listings."""

    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                source,
                source_listing_id,
                observed_at,
                crawl_run_id,
                rent_price,
                availability_status,
                days_on_market,
                title,
                area_sqm,
                district,
                community_name
            FROM listing_observations
            ORDER BY source, source_listing_id, observed_at
            """
        ).fetchall()
    if rows:
        return [_observation_from_row(row) for row in rows]
    return [_observation_from_listing(listing) for listing in load_listings(db_path)]


def _row_for_listing(listing: NormalizedRentalListing) -> tuple[object, ...]:
    payload = listing.model_dump(mode="json")
    return (
        listing.source.value,
        listing.source_listing_id,
        str(listing.source_url),
        listing.title,
        listing.rent_price,
        listing.district,
        listing.community_name,
        json.dumps(payload, ensure_ascii=False),
        listing.first_seen_at.isoformat(),
        listing.last_seen_at.isoformat(),
    )


def _observation_from_row(row: tuple[object, ...]) -> ListingObservation:
    return ListingObservation(
        source=str(row[0]),
        source_listing_id=str(row[1]),
        observed_at=_parse_datetime(str(row[2])),
        crawl_run_id=int(row[3]) if row[3] is not None else None,
        rent_price=int(row[4]) if row[4] is not None else None,
        availability_status=_parse_availability_status(row[5]),
        days_on_market=int(row[6]) if row[6] is not None else None,
        title=str(row[7]),
        area_sqm=float(row[8]) if row[8] is not None else None,
        district=str(row[9]) if row[9] is not None else None,
        community_name=str(row[10]) if row[10] is not None else None,
    )


def _observation_from_listing(listing: NormalizedRentalListing) -> ListingObservation:
    return ListingObservation(
        source=listing.source.value,
        source_listing_id=listing.source_listing_id or "",
        observed_at=listing.last_seen_at,
        crawl_run_id=None,
        rent_price=listing.rent_price,
        availability_status=ListingAvailabilityStatus.ACTIVE,
        days_on_market=(listing.last_seen_at.date() - listing.first_seen_at.date()).days,
        title=listing.title,
        area_sqm=listing.area_sqm,
        district=listing.district,
        community_name=listing.community_name,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_availability_status(value: object) -> ListingAvailabilityStatus:
    try:
        return ListingAvailabilityStatus(str(value))
    except ValueError:
        return ListingAvailabilityStatus.UNKNOWN
