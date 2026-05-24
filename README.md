# RentalScout

RentalScout 是一个个人租房房源采集、验证、分析与交互式筛选项目。

当前范围：

- 阶段 0：侦察贝壳、Wellcee、豆瓣、小红书的数据源可行性。
- 阶段 1：实现贝壳和 Wellcee 的数据层 MVP。
- 后续阶段：验证层、分析层、交互式网站和 UGC 内容增强。

工作计划见 [plan.md](plan.md)。

## 本地分析工作台

启动 Streamlit 可视化：

```bash
uv run streamlit run rentalscout/web/streamlit_app.py
```

当前工作台覆盖：

- Wellcee 数据质量分析
- 工作地点直线距离分桶
- 价格与单位面积租金分析
- 附近房源位置价值分析
- 经纬度聚类分析

经纬度聚类页支持调整聚类半径和最小样本数；默认只做预览，点击保存后才会更新
`data/analysis/geo_clusters.csv` 和 `data/analysis/geo_clusters_summary.json`。
