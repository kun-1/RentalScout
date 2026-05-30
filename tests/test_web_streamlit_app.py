import pandas as pd

from rentalscout.analysis.commute import Workplace
from rentalscout.web.streamlit_app import (
    DEFAULT_WEB_WORKPLACE,
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
