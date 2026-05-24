from rentalscout.filters import apply_phase1_filters
from rentalscout.schemas.normalized import NormalizedRentalListing
from rentalscout.schemas.raw import SourceName


def test_phase1_filter_accepts_matching_beike_listing() -> None:
    listing = NormalizedRentalListing(
        source=SourceName.BEIKE,
        source_listing_id="SH1",
        source_url="https://sh.zu.ke.com/zufang/SH1.html",
        title="整租·测试小区 1室1厅 南",
        rent_price=4500,
        district="浦东",
        layout="1室1厅",
    )

    result = apply_phase1_filters(listing)

    assert result.accepted


def test_phase1_filter_rejects_apartment() -> None:
    listing = NormalizedRentalListing(
        source=SourceName.BEIKE,
        source_listing_id="A1",
        source_url="https://sh.zu.ke.com/apartment/1.html",
        title="独栋·测试公寓 1室1厅",
        rent_price=4500,
        district="浦东",
    )

    result = apply_phase1_filters(listing)

    assert not result.accepted
    assert "疑似公寓或集中式房源" in result.reasons
