import sqlite3
from datetime import UTC, datetime, timedelta

from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import (
    CURRENT_SCHEMA_VERSION,
    init_db,
    load_listings,
    load_observations,
    record_crawl_run,
    upsert_listings,
)


def _make_listing(
    *,
    source_listing_id: str,
    rent_price: int,
    first_seen_at: datetime,
    last_seen_at: datetime,
) -> NormalizedRentalListing:
    return NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id=source_listing_id,
        source_url=f"https://www.wellcee.com/rent-apartment/shanghai/{source_listing_id}",
        title="浦东 测试小区",
        rent_price=rent_price,
        district="浦东",
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


def test_upsert_and_load_listings(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    listing = NormalizedRentalListing(
        source=SourceName.WELLCEE,
        source_listing_id="1",
        source_url="https://www.wellcee.com/rent-apartment/shanghai/1",
        title="浦东 测试小区",
        rent_price=4000,
        district="浦东",
    )

    assert upsert_listings([listing], db_path=db_path) == 1
    loaded = load_listings(db_path=db_path)

    assert len(loaded) == 1
    assert loaded[0].source_listing_id == "1"


def test_upsert_accumulates_observations_across_crawls(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    first_seen = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    listing_day_one = _make_listing(
        source_listing_id="42",
        rent_price=4500,
        first_seen_at=first_seen,
        last_seen_at=first_seen,
    )
    listing_day_two = _make_listing(
        source_listing_id="42",
        rent_price=4300,
        first_seen_at=first_seen,
        last_seen_at=first_seen + timedelta(days=3),
    )

    assert upsert_listings([listing_day_one], db_path=db_path) == 1
    assert upsert_listings([listing_day_two], db_path=db_path) == 1

    observations = load_observations(db_path=db_path)
    assert len(observations) == 2
    # Sorted by (source, source_listing_id, observed_at) per SQL order.
    assert observations[0].rent_price == 4500
    assert observations[0].observed_at == first_seen
    assert observations[1].rent_price == 4300
    assert observations[1].days_on_market == 3


def test_upsert_idempotent_at_same_timestamp(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    seen = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    listing = _make_listing(
        source_listing_id="7",
        rent_price=4000,
        first_seen_at=seen,
        last_seen_at=seen,
    )

    assert upsert_listings([listing], db_path=db_path) == 1
    assert upsert_listings([listing], db_path=db_path) == 1

    observations = load_observations(db_path=db_path)
    assert len(observations) == 1


def test_record_crawl_run_inserts_and_returns_id(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"

    first_id = record_crawl_run(
        source="wellcee",
        url="https://www.wellcee.com/rent-apartment/shanghai",
        status_code=200,
        raw_path="/tmp/raw.html",
        db_path=db_path,
    )
    second_id = record_crawl_run(
        source="beike",
        url="https://sh.zu.ke.com/zufang",
        db_path=db_path,
    )

    assert isinstance(first_id, int) and first_id > 0
    assert second_id == first_id + 1

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT source, url, status_code, raw_path FROM crawl_runs ORDER BY id"
        ).fetchall()
    assert rows == [
        ("wellcee", "https://www.wellcee.com/rent-apartment/shanghai", 200, "/tmp/raw.html"),
        ("beike", "https://sh.zu.ke.com/zufang", None, None),
    ]


def test_init_db_enables_wal_mode(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    init_db(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_init_db_sets_user_version(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    init_db(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert version == CURRENT_SCHEMA_VERSION == 3


# Schema drift seen in real DBs before v2: listing_observations carried extra
# NOT NULL columns (source_url/payload_json) the writer never populated, so every
# INSERT OR IGNORE was silently dropped. The v2 migration must rebuild it.
_OLD_OBSERVATIONS_DDL = """
    CREATE TABLE listing_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_listing_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        crawl_run_id INTEGER,
        source_url TEXT NOT NULL,
        title TEXT NOT NULL,
        rent_price INTEGER,
        area_sqm REAL,
        district TEXT,
        community_name TEXT,
        availability_status TEXT NOT NULL,
        days_on_market INTEGER,
        payload_json TEXT NOT NULL,
        UNIQUE(source, source_listing_id, observed_at)
    )
"""


def test_migration_rebuilds_stale_observations_table(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    # Simulate a legacy DB: stale observations schema, wrongly stamped at v1.
    with sqlite3.connect(db_path) as connection:
        connection.execute(_OLD_OBSERVATIONS_DDL)
        connection.execute("PRAGMA user_version=1")

    init_db(db_path=db_path)  # should detect drift and rebuild

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(listing_observations)")}
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert "source_url" not in columns
    assert "payload_json" not in columns
    assert version == CURRENT_SCHEMA_VERSION

    # The actual bug: observations must now persist through upsert.
    seen = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    listing = _make_listing(
        source_listing_id="99",
        rent_price=4200,
        first_seen_at=seen,
        last_seen_at=seen,
    )
    assert upsert_listings([listing], db_path=db_path) == 1
    assert len(load_observations(db_path=db_path)) == 1


def test_migration_preserves_mappable_rows(tmp_path) -> None:
    db_path = tmp_path / "rentalscout.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(_OLD_OBSERVATIONS_DDL)
        connection.execute("PRAGMA user_version=1")
        connection.execute(
            """
            INSERT INTO listing_observations
              (source, source_listing_id, observed_at, source_url, title,
               rent_price, availability_status, payload_json)
            VALUES ('wellcee', '5', '2026-05-01T00:00:00+00:00',
                    'https://www.wellcee.com/x', '旧观测', 3900, 'active', '{}')
            """
        )

    init_db(db_path=db_path)

    observations = load_observations(db_path=db_path)
    assert len(observations) == 1
    assert observations[0].rent_price == 3900
    assert observations[0].source_listing_id == "5"