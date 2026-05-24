"""SQLite 本地存储。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from pydantic import TypeAdapter

from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.settings import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "rentalscout.sqlite3"
LISTING_ADAPTER = TypeAdapter(NormalizedRentalListing)


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
