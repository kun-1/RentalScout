from rentalscout.wellcee_api import api_item_to_partial


def test_api_item_to_partial_returns_canonical_url() -> None:
    partial = api_item_to_partial(
        {
            "id": "1776264233300648",
            "address": "Pudong 梅园三街坊",
            "rent": "4800 RMB/月",
            "district": "Pudong",
            "latitude": 31.2,
            "longitude": 121.5,
            "imgs": ["https://example.com/a.jpg"],
            "tags": ["近地铁"],
        }
    )

    assert partial is not None
    assert partial["listing_id"] == "1776264233300648"
    assert partial["rent_price"] == 4800
    assert partial["district"] == "浦东"
    assert partial["title"] == "浦东 梅园三街坊"
    assert partial["latitude"] == 31.2
    assert partial["longitude"] == 121.5
