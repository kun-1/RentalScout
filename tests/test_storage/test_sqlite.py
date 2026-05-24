from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName
from rentalscout.storage.sqlite import load_listings, upsert_listings


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
