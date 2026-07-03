"""RentalScout Streamlit 分析工作台。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from rentalscout.analysis.commute import (
    DEFAULT_WORKPLACE_ID,
    DEFAULT_WORKPLACE_NAME,
    Workplace,
    analyze_distance_buckets,
    resolve_workplace_from_amap,
)
from rentalscout.analysis.geo_clusters import (
    DEFAULT_CLUSTER_EPS_METERS,
    DEFAULT_CLUSTER_MIN_SAMPLES,
    DEFAULT_GEO_CLUSTER_CSV,
    DEFAULT_GEO_CLUSTER_SUMMARY_JSON,
    analyze_geo_clusters,
    generate_geo_cluster_outputs,
    summarize_geo_cluster_rows,
)
from rentalscout.analysis.location_value import PriceAreaInputRow, analyze_location_value
from rentalscout.analysis.price_area import analyze_price_area
from rentalscout.analysis.price_history import analyze_price_history
from rentalscout.analysis.wellcee_quality import analyze_wellcee_quality
from rentalscout.schemas.normalized import ListingAvailabilityStatus
from rentalscout.schemas.raw import SourceName
from rentalscout.settings import DATA_DIR
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, load_listings, load_observations

ANALYSIS_DIR = DATA_DIR / "analysis"
QUALITY_CSV = ANALYSIS_DIR / "wellcee_quality.csv"
DISTANCE_CSV = ANALYSIS_DIR / "commute_distance_buckets.csv"
PRICE_AREA_CSV = ANALYSIS_DIR / "price_area_analysis.csv"
LOCATION_VALUE_CSV = ANALYSIS_DIR / "location_value_analysis.csv"
GEO_CLUSTER_CSV = ANALYSIS_DIR / "geo_clusters.csv"
PRIVATE_DIR = DATA_DIR / "private"
DEFAULT_WORKPLACE_JSON = PRIVATE_DIR / "workplace_default.json"
DEFAULT_WEB_WORKPLACE = Workplace(
    workplace_id=DEFAULT_WORKPLACE_ID,
    name="上海市浦东新区浦东图书馆",
    longitude=121.541527,
    latitude=31.191880,
)
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
    data = render_workplace_controls(data)
    missing = missing_inputs(data)
    if missing:
        st.warning("以下分析文件暂未生成: " + "、".join(str(path) for path in missing))

    filters = render_sidebar(data)
    merged = merged_listing_frame(data)
    filtered = apply_listing_filters(merged, filters)
    filtered = add_value_scores(filtered, filters["value_weights"])

    render_overview(data, filtered)
    tabs = st.tabs(
        ["🗺 地图筛选", "📋 候选房源", "🧭 分析解释", "🛠 数据质量", "📈 价格与下架"]
    )
    with tabs[0]:
        render_map_tab(filtered, data["distance"], filters)
    with tabs[1]:
        render_candidate_tab(filtered)
    with tabs[2]:
        render_analysis_explanation_tab(filtered)
    with tabs[3]:
        render_data_quality_tab(data, filtered)
    with tabs[4]:
        render_price_changes_tab()


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


def render_workplace_controls(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """渲染工作中心搜索, 并在会话内即时重算距离与性价比。"""

    session_analysis = st.session_state.get("workplace_analysis")
    if isinstance(session_analysis, dict):
        data = {**data, **session_analysis}

    current = (
        current_workplace_from_session()
        or load_private_default_workplace()
        or DEFAULT_WEB_WORKPLACE
        or workplace_from_distance_frame(data["distance"])
    )
    if (
        current
        and session_analysis is None
        and not distance_frame_uses_workplace(data["distance"], current)
    ):
        data = {**data, **recompute_workplace_analysis(current)}

    with st.sidebar.expander("工作中心", expanded=True):
        default_name = current.name if current else ""
        city = st.text_input("城市", value="上海", key="workplace_city")
        name = st.text_input("地点", value=default_name, key="workplace_name")
        save_as_default = st.checkbox("设为本地默认", value=False)
        if st.button("搜索并重算", width="stretch"):
            if not name.strip():
                st.error("请输入工作地点。")
            else:
                workplace = resolve_workplace_for_ui(name=name, city=city)
                if workplace:
                    analysis = recompute_workplace_analysis(workplace)
                    st.session_state["workplace_analysis"] = analysis
                    st.session_state["current_workplace"] = workplace_to_dict(workplace)
                    clear_map_selection_state()
                    data = {**data, **analysis}
                    if save_as_default:
                        save_private_default_workplace(workplace)
                    st.success(f"已切换到: {workplace.name}")

        active = workplace_from_distance_frame(data["distance"]) or current_workplace_from_session()
        if active:
            st.caption(f"当前: {active.name}")
            st.caption(f"{active.longitude:.6f}, {active.latitude:.6f}")
            st.caption(f"分析版本: {workplace_signature(active)}")
        else:
            st.caption("未设置工作中心。")
    return data


def resolve_workplace_for_ui(*, name: str, city: str) -> Workplace | None:
    try:
        return resolve_workplace_from_amap(
            name=name.strip(),
            workplace_id=DEFAULT_WORKPLACE_ID,
            city=city.strip() or "上海",
        )
    except ValueError as error:
        if str(error) == "invalid_workplace_location":
            st.error("没有解析出经纬度, 请检查地理位置或补充城市/区县。")
        elif str(error) == "missing_amap_api_key":
            st.error("缺少 AMAP_API_KEY。请只在 .env 中保存 API key, 不要保存工作地点坐标。")
        else:
            st.error(f"工作地点解析失败: {error}")
        return None


@st.cache_data(show_spinner="正在根据工作中心重算距离和性价比...")
def recompute_workplace_analysis(workplace: Workplace) -> dict[str, pd.DataFrame]:
    listings = [
        listing for listing in load_listings(DEFAULT_DB_PATH) if listing.source == SourceName.WELLCEE
    ]
    distance_rows = analyze_distance_buckets(listings=listings, workplace=workplace)
    quality_rows = analyze_wellcee_quality(listings)
    distance_buckets = {
        row.listing_id: row.distance_bucket.value for row in distance_rows
    }
    price_rows = analyze_price_area(
        listings=listings,
        quality_rows=quality_rows,
        distance_buckets=distance_buckets,
    )
    location_rows = analyze_location_value(
        listings=listings,
        price_area_rows=price_area_input_rows(price_rows),
    )
    return {
        "distance": rows_to_frame(distance_rows),
        "price_area": rows_to_frame(price_rows),
        "location_value": rows_to_frame(location_rows),
    }


def price_area_input_rows(rows: list[object]) -> dict[str, PriceAreaInputRow]:
    inputs: dict[str, PriceAreaInputRow] = {}
    for row in rows:
        values = asdict_like(row)
        listing_id = str(values.get("listing_id") or "")
        if not listing_id:
            continue
        inputs[listing_id] = PriceAreaInputRow(
            listing_id=listing_id,
            rent_price=int(values["rent_price"]),
            area_sqm=float(values["area_sqm"]),
            rent_per_sqm=float(values["rent_per_sqm"]),
            distance_bucket=str(values["distance_bucket"]),
            apartment_like=bool(values["apartment_like"]),
            possible_duplicate=bool(values["possible_duplicate"]),
        )
    return inputs


def rows_to_frame(rows: list[object]) -> pd.DataFrame:
    frame = pd.DataFrame([asdict_like(row) for row in rows])
    for column in frame.columns:
        if frame[column].map(lambda value: hasattr(value, "value")).any():
            frame[column] = frame[column].map(lambda value: value.value if hasattr(value, "value") else value)
    frame = normalize_listing_id_columns(frame)
    for column in BOOLEAN_COLUMNS.intersection(frame.columns):
        frame[column] = frame[column].map(_to_bool)
    return frame


def current_workplace_from_data(distance: pd.DataFrame) -> Workplace | None:
    return current_workplace_from_session() or workplace_from_distance_frame(distance)


def current_workplace_from_session() -> Workplace | None:
    saved = st.session_state.get("current_workplace")
    if isinstance(saved, dict):
        return workplace_from_dict(saved)
    return None


def workplace_from_distance_frame(distance: pd.DataFrame) -> Workplace | None:
    if not distance.empty:
        required = {"workplace_id", "workplace_name", "workplace_longitude", "workplace_latitude"}
        if required.issubset(distance.columns):
            first = distance.dropna(subset=["workplace_longitude", "workplace_latitude"]).head(1)
            if not first.empty:
                row = first.iloc[0]
                return Workplace(
                    workplace_id=str(row.get("workplace_id") or DEFAULT_WORKPLACE_ID),
                    name=str(row.get("workplace_name") or DEFAULT_WORKPLACE_NAME),
                    longitude=float(row["workplace_longitude"]),
                    latitude=float(row["workplace_latitude"]),
                )
    return None


def distance_frame_uses_workplace(distance: pd.DataFrame, workplace: Workplace) -> bool:
    active = workplace_from_distance_frame(distance)
    if active is None:
        return False
    return (
        active.workplace_id == workplace.workplace_id
        and active.name == workplace.name
        and abs(active.longitude - workplace.longitude) < 0.000001
        and abs(active.latitude - workplace.latitude) < 0.000001
    )


def workplace_signature(workplace: Workplace) -> str:
    return f"{workplace.name} · {workplace.longitude:.6f},{workplace.latitude:.6f}"


def clear_map_selection_state() -> None:
    for key in ("map_selected_id", "map_selected_input", "map_selected_last_input"):
        st.session_state.pop(key, None)


def load_private_default_workplace() -> Workplace | None:
    if not DEFAULT_WORKPLACE_JSON.exists():
        return None
    try:
        return workplace_from_dict(json.loads(DEFAULT_WORKPLACE_JSON.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_private_default_workplace(workplace: Workplace) -> None:
    DEFAULT_WORKPLACE_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_WORKPLACE_JSON.write_text(
        json.dumps(workplace_to_dict(workplace), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def workplace_to_dict(workplace: Workplace) -> dict[str, object]:
    return {
        "workplace_id": workplace.workplace_id,
        "name": workplace.name,
        "longitude": workplace.longitude,
        "latitude": workplace.latitude,
    }


def workplace_from_dict(payload: dict[str, object]) -> Workplace:
    return Workplace(
        workplace_id=str(payload.get("workplace_id") or DEFAULT_WORKPLACE_ID),
        name=str(payload.get("name") or DEFAULT_WORKPLACE_NAME),
        longitude=float(payload["longitude"]),
        latitude=float(payload["latitude"]),
    )


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

    quality = normalize_listing_id_columns(
        data["quality"].rename(columns={"source_listing_id": "listing_id"}).copy()
    )
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
            frame = normalize_listing_id_columns(frame)
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


def normalize_listing_id_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in ["listing_id", "source_listing_id"]:
        if column in normalized.columns:
            normalized[column] = normalized[column].astype(str)
    return normalized


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

    # 房源卡片: 房主最后登录 + 价格变化
    map_frame = _enrich_card_columns(map_frame)

    st.iframe(build_leaflet_map_html(map_frame), height=740)


def _enrich_card_columns(map_frame: pd.DataFrame) -> pd.DataFrame:
    """为地图房源卡片补 房主最后登录 + 价格变化 两列。

    - 房主最后登录: 从 rental_listings.host_last_login_at 计算 days_since_login,
      给出文本 + 严重等级 class(>90d 红, >30d 黄, 已知近期 默认, 未知 灰)。
    - 价格变化: 从 listing_observations 找每个 listing 最新一次价格变动
      (price_delta != 0/None), 给文本(↑+300 / ↓-200 / "首次") + class。
    """

    enriched = map_frame.copy()
    if "listing_id" not in enriched.columns:
        enriched["card_login_text"] = "未知"
        enriched["card_login_class"] = "rs-login-unknown"
        enriched["card_price_text"] = ""
        enriched["card_price_class"] = "rs-price-none"
        return enriched

    ids = enriched["listing_id"].astype(str).tolist()

    # ---- 房主最后登录 ----
    login_by_id: dict[str, str | None] = {}
    try:
        for listing in load_listings(db_path=DEFAULT_DB_PATH):
            login_by_id[listing.source_listing_id or ""] = (
                listing.host_last_login_at.isoformat() if listing.host_last_login_at else None
            )
    except Exception:
        login_by_id = {}

    from datetime import datetime
    from zoneinfo import ZoneInfo
    local_tz = ZoneInfo("Asia/Shanghai")
    today_local = datetime.now(local_tz).date()
    login_text: list[str] = []
    login_class: list[str] = []
    for lid in ids:
        ts = login_by_id.get(lid)
        if not ts:
            login_text.append("未知")
            login_class.append("rs-login-unknown")
            continue
        try:
            d_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            login_text.append("未知")
            login_class.append("rs-login-unknown")
            continue
        d_local = d_utc.astimezone(local_tz)
        # 颜色阈值用"距今多少个本地日历日"判定
        delta_days = (today_local - d_local.date()).days
        if delta_days <= 1 or delta_days < 30:
            css = "rs-login-fresh"
        elif delta_days < 90:
            css = "rs-login-warn"
        else:
            css = "rs-login-stale"
        login_text.append(d_local.strftime("%Y-%m-%d"))
        login_class.append(css)

    enriched["card_login_text"] = login_text
    enriched["card_login_class"] = login_class

    # ---- 价格变化 (最新一次有效变动) ----
    price_by_id: dict[str, dict[str, object]] = {}
    try:
        for row in analyze_price_history(load_observations(db_path=DEFAULT_DB_PATH)):
            if row.source_listing_id in price_by_id:
                continue  # price_history rows are sorted ascending; first hit = oldest, skip
            if row.price_delta is None or row.price_delta == 0:
                continue
            price_by_id[row.source_listing_id] = {
                "delta": int(row.price_delta),
                "current": row.rent_price,
                "previous": row.previous_rent_price,
                "direction": "up" if row.price_delta > 0 else "down",
            }
    except Exception:
        price_by_id = {}

    price_text: list[str] = []
    price_class: list[str] = []
    for lid in ids:
        info = price_by_id.get(lid)
        if not info:
            price_text.append("首次记录")
            price_class.append("rs-price-none")
            continue
        sign = "+" if info["direction"] == "up" else ""
        arrow = "↑" if info["direction"] == "up" else "↓"
        price_text.append(
            f"{arrow}{sign}{info['delta']}  {info['previous']}→{info['current']}"
        )
        price_class.append(
            "rs-price-up" if info["direction"] == "up" else "rs-price-down"
        )

    enriched["card_price_text"] = price_text
    enriched["card_price_class"] = price_class
    return enriched


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
    signature = map_workplace_signature(points)
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="rentalscout-workplace" content="{signature}" />
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
    .rs-card-rows {{
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-top: 6px;
        padding: 6px 8px;
        background: #faf8f4;
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 6px;
    }}
    .rs-card-row {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 10.5px;
        line-height: 1.3;
        color: #4a4a47;
    }}
    .rs-card-row .rs-card-ico {{
        font-size: 11px;
        width: 14px;
        text-align: center;
    }}
    .rs-card-row .rs-card-label {{
        color: #7a7974;
        font-weight: 500;
        flex-shrink: 0;
    }}
    .rs-card-row .rs-card-val {{
        font-weight: 600;
        font-variant-numeric: tabular-nums lining-nums;
        margin-left: auto;
        text-align: right;
    }}
    .rs-login-fresh   {{ color: #01696f; }}
    .rs-login-warn    {{ color: #d19900; }}
    .rs-login-stale   {{ color: #a12c7b; }}
    .rs-login-unknown {{ color: #9c9a93; }}
    .rs-price-up   {{ color: #bb653b; }}
    .rs-price-down {{ color: #437a22; }}
    .rs-price-none {{ color: #9c9a93; font-weight: 500 !important; }}
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
      越近越清晰
    </div>
    <div class="rs-legend-row" style="gap:5px;color:#7a7974;font-size:10px;">
      <span class="rs-legend-dot" style="background:#fff;border-color:#28251d;opacity:1.0;"></span>
      <span class="rs-legend-dot" style="background:#fff;border-color:#28251d;opacity:0.72;"></span>
      <span class="rs-legend-dot" style="background:#fff;border-color:#28251d;opacity:0.52;"></span>
      <span class="rs-legend-dot" style="background:#fff;border-color:#28251d;opacity:0.35;"></span>
      <span style="margin-left:2px;">&lt; 4 · 4-8 · 8-12 · &gt; 12 km</span>
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

        const loginClass = point.card_login_class || "rs-login-unknown";
        const loginText  = escapeHtml(point.card_login_text || "\\u672a\\u77e5");
        const priceClass = point.card_price_class || "rs-price-none";
        const priceText  = escapeHtml(point.card_price_text || "\\u9996\\u6b21\\u8bb0\\u5f55");

        const cardRows = `
            <div class="rs-card-rows">
                <div class="rs-card-row">
                    <span class="rs-card-ico">👤</span>
                    <span class="rs-card-label">房主登录</span>
                    <span class="rs-card-val ${{loginClass}}">${{loginText}}</span>
                </div>
                <div class="rs-card-row">
                    <span class="rs-card-ico">💹</span>
                    <span class="rs-card-label">价格变化</span>
                    <span class="rs-card-val ${{priceClass}}">${{priceText}}</span>
                </div>
            </div>
        `;

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
            ${{cardRows}}
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


def map_workplace_signature(points: list[dict[str, object]]) -> str:
    for point in points:
        if point.get("marker_type") == "workplace":
            return (
                f"{point.get('title', '')}|"
                f"{float(point.get('longitude') or 0):.6f},"
                f"{float(point.get('latitude') or 0):.6f}"
            )
    return "no-workplace"


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
        "card_login_text": str(row.get("card_login_text") or "未知"),
        "card_login_class": str(row.get("card_login_class") or "rs-login-unknown"),
        "card_price_text": str(row.get("card_price_text") or "首次记录"),
        "card_price_class": str(row.get("card_price_class") or "rs-price-none"),
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


def render_candidate_tab(frame: pd.DataFrame) -> None:
    st.subheader("候选房源")
    if frame.empty:
        st.info("没有符合筛选条件的房源。")
        return
    columns = st.columns(4)
    columns[0].metric("候选数", len(frame))
    columns[1].metric("高性价比", _count_value(frame, "value_level", "高性价比"))
    columns[2].metric("Ready", _count_value(frame, "analysis_tier", "ready"))
    columns[3].metric("附近低单价", _count_value(frame, "nearby_good_value", True))

    display = _display_columns(
        ranked_candidate_frame(frame),
        [
            "title",
            "rent_price",
            "area_sqm",
            "rent_per_sqm",
            "value_score",
            "value_level",
            "straight_distance_meters",
            "distance_bucket",
            "analysis_tier",
            "nearby_good_value",
            "good_price",
            "good_area_price",
            "source_url",
        ],
    )
    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="candidate_table",
    )
    if event and event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        selected_id = display.iloc[idx].get("listing_id") if "listing_id" in display else None
        if not selected_id:
            selected_id = ranked_candidate_frame(frame).iloc[idx].get("listing_id")
        if selected_id:
            st.session_state["map_selected_id"] = str(selected_id)


def ranked_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.copy()
    if "value_score" not in ranked.columns:
        ranked["value_score"] = None
    sort_columns = [
        column
        for column in ["value_score", "nearby_good_value", "good_price", "straight_distance_meters"]
        if column in ranked.columns
    ]
    if not sort_columns:
        return ranked
    ascending = [column == "straight_distance_meters" for column in sort_columns]
    return ranked.sort_values(sort_columns, ascending=ascending, na_position="last")


def render_analysis_explanation_tab(frame: pd.DataFrame) -> None:
    st.subheader("分析解释")
    if frame.empty:
        st.info("没有符合筛选条件的房源。")
        return
    selected = selected_listing_row(frame)
    if selected is None:
        st.info("没有可解释的房源。")
        return

    title = str(selected.get("title") or "未命名房源")
    st.markdown(f"#### {title}")
    columns = st.columns(5)
    columns[0].metric("租金", _money_text(selected.get("rent_price")))
    columns[1].metric("面积", _area_text(selected.get("area_sqm")))
    columns[2].metric("单价", _rent_per_sqm_text(selected.get("rent_per_sqm")))
    columns[3].metric("距离", _distance_text(selected.get("straight_distance_meters")))
    columns[4].metric("综合", str(selected.get("value_level") or "-"))

    reason_columns = st.columns(2)
    with reason_columns[0]:
        st.markdown("##### 推荐依据")
        for reason in listing_positive_reasons(selected):
            st.markdown(f"- {reason}")
    with reason_columns[1]:
        st.markdown("##### 注意事项")
        for risk in listing_risk_reasons(selected):
            st.markdown(f"- {risk}")

    source_url = selected.get("source_url")
    if isinstance(source_url, str) and source_url:
        st.link_button("打开来源页面", source_url)


def selected_listing_row(frame: pd.DataFrame) -> pd.Series | None:
    selected_id = st.session_state.get("map_selected_id")
    if selected_id and "listing_id" in frame.columns:
        matched = frame[frame["listing_id"].astype(str) == str(selected_id)]
        if not matched.empty:
            return matched.iloc[0]
    ranked = ranked_candidate_frame(frame)
    if ranked.empty:
        return None
    return ranked.iloc[0]


def listing_positive_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    if row.get("analysis_tier") == "ready":
        reasons.append("质量层级 ready, 基础字段适合继续比较")
    if row.get("value_level") == "高性价比":
        reasons.append("综合评分处于当前筛选结果的高位")
    if _to_bool(row.get("good_price")):
        reasons.append("租金低于同距离桶的低位阈值")
    if _to_bool(row.get("good_area_price")):
        reasons.append("单位面积租金低于同距离桶的低位阈值")
    if _to_bool(row.get("nearby_good_value")):
        reasons.append("附近 1km 内单位面积租金有优势")
    if _to_bool(row.get("below_nearby_median")):
        reasons.append("租金低于附近房源中位数")
    if not reasons:
        reasons.append("当前筛选条件下可作为中性候选继续比较")
    return reasons


def listing_risk_reasons(row: pd.Series) -> list[str]:
    risks: list[str] = []
    if row.get("analysis_tier") == "blocked":
        risks.append("质量层级 blocked, 需要谨慎查看来源页")
    if row.get("analysis_tier") == "caution":
        risks.append("质量层级 caution, 信息完整度或可信度有待确认")
    if _to_bool(row.get("apartment_like")):
        risks.append("疑似公寓类房源")
    if _to_bool(row.get("possible_duplicate")):
        risks.append("存在重复候选风险")
    if (
        row.get("nearby_sample_size") is not None
        and pd.notna(row.get("nearby_sample_size"))
        and float(row.get("nearby_sample_size")) < 5
    ):
        risks.append("附近样本量偏少")
    notes = row.get("quality_notes")
    if isinstance(notes, str) and notes.strip():
        risks.append(notes.strip())
    if not risks:
        risks.append("暂无明显风险标记")
    return risks


def render_data_quality_tab(data: dict[str, pd.DataFrame], filtered: pd.DataFrame) -> None:
    st.subheader("数据质量")
    with st.expander("质量", expanded=True):
        render_quality_tab(data["quality"], filtered)
    with st.expander("距离"):
        render_distance_tab(data["distance"], filtered)
    with st.expander("价格面积"):
        render_price_area_tab(data["price_area"], filtered)
    with st.expander("位置价值"):
        render_location_value_tab(data["location_value"], filtered)
    with st.expander("经纬度聚类"):
        render_geo_cluster_tab(data["geo_cluster"])


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
    title = str(row.get("workplace_name") or DEFAULT_WORKPLACE_NAME)
    return {
        "title": f"工作中心: {title}",
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


@st.cache_data(show_spinner="正在加载价格与下架数据...")
def load_price_change_data(db_path_str: str) -> dict[str, pd.DataFrame]:
    """Build per-listing frames from observations + listings for the 价格与下架 tab.

    Returns frames:
      - ``ups`` / ``downs``  : 涨价 / 降价 观测
      - ``offline``         : latest status = offline (被 API 搜索上限挤出)
      - ``out_of_window``   : latest status = out_of_window (真的从搜索结果消失)
      - ``listings``        : 当前所有房源, 含 host_last_login_at + days_since_login
    """
    from datetime import UTC, datetime
    db_path = Path(db_path_str)
    rows = analyze_price_history(load_observations(db_path=db_path))

    ups = [r for r in rows if r.price_delta and r.price_delta > 0]
    downs = [r for r in rows if r.price_delta and r.price_delta < 0]
    ups.sort(key=lambda r: -(r.price_delta_pct or 0))
    downs.sort(key=lambda r: r.price_delta_pct or 0)

    def _to_frame(items: list[object]) -> pd.DataFrame:
        if not items:
            return pd.DataFrame()
        records = [
            {k: v for k, v in asdict_like(item).items() if k != "availability_status"}
            for item in items
        ]
        return pd.DataFrame.from_records(records)

    # latest status per listing
    latest: dict[tuple[str, str], object] = {}
    for o in load_observations(db_path=db_path):
        k = (o.source, o.source_listing_id)
        if k not in latest or o.observed_at > latest[k].observed_at:
            latest[k] = o

    def _by_status(status: ListingAvailabilityStatus) -> pd.DataFrame:
        items = [
            {
                "source": o.source,
                "source_listing_id": o.source_listing_id,
                "title": o.title,
                "community_name": o.community_name,
                "district": o.district,
                "last_rent_price": o.rent_price,
                "delisted_at": o.observed_at.isoformat(),
            }
            for o in latest.values()
            if o.availability_status == status
        ]
        items.sort(key=lambda r: r["delisted_at"])
        return pd.DataFrame.from_records(items) if items else pd.DataFrame()

    # listings: per-row host_last_login + days_since_login (None = no data)
    now = datetime.now(UTC)
    listing_rows = []
    for listing in load_listings(db_path=db_path):
        login = listing.host_last_login_at
        days = (now - login).days if login else None
        listing_rows.append(
            {
                "source": listing.source.value,
                "source_listing_id": listing.source_listing_id,
                "title": listing.title,
                "community_name": listing.community_name,
                "district": listing.district,
                "rent_price": listing.rent_price,
                "host_last_login_at": login.isoformat() if login else None,
                "days_since_login": days,
            }
        )
    listings_df = pd.DataFrame.from_records(listing_rows)

    return {
        "ups": _to_frame(ups),
        "downs": _to_frame(downs),
        "out_of_window": _by_status(ListingAvailabilityStatus.OUT_OF_WINDOW),
        "offline": _by_status(ListingAvailabilityStatus.OFFLINE),
        "listings": listings_df,
    }


def render_price_changes_tab() -> None:
    """5th tab: price up/down, delisted/out-of-window, and owner-stale listings."""

    data = load_price_change_data(str(DEFAULT_DB_PATH))
    ups = data["ups"]
    downs = data["downs"]
    out_of_window = data["out_of_window"]
    offline = data["offline"]
    listings = data["listings"]

    # 5 metric cards
    cols = st.columns(5)
    cols[0].metric("📈 涨价", len(ups))
    cols[1].metric("📉 降价", len(downs))
    cols[2].metric("✕ 真下架", len(offline))
    cols[3].metric("⊙ 搜索出窗", len(out_of_window))
    if not listings.empty and "days_since_login" in listings.columns:
        stale = (listings["days_since_login"].dropna() > 30).sum()
    else:
        stale = 0
    cols[4].metric("⏳ 房主>30天未登录", int(stale))

    st.divider()

    col_up, col_down = st.columns(2)
    with col_up:
        st.subheader("📈 涨价房源")
        if ups.empty:
            st.info("暂无涨价记录。")
        else:
            show = ups[
                [
                    "community_name",
                    "title",
                    "previous_rent_price",
                    "rent_price",
                    "price_delta",
                    "price_delta_pct",
                    "observed_at",
                ]
            ].copy()
            show["变化"] = show.apply(
                lambda row: f"+{row['price_delta']} ({row['price_delta_pct']*100:+.1f}%)",
                axis=1,
            )
            st.dataframe(
                show.rename(
                    columns={
                        "community_name": "小区",
                        "title": "标题",
                        "previous_rent_price": "原价",
                        "rent_price": "现价",
                        "observed_at": "观测时间",
                    }
                )[["小区", "标题", "原价", "现价", "变化", "观测时间"]],
                use_container_width=True,
                hide_index=True,
            )
    with col_down:
        st.subheader("📉 降价房源")
        if downs.empty:
            st.info("暂无降价记录。")
        else:
            show = downs[
                [
                    "community_name",
                    "title",
                    "previous_rent_price",
                    "rent_price",
                    "price_delta",
                    "price_delta_pct",
                    "observed_at",
                ]
            ].copy()
            show["变化"] = show.apply(
                lambda row: f"{row['price_delta']} ({row['price_delta_pct']*100:+.1f}%)",
                axis=1,
            )
            st.dataframe(
                show.rename(
                    columns={
                        "community_name": "小区",
                        "title": "标题",
                        "previous_rent_price": "原价",
                        "rent_price": "现价",
                        "observed_at": "观测时间",
                    }
                )[["小区", "标题", "原价", "现价", "变化", "观测时间"]],
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    col_oow, col_off = st.columns(2)
    with col_oow:
        st.subheader("⊙ 搜索出窗 (out_of_window)")
        st.caption("历史在架, 但本次 API 搜索没出现 — 通常是 Wellcee 排序上限把老房源挤到窗外, 不一定真下架。")
        if out_of_window.empty:
            st.info("暂无。")
        else:
            st.dataframe(
                out_of_window[["community_name", "title", "district", "last_rent_price", "delisted_at"]]
                .rename(columns={"community_name": "小区", "title": "标题", "district": "区域",
                                  "last_rent_price": "上次租金", "delisted_at": "判定时间"}),
                use_container_width=True,
                hide_index=True,
                height=320,
            )
    with col_off:
        st.subheader("✕ 真下架 (offline)")
        st.caption("全量抓取确认, 这次确实没出现的房源。")
        if offline.empty:
            st.info("暂无。")
        else:
            st.dataframe(
                offline[["community_name", "title", "district", "last_rent_price", "delisted_at"]]
                .rename(columns={"community_name": "小区", "title": "标题", "district": "区域",
                                  "last_rent_price": "上次租金", "delisted_at": "判定时间"}),
                use_container_width=True,
                hide_index=True,
                height=320,
            )

    st.divider()
    st.subheader("⏳ 房主最后登录 (>30天标深灰)")
    if listings.empty or "days_since_login" not in listings.columns:
        st.info("暂无数据。")
        return
    df = listings.copy()

    def _stale_label(d: object) -> str:
        if d is None or (isinstance(d, float) and pd.isna(d)):
            return "未知"
        if d > 30:
            return "⚠ 深灰>30天"
        return f"{int(d)}天"

    df["stale"] = df["days_since_login"].apply(_stale_label)
    df = df.sort_values(by="days_since_login", ascending=False, na_position="last")
    st.dataframe(
        df[["community_name", "title", "district", "rent_price", "host_last_login_at", "stale"]]
        .rename(columns={
            "community_name": "小区", "title": "标题", "district": "区域",
            "rent_price": "租金", "host_last_login_at": "最后登录",
        }),
        use_container_width=True,
        hide_index=True,
        height=420,
    )


if __name__ == "__main__":
    main()
