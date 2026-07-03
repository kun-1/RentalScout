import folium
import pandas as pd

from rentalscout.analysis.commute import Workplace
from rentalscout.web.streamlit_app import (
    DEFAULT_WEB_WORKPLACE,
    _build_folium_map,
    build_leaflet_map_html,
    distance_frame_uses_workplace,
    price_area_input_rows,
    workplace_from_distance_frame,
)


def test_workplace_from_distance_frame_reads_active_workplace() -> None:
    frame = pd.DataFrame(
        [
            {
                "workplace_id": "default-workplace",
                "workplace_name": "上海市浦东新区世纪公园",
                "workplace_longitude": 121.550909,
                "workplace_latitude": 31.215449,
            }
        ]
    )

    workplace = workplace_from_distance_frame(frame)

    assert workplace == Workplace(
        workplace_id="default-workplace",
        name="上海市浦东新区世纪公园",
        longitude=121.550909,
        latitude=31.215449,
    )


def test_builtin_default_workplace_is_pudong_library() -> None:
    assert Workplace(
        workplace_id="default-workplace",
        name="上海市浦东新区浦东图书馆",
        longitude=121.541527,
        latitude=31.191880,
    ) == DEFAULT_WEB_WORKPLACE


def test_distance_frame_uses_workplace_detects_stale_analysis() -> None:
    frame = pd.DataFrame(
        [
            {
                "workplace_id": "default-workplace",
                "workplace_name": "上海市浦东新区世纪公园",
                "workplace_longitude": 121.550909,
                "workplace_latitude": 31.215449,
            }
        ]
    )

    assert not distance_frame_uses_workplace(
        frame,
        Workplace(
            workplace_id="default-workplace",
            name="上海市静安区静安寺",
            longitude=121.445321,
            latitude=31.223083,
        ),
    )


def test_price_area_input_rows_keeps_current_distance_bucket() -> None:
    rows = [
        {
            "listing_id": "listing-1",
            "rent_price": 5000,
            "area_sqm": 38.5,
            "rent_per_sqm": 129.87,
            "distance_bucket": "within_4km",
            "apartment_like": False,
            "possible_duplicate": True,
        }
    ]

    inputs = price_area_input_rows(rows)

    assert inputs["listing-1"].distance_bucket == "within_4km"
    assert inputs["listing-1"].rent_per_sqm == 129.87
    assert inputs["listing-1"].possible_duplicate is True


def test_leaflet_map_html_contains_workplace_signature() -> None:
    frame = pd.DataFrame(
        [
            {
                "title": "工作中心: 上海市静安区静安寺",
                "latitude": 31.223505,
                "longitude": 121.445320,
                "marker_type": "workplace",
                "source_url": "",
                "fill_color": "#FF5A5F",
                "rent_text": "-",
                "area_text": "-",
                "rent_per_sqm_text": "-",
                "distance_text": "0 m",
                "distance_bucket": "workplace",
                "cluster_text": "workplace",
                "quality_text": "",
                "apartment_like": False,
                "value_level_text": "-",
            }
        ]
    )

    html = build_leaflet_map_html(frame)

    assert 'name="rentalscout-workplace"' in html
    assert "上海市静安区静安寺|121.445320,31.223505" in html
    assert "map.setView([workplacePoint.latitude, workplacePoint.longitude], 13)" in html


def test_build_folium_map_contains_marker_html() -> None:
    frame = pd.DataFrame(
        [
            {
                "title": "工作中心: 上海市浦东图书馆",
                "latitude": DEFAULT_WEB_WORKPLACE.latitude,
                "longitude": DEFAULT_WEB_WORKPLACE.longitude,
                "marker_type": "workplace",
                "source_url": "",
                "rent_text": "-",
                "area_text": "-",
                "rent_per_sqm_text": "-",
                "distance_text": "0 m",
                "distance_bucket": "workplace",
                "cluster_text": "workplace",
                "quality_text": "",
                "apartment_like": False,
                "value_level_text": "-",
                "card_login_text": "未知",
                "card_login_class": "rs-login-unknown",
                "card_price_text": "首次记录",
                "card_price_class": "rs-price-none",
            },
            {
                "title": "陆家嘴精装两室",
                "latitude": 31.240000,
                "longitude": 121.505000,
                "marker_type": "listing",
                "source_url": "https://example.com/listing/1",
                "rent_text": "6500 元/月",
                "area_text": "65.0 平米",
                "rent_per_sqm_text": "¥100.0/㎡",
                "distance_text": "3.2 km",
                "distance_bucket": "within_4km",
                "cluster_text": "陆家嘴",
                "quality_text": "ready",
                "apartment_like": False,
                "value_level_text": "高性价比",
                "card_login_text": "2026-06-30",
                "card_login_class": "rs-login-fresh",
                "card_price_text": "↓-200  6500→6300",
                "card_price_class": "rs-price-down",
            },
            {
                "title": "公寓整租",
                "latitude": 31.235000,
                "longitude": 121.510000,
                "marker_type": "listing",
                "source_url": "https://example.com/listing/2",
                "rent_text": "8000 元/月",
                "area_text": "40.0 平米",
                "rent_per_sqm_text": "¥200.0/㎡",
                "distance_text": "4.5 km",
                "distance_bucket": "4_to_8km",
                "cluster_text": "世纪公园",
                "quality_text": "caution",
                "apartment_like": True,
                "value_level_text": "低性价比",
                "card_login_text": "2025-09-01",
                "card_login_class": "rs-login-stale",
                "card_price_text": "↑+300  7700→8000",
                "card_price_class": "rs-price-up",
            },
        ]
    )

    fmap = _build_folium_map(frame)
    html = fmap.get_root().render()

    # Workplace pulse + the listing price-bubble are both present.
    assert "rs-workplace-pulse" in html
    assert "rs-price-bubble" in html
    # Card data (host login + price change) ends up in the marker popup HTML
    # that is bound to each marker; the inner HTML uses the row's rent_text.
    assert "6500 元/月" in html
    assert "8000 元/月" in html
    # The two cluster groups are registered in the rendered output.
    assert "MarkerCluster" in html
    # Distance circles + AMAP tile URL still wired.
    assert "autonavi.com" in html
    # Map type is folium.Map.
    assert isinstance(fmap, folium.Map)
