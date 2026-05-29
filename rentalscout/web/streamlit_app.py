"""RentalScout Streamlit 分析工作台。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

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
AMAP_BASE_URL = (
    "https://wprd01.is.autonavi.com/appmaptile?"
    "x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=2&style=8"
)

AMAP_LABEL_URL = (
    "https://wprd01.is.autonavi.com/appmaptile?"
    "x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=8"
)

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
BUCKET_ORDER = ["within_4km", "4_to_8km", "8_to_12km", "over_12km"]
TIER_ORDER = ["ready", "caution", "blocked"]


def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&display=swap');

        html, body, [class*="css"], .stApp {
            font-family: 'Satoshi', system-ui, sans-serif !important;
        }
        .stApp > header { background: transparent !important; }
        .stDeployButton { display: none; }
        h1 {
            font-size: 1.5rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.025em !important;
            color: #28251d !important;
        }
        h2, h3 {
            font-size: 1.05rem !important;
            font-weight: 600 !important;
            color: #28251d !important;
        }
        [data-testid="metric-container"] {
            background: #ffffff !important;
            border: 1px solid rgba(0, 0, 0, 0.08) !important;
            border-radius: 10px !important;
            padding: 1rem 1.25rem !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.75rem !important;
            font-weight: 700 !important;
            font-variant-numeric: tabular-nums lining-nums !important;
            color: #28251d !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
            font-weight: 500 !important;
            color: #7a7974 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.04em !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.75rem !important;
            font-variant-numeric: tabular-nums !important;
        }
        button[data-baseweb="tab"] {
            font-size: 0.875rem !important;
            font-weight: 500 !important;
            color: #7a7974 !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #01696f !important;
            font-weight: 600 !important;
        }
        [data-baseweb="tab-highlight"] {
            background-color: #01696f !important;
        }
        [data-baseweb="tab-border"] {
            background-color: #dcd9d5 !important;
        }
        [data-testid="stSidebar"] {
            background-color: #f0eeea !important;
            border-right: 1px solid #dcd9d5 !important;
        }
        [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
            font-size: 0.7rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
            color: #7a7974 !important;
        }
        [data-testid="stSidebar"] .stCheckbox label {
            font-size: 0.875rem !important;
        }
        .stButton > button {
            background-color: #01696f !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            font-size: 0.875rem !important;
            padding: 0.5rem 1.25rem !important;
            transition: background-color 150ms ease !important;
        }
        .stButton > button:hover { background-color: #0c4e54 !important; }
        .stButton > button:active { background-color: #0f3638 !important; }
        [data-testid="stDataFrame"] {
            border-radius: 8px !important;
            overflow: hidden !important;
            border: 1px solid rgba(0, 0, 0, 0.08) !important;
        }
        [data-testid="stDataFrame"] table {
            font-size: 0.8125rem !important;
            font-variant-numeric: tabular-nums lining-nums !important;
        }
        [data-testid="stWarning"] {
            background-color: #fdf6ee !important;
            border-color: #d19900 !important;
            border-radius: 8px !important;
        }
        [data-testid="stInfo"] {
            background-color: #eef6f6 !important;
            border-color: #01696f !important;
            border-radius: 8px !important;
        }
        [data-testid="stSlider"] [role="slider"] { background-color: #01696f !important; }
        .stSlider [data-baseweb="slider"] [data-testid="stTickBarMin"],
        .stSlider [data-baseweb="slider"] [data-testid="stTickBarMax"] {
            font-size: 0.75rem !important;
            color: #7a7974 !important;
        }
        [data-testid="stNumberInput"] input {
            font-variant-numeric: tabular-nums !important;
            font-size: 0.875rem !important;
        }
        [data-testid="stCaptionContainer"] {
            font-size: 0.75rem !important;
            color: #7a7974 !important;
        }
        hr { border-color: #dcd9d5 !important; margin: 1.25rem 0 !important; }
        [data-testid="stSuccess"] {
            background-color: #edf5e9 !important;
            border-color: #437a22 !important;
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="RentalScout 分析工作台",
        page_icon="🏠",
        layout="wide",
    )
    inject_custom_css()

    col_title, col_desc = st.columns([3, 1])
    with col_title:
        st.title("RentalScout 分析工作台")
    with col_desc:
        st.markdown(
            "<p style='text-align:right; color:#7a7974; font-size:0.75rem; "
            "padding-top:1.2rem;'>上海租房数据 · 实时分析</p>",
            unsafe_allow_html=True,
        )

    data = load_all_analysis()
    missing = missing_inputs(data)
    if missing:
        st.warning("以下分析文件暂未生成: " + "、".join(str(path) for path in missing))

    filters = render_sidebar(data)
    merged = merged_listing_frame(data)
    filtered = apply_listing_filters(merged, filters)

    render_overview(data, filtered)
    tabs = st.tabs(
        ["🗺 地图", "📊 质量", "📍 距离", "💰 价格面积", "📌 位置价值", "🔵 经纬度聚类", "📋 房源表"]
    )
    with tabs[0]:
        render_map_tab(filtered, data["distance"], filters)
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


def _bounded_range_inputs(
    label: str,
    *,
    min_allowed: int,
    max_allowed: int,
    default_min: int,
    default_max: int,
    step: int,
    suffix: str,
) -> tuple[int, int]:
    """渲染带上下限保护的范围输入。"""

    st.sidebar.caption(f"{label} ({min_allowed}-{max_allowed} {suffix})")
    left, right = st.sidebar.columns(2)
    lower = left.number_input(
        "最小值",
        min_value=min_allowed,
        max_value=max_allowed,
        value=max(min_allowed, min(default_min, max_allowed)),
        step=step,
        key=f"{label}_min",
        label_visibility="collapsed",
    )
    upper = right.number_input(
        "最大值",
        min_value=min_allowed,
        max_value=max_allowed,
        value=max(min_allowed, min(default_max, max_allowed)),
        step=step,
        key=f"{label}_max",
        label_visibility="collapsed",
    )
    low = int(min(lower, upper))
    high = int(max(lower, upper))
    return low, high


def _sidebar_multi_pills(
    label: str,
    *,
    options: list[str],
    default: list[str],
    format_func: object,
) -> list[str]:
    """优先使用 pill 风格多选, 兼容旧版 Streamlit。"""

    pills = getattr(st.sidebar, "pills", None)
    if pills is None:
        return st.sidebar.multiselect(
            label,
            options=options,
            default=default,
            format_func=format_func,
        )
    selected = pills(
        label,
        options=options,
        default=default,
        format_func=format_func,
        selection_mode="multi",
    )
    return list(selected)


def _tier_label(value: str) -> str:
    labels = {
        "ready": "Ready",
        "caution": "Caution",
        "blocked": "Blocked",
    }
    return labels.get(value, value)


def render_sidebar(data: dict[str, pd.DataFrame]) -> dict[str, object]:
    """渲染全局筛选器。"""

    st.sidebar.header("筛选")
    quality = data["quality"]
    price_area = data["price_area"]
    distance = data["distance"]
    geo_cluster = data["geo_cluster"]

    st.sidebar.subheader("数值范围")
    max_price = max(int(_max_or_default(quality, "rent_price", 6000)), 6000)
    max_area = max(int(_max_or_default(quality, "area_sqm", 120)), 120)
    max_rent_per_sqm = max(int(_max_or_default(price_area, "rent_per_sqm", 300)), 300)
    price_range = _bounded_range_inputs(
        "租金",
        min_allowed=0,
        max_allowed=max_price,
        default_min=3500,
        default_max=min(6000, max_price),
        step=100,
        suffix="元/月",
    )
    area_range = _bounded_range_inputs(
        "面积",
        min_allowed=0,
        max_allowed=max_area,
        default_min=10,
        default_max=min(120, max_area),
        step=5,
        suffix="平米",
    )
    rent_per_sqm_range = _bounded_range_inputs(
        "单位面积租金",
        min_allowed=0,
        max_allowed=max_rent_per_sqm,
        default_min=0,
        default_max=min(300, max_rent_per_sqm),
        step=5,
        suffix="元/平米/月",
    )

    st.sidebar.subheader("分类筛选")
    available_buckets = set(distance.get("distance_bucket", pd.Series(dtype=str)).dropna().unique())
    bucket_options = [value for value in BUCKET_ORDER if value in available_buckets]
    selected_buckets = _sidebar_multi_pills(
        "距离分桶",
        options=bucket_options,
        default=bucket_options,
        format_func=lambda value: BUCKET_LABELS.get(value, value),
    )

    available_tiers = set(quality.get("analysis_tier", pd.Series(dtype=str)).dropna().unique())
    tier_options = [value for value in TIER_ORDER if value in available_tiers]
    selected_tiers = _sidebar_multi_pills(
        "质量层级",
        options=tier_options,
        default=tier_options,
        format_func=_tier_label,
    )

    cluster_options = sorted(
        value
        for value in geo_cluster.get("geo_cluster_id", pd.Series(dtype=str)).dropna().unique()
        if value != "noise"
    )
    cluster_labels = cluster_label_map(geo_cluster, quality)
    selected_clusters = st.sidebar.multiselect(
        "空间簇",
        cluster_options,
        default=[],
        format_func=lambda value: cluster_labels.get(value, value),
        placeholder="选择空间区域",
    )

    st.sidebar.divider()
    st.sidebar.subheader("偏好")
    value_weights = render_value_weight_controls()
    exclude_apartment = st.sidebar.checkbox("排除疑似公寓", value=False)
    exclude_duplicates = st.sidebar.checkbox("排除重复候选", value=False)
    only_good_value = st.sidebar.checkbox("只看附近低单价", value=False)
    only_good_price = st.sidebar.checkbox("只看同距离低租金", value=False)

    return {
        "price_range": price_range,
        "area_range": area_range,
        "rent_per_sqm_range": rent_per_sqm_range,
        "distance_buckets": selected_buckets,
        "distance_filter_active": set(selected_buckets) != set(bucket_options),
        "analysis_tiers": selected_tiers,
        "geo_clusters": selected_clusters,
        "exclude_apartment": exclude_apartment,
        "exclude_duplicates": exclude_duplicates,
        "only_good_value": only_good_value,
        "only_good_price": only_good_price,
        "value_weights": value_weights,
    }


def render_value_weight_controls() -> dict[str, int]:
    """渲染动态性价比权重控制。"""

    with st.sidebar.expander("性价比权重", expanded=False):
        area_weight = st.slider("面积", 0, 100, 45, step=5)
        distance_weight = st.slider("距离", 0, 100, 35, step=5)
        money_weight = st.slider("金钱", 0, 100, 20, step=5)
        total = area_weight + distance_weight + money_weight
        if total == 0:
            st.caption("三个权重不能同时为 0, 当前会按等权计算。")
        else:
            st.caption(
                f"当前比例: 面积 {area_weight / total:.0%}, "
                f"距离 {distance_weight / total:.0%}, 金钱 {money_weight / total:.0%}"
            )
    return {
        "area": area_weight,
        "distance": distance_weight,
        "money": money_weight,
    }


def cluster_label_map(geo_cluster: pd.DataFrame, quality: pd.DataFrame) -> dict[str, str]:
    """为空间簇生成面向人的区域名称。"""

    if geo_cluster.empty or quality.empty:
        return {}
    quality_names = quality.rename(columns={"source_listing_id": "listing_id"})
    columns = [
        column
        for column in ["listing_id", "subdistrict", "community_name", "title"]
        if column in quality_names.columns
    ]
    if "listing_id" not in columns:
        return {}
    merged = geo_cluster.merge(quality_names[columns], how="left", on="listing_id")
    labels: dict[str, str] = {}
    for cluster_id, group in merged.groupby("geo_cluster_id"):
        if not isinstance(cluster_id, str) or cluster_id == "noise":
            continue
        size = int(group["listing_id"].count())
        area_name = _best_cluster_area_name(group)
        labels[cluster_id] = f"{area_name}区域 ({size}套, {cluster_id})"
    return labels


def _best_cluster_area_name(group: pd.DataFrame) -> str:
    for column in ["subdistrict", "community_name", "title"]:
        if column not in group.columns:
            continue
        names = [
            str(value).strip()
            for value in group[column].dropna()
            if str(value).strip() and str(value).strip().lower() != "nan"
        ]
        if names:
            return Counter(names).most_common(1)[0][0]
    return "未命名"


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
    if (
        filters.get("distance_filter_active")
        and filters["distance_buckets"]
        and "distance_bucket" in filtered.columns
    ):
        filtered = filtered[filtered["distance_bucket"].isin(filters["distance_buckets"])]
    if "analysis_tier" in filtered.columns:
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

    st.markdown(
        "<p style='font-size:0.75rem; color:#7a7974; margin-bottom:0.25rem;'>当前数据概览</p>",
        unsafe_allow_html=True,
    )

    columns = st.columns(5)
    columns[0].metric("筛选后房源", len(filtered))
    columns[1].metric("质量样本总量", len(quality))
    columns[2].metric("Ready 层级", _count_value(quality, "analysis_tier", "ready"))
    cluster_count = geo_cluster["geo_cluster_id"].nunique() if not geo_cluster.empty else 0
    columns[3].metric("空间簇数量", cluster_count)
    columns[4].metric(
        "地理离群点",
        int(geo_cluster["is_geo_noise"].sum()) if "is_geo_noise" in geo_cluster else 0,
    )

    st.markdown(
        "<hr style='margin: 0.75rem 0 1.25rem; border-color: #dcd9d5;'>",
        unsafe_allow_html=True,
    )


def render_map_tab(
    frame: pd.DataFrame,
    distance: pd.DataFrame,
    filters: dict[str, object],
) -> None:
    st.subheader("地图视图")
    missing_coordinate = frame[["latitude", "longitude"]].isna().any(axis=1)
    suspicious_coordinate = (
        frame["coordinate_suspicious"].fillna(False)
        if "coordinate_suspicious" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    hidden_coordinate_count = int((missing_coordinate | suspicious_coordinate).sum())
    map_frame = frame[~missing_coordinate & ~suspicious_coordinate].copy()
    map_frame["marker_type"] = "listing"
    map_frame = add_value_scores(map_frame, filters["value_weights"])
    workplace = workplace_marker(distance)
    if workplace:
        map_frame = pd.concat([map_frame, pd.DataFrame([workplace])], ignore_index=True)
    if map_frame.empty:
        st.info("没有可用于地图展示的坐标。")
        if hidden_coordinate_count:
            st.warning(f"{hidden_coordinate_count} 条房源无可用上海坐标, 已从地图中隐藏。")
        return
    map_frame = ensure_map_value_columns(map_frame)
    map_frame["fill_color"] = map_frame.apply(_map_color, axis=1)
    map_frame["rent_text"] = map_frame["rent_price"].map(_money_text)
    map_frame["area_text"] = map_frame["area_sqm"].map(_area_text)
    map_frame["rent_per_sqm_text"] = map_frame["rent_per_sqm"].map(_rent_per_sqm_text)
    map_frame["distance_text"] = map_frame["straight_distance_meters"].map(_distance_text)
    map_frame["value_level_text"] = map_frame["value_level"].fillna("")
    map_frame["cluster_text"] = (
        map_frame.get("subdistrict", pd.Series(dtype=str))
        .fillna(map_frame.get("community_name", pd.Series(dtype=str)))
        .fillna(map_frame.get("geo_cluster_id", pd.Series(dtype=str)))
        .fillna("")
    )
    map_frame["quality_text"] = map_frame["analysis_tier"].fillna("")
    map_frame["apartment_like"] = map_frame["apartment_like"].fillna(False)
    st.caption(
        "气泡颜色: 🟢 绿边=高性价比 · ⚫ 黑边=中性 · 🟣 紫边=低性价比 "
        "透明度: 越近越清晰, 越远越淡 "
        "虚线圆: 距工作地 4 / 8 / 12 km "
        "删除线: blocked 质量房源"
    )
    if hidden_coordinate_count:
        st.warning(f"{hidden_coordinate_count} 条房源无可用上海坐标, 已从地图中隐藏。")

    st.markdown(
        """
<script>
window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'map_select') {
        var input = document.querySelector('[data-testid="stTextInput"] input');
        if (input) {
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, e.data.id || '');
            input.dispatchEvent(new Event('input', {bubbles: true}));
        }
    }
});
</script>
""",
        unsafe_allow_html=True,
    )

    st.text_input(
        "",
        key="map_selected_input",
        label_visibility="collapsed",
    )
    _set_map_selected_id()

    components.html(
        build_leaflet_map_html(map_frame),
        height=740,
        scrolling=False,
    )


def _set_map_selected_id() -> None:
    value = st.session_state.get("map_selected_input", "")
    if value:
        st.session_state["map_selected_id"] = value
        st.session_state["map_selected_input"] = ""


def ensure_map_value_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """补齐地图 hover/tooltip 所需的动态评分字段。"""

    ensured = frame.copy()
    if "value_score" not in ensured.columns:
        ensured["value_score"] = None
    if "value_level" not in ensured.columns:
        ensured["value_level"] = ""
    if "value_level_text" not in ensured.columns:
        ensured["value_level_text"] = ensured["value_level"].fillna("")
    return ensured


def build_leaflet_map_html(frame: pd.DataFrame) -> str:
    """价格气泡 Leaflet 地图 + MarkerCluster 聚合 + 工作地同心圆。"""

    points = [_leaflet_point(row) for _, row in frame.iterrows()]
    payload = json.dumps(points, ensure_ascii=False, allow_nan=False)
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
  <style>
    html, body, #map {{
        height: 720px;
        margin: 0;
        width: 100%;
        font-family: 'Satoshi', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .leaflet-container {{
        background: #eef2f3;
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 10px;
        overflow: hidden;
    }}
    .leaflet-tile-pane {{
        filter: grayscale(25%) sepia(10%) brightness(1.05) contrast(0.93);
    }}
    .rs-price-bubble {{
        background: #ffffff;
        border: 2px solid #28251d;
        border-radius: 999px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.18);
        color: #28251d;
        cursor: pointer;
        font-family: 'Satoshi', system-ui, sans-serif;
        font-size: 11px;
        font-weight: 700;
        font-variant-numeric: tabular-nums lining-nums;
        padding: 3px 9px;
        white-space: nowrap;
        transition: transform 120ms ease, box-shadow 120ms ease, opacity 120ms ease;
        display: inline-block;
    }}
    .rs-price-bubble:hover {{
        transform: scale(1.1);
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.28);
        z-index: 9999 !important;
    }}
    .rs-bubble-high {{
        border-color: #437a22;
        background: #edf5e9;
        color: #2a5010;
    }}
    .rs-bubble-low {{
        border-color: #a12c7b;
        background: #f9eef5;
        color: #7a1a5e;
    }}
    .rs-bubble-mid {{
        border-color: #28251d;
        background: #ffffff;
        color: #28251d;
    }}
    .rs-bubble-blocked {{
        text-decoration: line-through;
        filter: opacity(0.55);
    }}
    @keyframes rs-pulse-ring {{
        0%   {{ transform: scale(0.5); opacity: 0.75; }}
        100% {{ transform: scale(2.4); opacity: 0; }}
    }}
    .rs-workplace-pulse {{
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: #28251d;
        position: relative;
        display: block;
        box-shadow: 0 0 0 3px rgba(40, 37, 29, 0.15);
    }}
    .rs-workplace-pulse::before,
    .rs-workplace-pulse::after {{
        content: "";
        position: absolute;
        inset: -3px;
        border-radius: 50%;
        border: 2px solid #28251d;
        animation: rs-pulse-ring 2.2s cubic-bezier(0.2, 0.8, 0.4, 1) infinite;
        pointer-events: none;
    }}
    .rs-workplace-pulse::after {{
        animation-delay: 0.75s;
    }}
    .rs-tooltip {{
        min-width: 220px;
        max-width: 280px;
        white-space: normal;
        font-family: 'Satoshi', system-ui, sans-serif;
    }}
    .rs-popup-title {{
        font-size: 12px;
        font-weight: 600;
        line-height: 1.45;
        color: #28251d;
        margin-bottom: 6px;
    }}
    .rs-popup-price-row {{
        display: flex;
        align-items: baseline;
        gap: 6px;
        margin: 6px 0 4px;
    }}
    .rs-popup-price-main {{
        font-size: 20px;
        font-weight: 700;
        color: #28251d;
        font-variant-numeric: tabular-nums lining-nums;
    }}
    .rs-popup-price-sub {{
        font-size: 11px;
        color: #7a7974;
    }}
    .rs-popup-meta {{
        font-size: 11px;
        color: #7a7974;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 8px;
    }}
    .rs-popup-badge {{
        border-radius: 999px;
        padding: 2px 8px;
        font-size: 10px;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 6px;
    }}
    .rs-badge-high   {{ background: #edf5e9; color: #437a22; }}
    .rs-badge-low    {{ background: #f9eef5; color: #a12c7b; }}
    .rs-badge-mid    {{ background: #f0eeea; color: #7a7974; }}
    .rs-badge-ready    {{ background: #eef6f6; color: #01696f; }}
    .rs-badge-caution  {{ background: #fdf6ee; color: #d19900; }}
    .rs-badge-blocked  {{ background: #fdf0f5; color: #a12c7b; }}
    .rs-popup-link {{
        background: #28251d;
        border-radius: 7px;
        color: #ffffff !important;
        display: inline-block;
        font-size: 11px;
        font-weight: 500;
        margin-top: 8px;
        padding: 6px 10px;
        text-decoration: none;
    }}
    .rs-popup-link:hover {{ background: #01696f; }}
    #rs-legend {{
        position: absolute;
        bottom: 32px;
        right: 10px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border: 1px solid rgba(0, 0, 0, 0.08);
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 11px;
        font-family: 'Satoshi', system-ui, sans-serif;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.10);
        min-width: 130px;
    }}
    #rs-legend-title {{
        font-weight: 600;
        color: #28251d;
        margin-bottom: 7px;
        font-size: 11px;
    }}
    .rs-legend-row {{
        display: flex;
        align-items: center;
        gap: 7px;
        color: #28251d;
        margin-bottom: 4px;
        font-size: 11px;
    }}
    .rs-legend-dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        border: 2px solid;
        flex-shrink: 0;
    }}
    .rs-legend-divider {{
        border: none;
        border-top: 1px solid #dcd9d5;
        margin: 6px 0;
    }}
    .marker-cluster-small,
    .marker-cluster-medium,
    .marker-cluster-large {{
        background: transparent !important;
    }}
    .marker-cluster-small div,
    .marker-cluster-medium div,
    .marker-cluster-large div {{
        background: transparent !important;
    }}
    .cluster-house-icon {{
        align-items: center;
        border-radius: 50%;
        color: #fff;
        display: flex;
        flex-direction: column;
        font-size: 10px;
        font-weight: 700;
        gap: 1px;
        height: 100%;
        justify-content: center;
        line-height: 1;
        width: 100%;
    }}
    .cluster-house-icon svg {{
        display: block;
        width: 16px;
        height: 16px;
    }}
    .cluster-community {{
        background: #01696f;
        box-shadow: 0 2px 8px rgba(1, 105, 111, 0.35);
    }}
    .cluster-apartment {{
        background: #d19900;
        box-shadow: 0 2px 8px rgba(209, 153, 0, 0.35);
    }}
  </style>
</head>
<body>
  <div id="map" style="position:relative;"></div>
  <div id="rs-legend">
    <div id="rs-legend-title">图例</div>
    <div class="rs-legend-row">
      <span class="rs-legend-dot" style="background:#edf5e9;border-color:#437a22;"></span>高性价比
    </div>
    <div class="rs-legend-row">
      <span class="rs-legend-dot" style="background:#fff;border-color:#28251d;"></span>中性
    </div>
    <div class="rs-legend-row">
      <span class="rs-legend-dot" style="background:#f9eef5;border-color:#a12c7b;"></span>低性价比
    </div>
    <hr class="rs-legend-divider">
    <div class="rs-legend-row">
      <span style="text-decoration:line-through;opacity:0.5;font-size:10px;margin-right:2px;">价格</span>blocked
    </div>
    <hr class="rs-legend-divider">
    <div class="rs-legend-row">
      <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:#01696f;"></span>小区聚合
    </div>
    <div class="rs-legend-row">
      <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:#d19900;"></span>公寓聚合
    </div>
    <hr class="rs-legend-divider">
    <div class="rs-legend-row" style="color:#7a7974;font-size:10px;">
      虚线圆 = 通勤距离圈
    </div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script>
    const points = {payload};

    const map = L.map("map", {{ preferCanvas: false, zoomControl: true }});
    L.tileLayer("{AMAP_BASE_URL}", {{
        maxZoom: 19, minZoom: 3, attribution: "\\u00a9 \\u9ad8\\u5fb7\\u5730\\u56fe",
        opacity: 1.0,
    }}).addTo(map);

    L.tileLayer("{AMAP_LABEL_URL}", {{
        maxZoom: 19, minZoom: 3,
        opacity: 0.82,
    }}).addTo(map);

    function escapeHtml(value) {{
        return String(value).replace(/[&<>"']/g, ch => ({{
            "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
        }}[ch]));
    }}
    function escapeAttribute(value) {{
        return escapeHtml(value).replace(/\\`/g, "&#096;");
    }}

    function markerHtml(point) {{
        if (point.marker_type === "workplace") return "";

        const levelClass = point.value_level_text === "高性价比" ? "rs-bubble-high"
            : point.value_level_text === "低性价比" ? "rs-bubble-low"
            : "rs-bubble-mid";

        const blockedClass = point.quality_text === "blocked" ? " rs-bubble-blocked" : "";

        const opacityMap = {{
            "within_4km": 1.0,
            "4_to_8km":   0.72,
            "8_to_12km":  0.52,
            "over_12km":  0.35,
        }};
        const opacity = opacityMap[point.distance_bucket] !== undefined
            ? opacityMap[point.distance_bucket] : 0.8;

        return `<span class="rs-price-bubble ${{levelClass}}${{blockedClass}}"
                      style="opacity:${{opacity}};">${{escapeHtml(point.rent_text)}}</span>`;
    }}

    function popupHtml(point) {{
        if (point.marker_type === "workplace") {{
            return `<div class="rs-tooltip">
                <div class="rs-popup-title">📍 \\u5de5\\u4f5c\\u5730</div>
                <div style="font-size:12px;color:#7a7974;">${{escapeHtml(point.title || "")}}</div>
            </div>`;
        }}

        const title = escapeHtml(point.title || "\\u672a\\u547d\\u540d\\u623f\\u6e90");

        const valueBadgeClass = point.value_level_text === "高性价比" ? "rs-badge-high"
            : point.value_level_text === "低性价比" ? "rs-badge-low"
            : "rs-badge-mid";
        const valueBadge = point.value_level_text
            ? `<span class="rs-popup-badge ${{valueBadgeClass}}">${{escapeHtml(point.value_level_text)}}</span> `
            : "";

        const tierBadgeClass = point.quality_text === "ready" ? "rs-badge-ready"
            : point.quality_text === "caution" ? "rs-badge-caution"
            : point.quality_text === "blocked" ? "rs-badge-blocked"
            : "rs-badge-mid";
        const tierLabel = point.quality_text === "ready" ? "\\u53ef\\u7528"
            : point.quality_text === "caution" ? "\\u8b66\\u544a"
            : point.quality_text === "blocked" ? "\\u5df2\\u62d2"
            : "";
        const tierBadge = point.quality_text
            ? `<span class="rs-popup-badge ${{tierBadgeClass}}">${{tierLabel}}</span>`
            : "";

        const link = point.source_url
            ? `<a class="rs-popup-link" href="${{escapeAttribute(point.source_url)}}"
                  target="_blank" rel="noopener noreferrer">\\u67e5\\u770b\\u539f\\u59cb\\u623f\\u6e90 \\u2192</a>`
            : "";

        return `<div class="rs-tooltip">
            <div class="rs-popup-title">${{title}}</div>
            <div style="margin-bottom:4px;">${{valueBadge}}${{tierBadge}}</div>
            <div class="rs-popup-price-row">
                <span class="rs-popup-price-main">${{escapeHtml(point.rent_text)}}</span>
                <span class="rs-popup-price-sub">${{escapeHtml(point.area_text)}}</span>
            </div>
            <div class="rs-popup-meta">
                <span>📍 ${{escapeHtml(point.distance_text)}}</span>
                <span>${{escapeHtml(point.rent_per_sqm_text)}}</span>
                <span>🏘 ${{escapeHtml(point.cluster_text)}}</span>
            </div>
            ${{link}}
        </div>`;
    }}

    const workplacePoint = points.find(p => p.marker_type === "workplace");
    if (workplacePoint && Number.isFinite(workplacePoint.latitude) && Number.isFinite(workplacePoint.longitude)) {{
        const wlat = workplacePoint.latitude;
        const wlng = workplacePoint.longitude;

        [
            {{ radius: 4000,  color: "#01696f", fillOpacity: 0.04 }},
            {{ radius: 8000,  color: "#d19900", fillOpacity: 0.03 }},
            {{ radius: 12000, color: "#bb653b", fillOpacity: 0.02 }},
        ].forEach(({{ radius, color, fillOpacity }}) => {{
            L.circle([wlat, wlng], {{
                radius,
                color,
                weight: 1.5,
                opacity: 0.55,
                fillColor: color,
                fillOpacity,
                dashArray: "5 5",
                interactive: false,
            }}).addTo(map);
        }});

        const pulseIcon = L.divIcon({{
            className: "",
            html: `<span class="rs-workplace-pulse"></span>`,
            iconSize: [36, 36],
            iconAnchor: [18, 18],
        }});
        L.marker([wlat, wlng], {{ icon: pulseIcon, zIndexOffset: 9000 }})
            .bindPopup(popupHtml(workplacePoint))
            .addTo(map);
    }}

    const communityPts = [];
    const apartmentPts = [];

    function createClusterIcon(cluster, type) {{
        const count = cluster.getChildCount();
        const cls = type === "community" ? "cluster-community" : "cluster-apartment";
        const svg = type === "community"
            ? `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3L2 12h3v8h5v-6h4v6h5v-8h3L12 3z"/></svg>`
            : `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="10" width="16" height="12" rx="1"/><rect x="7" y="2" width="10" height="8" rx="1.5"/></svg>`;
        const html = `<div class="cluster-house-icon ${{cls}}">${{svg}}<span>${{count}}</span></div>`;
        return L.divIcon({{ className: "", html, iconSize: [44, 44], iconAnchor: [22, 22] }});
    }}

    const communityCluster = L.markerClusterGroup({{
        chunkedLoading: true,
        disableClusteringAtZoom: 15,
        maxClusterRadius: 46,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        zoomToBoundsOnClick: true,
        iconCreateFunction: function(cluster) {{ return createClusterIcon(cluster, "community"); }},
    }});
    const apartmentCluster = L.markerClusterGroup({{
        chunkedLoading: true,
        disableClusteringAtZoom: 15,
        maxClusterRadius: 46,
        showCoverageOnHover: false,
        spiderfyOnMaxZoom: true,
        zoomToBoundsOnClick: true,
        iconCreateFunction: function(cluster) {{ return createClusterIcon(cluster, "apartment"); }},
    }});

    points.forEach(point => {{
        if (point.marker_type === "workplace") return;
        if (!Number.isFinite(point.latitude) || !Number.isFinite(point.longitude)) return;

        const latLng = [point.latitude, point.longitude];

        const html = markerHtml(point);
        const bubbleWidth = Math.max(60, (point.rent_text || "").length * 7 + 24);
        const icon = L.divIcon({{
            className: "",
            html,
            iconSize: [bubbleWidth, 24],
            iconAnchor: [bubbleWidth / 2, 12],
        }});

        const marker = L.marker(latLng, {{ icon }});
        marker.bindTooltip(popupHtml(point), {{
            direction: "top",
            offset: [0, -16],
            opacity: 0.97,
            sticky: false,
        }});
        if (point.source_url) {{
            marker.on("click", () => window.open(point.source_url, "_blank", "noopener,noreferrer"));
        }}
        if (point.apartment_like) {{
            apartmentPts.push(latLng);
            apartmentCluster.addLayer(marker);
        }} else {{
            communityPts.push(latLng);
            communityCluster.addLayer(marker);
        }}
    }});

    map.addLayer(communityCluster);
    map.addLayer(apartmentCluster);

    const allCoords = [...communityPts, ...apartmentPts];
    if (workplacePoint && Number.isFinite(workplacePoint.latitude)) {{
        map.setView([workplacePoint.latitude, workplacePoint.longitude], 13);
    }} else if (allCoords.length > 1) {{
        map.fitBounds(allCoords, {{ padding: [32, 32], maxZoom: 14 }});
    }} else if (allCoords.length === 1) {{
        map.setView(allCoords[0], 13);
    }} else {{
        map.setView([31.2304, 121.4737], 12);
    }}
  </script>
</body>
</html>
"""


def _leaflet_point(row: pd.Series) -> dict[str, object]:
    return {
        "latitude": _json_float(row.get("latitude")),
        "longitude": _json_float(row.get("longitude")),
        "marker_type": str(row.get("marker_type") or "listing"),
        "analysis_tier": str(row.get("analysis_tier") or "ready"),
        "title": str(row.get("title") or ""),
        "source_url": str(row.get("source_url") or ""),
        "listing_id": str(row.get("listing_id") or row.get("source_listing_id") or ""),
        "color": row.get("fill_color") or "#2563eb",
        "rent_text": str(row.get("rent_text") or "-"),
        "area_text": str(row.get("area_text") or "-"),
        "rent_per_sqm_text": str(row.get("rent_per_sqm_text") or "-"),
        "distance_text": str(row.get("distance_text") or "-"),
        "distance_bucket": str(row.get("distance_bucket") or ""),
        "cluster_text": str(row.get("cluster_text") or ""),
        "quality_text": str(row.get("quality_text") or ""),
        "apartment_like": bool(row.get("apartment_like")),
        "value_level_text": str(row.get("value_level_text") or "-"),
    }


def _json_float(value: object) -> float:
    return float(value) if pd.notna(value) else 0.0


def add_value_scores(frame: pd.DataFrame, weights: object) -> pd.DataFrame:
    """按面积、距离、金钱权重动态计算综合性价比。"""

    if frame.empty:
        return frame
    scored = frame.copy()
    weight_map = weights if isinstance(weights, dict) else {}
    area_weight = float(weight_map.get("area", 45))
    distance_weight = float(weight_map.get("distance", 35))
    money_weight = float(weight_map.get("money", 20))
    total_weight = area_weight + distance_weight + money_weight
    if total_weight <= 0:
        area_weight = distance_weight = money_weight = 1
        total_weight = 3

    area_score = _normalize_high_good(scored.get("area_sqm"))
    distance_score = _normalize_low_good(scored.get("straight_distance_meters"))
    money_score = _normalize_low_good(scored.get("rent_price"))
    scored["value_score"] = (
        area_score * area_weight + distance_score * distance_weight + money_score * money_weight
    ) / total_weight
    scored["value_score"] = (scored["value_score"] * 100).round(1)
    scored["value_level"] = value_levels(scored["value_score"])
    return scored


def value_levels(scores: pd.Series) -> pd.Series:
    """把综合性价比分成低、中、高三档。"""

    if scores.empty:
        return pd.Series(dtype=str)
    valid = scores.dropna()
    if valid.empty:
        return pd.Series(["中性"] * len(scores), index=scores.index)
    low_threshold = valid.quantile(0.3)
    high_threshold = valid.quantile(0.7)
    if low_threshold == high_threshold:
        return pd.Series(["中性"] * len(scores), index=scores.index)
    return scores.map(
        lambda score: (
            "高性价比"
            if score >= high_threshold
            else "低性价比"
            if score <= low_threshold
            else "中性"
        )
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
    tier_counts = quality["analysis_tier"].value_counts().reset_index()
    tier_counts.columns = ["质量层级", "数量"]
    tier_color_map = {"ready": "#437a22", "caution": "#d19900", "blocked": "#a12c7b"}
    fig_tier = px.bar(
        tier_counts,
        x="质量层级",
        y="数量",
        color="质量层级",
        color_discrete_map=tier_color_map,
        title="质量层级分布",
    )
    fig_tier.update_layout(
        showlegend=False,
        plot_bgcolor="#f9f8f5",
        paper_bgcolor="#f9f8f5",
        font_family="Satoshi, system-ui, sans-serif",
        font_color="#28251d",
        title_font_size=13,
        margin=dict(l=0, r=0, t=32, b=0),
    )
    fig_tier.update_traces(marker_line_width=0)
    st.plotly_chart(fig_tier, width="stretch")
    risk_columns = [
        "area_outlier",
        "subdistrict_low_confidence",
        "apartment_like",
        "possible_duplicate",
        "missing_published_at",
        "coordinate_suspicious",
    ]
    risk_counts = {
        column: int(quality[column].sum()) for column in risk_columns if column in quality.columns
    }
    risk_series = pd.Series(risk_counts, name="数量").reset_index()
    risk_series.columns = ["风险项", "数量"]
    fig_risk = px.bar(
        risk_series,
        x="风险项",
        y="数量",
        title="风险标记分布",
        color_discrete_sequence=["#bb653b"],
    )
    fig_risk.update_layout(
        showlegend=False,
        plot_bgcolor="#f9f8f5",
        paper_bgcolor="#f9f8f5",
        font_family="Satoshi, system-ui, sans-serif",
        font_color="#28251d",
        title_font_size=13,
        margin=dict(l=0, r=0, t=32, b=0),
    )
    fig_risk.update_traces(marker_line_width=0)
    st.plotly_chart(fig_risk, width="stretch")


def render_distance_tab(distance: pd.DataFrame, filtered: pd.DataFrame) -> None:
    st.subheader("工作地点直线距离")
    if distance.empty:
        st.info("缺少距离分桶输出。")
        return
    bucket_counts = (
        distance["distance_bucket"]
        .map(BUCKET_LABELS)
        .value_counts()
        .reindex([BUCKET_LABELS[k] for k in BUCKET_ORDER if k in BUCKET_LABELS], fill_value=0)
        .reset_index()
    )
    bucket_counts.columns = ["距离段", "数量"]
    fig_dist = px.bar(
        bucket_counts,
        x="距离段",
        y="数量",
        title="各距离段房源数量",
        color_discrete_sequence=["#01696f"],
    )
    fig_dist.update_layout(
        showlegend=False,
        plot_bgcolor="#f9f8f5",
        paper_bgcolor="#f9f8f5",
        font_family="Satoshi, system-ui, sans-serif",
        font_color="#28251d",
        title_font_size=13,
        margin=dict(l=0, r=0, t=32, b=0),
    )
    fig_dist.update_traces(marker_line_width=0)
    st.plotly_chart(fig_dist, width="stretch")
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

    cluster_counts = preview["geo_cluster_id"].value_counts().head(20).reset_index()
    cluster_counts.columns = ["空间簇 ID", "房源数"]
    fig_cluster = px.bar(
        cluster_counts,
        x="空间簇 ID",
        y="房源数",
        title="各空间簇房源数量 (Top 20)",
        color_discrete_sequence=["#006494"],
    )
    fig_cluster.update_layout(
        showlegend=False,
        plot_bgcolor="#f9f8f5",
        paper_bgcolor="#f9f8f5",
        font_family="Satoshi, system-ui, sans-serif",
        font_color="#28251d",
        title_font_size=13,
        margin=dict(l=0, r=0, t=32, b=0),
    )
    fig_cluster.update_traces(marker_line_width=0)
    st.plotly_chart(fig_cluster, width="stretch")
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
    columns = [
        "title",
        "rent_price",
        "area_sqm",
        "rent_per_sqm",
        "analysis_tier",
        "opportunity_score",
        "distance_bucket",
        "straight_distance_meters",
        "geo_cluster_id",
        "geo_cluster_size",
        "nearby_good_value",
        "apartment_like",
        "possible_duplicate",
        "quality_notes",
        "source_url",
    ]
    display = _display_columns(frame, columns)
    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="listing_table",
    )
    if event and event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        selected_id = frame.iloc[idx].get("listing_id") or frame.iloc[idx].get("source_listing_id")
        if selected_id:
            st.session_state["map_selected_id"] = str(selected_id)


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


def _normalize_high_good(values: pd.Series | None) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    numeric = pd.to_numeric(values, errors="coerce")
    minimum = numeric.min()
    maximum = numeric.max()
    if pd.isna(minimum) or pd.isna(maximum) or minimum == maximum:
        return pd.Series([0.5] * len(numeric), index=numeric.index)
    return ((numeric - minimum) / (maximum - minimum)).fillna(0.5)


def _normalize_low_good(values: pd.Series | None) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    return 1 - _normalize_high_good(values)


def _map_color(row: pd.Series) -> str:
    if row.get("marker_type") == "workplace":
        return "#FF5A5F"
    if row.get("value_level") == "高性价比":
        return "#10B981"
    if row.get("value_level") == "低性价比":
        return "#F43F5E"
    return "#6B7280"


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
    return f"¥{float(value):.1f}/㎡"


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
