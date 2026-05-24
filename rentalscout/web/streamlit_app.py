"""RentalScout Streamlit 分析工作台。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from rentalscout.analysis.geo_clusters import (
    DEFAULT_CLUSTER_EPS_METERS,
    DEFAULT_CLUSTER_MIN_SAMPLES,
    DEFAULT_GEO_CLUSTER_CSV,
    DEFAULT_GEO_CLUSTER_SUMMARY_JSON,
    analyze_geo_clusters,
    generate_geo_cluster_outputs,
    summarize_geo_cluster_rows,
)
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings

ANALYSIS_DIR = DATA_DIR / "analysis"
QUALITY_CSV = ANALYSIS_DIR / "wellcee_quality.csv"
DISTANCE_CSV = ANALYSIS_DIR / "commute_distance_buckets.csv"
PRICE_AREA_CSV = ANALYSIS_DIR / "price_area_analysis.csv"
LOCATION_VALUE_CSV = ANALYSIS_DIR / "location_value_analysis.csv"
GEO_CLUSTER_CSV = ANALYSIS_DIR / "geo_clusters.csv"
WORKPLACE_MARKER_TITLE = "工作中心: 上海本冠医疗美容门诊部"

BOOLEAN_COLUMNS = {
    "has_price",
    "has_area",
    "has_location",
    "has_region",
    "has_layout",
    "has_images",
    "has_published_at",
    "has_listing_type",
    "has_duplicate_risk",
    "can_analyze_price",
    "can_analyze_area_price",
    "can_analyze_map",
    "can_analyze_commute",
    "can_analyze_region",
    "can_analyze_freshness",
    "can_analyze_duplicates",
    "area_outlier",
    "subdistrict_low_confidence",
    "apartment_like",
    "possible_duplicate",
    "missing_published_at",
    "coordinate_suspicious",
    "good_price",
    "good_area_price",
    "expensive",
    "area_price_expensive",
    "low_price_outlier",
    "high_price_outlier",
    "low_area_price_outlier",
    "high_area_price_outlier",
    "below_nearby_median",
    "nearby_good_value",
    "nearby_expensive",
    "below_community_median",
    "above_community_median",
    "best_price_in_community",
    "best_area_price_in_community",
    "is_geo_noise",
    "is_core_point",
}

BUCKET_LABELS = {
    "within_4km": "4km 以内",
    "4_to_8km": "4-8km",
    "8_to_12km": "8-12km",
    "over_12km": "12km 以外",
}


def main() -> None:
    """渲染 Streamlit 工作台。"""

    st.set_page_config(page_title="RentalScout 分析工作台", layout="wide")
    st.title("RentalScout 分析工作台")

    data = load_all_analysis()
    missing = missing_inputs(data)
    if missing:
        st.warning("以下分析文件暂未生成: " + "、".join(str(path) for path in missing))

    filters = render_sidebar(data)
    merged = merged_listing_frame(data)
    filtered = apply_listing_filters(merged, filters)

    render_overview(data, filtered)
    tabs = st.tabs(["地图", "质量", "距离", "价格面积", "位置价值", "经纬度聚类", "房源表"])
    with tabs[0]:
        render_map_tab(filtered, data["distance"])
    with tabs[1]:
        render_quality_tab(data["quality"], filtered)
    with tabs[2]:
        render_distance_tab(data["distance"], filtered)
    with tabs[3]:
        render_price_area_tab(data["price_area"], filtered)
    with tabs[4]:
        render_location_value_tab(data["location_value"], filtered)
    with tabs[5]:
        render_geo_cluster_tab(data["geo_cluster"])
    with tabs[6]:
        render_listing_table(filtered)


@st.cache_data(show_spinner=False)
def read_csv(path: Path) -> pd.DataFrame:
    """读取 CSV, 并做轻量类型修正。"""

    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    for column in BOOLEAN_COLUMNS.intersection(frame.columns):
        frame[column] = frame[column].map(_to_bool)
    return frame


def load_all_analysis() -> dict[str, pd.DataFrame]:
    """加载当前所有分析输出。"""

    return {
        "quality": read_csv(QUALITY_CSV),
        "distance": read_csv(DISTANCE_CSV),
        "price_area": read_csv(PRICE_AREA_CSV),
        "location_value": read_csv(LOCATION_VALUE_CSV),
        "geo_cluster": read_csv(GEO_CLUSTER_CSV),
    }


def missing_inputs(data: dict[str, pd.DataFrame]) -> list[Path]:
    paths = {
        "quality": QUALITY_CSV,
        "distance": DISTANCE_CSV,
        "price_area": PRICE_AREA_CSV,
        "location_value": LOCATION_VALUE_CSV,
        "geo_cluster": GEO_CLUSTER_CSV,
    }
    return [path for key, path in paths.items() if data[key].empty]


def render_sidebar(data: dict[str, pd.DataFrame]) -> dict[str, object]:
    """渲染全局筛选器。"""

    st.sidebar.header("筛选")
    quality = data["quality"]
    price_area = data["price_area"]
    distance = data["distance"]
    geo_cluster = data["geo_cluster"]

    max_price = int(_max_or_default(quality, "rent_price", 6000))
    price_range = st.sidebar.slider("租金", 0, max(max_price, 6000), (3500, min(6000, max_price)))
    max_area = int(_max_or_default(quality, "area_sqm", 120))
    area_range = st.sidebar.slider("面积", 0, max(max_area, 120), (10, min(max_area, 120)))

    bucket_options = sorted(
        value for value in distance.get("distance_bucket", pd.Series(dtype=str)).dropna().unique()
    )
    selected_buckets = st.sidebar.multiselect(
        "距离分桶",
        options=bucket_options,
        default=bucket_options,
        format_func=lambda value: BUCKET_LABELS.get(value, value),
    )

    tier_options = sorted(
        value for value in quality.get("analysis_tier", pd.Series(dtype=str)).dropna().unique()
    )
    selected_tiers = st.sidebar.multiselect("质量层级", tier_options, default=tier_options)

    cluster_options = sorted(
        value
        for value in geo_cluster.get("geo_cluster_id", pd.Series(dtype=str)).dropna().unique()
        if value != "noise"
    )
    selected_clusters = st.sidebar.multiselect("空间簇", cluster_options, default=[])

    st.sidebar.divider()
    exclude_apartment = st.sidebar.checkbox("排除疑似公寓", value=False)
    exclude_duplicates = st.sidebar.checkbox("排除重复候选", value=False)
    only_good_value = st.sidebar.checkbox("只看附近低单价", value=False)
    only_good_price = st.sidebar.checkbox("只看同距离低租金", value=False)

    if not price_area.empty:
        rent_per_sqm_max = int(_max_or_default(price_area, "rent_per_sqm", 300))
        rent_per_sqm_range = st.sidebar.slider(
            "单位面积租金",
            0,
            max(rent_per_sqm_max, 300),
            (0, min(rent_per_sqm_max, 300)),
        )
    else:
        rent_per_sqm_range = (0, 300)

    return {
        "price_range": price_range,
        "area_range": area_range,
        "rent_per_sqm_range": rent_per_sqm_range,
        "distance_buckets": selected_buckets,
        "analysis_tiers": selected_tiers,
        "geo_clusters": selected_clusters,
        "exclude_apartment": exclude_apartment,
        "exclude_duplicates": exclude_duplicates,
        "only_good_value": only_good_value,
        "only_good_price": only_good_price,
    }


def merged_listing_frame(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把各分析层按房源 ID 合并成前端消费表。"""

    quality = data["quality"].rename(columns={"source_listing_id": "listing_id"}).copy()
    if quality.empty:
        return pd.DataFrame()
    merged = quality
    merge_specs = [
        (
            data["distance"],
            [
                "listing_id",
                "straight_distance_meters",
                "distance_bucket",
                "listing_longitude",
                "listing_latitude",
            ],
        ),
        (
            data["price_area"],
            [
                "listing_id",
                "rent_per_sqm",
                "bucket_price_median",
                "bucket_rent_per_sqm_median",
                "price_delta_from_bucket_median",
                "rent_per_sqm_delta_from_bucket_median",
                "good_price",
                "good_area_price",
                "expensive",
                "area_price_expensive",
                "low_price_outlier",
                "high_price_outlier",
                "low_area_price_outlier",
                "high_area_price_outlier",
            ],
        ),
        (
            data["location_value"],
            [
                "listing_id",
                "nearby_sample_size",
                "nearby_price_median",
                "nearby_rent_per_sqm_median",
                "below_nearby_median",
                "nearby_good_value",
                "nearby_expensive",
            ],
        ),
        (
            data["geo_cluster"],
            [
                "listing_id",
                "geo_cluster_id",
                "geo_cluster_size",
                "is_geo_noise",
                "is_core_point",
                "neighbor_count",
                "cluster_centroid_longitude",
                "cluster_centroid_latitude",
            ],
        ),
    ]
    for frame, columns in merge_specs:
        if not frame.empty:
            available = [
                column
                for column in columns
                if column in frame.columns and (column == "listing_id" or column not in merged)
            ]
            merged = merged.merge(frame[available], how="left", on="listing_id")
    if "latitude" not in merged.columns and "listing_latitude" in merged.columns:
        merged["latitude"] = merged["listing_latitude"]
    if "longitude" not in merged.columns and "listing_longitude" in merged.columns:
        merged["longitude"] = merged["listing_longitude"]
    return merged


def apply_listing_filters(frame: pd.DataFrame, filters: dict[str, object]) -> pd.DataFrame:
    """应用全局筛选。"""

    if frame.empty:
        return frame
    filtered = frame.copy()
    price_min, price_max = filters["price_range"]
    area_min, area_max = filters["area_range"]
    rent_per_sqm_min, rent_per_sqm_max = filters["rent_per_sqm_range"]
    filtered = filtered[
        filtered["rent_price"].between(price_min, price_max, inclusive="both")
        & filtered["area_sqm"].between(area_min, area_max, inclusive="both")
    ]
    if "rent_per_sqm" in filtered.columns:
        filtered = filtered[
            filtered["rent_per_sqm"].between(
                rent_per_sqm_min,
                rent_per_sqm_max,
                inclusive="both",
            )
        ]
    if filters["distance_buckets"] and "distance_bucket" in filtered.columns:
        filtered = filtered[filtered["distance_bucket"].isin(filters["distance_buckets"])]
    if filters["analysis_tiers"] and "analysis_tier" in filtered.columns:
        filtered = filtered[filtered["analysis_tier"].isin(filters["analysis_tiers"])]
    if filters["geo_clusters"] and "geo_cluster_id" in filtered.columns:
        filtered = filtered[filtered["geo_cluster_id"].isin(filters["geo_clusters"])]
    if filters["exclude_apartment"] and "apartment_like" in filtered.columns:
        filtered = filtered[~filtered["apartment_like"].fillna(False)]
    if filters["exclude_duplicates"] and "possible_duplicate" in filtered.columns:
        filtered = filtered[~filtered["possible_duplicate"].fillna(False)]
    if filters["only_good_value"] and "nearby_good_value" in filtered.columns:
        filtered = filtered[filtered["nearby_good_value"].fillna(False)]
    if filters["only_good_price"] and "good_price" in filtered.columns:
        filtered = filtered[filtered["good_price"].fillna(False)]
    return filtered


def render_overview(data: dict[str, pd.DataFrame], filtered: pd.DataFrame) -> None:
    quality = data["quality"]
    geo_cluster = data["geo_cluster"]
    columns = st.columns(5)
    columns[0].metric("当前筛选", len(filtered))
    columns[1].metric("质量样本", len(quality))
    columns[2].metric("Ready", _count_value(quality, "analysis_tier", "ready"))
    cluster_count = geo_cluster["geo_cluster_id"].nunique() if not geo_cluster.empty else 0
    columns[3].metric("空间簇", cluster_count)
    columns[4].metric(
        "离群点",
        int(geo_cluster["is_geo_noise"].sum()) if "is_geo_noise" in geo_cluster else 0,
    )


def render_map_tab(frame: pd.DataFrame, distance: pd.DataFrame) -> None:
    st.subheader("地图视图")
    map_frame = frame.dropna(subset=["latitude", "longitude"]).copy()
    map_frame["marker_type"] = "listing"
    workplace = workplace_marker(distance)
    if workplace:
        map_frame = pd.concat([map_frame, pd.DataFrame([workplace])], ignore_index=True)
    if map_frame.empty:
        st.info("没有可用于地图展示的坐标。")
        return
    map_frame["radius"] = map_frame["marker_type"].map({"workplace": 260}).fillna(70)
    map_frame["fill_color"] = map_frame.apply(_map_color, axis=1)
    map_frame["rent_text"] = map_frame["rent_price"].map(_money_text)
    map_frame["area_text"] = map_frame["area_sqm"].map(_area_text)
    map_frame["rent_per_sqm_text"] = map_frame["rent_per_sqm"].map(_rent_per_sqm_text)
    map_frame["distance_text"] = map_frame["straight_distance_meters"].map(_distance_text)
    map_frame["cluster_text"] = map_frame["geo_cluster_id"].fillna("")
    map_frame["url_text"] = map_frame["source_url"].fillna("")
    st.caption("红色大点为工作中心; 绿色为附近低单价房源, 红色小点为附近高单价房源。")
    st.pydeck_chart(
        pdk.Deck(
            initial_view_state=_map_view_state(map_frame),
            layers=[
                pdk.Layer(
                    "ScatterplotLayer",
                    data=map_frame,
                    get_position="[longitude, latitude]",
                    get_radius="radius",
                    get_fill_color="fill_color",
                    get_line_color=[255, 255, 255, 220],
                    line_width_min_pixels=1,
                    pickable=True,
                    opacity=0.86,
                    stroked=True,
                    filled=True,
                )
            ],
            tooltip={
                "html": (
                    "<div style='max-width:280px'>"
                    "<b>{title}</b><br/>"
                    "租金: {rent_text}<br/>"
                    "面积: {area_text}<br/>"
                    "单价: {rent_per_sqm_text}<br/>"
                    "距离: {distance_text}<br/>"
                    "空间簇: {cluster_text}<br/>"
                    "<span style='font-size:11px'>{url_text}</span>"
                    "</div>"
                ),
                "style": {
                    "backgroundColor": "rgba(17, 24, 39, 0.92)",
                    "color": "white",
                    "fontSize": "13px",
                    "lineHeight": "1.45",
                },
            },
            map_style=None,
        ),
        height=720,
    )


def render_quality_tab(quality: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("数据质量")
    if quality.empty:
        st.info("缺少质量分析输出。")
        return
    columns = st.columns(4)
    columns[0].metric("ready", _count_value(quality, "analysis_tier", "ready"))
    columns[1].metric("caution", _count_value(quality, "analysis_tier", "caution"))
    columns[2].metric("blocked", _count_value(quality, "analysis_tier", "blocked"))
    columns[3].metric("当前筛选 blocked", _count_value(filtered, "analysis_tier", "blocked"))
    st.bar_chart(quality["analysis_tier"].value_counts())
    risk_columns = [
        "area_outlier",
        "subdistrict_low_confidence",
        "apartment_like",
        "possible_duplicate",
        "missing_published_at",
        "coordinate_suspicious",
    ]
    risk_counts = {
        column: int(quality[column].sum())
        for column in risk_columns
        if column in quality.columns
    }
    st.bar_chart(pd.Series(risk_counts, name="count"))


def render_distance_tab(distance: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("工作地点直线距离")
    if distance.empty:
        st.info("缺少距离分桶输出。")
        return
    st.bar_chart(distance["distance_bucket"].map(BUCKET_LABELS).value_counts())
    st.dataframe(
        _display_columns(
            filtered,
            [
                "title",
                "rent_price",
                "area_sqm",
                "straight_distance_meters",
                "distance_bucket",
                "source_url",
            ],
        ),
        width="stretch",
        hide_index=True,
    )


def render_price_area_tab(price_area: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("价格与单位面积租金")
    if price_area.empty:
        st.info("缺少价格面积分析输出。")
        return
    columns = st.columns(4)
    columns[0].metric("低租金", int(price_area["good_price"].sum()))
    columns[1].metric("低单价", int(price_area["good_area_price"].sum()))
    columns[2].metric("高租金", int(price_area["expensive"].sum()))
    columns[3].metric("高单价", int(price_area["area_price_expensive"].sum()))
    chart_source = filtered.dropna(subset=["rent_price", "rent_per_sqm"])
    st.scatter_chart(chart_source, x="area_sqm", y="rent_price", color="rent_per_sqm")
    st.dataframe(
        _display_columns(
            filtered,
            [
                "title",
                "rent_price",
                "area_sqm",
                "rent_per_sqm",
                "price_delta_from_bucket_median",
                "rent_per_sqm_delta_from_bucket_median",
                "good_price",
                "good_area_price",
                "source_url",
            ],
        ),
        width="stretch",
        hide_index=True,
    )


def render_location_value_tab(location_value: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("附近房源价值比较")
    if location_value.empty:
        st.info("缺少位置价值分析输出。")
        return
    columns = st.columns(3)
    columns[0].metric("附近低租金", int(location_value["below_nearby_median"].sum()))
    columns[1].metric("附近低单价", int(location_value["nearby_good_value"].sum()))
    columns[2].metric("附近高单价", int(location_value["nearby_expensive"].sum()))
    st.scatter_chart(
        filtered.dropna(subset=["nearby_sample_size", "rent_per_sqm"]),
        x="nearby_sample_size",
        y="rent_per_sqm",
        color="straight_distance_meters",
    )
    st.dataframe(
        _display_columns(
            filtered,
            [
                "title",
                "rent_price",
                "rent_per_sqm",
                "nearby_sample_size",
                "nearby_price_median",
                "nearby_rent_per_sqm_median",
                "below_nearby_median",
                "nearby_good_value",
                "nearby_expensive",
                "source_url",
            ],
        ),
        width="stretch",
        hide_index=True,
    )


def render_geo_cluster_tab(saved_geo_cluster: pd.DataFrame) -> None:
    st.subheader("经纬度聚类")
    eps_meters = st.slider("聚类半径", 100, 1500, DEFAULT_CLUSTER_EPS_METERS, step=50)
    min_samples = st.slider("最小样本数", 2, 20, DEFAULT_CLUSTER_MIN_SAMPLES, step=1)

    rows, summary = run_geo_cluster_preview(eps_meters, min_samples)
    preview = pd.DataFrame([asdict_like(row) for row in rows])

    columns = st.columns(4)
    columns[0].metric("空间簇", summary["cluster_count"])
    columns[1].metric("已聚类", summary["clustered_listings"])
    columns[2].metric("离群点", summary["noise_listings"])
    columns[3].metric("最大簇", summary["cluster_size"]["largest"])

    if st.button("保存当前聚类参数到分析文件"):
        generate_geo_cluster_outputs(
            db_path=DEFAULT_DB_PATH,
            csv_path=DEFAULT_GEO_CLUSTER_CSV,
            summary_path=DEFAULT_GEO_CLUSTER_SUMMARY_JSON,
            eps_meters=eps_meters,
            min_samples=min_samples,
        )
        read_csv.clear()
        st.success("已保存聚类分析输出。")

    if not saved_geo_cluster.empty:
        current_params = (
            int(saved_geo_cluster["eps_meters"].iloc[0]),
            int(saved_geo_cluster["min_samples"].iloc[0]),
        )
        st.caption(f"当前文件参数: {current_params[0]} 米 / {current_params[1]} 样本")

    st.bar_chart(preview["geo_cluster_id"].value_counts().head(20))
    st.dataframe(
        _display_columns(
            preview,
            [
                "title",
                "rent_price",
                "area_sqm",
                "geo_cluster_id",
                "geo_cluster_size",
                "is_geo_noise",
                "is_core_point",
                "neighbor_count",
                "distance_to_cluster_centroid_meters",
                "source_url",
            ],
        ),
        width="stretch",
        hide_index=True,
    )


@st.cache_data(show_spinner="正在重新计算经纬度聚类...")
def run_geo_cluster_preview(
    eps_meters: int,
    min_samples: int,
) -> tuple[list[object], dict[str, object]]:
    listings = load_listings(DEFAULT_DB_PATH)
    rows = analyze_geo_clusters(listings, eps_meters=eps_meters, min_samples=min_samples)
    summary = summarize_geo_cluster_rows(rows, eps_meters=eps_meters, min_samples=min_samples)
    return rows, summary


def render_listing_table(frame: pd.DataFrame) -> None:
    st.subheader("房源明细")
    if frame.empty:
        st.info("没有符合筛选条件的房源。")
        return
    st.dataframe(
        _display_columns(
            frame,
            [
                "title",
                "rent_price",
                "area_sqm",
                "rent_per_sqm",
                "analysis_tier",
                "distance_bucket",
                "straight_distance_meters",
                "geo_cluster_id",
                "geo_cluster_size",
                "nearby_good_value",
                "apartment_like",
                "possible_duplicate",
                "quality_notes",
                "source_url",
            ],
        ),
        width="stretch",
        hide_index=True,
    )


def _display_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    available = [column for column in columns if column in frame.columns]
    return frame[available].copy()


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).lower() == "true"


def _max_or_default(frame: pd.DataFrame, column: str, default: int) -> float:
    if frame.empty or column not in frame.columns:
        return float(default)
    value = frame[column].max()
    if pd.isna(value):
        return float(default)
    return float(value)


def _count_value(frame: pd.DataFrame, column: str, value: object) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column] == value).sum())


def _map_color(row: pd.Series) -> list[int]:
    if row.get("marker_type") == "workplace":
        return [239, 68, 68, 245]
    if bool(row.get("nearby_good_value", False)):
        return [22, 163, 74, 220]
    if bool(row.get("nearby_expensive", False)):
        return [220, 38, 38, 220]
    if bool(row.get("is_geo_noise", False)):
        return [107, 114, 128, 200]
    return [37, 99, 235, 210]


def _map_view_state(frame: pd.DataFrame) -> pdk.ViewState:
    return pdk.ViewState(
        latitude=float(frame["latitude"].mean()),
        longitude=float(frame["longitude"].mean()),
        zoom=10.7,
        pitch=0,
    )


def _money_text(value: object) -> str:
    if pd.isna(value):
        return "-"
    return f"{int(float(value))} 元/月"


def _area_text(value: object) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.1f} 平米"


def _rent_per_sqm_text(value: object) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.1f} 元/平米/月"


def _distance_text(value: object) -> str:
    if pd.isna(value):
        return "-"
    meters = float(value)
    if meters >= 1_000:
        return f"{meters / 1_000:.1f} km"
    return f"{int(meters)} m"


def workplace_marker(distance: pd.DataFrame) -> dict[str, object] | None:
    """从距离分析输出中取工作地点坐标。"""

    required = {"workplace_longitude", "workplace_latitude"}
    if distance.empty or not required.issubset(distance.columns):
        return None
    first = distance.dropna(subset=["workplace_longitude", "workplace_latitude"]).head(1)
    if first.empty:
        return None
    row = first.iloc[0]
    return {
        "title": WORKPLACE_MARKER_TITLE,
        "latitude": float(row["workplace_latitude"]),
        "longitude": float(row["workplace_longitude"]),
        "rent_price": None,
        "area_sqm": None,
        "rent_per_sqm": None,
        "distance_bucket": "workplace",
        "straight_distance_meters": 0,
        "geo_cluster_id": "workplace",
        "geo_cluster_size": None,
        "nearby_good_value": False,
        "source_url": "",
        "marker_type": "workplace",
    }


def asdict_like(row: object) -> dict[str, object]:
    if hasattr(row, "__dataclass_fields__"):
        return {field: getattr(row, field) for field in row.__dataclass_fields__}
    return dict(row)


if __name__ == "__main__":
    main()
