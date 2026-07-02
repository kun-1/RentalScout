from rentalscout.wellcee_api import _parse_login_time, api_item_to_partial


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


def test_parse_login_time_int_and_string_and_none() -> None:
    from datetime import UTC, datetime
    got_int = _parse_login_time(1782971822)
    got_str = _parse_login_time("1782971822")
    got_none = _parse_login_time(None)
    assert isinstance(got_int, datetime) and got_int.tzinfo == UTC
    assert got_int == got_str
    assert got_none is None
