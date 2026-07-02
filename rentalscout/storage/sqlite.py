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

# Bumped when schema migrations are added. Stored in PRAGMA user_version.
# v2: rebuild drifted listing_observations tables that carried extra NOT NULL
#     columns (source_url/payload_json) which silently blocked observation writes.
# v3: add host_last_login_at (房主最后登录时间) to listings + observations.
CURRENT_SCHEMA_VERSION = 3

# Canonical column order for listing_observations; used by migrations to copy rows.
_OBSERVATION_COLUMNS = (
    "source",
    "source_listing_id",
    "observed_at",
    "crawl_run_id",
    "rent_price",
    "availability_status",
    "days_on_market",
    "title",
    "area_sqm",
    "district",
    "community_name",
    "host_last_login_at",
)


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
    host_last_login_at: datetime | None = None


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化本地 SQLite 数据库。"""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        # WAL lets the Streamlit dashboard read while the crawler writes.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
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
                host_last_login_at TEXT,
                PRIMARY KEY (source, source_listing_id)
            )
            """
        )
        _create_observations_table(connection)
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
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version < CURRENT_SCHEMA_VERSION:
            _run_migrations(connection, current_version)
            connection.execute(f"PRAGMA user_version={CURRENT_SCHEMA_VERSION}")


def _create_observations_table(connection: sqlite3.Connection) -> None:
    """Create listing_observations with the canonical lean schema (idempotent)."""

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
            host_last_login_at TEXT,
            PRIMARY KEY (source, source_listing_id, observed_at)
        )
        """
    )


def _run_migrations(connection: sqlite3.Connection, from_version: int) -> None:
    """Apply schema migrations forward from ``from_version`` to CURRENT_SCHEMA_VERSION.

    To extend:
      1. Bump ``CURRENT_SCHEMA_VERSION``.
      2. Add an ``if from_version < N:`` branch here that issues the
         necessary ``ALTER TABLE`` / ``CREATE ...`` statements.
    Keep it linear and additive — no rollback logic needed for a local cache.
    """

    if from_version < 2:
        _rebuild_observations_if_stale(connection)
    if from_version < 3:
        _add_host_last_login_columns(connection)


def _add_host_last_login_columns(connection: sqlite3.Connection) -> None:
    """v3: add host_last_login_at to both tables. SQLite ALTER is idempotent-safe."""
    for ddl in (
        "ALTER TABLE rental_listings ADD COLUMN host_last_login_at TEXT",
        "ALTER TABLE listing_observations ADD COLUMN host_last_login_at TEXT",
    ):
        try:
            connection.execute(ddl)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise


def _rebuild_observations_if_stale(connection: sqlite3.Connection) -> None:
    """Rebuild listing_observations if it still carries the pre-v2 schema.

    Older DBs created this table with extra ``NOT NULL`` columns
    (``source_url``/``payload_json``) that the observation writer never
    populates, so every ``INSERT OR IGNORE`` was silently dropped. Rebuild to the
    canonical shape, preserving any rows whose columns map cleanly.
    """

    columns = {row[1] for row in connection.execute("PRAGMA table_info(listing_observations)")}
    if not ({"source_url", "payload_json"} & columns):
        return  # fresh or already-canonical table

    shared = [name for name in _OBSERVATION_COLUMNS if name in columns]
    column_list = ", ".join(shared)
    connection.execute("ALTER TABLE listing_observations RENAME TO _listing_observations_old")
    _create_observations_table(connection)
    connection.execute(
        f"INSERT OR IGNORE INTO listing_observations ({column_list}) "
        f"SELECT {column_list} FROM _listing_observations_old"
    )
    connection.execute("DROP TABLE _listing_observations_old")


def upsert_listings(
    listings: Iterable[NormalizedRentalListing],
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """写入或更新标准化房源, 同时追加一条 listing_observations 快照。"""

    init_db(db_path)
    materialized = [listing for listing in listings if listing.source_listing_id]
    rows = [_row_for_listing(listing) for listing in materialized]
    observation_rows = [
        _row_for_observation(_observation_from_listing(listing)) for listing in materialized
    ]
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
                last_seen_at,
                host_last_login_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_listing_id) DO UPDATE SET
                source_url = excluded.source_url,
                title = excluded.title,
                rent_price = excluded.rent_price,
                district = excluded.district,
                community_name = excluded.community_name,
                payload_json = excluded.payload_json,
                last_seen_at = excluded.last_seen_at,
                host_last_login_at = excluded.host_last_login_at
            """,
            rows,
        )
        if observation_rows:
            columns = ", ".join(_OBSERVATION_COLUMNS)
            placeholders = ", ".join("?" for _ in _OBSERVATION_COLUMNS)
            # INSERT OR IGNORE so a re-run at the same observed_at does not duplicate.
            connection.executemany(
                f"INSERT OR IGNORE INTO listing_observations ({columns}) VALUES ({placeholders})",
                observation_rows,
            )
    return len(rows)


def record_crawl_run(
    source: str,
    url: str,
    status_code: int | None = None,
    raw_path: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """在 crawl_runs 表插入一条记录并返回新自增 id。"""

    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO crawl_runs (source, url, raw_path, status_code)
            VALUES (?, ?, ?, ?)
            """,
            (source, url, raw_path, status_code),
        )
        return int(cursor.lastrowid)


def record_observations(
    observations: Iterable[ListingObservation],
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """直接写入观测行(例如下架检测生成的 OFFLINE 快照)。"""

    init_db(db_path)
    rows = [_row_for_observation(observation) for observation in observations]
    if not rows:
        return 0
    columns = ", ".join(_OBSERVATION_COLUMNS)
    placeholders = ", ".join("?" for _ in _OBSERVATION_COLUMNS)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            f"INSERT OR IGNORE INTO listing_observations ({columns}) VALUES ({placeholders})",
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
            f"""
            SELECT {", ".join(_OBSERVATION_COLUMNS)}
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
        listing.host_last_login_at.isoformat() if listing.host_last_login_at else None,
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
        host_last_login_at=_parse_datetime(str(row[11])) if row[11] else None,
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
        host_last_login_at=listing.host_last_login_at,
    )


def _row_for_observation(observation: ListingObservation) -> tuple[object, ...]:
    return (
        observation.source,
        observation.source_listing_id,
        observation.observed_at.isoformat(),
        observation.crawl_run_id,
        observation.rent_price,
        observation.availability_status.value,
        observation.days_on_market,
        observation.title,
        observation.area_sqm,
        observation.district,
        observation.community_name,
        observation.host_last_login_at.isoformat() if observation.host_last_login_at else None,
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_availability_status(value: object) -> ListingAvailabilityStatus:
    try:
        return ListingAvailabilityStatus(str(value))
    except ValueError:
        return ListingAvailabilityStatus.UNKNOWN
