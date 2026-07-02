"""RentalScout 命令行入口。"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from scrapy.crawler import CrawlerProcess

from rentalscout.analysis.availability import reconcile_availability
from rentalscout.analysis.commute import (
    DEFAULT_DISTANCE_BUCKET_CSV,
    DEFAULT_DISTANCE_BUCKET_SUMMARY_JSON,
    DEFAULT_WORKPLACE_ID,
    DEFAULT_WORKPLACE_NAME,
    Workplace,
    generate_distance_bucket_outputs,
    resolve_workplace_from_amap,
)
from rentalscout.analysis.geo_clusters import (
    DEFAULT_CLUSTER_EPS_METERS,
    DEFAULT_CLUSTER_MIN_SAMPLES,
    DEFAULT_GEO_CLUSTER_CSV,
    DEFAULT_GEO_CLUSTER_SUMMARY_JSON,
    generate_geo_cluster_outputs,
)
from rentalscout.analysis.location_value import (
    DEFAULT_LOCATION_VALUE_CSV,
    DEFAULT_LOCATION_VALUE_SUMMARY_JSON,
    DEFAULT_NEARBY_RADIUS_METERS,
    generate_location_value_outputs,
)
from rentalscout.analysis.price_area import (
    DEFAULT_PRICE_AREA_CSV,
    DEFAULT_PRICE_AREA_SUMMARY_JSON,
    generate_price_area_outputs,
)
from rentalscout.analysis.wellcee_quality import (
    DEFAULT_WELLCEE_QUALITY_CSV,
    DEFAULT_WELLCEE_QUALITY_SUMMARY_JSON,
    generate_wellcee_quality_outputs,
)
from rentalscout.batch import (
    BeikeCaptchaStop,
    scrape_beike_detail_listings,
    scrape_beike_pages,
    scrape_wellcee_pages,
)
from rentalscout.crawl_control import BeikeCrawlControl, beike_profile_names
from rentalscout.fetch import fetch_public_page
from rentalscout.filters import ListingFilterResult, apply_phase1_filters
from rentalscout.inspect import summarize_html
from rentalscout.parsers.beike import parse_beike_listings
from rentalscout.parsers.wellcee import parse_wellcee_detail_title
from rentalscout.schemas.normalized import (
    ListingAvailabilityStatus,
    ListingType,
    NormalizedRentalListing,
)
from rentalscout.schemas.raw import SourceName
from rentalscout.sources import DEFAULT_SOURCE_ENTRIES
from rentalscout.spiders.beike import BeikeSpider
from rentalscout.spiders.wellcee import WellceeSpider
from rentalscout.storage.sqlite import DEFAULT_DB_PATH, upsert_listings
from rentalscout.validation.export import (
    DEFAULT_FILTER_CSV,
    DEFAULT_VALIDATION_CSV,
    export_filter_candidates,
    export_validation_sample,
)


def main(argv: Sequence[str] | None = None) -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stderr,
        )
    parser = argparse.ArgumentParser(prog="rentalscout")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scout-sources", help="抓取公开入口页并输出侦察摘要")

    scrapy_parser = subparsers.add_parser("scrapy-crawl", help="使用 Scrapy + curl_cffi 爬取")
    scrapy_parser.add_argument("spider", choices=["beike", "wellcee", "all"], help="爬虫名称")
    scrapy_parser.add_argument("--start-page", type=int, default=1, help="贝壳起始页")
    scrapy_parser.add_argument("--pages", type=int, default=None, help="页数上限")
    scrapy_parser.add_argument("--dry-run", action="store_true", help="仅展示统计, 不写库和导出")

    crawl_parser = subparsers.add_parser("crawl-phase1", help="执行阶段 1 批量抓取")
    crawl_parser.add_argument("--beike-pages", type=int, default=75, help="贝壳抓取页数上限")
    crawl_parser.add_argument("--beike-start-page", type=int, default=None, help="resume page")
    crawl_parser.add_argument("--beike-retries", type=int, default=3, help="每页重试次数")
    crawl_parser.add_argument("--beike-delay-min", type=float, default=10.0, help="翻页间隔最小值")
    crawl_parser.add_argument("--beike-delay-max", type=float, default=15.0, help="翻页间隔最大值")
    crawl_parser.add_argument(
        "--beike-profile",
        choices=beike_profile_names(),
        default=None,
        help="贝壳抓取限速档位; 传入后覆盖手动 delay 参数",
    )
    crawl_parser.add_argument(
        "--beike-adaptive",
        action="store_true",
        help="遇到 captcha 后记录下一次建议使用的更慢档位",
    )
    crawl_parser.add_argument(
        "--beike-list-delay-min",
        type=float,
        default=None,
        help="贝壳列表页请求间隔最小秒数; 未设置时沿用 --beike-delay-min",
    )
    crawl_parser.add_argument(
        "--beike-list-delay-max",
        type=float,
        default=None,
        help="贝壳列表页请求间隔最大秒数; 未设置时沿用 --beike-delay-max",
    )
    crawl_parser.add_argument(
        "--beike-detail-delay-min",
        type=float,
        default=None,
        help="贝壳详情页请求间隔最小秒数; 未设置时沿用 --beike-delay-min",
    )
    crawl_parser.add_argument(
        "--beike-detail-delay-max",
        type=float,
        default=None,
        help="贝壳详情页请求间隔最大秒数; 未设置时沿用 --beike-delay-max",
    )
    crawl_parser.add_argument(
        "--beike-human-break-every",
        type=int,
        default=7,
        help="贝壳每抓取多少个列表页后长暂停一次",
    )
    crawl_parser.add_argument(
        "--beike-human-break-min",
        type=float,
        default=60.0,
        help="贝壳长暂停最小秒数",
    )
    crawl_parser.add_argument(
        "--beike-human-break-max",
        type=float,
        default=120.0,
        help="贝壳长暂停最大秒数",
    )
    crawl_parser.add_argument(
        "--beike-detail-limit",
        type=int,
        default=None,
        help="贝壳详情页抓取上限, 默认抓取所有通过粗过滤的候选",
    )
    crawl_parser.add_argument("--wellcee-pages", type=int, default=None, help="Wellcee pages")
    crawl_parser.add_argument("--wellcee-retries", type=int, default=3, help="每页 API 重试次数")
    crawl_parser.add_argument("--detail-limit", type=int, default=12, help="Wellcee 详情页抓取上限")
    crawl_parser.add_argument("--dry-run", action="store_true", help="仅展示统计, 不写库和导出")
    crawl_parser.add_argument(
        "--reconcile-availability",
        action="store_true",
        help="全量抓取后标记下架房源(仅在抓满当前口径全部页时生效)",
    )

    quality_parser = subparsers.add_parser(
        "analyze-wellcee-quality",
        help="生成 Wellcee 数据质量分析",
    )
    quality_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite 数据库路径")
    quality_parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_WELLCEE_QUALITY_CSV),
        help="质量明细 CSV 输出路径",
    )
    quality_parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_WELLCEE_QUALITY_SUMMARY_JSON),
        help="质量摘要 JSON 输出路径",
    )

    geocode_parser = subparsers.add_parser("resolve-workplace", help="用高德解析工作地点坐标")
    geocode_parser.add_argument(
        "--workplace-id",
        default=DEFAULT_WORKPLACE_ID,
        help="工作地点 ID",
    )
    geocode_parser.add_argument(
        "--workplace-name",
        default=DEFAULT_WORKPLACE_NAME,
        help="工作地点名称",
    )
    geocode_parser.add_argument("--city", default="上海", help="地理编码城市")
    geocode_parser.add_argument("--amap-key", default=None, help="高德 Web 服务 API key")

    distance_parser = subparsers.add_parser("analyze-distance-buckets", help="生成直线距离分桶")
    distance_parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 数据库路径",
    )
    distance_parser.add_argument(
        "--workplace-id",
        default=DEFAULT_WORKPLACE_ID,
        help="工作地点 ID",
    )
    distance_parser.add_argument(
        "--workplace-name",
        default=DEFAULT_WORKPLACE_NAME,
        help="工作地点名称",
    )
    distance_parser.add_argument("--workplace-lng", type=float, default=None, help="工作地点经度")
    distance_parser.add_argument("--workplace-lat", type=float, default=None, help="工作地点纬度")
    distance_parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_DISTANCE_BUCKET_CSV),
        help="直线距离分桶 CSV 输出路径",
    )
    distance_parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_DISTANCE_BUCKET_SUMMARY_JSON),
        help="直线距离分桶摘要 JSON 输出路径",
    )

    price_area_parser = subparsers.add_parser("analyze-price-area", help="生成价格与面积分析")
    price_area_parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 数据库路径",
    )
    price_area_parser.add_argument(
        "--distance-bucket-csv",
        default=str(DEFAULT_DISTANCE_BUCKET_CSV),
        help="直线距离分桶 CSV 输入路径",
    )
    price_area_parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_PRICE_AREA_CSV),
        help="价格面积分析 CSV 输出路径",
    )
    price_area_parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_PRICE_AREA_SUMMARY_JSON),
        help="价格面积分析摘要 JSON 输出路径",
    )

    location_parser = subparsers.add_parser("analyze-location-value", help="生成位置价值分析")
    location_parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 数据库路径",
    )
    location_parser.add_argument(
        "--price-area-csv",
        default=str(DEFAULT_PRICE_AREA_CSV),
        help="价格面积分析 CSV 输入路径",
    )
    location_parser.add_argument(
        "--nearby-radius-meters",
        type=int,
        default=DEFAULT_NEARBY_RADIUS_METERS,
        help="附近比较半径, 单位米",
    )
    location_parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_LOCATION_VALUE_CSV),
        help="位置价值分析 CSV 输出路径",
    )
    location_parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_LOCATION_VALUE_SUMMARY_JSON),
        help="位置价值分析摘要 JSON 输出路径",
    )

    geo_cluster_parser = subparsers.add_parser("analyze-geo-clusters", help="生成经纬度聚类分析")
    geo_cluster_parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 数据库路径",
    )
    geo_cluster_parser.add_argument(
        "--eps-meters",
        type=int,
        default=DEFAULT_CLUSTER_EPS_METERS,
        help="DBSCAN 邻域半径, 单位米",
    )
    geo_cluster_parser.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_CLUSTER_MIN_SAMPLES,
        help="形成核心点所需的最小样本数",
    )
    geo_cluster_parser.add_argument(
        "--csv-path",
        default=str(DEFAULT_GEO_CLUSTER_CSV),
        help="经纬度聚类 CSV 输出路径",
    )
    geo_cluster_parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_GEO_CLUSTER_SUMMARY_JSON),
        help="经纬度聚类摘要 JSON 输出路径",
    )

    args = parser.parse_args(argv)
    if args.command == "scout-sources":
        return scout_sources()
    if args.command == "scrapy-crawl":
        return scrapy_crawl(
            spider=args.spider,
            start_page=args.start_page,
            max_pages=args.pages,
            dry_run=args.dry_run,
        )
    if args.command == "crawl-phase1":
        return crawl_phase1(
            beike_pages=args.beike_pages,
            beike_start_page=args.beike_start_page,
            beike_retries=args.beike_retries,
            beike_delay_min=args.beike_delay_min,
            beike_delay_max=args.beike_delay_max,
            beike_profile=args.beike_profile,
            beike_adaptive=args.beike_adaptive,
            beike_list_delay_min=args.beike_list_delay_min,
            beike_list_delay_max=args.beike_list_delay_max,
            beike_detail_delay_min=args.beike_detail_delay_min,
            beike_detail_delay_max=args.beike_detail_delay_max,
            beike_human_break_every=args.beike_human_break_every,
            beike_human_break_min=args.beike_human_break_min,
            beike_human_break_max=args.beike_human_break_max,
            beike_detail_limit=args.beike_detail_limit,
            wellcee_pages=args.wellcee_pages,
            wellcee_retries=args.wellcee_retries,
            detail_limit=args.detail_limit,
            dry_run=args.dry_run,
            reconcile_wellcee=args.reconcile_availability,
        )
    if args.command == "analyze-wellcee-quality":
        return analyze_wellcee_quality_command(
            db_path=args.db_path,
            csv_path=args.csv_path,
            summary_path=args.summary_path,
        )
    if args.command == "resolve-workplace":
        return resolve_workplace_command(
            workplace_id=args.workplace_id,
            workplace_name=args.workplace_name,
            city=args.city,
            amap_key=args.amap_key,
        )
    if args.command == "analyze-distance-buckets":
        return analyze_distance_buckets_command(
            db_path=args.db_path,
            workplace_id=args.workplace_id,
            workplace_name=args.workplace_name,
            workplace_lng=args.workplace_lng,
            workplace_lat=args.workplace_lat,
            csv_path=args.csv_path,
            summary_path=args.summary_path,
        )
    if args.command == "analyze-price-area":
        return analyze_price_area_command(
            db_path=args.db_path,
            distance_bucket_csv=args.distance_bucket_csv,
            csv_path=args.csv_path,
            summary_path=args.summary_path,
        )
    if args.command == "analyze-location-value":
        return analyze_location_value_command(
            db_path=args.db_path,
            price_area_csv=args.price_area_csv,
            nearby_radius_meters=args.nearby_radius_meters,
            csv_path=args.csv_path,
            summary_path=args.summary_path,
        )
    if args.command == "analyze-geo-clusters":
        return analyze_geo_clusters_command(
            db_path=args.db_path,
            eps_meters=args.eps_meters,
            min_samples=args.min_samples,
            csv_path=args.csv_path,
            summary_path=args.summary_path,
        )
    parser.error(f"未知命令: {args.command}")
    return 2


def analyze_wellcee_quality_command(*, db_path: str, csv_path: str, summary_path: str) -> int:
    """生成 Wellcee 质量分析输出。"""

    rows, summary = generate_wellcee_quality_outputs(
        db_path=Path(db_path),
        csv_path=Path(csv_path),
        summary_path=Path(summary_path),
    )
    print("## Wellcee 数据质量分析")
    print(f"- 输入 SQLite: {db_path}")
    print(f"- 房源数量: {len(rows)}")
    print(f"- ready: {summary['tiers']['ready']}")
    print(f"- caution: {summary['tiers']['caution']}")
    print(f"- blocked: {summary['tiers']['blocked']}")
    print(f"- 明细 CSV: {csv_path}")
    print(f"- 摘要 JSON: {summary_path}")
    return 0


def resolve_workplace_command(
    *,
    workplace_id: str,
    workplace_name: str,
    city: str,
    amap_key: str | None,
) -> int:
    """解析工作地点坐标。"""

    try:
        workplace = resolve_workplace_from_amap(
            name=workplace_name,
            workplace_id=workplace_id,
            city=city,
            api_key=amap_key,
        )
    except ValueError as error:
        print(f"工作地点解析失败: {error}")
        return 1

    print("## 工作地点坐标")
    print(f"- ID: {workplace.workplace_id}")
    print(f"- 名称: {workplace.name}")
    print(f"- 经度: {workplace.longitude}")
    print(f"- 纬度: {workplace.latitude}")
    return 0


def analyze_distance_buckets_command(
    *,
    db_path: str,
    workplace_id: str,
    workplace_name: str,
    workplace_lng: float | None,
    workplace_lat: float | None,
    csv_path: str,
    summary_path: str,
) -> int:
    """生成直线距离分桶输出。"""

    resolved_lng = workplace_lng
    resolved_lat = workplace_lat
    if resolved_lng is None or resolved_lat is None:
        print("缺少工作地点坐标: 请传入 --workplace-lng 和 --workplace-lat")
        print("工作地点坐标不会从 .env 读取, 避免泄露隐私位置。")
        return 2

    workplace = Workplace(
        workplace_id=workplace_id,
        name=workplace_name,
        longitude=resolved_lng,
        latitude=resolved_lat,
    )
    rows, summary = generate_distance_bucket_outputs(
        workplace=workplace,
        db_path=Path(db_path),
        csv_path=Path(csv_path),
        summary_path=Path(summary_path),
    )
    print("## 直线距离分桶")
    print(f"- 输入 SQLite: {db_path}")
    print(f"- 工作地点: {workplace_name} ({resolved_lng}, {resolved_lat})")
    print(f"- 房源数量: {len(rows)}")
    print(f"- 4km以内: {summary['distance_buckets']['within_4km']}")
    print(f"- 4-8km: {summary['distance_buckets']['4_to_8km']}")
    print(f"- 8-12km: {summary['distance_buckets']['8_to_12km']}")
    print(f"- 12km以外: {summary['distance_buckets']['over_12km']}")
    print(f"- 明细 CSV: {csv_path}")
    print(f"- 摘要 JSON: {summary_path}")
    return 0


def analyze_price_area_command(
    *,
    db_path: str,
    distance_bucket_csv: str,
    csv_path: str,
    summary_path: str,
) -> int:
    """生成价格与面积分析输出。"""

    rows, summary = generate_price_area_outputs(
        db_path=Path(db_path),
        distance_bucket_csv=Path(distance_bucket_csv),
        csv_path=Path(csv_path),
        summary_path=Path(summary_path),
    )
    print("## 价格与面积分析")
    print(f"- 输入 SQLite: {db_path}")
    print(f"- 距离分桶 CSV: {distance_bucket_csv}")
    print(f"- 房源数量: {len(rows)}")
    print(f"- 租金低于同距离桶 p25: {summary['labels']['good_price']}")
    print(f"- 单价低于同距离桶 p25: {summary['labels']['good_area_price']}")
    print(f"- 租金高于同距离桶 p75: {summary['labels']['expensive']}")
    print(f"- 单价高于同距离桶 p75: {summary['labels']['area_price_expensive']}")
    print(f"- 明细 CSV: {csv_path}")
    print(f"- 摘要 JSON: {summary_path}")
    return 0


def analyze_location_value_command(
    *,
    db_path: str,
    price_area_csv: str,
    nearby_radius_meters: int,
    csv_path: str,
    summary_path: str,
) -> int:
    """生成位置价值分析输出。"""

    rows, summary = generate_location_value_outputs(
        db_path=Path(db_path),
        price_area_csv=Path(price_area_csv),
        csv_path=Path(csv_path),
        summary_path=Path(summary_path),
        nearby_radius_meters=nearby_radius_meters,
    )
    print("## 位置价值分析")
    print(f"- 输入 SQLite: {db_path}")
    print(f"- 价格面积 CSV: {price_area_csv}")
    print(f"- 附近比较半径: {nearby_radius_meters} 米")
    print(f"- 房源数量: {len(rows)}")
    print(f"- 附近比较可用: {summary['coverage']['nearby_enabled']}")
    print(f"- 同小区比较可用: {summary['coverage']['community_enabled']}")
    print(f"- 附近低租金: {summary['labels']['below_nearby_median']}")
    print(f"- 附近低单价: {summary['labels']['nearby_good_value']}")
    print(f"- 附近高单价: {summary['labels']['nearby_expensive']}")
    print(f"- 明细 CSV: {csv_path}")
    print(f"- 摘要 JSON: {summary_path}")
    return 0


def analyze_geo_clusters_command(
    *,
    db_path: str,
    eps_meters: int,
    min_samples: int,
    csv_path: str,
    summary_path: str,
) -> int:
    """生成经纬度聚类分析输出。"""

    try:
        rows, summary = generate_geo_cluster_outputs(
            db_path=Path(db_path),
            csv_path=Path(csv_path),
            summary_path=Path(summary_path),
            eps_meters=eps_meters,
            min_samples=min_samples,
        )
    except ValueError as error:
        print(f"经纬度聚类参数无效: {error}")
        return 2

    print("## 经纬度聚类分析")
    print(f"- 输入 SQLite: {db_path}")
    print(f"- 聚类半径: {eps_meters} 米")
    print(f"- 最小样本数: {min_samples}")
    print(f"- 房源数量: {len(rows)}")
    print(f"- 空间簇数量: {summary['cluster_count']}")
    print(f"- 已聚类房源: {summary['clustered_listings']}")
    print(f"- 离群房源: {summary['noise_listings']}")
    print(f"- 明细 CSV: {csv_path}")
    print(f"- 摘要 JSON: {summary_path}")
    return 0


def scout_sources() -> int:
    exit_code = 0

    for entry in DEFAULT_SOURCE_ENTRIES:
        result = fetch_public_page(entry.source, entry.url)
        raw_page = result.raw_page
        print(f"## {entry.name}")
        print(f"- URL: {entry.url}")
        print(f"- 状态码: {raw_page.status_code or '无'}")
        print(f"- 内容类型: {raw_page.content_type or '无'}")
        print(f"- 原始文件: {raw_page.raw_path or '未保存'}")
        print(f"- 错误: {raw_page.error_message or '无'}")

        if result.body:
            summary = summarize_html(result.body, entry.url)
            print(f"- 页面标题: {summary.title or '无'}")
            print(f"- 页面大小: {summary.body_size} 字节")
            print(f"- 链接数量: {summary.link_count}")
            print(f"- 是否包含前端数据标记: {'是' if summary.contains_next_data else '否'}")
            if summary.links:
                print("- 链接样本:")
                for link in summary.links[:8]:
                    print(f"  - {link}")
        else:
            exit_code = 1
        print()

    return exit_code


def scrapy_crawl(
    *,
    spider: str = "all",
    start_page: int = 1,
    max_pages: int | None = None,
    dry_run: bool = False,
) -> int:
    """Run Scrapy spiders with curl_cffi download handler."""
    settings = {
        "ITEM_PIPELINES": {
            "rentalscout.pipelines.Phase1FilterPipeline": 100,
            "rentalscout.pipelines.StoragePipeline": 200,
            "rentalscout.pipelines.ExportPipeline": 300,
        },
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "LOG_LEVEL": "INFO",
    }
    if dry_run:
        settings["ITEM_PIPELINES"] = {
            "rentalscout.pipelines.Phase1FilterPipeline": 100,
        }

    process = CrawlerProcess(settings)

    spiders_to_run = ["beike", "wellcee"] if spider == "all" else [spider]

    for name in spiders_to_run:
        if name == "beike":
            process.crawl(
                BeikeSpider,
                start_page=start_page,
                max_pages=max_pages or 75,
            )
        elif name == "wellcee":
            process.crawl(WellceeSpider, max_pages=max_pages)

    process.start()
    return 0


def crawl_phase1(
    *,
    beike_pages: int = 75,
    beike_start_page: int | None = None,
    beike_retries: int = 3,
    beike_delay_min: float = 5.0,
    beike_delay_max: float = 8.0,
    beike_profile: str | None = None,
    beike_adaptive: bool = False,
    beike_list_delay_min: float | None = None,
    beike_list_delay_max: float | None = None,
    beike_detail_delay_min: float | None = None,
    beike_detail_delay_max: float | None = None,
    beike_human_break_every: int = 7,
    beike_human_break_min: float = 60.0,
    beike_human_break_max: float = 120.0,
    beike_detail_limit: int | None = None,
    wellcee_pages: int | None = None,
    wellcee_retries: int = 3,
    detail_limit: int = 12,
    dry_run: bool = False,
    reconcile_wellcee: bool = False,
) -> int:
    """执行阶段 1 批量抓取、解析、过滤、写库和验证样本导出。"""

    accepted: list[NormalizedRentalListing] = []
    filter_results: list[ListingFilterResult] = []

    # -- Beike batch --
    start_info = beike_start_page or "auto"
    list_delay_range = (
        beike_list_delay_min or beike_delay_min,
        beike_list_delay_max or beike_delay_max,
    )
    detail_delay_range = (
        beike_detail_delay_min or beike_delay_min,
        beike_detail_delay_max or beike_delay_max,
    )
    list_control = BeikeCrawlControl(
        profile_name=beike_profile,
        adaptive=beike_adaptive,
        delay_range=list_delay_range,
        human_break_every=beike_human_break_every,
        human_break_range=(beike_human_break_min, beike_human_break_max),
    )
    detail_control = BeikeCrawlControl(
        profile_name=beike_profile,
        adaptive=beike_adaptive,
        delay_range=detail_delay_range,
        human_break_every=beike_human_break_every,
        human_break_range=(beike_human_break_min, beike_human_break_max),
    )
    print(f"## Beike batch (pages {start_info}-{beike_pages})")
    print(f"- profile: {beike_profile or 'manual'}")
    print(f"- list delay: {list_control.delay_range[0]}-{list_control.delay_range[1]}s")
    print(f"- detail delay: {detail_control.delay_range[0]}-{detail_control.delay_range[1]}s")
    beike_parsed: list[NormalizedRentalListing] = []
    beike_detail_seen = 0
    for page_num, html in scrape_beike_pages(
        start_page=beike_start_page,
        max_pages=beike_pages,
        retry_attempts=beike_retries,
        delay_range=list_control.delay_range,
        human_break_every=beike_human_break_every,
        human_break_range=(beike_human_break_min, beike_human_break_max),
        crawl_control=list_control,
    ):
        parsed = parse_beike_listings(html, "https://sh.zu.ke.com")
        beike_parsed.extend(parsed)
        print(f"  Page {page_num}: {len(parsed)} listings parsed")
        beike_pre_results = [apply_phase1_filters(listing) for listing in parsed]
        beike_candidates = [r.listing for r in beike_pre_results if r.accepted]
        if beike_detail_limit is not None:
            remaining = beike_detail_limit - beike_detail_seen
            beike_candidates = [] if remaining <= 0 else beike_candidates[:remaining]
        print(f"  Page {page_num}: {len(beike_candidates)} detail candidates")

        filter_results.extend(r for r in beike_pre_results if not r.accepted)
        try:
            for detail_listing in scrape_beike_detail_listings(
                beike_candidates,
                retry_attempts=beike_retries,
                delay_range=detail_control.delay_range,
                crawl_control=detail_control,
            ):
                beike_detail_seen += 1
                detail_result = apply_phase1_filters(detail_listing)
                filter_results.append(detail_result)
                if not detail_result.accepted:
                    continue
                accepted.append(detail_result.listing)
                if not dry_run:
                    upsert_listings([detail_result.listing])
        except BeikeCaptchaStop as error:
            print(f"- Beike captcha stop: {error}")
            break

    beike_accepted_count = sum(
        1
        for result in filter_results
        if result.listing.source == SourceName.BEIKE and result.accepted
    )
    print(f"- beike total parsed: {len(beike_parsed)}")
    print(f"- detail pages parsed or reused: {beike_detail_seen}")
    print(f"- accepted after detail filter: {beike_accepted_count}")
    print()

    # -- Wellcee batch --
    print("## Wellcee batch")
    wellcee_all_listings: list[NormalizedRentalListing] = []
    wellcee_pages_fetched = scrape_wellcee_pages(
        max_pages=wellcee_pages,
        retry_attempts=wellcee_retries,
    )
    wellcee_all_listings = [listing for p in wellcee_pages_fetched for listing in p.listings]
    print(f"- Wellcee 批页数: {len(wellcee_pages_fetched)}")
    if wellcee_pages_fetched:
        print(f"- Wellcee 批总数: {wellcee_pages_fetched[0].total}")
    print(f"- Wellcee 批解析: {len(wellcee_all_listings)}")

    wellcee_results = _filter_wellcee_with_details(
        wellcee_all_listings,
        detail_limit=detail_limit,
    )
    wellcee_accepted = [r.listing for r in wellcee_results if r.accepted]
    print(f"- 过滤后数量: {len(wellcee_accepted)}")
    filter_results.extend(wellcee_results)
    accepted.extend(wellcee_accepted)
    print()

    # -- Summary --
    print("## Phase1 summary")
    print(f"- total parsed: {len(beike_parsed) + len(wellcee_all_listings)}")
    print(f"- accepted: {len(accepted)}")
    print(f"- rejected: {len(filter_results) - len(accepted)}")

    if dry_run:
        print("- [dry-run] skip write and export")
        return 0

    written = upsert_listings(accepted)
    exported = export_validation_sample(accepted)
    exported_candidates = export_filter_candidates(filter_results)
    print("\n## Output")
    print(f"- SQLite: {DEFAULT_DB_PATH}")
    print(f"- written: {written}")
    print(f"- validation CSV: {DEFAULT_VALIDATION_CSV}")
    print(f"- validation sample: {exported}")
    print(f"- filter candidates CSV: {DEFAULT_FILTER_CSV}")
    print(f"- filter records: {exported_candidates}")

    if reconcile_wellcee:
        total = wellcee_pages_fetched[0].total if wellcee_pages_fetched else 0
        _reconcile_wellcee_availability(wellcee_all_listings, total=total)
    return 0


def _reconcile_wellcee_availability(
    parsed: list[NormalizedRentalListing],
    *,
    total: int,
) -> None:
    """全量抓取后标记下架/出窗房源。"""

    print("\n## 下架/出窗检测")
    seen_ids = [listing.source_listing_id for listing in parsed if listing.source_listing_id]
    seen_total = total if total > 0 else None
    result = reconcile_availability(seen_ids, seen_total=seen_total)
    coverage = "全量" if result.is_full_crawl else "非全量"
    print(f"- 抓取: {result.saw_unique}/{result.saw_total} ({coverage})")
    print(f"- 口径内历史房源: {result.scope_total}")
    print(f"- 仍在架: {result.in_scope_active}")
    if result.is_full_crawl:
        print(f"- 本次新增下架: {result.newly_offline}")
        print(f"- 此前已下架: {result.already_offline}")
    else:
        print(f"- 本次新增出窗(被搜索上限挤出): {result.newly_out_of_window}")
        print(f"- 此前已出窗: {result.already_out_of_window}")
    for item in result.delisted[:10]:
        name = item.community_name or item.title[:20]
        status = "出窗" if item.status == ListingAvailabilityStatus.OUT_OF_WINDOW else "下架"
        print(f"  · [{status}] {name} (上次 {item.last_rent_price} 元/月)")


def _filter_wellcee_with_details(
    listings: list[NormalizedRentalListing],
    *,
    detail_limit: int,
) -> list[ListingFilterResult]:
    results: list[ListingFilterResult] = []
    detail_fetches = 0
    for listing in listings:
        first_pass = apply_phase1_filters(listing)
        if not first_pass.accepted:
            results.append(first_pass)
            continue

        detail_title = None
        if detail_fetches < detail_limit:
            detail_fetches += 1
            detail_result = fetch_public_page(SourceName.WELLCEE, str(listing.source_url))
            if detail_result.body:
                detail_title = parse_wellcee_detail_title(
                    detail_result.body,
                    str(listing.source_url),
                )

        enriched_listing = _with_wellcee_detail_title(listing, detail_title)
        detail_filter = apply_phase1_filters(enriched_listing, detail_title=detail_title)
        results.append(detail_filter)
    return results


def _with_wellcee_detail_title(
    listing: NormalizedRentalListing,
    detail_title: str | None,
) -> NormalizedRentalListing:
    if not detail_title:
        return listing
    listing_type = ListingType.SUBLET if "转租" in detail_title else listing.listing_type
    if "整租" in detail_title:
        listing_type = ListingType.WHOLE_RENT
    return listing.model_copy(
        update={
            "description": detail_title,
            "listing_type": listing_type,
            "parse_confidence": max(listing.parse_confidence, 0.65),
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
