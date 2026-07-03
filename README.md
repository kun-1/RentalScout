# RentalScout

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-Local_Data-003B57?style=for-the-badge&logo=sqlite&logoColor=white">
  <img alt="Scrapy" src="https://img.shields.io/badge/Scrapy-Crawling-60A839?style=for-the-badge">
  <img alt="Leaflet" src="https://img.shields.io/badge/Leaflet-Map_View-199900?style=for-the-badge&logo=leaflet&logoColor=white">
</p>

<p align="center">
  <b>一个把租房信息采集、清洗、地理分析和交互式筛选串起来的个人数据产品。</b>
</p>

RentalScout 聚焦上海浦东租房场景，把贝壳和 Wellcee 的房源统一整理到本地数据库，并提供地图、距离、价格、面积、位置价值和空间聚类等分析视图。它不是一个简单爬虫，而是一个从数据采集到决策界面的完整闭环：抓得到、洗得干净、看得清楚、能辅助选择。

## Demo

![Demo](assets/demo.gif)

## 项目亮点

- **真实需求驱动**：项目起源于对象准备换房。实际找房时需要在多个 App 之间反复切换，单个平台的数据量和视角都不够，很难看到区域、价格、通勤和房源质量的全貌。因此我开发了 RentalScout，用可视化方式把租房信息汇总起来，辅助租房决策，也为未来买房时的位置和价格判断提供数据基础。
- **数据源筛选过程真实**：在开发早期，我先和 AI 一起梳理国内主流租房 App，再按数据质量、可获取性和房源覆盖做取舍。最终选择贝壳租房和 Wellcee：贝壳的数据量更大，房源结构更稳定，整体质量更高；Wellcee 更偏无中介租房，能补充另一类真实租房需求。
- **技术选型围绕 MVP**：爬虫部分选择 Python，因为生态里有成熟的数据采集、解析、清洗和测试库；可视化选择 Streamlit，而不是更复杂的 JavaScript 前端，目标是尽快做出能用的本地 MVP；地图和位置能力接入高德地图 API，用于小区经纬度补全和工作中心切换。
- **地图优先体验**：以工作地点为中心查看房源分布、距离桶、空间簇和附近房源性价比。
- **可恢复采集流程**：贝壳抓取支持断点恢复、详情页缓存复用、验证码人工介入提醒和 adaptive 降速策略。
- **本地优先与隐私友好**：数据保存在本地 SQLite；工作地点坐标不写入 `.env`，避免泄露隐私位置。
- **可解释分析**：价格、面积、距离、附近比较和聚类结果都保留可追溯字段，方便复核而不是只给黑盒打分。

## 能做什么

RentalScout 当前覆盖四个核心环节：

1. **采集**：从 Wellcee API/详情页和贝壳列表/详情页获取房源信息。
2. **清洗**：统一价格、面积、户型、小区、板块、经纬度、来源链接和**房主最后登录时间**等字段。
3. **分析**：计算距离分桶、价格面积分位数、附近房源价值、空间聚类、数据质量标签、价格变化时序和**下架/出窗判定**。
4. **展示**：用 Streamlit 构建本地交互式工作台，在地图和表格中筛选候选房源。

## 产品界面

工作台包含 5 个标签：

- **地图筛选**：房源点位 + 聚类 + 距离同心圆；每个房源卡片内集成 **房主最后登录时间**（>30天/未登录有颜色提示）和 **历史价格变化**（↑涨价 / ↓降价 / 首次记录）。
- **候选房源**：按综合性价比、距离、租金、面积和来源链接审查候选。
- **分析解释**：把质量、距离、价格面积和附近比较整合成单套房源的推荐依据与注意事项。
- **数据质量**：保留质量分层、距离分桶、价格面积、位置价值和经纬度聚类等高级分析视图。
- **价格与下架**：5 个 metric（涨价 / 降价 / 真下架 / 搜索出窗 / 房主>30天未登录）+ 5 张明细表。

## 关键技术细节

- **价格变化追踪**：每次 `upsert_listings` 都会向 `listing_observations` 追加一条时间序列快照（含房主最后登录时间），用 `INSERT OR IGNORE` 防止同时间戳重复。`analyze_price_history` 在此之上计算 `price_delta`、`price_delta_pct`、`first_rent_price` 等可解释字段。
- **下架与出窗**：`reconcile_availability` 区分两种"消失"——`offline`（全量抓取下确实消失 = 真下架）和 `out_of_window`（被 Wellcee 528 条搜索上限挤出 = 不一定真下架，房源页面可能仍可访问）。CLI 默认不跑，需要时显式加 `--reconcile-availability`。
- **房主登录时效**：API 响应里 `loginTime` 字段直接存到 `rental_listings.host_last_login_at`，Streamlit 卡片和 tab 都用它做 >30 天未登录的视觉提示。验证表明，库内约 70% 的房源房主已超过 30 天未登录。
- **Schema 迁移**：用 SQLite `PRAGMA user_version` 维护 schema 版本（当前 v3）。每次启动自动检测旧版本并跑迁移：v2 重建曾被"漂移"加列的旧 observations 表，v3 加上 `host_last_login_at` 列。WAL 模式默认开启，Streamlit 读 + 爬虫写互不阻塞。
- **HTTP 栈统一**：`fetch.py` 和 `wellcee_api._post_json` 都用 `curl_cffi` + Chrome 指纹，与 `spiders/beike.py` 同一策略；详情页抓取内置 3 次指数退避重试。

## 技术能力展示

- Web 数据采集与反爬压力下的低频、可恢复抓取设计。
- Pydantic v2 数据建模和 SQLite 本地持久化（含 schema 迁移和 WAL）。
- 地理空间分析、Haversine 距离计算和 DBSCAN 风格聚类。
- 数据质量分层、异常检测和可解释标签设计。
- 时间序列观测（point-in-time listing snapshots）和价格变化分析。
- Streamlit + Leaflet 的本地分析工作台，含富 popup 卡片与图例。
- pytest / Ruff / mypy 驱动的质量保障 + GitHub Actions CI。

## 技术栈

| Layer | Stack |
| --- | --- |
| Language | Python 3.13 |
| Crawling | Scrapy, curl_cffi, Chrome profile scraping |
| Data Model | Pydantic v2 |
| Storage | SQLite (WAL + PRAGMA user_version 迁移) |
| Analysis | pandas, custom geospatial algorithms |
| UI | Streamlit, Leaflet |
| Tooling | uv, pytest, Ruff, mypy, GitHub Actions |

## 快速运行

安装依赖：

```bash
uv sync
```

启动工作台：

```bash
uv run streamlit run rentalscout/web/streamlit_app.py
```

运行测试：

```bash
uv run pytest
```

抓取贝壳数据示例：

```bash
uv run python scripts/extract_cookies.py
uv run python -m rentalscout.cli crawl-phase1 \
  --beike-pages 20 \
  --wellcee-pages 0 \
  --beike-profile safe \
  --beike-adaptive
```

## 当前状态

- Wellcee 数据链路较完整，适合作为主要分析来源。
- 贝壳已支持详情页解析、经纬度提取、断点恢复和限速 profile，但仍需要低频运行并保留人工处理验证码的空间。
- 数据采集仅用于个人研究和租房辅助决策，应遵守目标网站服务条款并避免高压抓取。

## 下一步

- 增加定时刷新任务，沉淀房源生命周期和价格变化。
- 继续优化贝壳采集的稳定性和 adaptive 降速策略。
- 将工作台进一步打磨成更接近真实租房决策工具的产品体验。
