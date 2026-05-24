# 计划技术栈

初始可安装项目只保留当前代码真正需要的依赖。爬虫、存储、分析和编排相关依赖，应在对应模块开始实现时再加入，避免基础测试被重型依赖拖慢。

## 基础环境

- Python 3.13
- uv
- Pydantic v2
- Ruff
- pytest

## 爬虫与解析

- Scrapy 2.16+
- scrapy-playwright
- Playwright Python
- parsel
- selectolax

## 清洗与分析

- Polars
- DuckDB

## 存储与空间能力

- PostgreSQL
- PostGIS

## 编排

- Prefect 3
