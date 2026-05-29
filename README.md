# RentalScout

RentalScout 是一个面向个人租房决策的房源采集、清洗、验证、分析与交互式筛选工具。当前版本聚焦上海浦东租房场景，将贝壳和 Wellcee 的房源统一为标准化数据模型，再围绕价格、面积、通勤、空间密度和附近房源价值做本地分析。

## Demo

![Demo](assets/demo.gif)

## 项目结构

```text
rentalscout/
  spiders/        Scrapy 爬虫入口
  parsers/        贝壳、Wellcee 页面/API 解析
  analysis/       数据质量、通勤、价格、位置价值、空间聚类分析
  crawl_control.py 贝壳抓取限速、指标记录与 adaptive 状态
  storage/        SQLite 本地存储
  web/            Streamlit 分析工作台
scripts/          Cookie 提取、街道表构建等辅助脚本
data/             本地原始数据、SQLite、分析 CSV/JSON 输出
tests/            单元测试
```

## 数据层

RentalScout 的数据层以“原始响应留痕 + 标准化入库”为核心。爬虫先保存原始 HTML 或 JSON，再解析为统一的 `NormalizedRentalListing`，最后通过 SQLite upsert 写入 `data/rentalscout.sqlite3` 的 `rental_listings` 表。完整标准化 payload 会保存在 `payload_json` 中，便于后续分析复用和回溯。

### Wellcee 数据抓取

Wellcee 采用公开房源 API 与详情页 HTML 合并的方式采集：

- API 入口：`https://www.wellcee.com/api/v3/frontend/house/get`
- 请求方式：POST JSON payload
- 当前筛选条件：上海、浦东、整租、长租、一居、3500-6000 元/月
- 原始 API 响应保存到 `data/raw/wellcee/api/*.json`
- 每条 API item 会生成详情页 URL：`https://www.wellcee.com/rent-apartment/{listing_id}`
- 详情页中解析 `schema.org` 的 `RealEstateListing` JSON-LD，并补充 HTML 详情模块字段

Wellcee 字段合并策略为 `JSON-LD > HTML > API partial`。API 列表负责提供房源 ID、标题、价格、图片和初始坐标；详情页 JSON-LD 提供更完整的价格、面积、房间数、发布时间、经纬度、图片和地址；HTML 详情模块补充押金、楼层、地铁、类型等 JSON-LD 没有的字段。

街道/板块提取采用两段式策略：先查 `data/subdistricts/shanghai_pudong.json` 中的浦东街道前缀表，匹配失败后再用社区名启发式提取，最终为每条房源生成 `district`、`subdistrict`、`community_name` 等区域字段。

### 贝壳数据抓取

贝壳采用“列表页发现候选 + 详情页主解析”的两段式抓取：

- 当前入口：`https://sh.zu.ke.com/zufang/pudong/rt200600000001l0brp3500erp6000/`
- 翻页规则：第 2 页开始使用 `/pg{page}rt200600000001l0brp3500erp6000/`
- 当前筛选条件：上海浦东、整租、一居、3500-6000 元/月
- 列表页原始 HTML 保存到 `data/raw/beike/*.html`
- 详情页原始 HTML 保存到 `data/raw/beike/detail/*.html`

贝壳有两套抓取路径：

- `rentalscout/spiders/beike.py` 使用 Scrapy 调度，实际请求由 `curl_cffi` 以 Chrome TLS 指纹发起，并读取 `data/beike_cookies.json` 中的登录 Cookie；列表页解析后会进入详情页解析。
- `rentalscout/batch.py` 调用本机 Chrome browser-tools 脚本抓取页面，复用真实 Chrome profile，并支持随机延迟、定期长暂停、验证码检测、人工介入提醒和断点续抓。

列表页只用于提取房源 URL、房源 ID、标题、价格和基础区域信息，并先做一次粗过滤；只有符合目标条件的候选才会请求详情页。详情页解析价格、面积、户型、楼层、朝向、入住时间、地铁、经纬度、小区名和板块，并将中介来源标记为 `LandlordType.AGENCY`。贝壳不保存图片 URL，查看图片时直接跳转 `source_url` 到原始详情页。

贝壳批量抓取还会写入真实运行指标：

- `data/crawl_runs/beike_metrics.jsonl`：记录列表页和详情页请求结果、耗时、HTML 大小、captcha、缓存复用和 raw path。
- `data/crawl_runs/beike_state.json`：在 `--beike-adaptive` 模式下记录下一次建议使用的更慢抓取档位。

内置限速档位包括 `fast`、`balanced`、`safe` 和 `ultra`。遇到 captcha 时，抓取会停止、发出终端响铃和 macOS 通知，并把触发 captcha 的 URL 打开到 Chrome 新标签，方便人工处理。重新运行同一命令时，已保存的列表页和详情页 HTML 会被复用，不会重复下载。

### 本地存储

SQLite 表结构保持轻量：

- `rental_listings`：按 `(source, source_listing_id)` 去重保存标准化房源。
- `crawl_runs`：预留采集运行记录。

写入策略使用 SQLite `ON CONFLICT DO UPDATE`，同一来源同一房源再次采集时只更新最新字段和 `last_seen_at`，保留统一 JSON payload 作为分析层输入。

## 分析层

分析层位于 `rentalscout/analysis/`，主要针对 Wellcee 的结构化数据运行，因为 Wellcee 当前包含更完整的经纬度、面积和发布时间。

### 数据质量准入

`wellcee_quality.py` 为每条房源生成分析可用性标签：

- 核心字段检查：价格、面积、经纬度、区域、户型、图片、发布时间。
- 价格范围检查：默认 3500-6000 元/月。
- 面积与单价异常检测：面积需在 10-120 平米，单位面积租金需在 40-300 元/平米/月。
- 坐标校验：经纬度需落在上海范围内，且当前地图分析要求 `district == "浦东"`。
- 公寓识别：用关键词匹配“公寓、自如、魔方、泊寓、冠寓、青年公寓”等集中式房源。
- 重复候选识别：按标题、租金、小区名构造重复 key。
- 街道低置信度识别：过滤地铁站、道路、线路等非街道文本。

质量结果会分为 `ready`、`caution`、`blocked` 三档，并导出 `data/analysis/wellcee_quality.csv` 和摘要 JSON。

### 工作中心与距离分析

`commute.py` 结合高德地图 Web 服务 API 和本地距离算法计算工作中心相关指标：

- `resolve-workplace` 调用高德地理编码 API，将工作地点名称解析为经纬度。
- `analyze-distance-buckets` 使用 Haversine 公式计算房源到工作地点的球面直线距离。
- 距离分桶：`within_4km`、`4_to_8km`、`8_to_12km`、`over_12km`。

工作中心坐标不写入 `.env`，避免泄露隐私位置；`.env` 只需要保存 `AMAP_API_KEY`。工作台中切换工作中心后，会即时重算直线距离、距离分桶和同距离桶内的价格/面积性价比。

高德地理编码原始响应会保存到 `data/raw/amap/`，便于复核 API 返回。

### 价格与面积分析

`price_area.py` 基于距离分桶做价格分布比较：

- 计算每条房源的 `rent_per_sqm = rent_price / area_sqm`。
- 在同一距离桶内计算租金和单位面积租金的 `min`、`p25`、`median`、`p75`、`max`、`IQR`。
- 计算房源在同距离桶内的价格百分位和单价百分位。
- 标记低价、低单价、高价、高单价。
- 使用 IQR 规则识别低价异常和高价异常。
- 当同小区样本数不少于 3 条时，启用同小区中位数辅助比较。

该层输出 `data/analysis/price_area_analysis.csv` 和 `price_area_summary.json`。

### 位置价值分析

`location_value.py` 用空间邻近关系和同小区关系评估“同位置下是否划算”：

- 默认以 1000 米为附近房源半径。
- 使用 Haversine 公式计算两套房源之间的距离。
- 附近样本数不少于 5 条时，计算附近租金中位数和单位面积租金中位数。
- 同小区样本数不少于 3 条时，计算同小区价格分布。
- 标记“低于附近中位数”“附近低单价”“附近高单价”“同小区最低租金”“同小区最低单位面积租金”等标签。

位置价值分析依赖前置的价格面积输出，结果写入 `data/analysis/location_value_analysis.csv`。

### 经纬度空间聚类

`geo_clusters.py` 实现了 DBSCAN 风格的空间聚类算法，用于识别房源密集区域：

- 默认半径 `eps_meters = 800` 米。
- 默认最小样本数 `min_samples = 5`。
- 两点距离使用 Haversine 公式。
- 每个点先构建邻域列表，再按 DBSCAN 扩展核心点、边界点和噪声点。
- 输出空间簇 ID、簇大小、是否核心点、邻居数量、簇中心点、到簇中心距离。
- 未进入任何簇的房源标记为 `noise`。

该算法不依赖 scikit-learn，当前为项目内纯 Python 实现，便于按租房场景调整参数和解释结果。

## 交互式工作台

项目提供 Streamlit 分析工作台：

```bash
uv run streamlit run rentalscout/web/streamlit_app.py
```

工作台包含：

- 地图视图：基于 Leaflet 渲染房源点位，并使用高德瓦片作为底图。
- 质量页：查看 ready/caution/blocked 和字段缺失风险。
- 距离页：查看工作地点直线距离分桶。
- 价格面积页：查看租金、单价、分位数和异常标签。
- 位置价值页：查看附近房源和同小区比较。
- 经纬度聚类页：调整 DBSCAN 半径和最小样本数，预览并保存空间簇结果。
- 房源表：查看合并后的房源明细。

## 常用命令

安装依赖：

```bash
uv sync
```

侦察公开入口页：

```bash
uv run python -m rentalscout.cli scout-sources
```

抓取 Wellcee：

```bash
uv run python -m rentalscout.cli scrapy-crawl wellcee --pages 3
```

抓取贝壳前先导出 Cookie：

```bash
uv run python scripts/extract_cookies.py
uv run python -m rentalscout.cli crawl-phase1 --beike-pages 20 --wellcee-pages 0 --beike-profile safe --beike-adaptive
```

贝壳抓取支持手动调参和 profile 调参。推荐先从 `balanced` 开始试跑；如果在详情页阶段触发 captcha，则切换到 `safe` 或继续使用 `--beike-adaptive` 读取上次建议档位：

```bash
uv run python -m rentalscout.cli crawl-phase1 \
  --beike-pages 20 \
  --wellcee-pages 0 \
  --beike-profile balanced \
  --beike-adaptive
```

生成质量分析：

```bash
uv run python -m rentalscout.cli analyze-wellcee-quality
```

用高德解析工作地点坐标：

```bash
uv run python -m rentalscout.cli resolve-workplace --amap-key YOUR_AMAP_KEY
```

生成距离分桶：

```bash
uv run python -m rentalscout.cli analyze-distance-buckets --workplace-lng YOUR_LNG --workplace-lat YOUR_LAT
```

生成价格面积分析：

```bash
uv run python -m rentalscout.cli analyze-price-area
```

生成位置价值分析：

```bash
uv run python -m rentalscout.cli analyze-location-value
```

生成经纬度聚类分析：

```bash
uv run python -m rentalscout.cli analyze-geo-clusters --eps-meters 800 --min-samples 5
```

运行测试：

```bash
uv run pytest
```

## 技术栈

- Python 3.13
- uv
- Scrapy
- curl_cffi
- Pydantic v2
- SQLite
- pandas
- Streamlit
- Leaflet
- pytest / Ruff

## 当前边界

- 当前分析主路径仍以 Wellcee 为主；贝壳已经支持详情页抓取和经纬度解析，但受目标站反爬和验证码影响，需要低频、分批、可恢复地运行。
- 高德路线分析需要 `AMAP_API_KEY`；没有 key 时可以先运行直线距离分桶和其他离线分析。
- 数据采集用于个人研究和租房辅助决策，应遵守目标网站服务条款，控制频率，避免高压抓取。

## 下一步: 定时更新数据

后续会新增定时更新数据脚本，用于周期性刷新房源状态并沉淀历史变化：

- 定时执行 Wellcee 和贝壳抓取任务，按天或按小时刷新最新房源。
- 使用增量抓取策略：优先抓取新房源和近期更新房源，避免重复拉取全部页面。
- 每次运行生成 crawl run 记录，保存抓取时间、数据源、页数、成功/失败状态和原始文件路径。
- 入库时继续使用 upsert，更新 `last_seen_at`，保留 `first_seen_at`，用于判断房源生命周期。
- 输出定时任务日志和失败重试信息，方便排查验证码、网络异常、API 失败等问题。
- 定时任务可先以本地 cron/launchd 脚本形式运行，后续再按需要升级为更完整的任务编排。

这一阶段完成后，RentalScout 会从一次性租房分析工具升级为持续更新的本地房源监控系统。
