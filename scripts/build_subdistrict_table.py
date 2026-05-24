"""Build Shanghai Pudong subdistrict lookup table.

Usage:
  # Generate from built-in curated data (no API key needed):
  uv run python scripts/build_subdistrict_table.py

  # Fetch from Amap API for verification:
  uv run python scripts/build_subdistrict_table.py --amap-key YOUR_KEY
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "subdistricts"
OUTPUT_PATH = OUTPUT_DIR / "shanghai_pudong.json"

# Curated mapping: community_name_prefix → subdistrict_full_name
# Sorted by prefix length (longest first) so more specific matches win
CURATED_PREFIXES: list[dict[str, str]] = [
    # Priority: multi-word / long prefixes first

    # 潍坊新村街道 — covers 潍坊/崂山/乳山/浦电路 areas
    {"prefix": "潍坊十村二小区", "name": "潍坊新村街道"},
    {"prefix": "潍坊十村", "name": "潍坊新村街道"},
    {"prefix": "潍坊九村", "name": "潍坊新村街道"},
    {"prefix": "潍坊八村", "name": "潍坊新村街道"},
    {"prefix": "潍坊七村", "name": "潍坊新村街道"},
    {"prefix": "潍坊六村", "name": "潍坊新村街道"},
    {"prefix": "潍坊五村", "name": "潍坊新村街道"},
    {"prefix": "潍坊四村", "name": "潍坊新村街道"},
    {"prefix": "潍坊三村", "name": "潍坊新村街道"},
    {"prefix": "潍坊二村", "name": "潍坊新村街道"},
    {"prefix": "潍坊一村", "name": "潍坊新村街道"},
    {"prefix": "潍坊社区", "name": "潍坊新村街道"},
    {"prefix": "潍坊路", "name": "潍坊新村街道"},
    {"prefix": "崂山新村", "name": "潍坊新村街道"},
    {"prefix": "崂山六村", "name": "潍坊新村街道"},
    {"prefix": "崂山五村", "name": "潍坊新村街道"},
    {"prefix": "崂山四村", "name": "潍坊新村街道"},
    {"prefix": "崂山三村", "name": "潍坊新村街道"},
    {"prefix": "崂山二村", "name": "潍坊新村街道"},
    {"prefix": "崂山一村", "name": "潍坊新村街道"},
    {"prefix": "崂山路", "name": "潍坊新村街道"},
    {"prefix": "乳山五村", "name": "潍坊新村街道"},
    {"prefix": "乳山三村", "name": "潍坊新村街道"},
    {"prefix": "乳山二村", "name": "潍坊新村街道"},
    {"prefix": "乳山路", "name": "潍坊新村街道"},
    {"prefix": "浦电路", "name": "潍坊新村街道"},
    {"prefix": "竹园小区", "name": "潍坊新村街道"},
    {"prefix": "松山小区", "name": "潍坊新村街道"},
    {"prefix": "朱家滩小区", "name": "潍坊新村街道"},
    {"prefix": "谢家宅小区", "name": "潍坊新村街道"},
    {"prefix": "陈家宅小区", "name": "潍坊新村街道"},
    {"prefix": "蓝高小区", "name": "潍坊新村街道"},
    {"prefix": "蓝村小区", "name": "潍坊新村街道"},
    {"prefix": "蓝村路", "name": "潍坊新村街道"},
    {"prefix": "峨山小区", "name": "潍坊新村街道"},
    {"prefix": "源竹小区", "name": "潍坊新村街道"},
    {"prefix": "福竹小区", "name": "潍坊新村街道"},
    {"prefix": "潍坊", "name": "潍坊新村街道"},

    # 陆家嘴街道 — 梅园/东昌/市新/招远/福山
    {"prefix": "梅园三街坊", "name": "陆家嘴街道"},
    {"prefix": "梅园新村", "name": "陆家嘴街道"},
    {"prefix": "梅园三村", "name": "陆家嘴街道"},
    {"prefix": "东园二村", "name": "陆家嘴街道"},
    {"prefix": "东园一村", "name": "陆家嘴街道"},
    {"prefix": "市新小区", "name": "陆家嘴街道"},
    {"prefix": "招远小区", "name": "陆家嘴街道"},
    {"prefix": "福山小区", "name": "陆家嘴街道"},
    {"prefix": "隧成小区", "name": "陆家嘴街道"},
    {"prefix": "荣城花苑", "name": "陆家嘴街道"},
    {"prefix": "东昌新村", "name": "陆家嘴街道"},
    {"prefix": "东昌路", "name": "陆家嘴街道"},
    {"prefix": "乳山路", "name": "陆家嘴街道"},
    {"prefix": "陆家嘴", "name": "陆家嘴街道"},

    # 上钢新村街道
    {"prefix": "上钢十村", "name": "上钢新村街道"},
    {"prefix": "上钢九村", "name": "上钢新村街道"},
    {"prefix": "上钢八村", "name": "上钢新村街道"},
    {"prefix": "上钢七村", "name": "上钢新村街道"},
    {"prefix": "上钢六村", "name": "上钢新村街道"},
    {"prefix": "上钢五村", "name": "上钢新村街道"},
    {"prefix": "上钢四村", "name": "上钢新村街道"},
    {"prefix": "上钢三村", "name": "上钢新村街道"},
    {"prefix": "上钢二村", "name": "上钢新村街道"},
    {"prefix": "上钢一村", "name": "上钢新村街道"},
    {"prefix": "上钢", "name": "上钢新村街道"},

    # 周家渡街道 — 上南/德州/雪野/齐河
    {"prefix": "上南十一村", "name": "周家渡街道"},
    {"prefix": "上南十村", "name": "周家渡街道"},
    {"prefix": "上南九村", "name": "周家渡街道"},
    {"prefix": "上南八村", "name": "周家渡街道"},
    {"prefix": "上南七村", "name": "周家渡街道"},
    {"prefix": "上南六村", "name": "周家渡街道"},
    {"prefix": "上南五村", "name": "周家渡街道"},
    {"prefix": "上南四村", "name": "周家渡街道"},
    {"prefix": "上南三村", "name": "周家渡街道"},
    {"prefix": "上南二村", "name": "周家渡街道"},
    {"prefix": "上南一村", "name": "周家渡街道"},
    {"prefix": "上南", "name": "周家渡街道"},
    {"prefix": "德州六村", "name": "周家渡街道"},
    {"prefix": "德州五村", "name": "周家渡街道"},
    {"prefix": "德州四村", "name": "周家渡街道"},
    {"prefix": "德州三村", "name": "周家渡街道"},
    {"prefix": "雪野", "name": "周家渡街道"},
    {"prefix": "齐河", "name": "周家渡街道"},
    {"prefix": "周家渡", "name": "周家渡街道"},

    # 塘桥街道
    {"prefix": "塘桥二村", "name": "塘桥街道"},
    {"prefix": "塘桥小区", "name": "塘桥街道"},
    {"prefix": "塘桥路", "name": "塘桥街道"},
    {"prefix": "塘东小区", "name": "塘桥街道"},
    {"prefix": "浦建小区", "name": "塘桥街道"},
    {"prefix": "蓝村小区", "name": "塘桥街道"},
    {"prefix": "蓝村路", "name": "塘桥街道"},
    {"prefix": "南泉小区", "name": "塘桥街道"},
    {"prefix": "宁阳小区", "name": "塘桥街道"},
    {"prefix": "塘桥", "name": "塘桥街道"},
    {"prefix": "微山新村", "name": "塘桥街道"},
    {"prefix": "微山三村", "name": "塘桥街道"},

    # 南码头路街道
    {"prefix": "南码头路", "name": "南码头路街道"},
    {"prefix": "临沂八村", "name": "南码头路街道"},
    {"prefix": "临沂七村", "name": "南码头路街道"},
    {"prefix": "临沂六村", "name": "南码头路街道"},
    {"prefix": "临沂五村", "name": "南码头路街道"},
    {"prefix": "临沂四村", "name": "南码头路街道"},
    {"prefix": "临沂三村", "name": "南码头路街道"},
    {"prefix": "临沂二村", "name": "南码头路街道"},
    {"prefix": "临沂一村", "name": "南码头路街道"},
    {"prefix": "临沂大楼", "name": "南码头路街道"},
    {"prefix": "临沂", "name": "南码头路街道"},
    {"prefix": "港机新村", "name": "南码头路街道"},
    {"prefix": "东三小区", "name": "南码头路街道"},
    {"prefix": "浦三路", "name": "南码头路街道"},
    {"prefix": "东方城市花园", "name": "南码头路街道"},
    {"prefix": "银河小区", "name": "南码头路街道"},

    # 金杨新村街道
    {"prefix": "金杨新村七街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村六街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村五街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村四街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村三街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村二街坊", "name": "金杨新村街道"},
    {"prefix": "金杨九街坊", "name": "金杨新村街道"},
    {"prefix": "金杨十街坊", "name": "金杨新村街道"},
    {"prefix": "金杨十一街坊", "name": "金杨新村街道"},
    {"prefix": "金杨新村", "name": "金杨新村街道"},
    {"prefix": "金杨路", "name": "金杨新村街道"},
    {"prefix": "金口路", "name": "金杨新村街道"},
    {"prefix": "金杨", "name": "金杨新村街道"},
    {"prefix": "罗山三", "name": "金杨新村街道"},
    {"prefix": "罗山四村", "name": "金杨新村街道"},
    {"prefix": "罗山新村", "name": "金杨新村街道"},
    {"prefix": "黄山新村", "name": "金杨新村街道"},
    {"prefix": "黄山始信苑", "name": "金杨新村街道"},
    {"prefix": "庆宁寺", "name": "金杨新村街道"},
    {"prefix": "居家桥", "name": "金杨新村街道"},

    # 沪东新村街道
    {"prefix": "沪东新村", "name": "沪东新村街道"},
    {"prefix": "沪南小区", "name": "沪东新村街道"},
    {"prefix": "沪二小区", "name": "沪东新村街道"},
    {"prefix": "沪东", "name": "沪东新村街道"},
    {"prefix": "船舶新村", "name": "沪东新村街道"},
    {"prefix": "朱家门小区", "name": "沪东新村街道"},
    {"prefix": "莱阳路", "name": "沪东新村街道"},
    {"prefix": "陈家宅", "name": "沪东新村街道"},
    {"prefix": "浦东大道", "name": "沪东新村街道"},

    # 浦兴路街道
    {"prefix": "浦兴", "name": "浦兴路街道"},
    {"prefix": "东波苑", "name": "浦兴路街道"},
    {"prefix": "东荷小区", "name": "浦兴路街道"},
    {"prefix": "金桥湾清水苑", "name": "浦兴路街道"},
    {"prefix": "长岛花苑", "name": "浦兴路街道"},
    {"prefix": "长岛路", "name": "浦兴路街道"},
    {"prefix": "荷泽路", "name": "浦兴路街道"},
    {"prefix": "凌河路", "name": "浦兴路街道"},
    {"prefix": "博兴路", "name": "浦兴路街道"},
    {"prefix": "平度路", "name": "浦兴路街道"},
    {"prefix": "牟平路", "name": "浦兴路街道"},
    {"prefix": "台儿庄路", "name": "浦兴路街道"},

    # 洋泾街道
    {"prefix": "洋泾", "name": "洋泾街道"},
    {"prefix": "泾东小区", "name": "洋泾街道"},
    {"prefix": "泾西", "name": "洋泾街道"},
    {"prefix": "崮山小区", "name": "洋泾街道"},
    {"prefix": "崮山路", "name": "洋泾街道"},
    {"prefix": "巨东小区", "name": "洋泾街道"},
    {"prefix": "巨野小区", "name": "洋泾街道"},
    {"prefix": "巨野路", "name": "洋泾街道"},
    {"prefix": "海院小区", "name": "洋泾街道"},
    {"prefix": "桃林路", "name": "洋泾街道"},
    {"prefix": "羽山路", "name": "洋泾街道"},
    {"prefix": "张杨路", "name": "洋泾街道"},

    # 花木街道
    {"prefix": "花木", "name": "花木街道"},
    {"prefix": "龙沟新苑", "name": "花木街道"},
    {"prefix": "龙沟", "name": "花木街道"},
    {"prefix": "芳芯路", "name": "花木街道"},
    {"prefix": "芳华路", "name": "花木街道"},
    {"prefix": "芳草路", "name": "花木街道"},
    {"prefix": "白杨路", "name": "花木街道"},
    {"prefix": "杜鹃路", "name": "花木街道"},
    {"prefix": "海桐路", "name": "花木街道"},
    {"prefix": "樱花路", "name": "花木街道"},
    {"prefix": "牡丹路", "name": "花木街道"},
    {"prefix": "玉兰路", "name": "花木街道"},
    {"prefix": "浦建路", "name": "花木街道"},
    {"prefix": "世纪大道", "name": "花木街道"},
    {"prefix": "锦绣路", "name": "花木街道"},
    {"prefix": "东绣路", "name": "花木街道"},

    # 东明路街道
    {"prefix": "东明路", "name": "东明路街道"},
    {"prefix": "东明", "name": "东明路街道"},
    {"prefix": "凌兆", "name": "东明路街道"},
    {"prefix": "凌三小区", "name": "东明路街道"},
    {"prefix": "凌二小区", "name": "东明路街道"},
    {"prefix": "凌四小区", "name": "东明路街道"},
    {"prefix": "金禾苑", "name": "东明路街道"},
    {"prefix": "金光小区", "name": "东明路街道"},
    {"prefix": "三林苑", "name": "东明路街道"},
    {"prefix": "永泰花苑", "name": "东明路街道"},
    {"prefix": "品华苑", "name": "东明路街道"},

    # 北蔡镇
    {"prefix": "北蔡", "name": "北蔡镇"},
    {"prefix": "莲康苑", "name": "北蔡镇"},
    {"prefix": "莲文苑", "name": "北蔡镇"},
    {"prefix": "莲怡苑", "name": "北蔡镇"},
    {"prefix": "莲业新村", "name": "北蔡镇"},
    {"prefix": "莲园路", "name": "北蔡镇"},
    {"prefix": "北中路", "name": "北蔡镇"},
    {"prefix": "安建苑", "name": "北蔡镇"},
    {"prefix": "锦华花苑", "name": "北蔡镇"},
    {"prefix": "大华锦绣华城", "name": "北蔡镇"},
    {"prefix": "艾南花苑", "name": "北蔡镇"},
    {"prefix": "艾南小区", "name": "北蔡镇"},
    {"prefix": "艾东小区", "name": "北蔡镇"},
    {"prefix": "南新四村", "name": "北蔡镇"},
    {"prefix": "南新西园", "name": "北蔡镇"},
    {"prefix": "南杨小区", "name": "北蔡镇"},
    {"prefix": "绿星小区", "name": "北蔡镇"},
    {"prefix": "锦川佳苑", "name": "北蔡镇"},
    {"prefix": "博华园", "name": "北蔡镇"},

    # 三林镇
    {"prefix": "三林新村", "name": "三林镇"},
    {"prefix": "三林世博家园", "name": "三林镇"},
    {"prefix": "三林", "name": "三林镇"},
    {"prefix": "永泰花苑", "name": "三林镇"},
    {"prefix": "浦发绿城", "name": "三林镇"},
    {"prefix": "浦发仁恒有园", "name": "三林镇"},
    {"prefix": "浦发东悦城", "name": "三林镇"},
    {"prefix": "浦峻澜庭", "name": "三林镇"},
    {"prefix": "金海湾", "name": "三林镇"},
    {"prefix": "杨思", "name": "三林镇"},
    {"prefix": "前滩", "name": "三林镇"},
    {"prefix": "中粮前滩", "name": "三林镇"},
    {"prefix": "江悦名庭", "name": "三林镇"},
    {"prefix": "海阳路", "name": "三林镇"},
    {"prefix": "灵岩南路", "name": "三林镇"},
    {"prefix": "上浦路", "name": "三林镇"},
    {"prefix": "依水园", "name": "三林镇"},
    {"prefix": "城林美苑", "name": "三林镇"},
    {"prefix": "城林雅苑", "name": "三林镇"},
    {"prefix": "城林嘉苑", "name": "三林镇"},
    {"prefix": "香樟苑", "name": "三林镇"},
    {"prefix": "盛苑路", "name": "三林镇"},
    {"prefix": "西泰林路", "name": "三林镇"},
    {"prefix": "东泰林路", "name": "三林镇"},

    # 张江镇
    {"prefix": "张江", "name": "张江镇"},
    {"prefix": "古桐四村", "name": "张江镇"},
    {"prefix": "古桐公寓", "name": "张江镇"},
    {"prefix": "玉兰香苑", "name": "张江镇"},
    {"prefix": "紫薇路", "name": "张江镇"},
    {"prefix": "高斯路", "name": "张江镇"},
    {"prefix": "孙农路", "name": "张江镇"},
    {"prefix": "香楠小区", "name": "张江镇"},
    {"prefix": "春港丽园", "name": "张江镇"},
    {"prefix": "川杨新苑", "name": "张江镇"},
    {"prefix": "孙桥", "name": "张江镇"},
    {"prefix": "广兰路", "name": "张江镇"},
    {"prefix": "金科路", "name": "张江镇"},
    {"prefix": "居里路", "name": "张江镇"},
    {"prefix": "碧波路", "name": "张江镇"},

    # 金桥镇
    {"prefix": "金桥新村四街坊", "name": "金桥镇"},
    {"prefix": "金桥新村", "name": "金桥镇"},
    {"prefix": "金桥路", "name": "金桥镇"},
    {"prefix": "金桥湾", "name": "金桥镇"},
    {"prefix": "金桥", "name": "金桥镇"},
    {"prefix": "金东名苑", "name": "金桥镇"},
    {"prefix": "金葵新城", "name": "金桥镇"},
    {"prefix": "金海华城", "name": "金桥镇"},
    {"prefix": "禹洲金桥", "name": "金桥镇"},
    {"prefix": "禹洲蓝爵", "name": "金桥镇"},
    {"prefix": "佳虹小区", "name": "金桥镇"},
    {"prefix": "永宁路", "name": "金桥镇"},

    # 高行镇
    {"prefix": "高行绿洲", "name": "高行镇"},
    {"prefix": "高行馨苑", "name": "高行镇"},
    {"prefix": "高行", "name": "高行镇"},
    {"prefix": "东靖路", "name": "高行镇"},
    {"prefix": "金高路", "name": "高行镇"},
    {"prefix": "新行路", "name": "高行镇"},
    {"prefix": "兰谷路", "name": "高行镇"},
    {"prefix": "紫翠", "name": "高行镇"},

    # 高东镇
    {"prefix": "高东", "name": "高东镇"},
    {"prefix": "新高苑", "name": "高东镇"},

    # 高桥镇
    {"prefix": "高桥", "name": "高桥镇"},
    {"prefix": "凌桥", "name": "高桥镇"},
    {"prefix": "浦凌佳苑", "name": "高桥镇"},

    # 曹路镇
    {"prefix": "曹路", "name": "曹路镇"},
    {"prefix": "顾路", "name": "曹路镇"},
    {"prefix": "龚路", "name": "曹路镇"},
    {"prefix": "民耀路", "name": "曹路镇"},
    {"prefix": "民春路", "name": "曹路镇"},
    {"prefix": "民雪路", "name": "曹路镇"},
    {"prefix": "川沙路", "name": "曹路镇"},

    # 唐镇
    {"prefix": "唐镇", "name": "唐镇"},
    {"prefix": "唐丰苑", "name": "唐镇"},
    {"prefix": "唐融公寓", "name": "唐镇"},
    {"prefix": "王港", "name": "唐镇"},
    {"prefix": "机口村", "name": "唐镇"},
    {"prefix": "创新西路", "name": "唐镇"},
    {"prefix": "齐爱路", "name": "唐镇"},

    # 合庆镇
    {"prefix": "合庆", "name": "合庆镇"},
    {"prefix": "庆丰", "name": "合庆镇"},

    # 川沙新镇
    {"prefix": "川沙", "name": "川沙新镇"},
    {"prefix": "妙虹新苑", "name": "川沙新镇"},
    {"prefix": "华府", "name": "川沙新镇"},
    {"prefix": "翔川路", "name": "川沙新镇"},
    {"prefix": "新德路", "name": "川沙新镇"},
    {"prefix": "华夏", "name": "川沙新镇"},

    # 祝桥镇
    {"prefix": "祝桥", "name": "祝桥镇"},
    {"prefix": "施湾", "name": "祝桥镇"},
    {"prefix": "盐仓", "name": "祝桥镇"},
    {"prefix": "江镇", "name": "祝桥镇"},

    # 惠南镇
    {"prefix": "惠南", "name": "惠南镇"},
    {"prefix": "民乐大居", "name": "惠南镇"},
    {"prefix": "东城", "name": "惠南镇"},

    # 航头镇
    {"prefix": "航头", "name": "航头镇"},
    {"prefix": "鹤沙航城", "name": "航头镇"},
    {"prefix": "鹤沙", "name": "航头镇"},
    {"prefix": "航昌路", "name": "航头镇"},
    {"prefix": "航梅路", "name": "航头镇"},

    # 周浦镇
    {"prefix": "周浦", "name": "周浦镇"},
    {"prefix": "周康", "name": "周浦镇"},
    {"prefix": "繁荣华庭", "name": "周浦镇"},
    {"prefix": "安康新村", "name": "周浦镇"},
    {"prefix": "汇福家园", "name": "周浦镇"},
    {"prefix": "浦发有家", "name": "周浦镇"},
    {"prefix": "康桥", "name": "周浦镇"},

    # 新场镇
    {"prefix": "新场", "name": "新场镇"},
    {"prefix": "坦直", "name": "新场镇"},

    # 宣桥镇
    {"prefix": "宣桥", "name": "宣桥镇"},

    # 书院镇
    {"prefix": "书院", "name": "书院镇"},

    # 泥城镇
    {"prefix": "泥城", "name": "泥城镇"},
    {"prefix": "云汉", "name": "泥城镇"},

    # 万祥镇
    {"prefix": "万祥", "name": "万祥镇"},

    # 老港镇
    {"prefix": "老港", "name": "老港镇"},

    # 大团镇
    {"prefix": "大团", "name": "大团镇"},

    # 南汇新城镇
    {"prefix": "南汇新城", "name": "南汇新城镇"},
    {"prefix": "临港", "name": "南汇新城镇"},
    {"prefix": "滴水湖", "name": "南汇新城镇"},
    {"prefix": "芦恒路", "name": "南汇新城镇"},
]


def fetch_from_amap(api_key: str) -> list[dict[str, str]]:
    """Fetch Pudong subdistricts from Amap API."""
    import requests

    resp = requests.get(
        "https://restapi.amap.com/v3/config/district",
        params={
            "key": api_key,
            "keywords": "浦东新区",
            "subdistrict": 2,
            "extensions": "base",
            "page": 1,
            "offset": 50,
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("status") != "1":
        msg = f"Amap API error: {data.get('info', 'unknown')}"
        raise RuntimeError(msg)

    districts = data.get("districts", [])
    if not districts:
        return []

    subdistricts = districts[0].get("districts", [])
    print(f"Amap returned {len(subdistricts)} subdistricts for 浦东新区")

    result: list[dict[str, str]] = []
    for sd in subdistricts:
        name = sd.get("name", "")
        if not name:
            continue
        # Generate prefix: the first 2 Chinese characters of the name
        # (e.g., 潍坊新村街道 → 潍坊)
        clean = re.sub(r"(新村)?(街道|镇)$", "", name)
        if len(clean) >= 2:
            result.append({"prefix": clean, "name": name})
        result.append({"prefix": name.replace("街道", "").replace("镇", ""), "name": name})
        result.append({"prefix": name[:2], "name": name})

    return result


def build_table(*, amap_key: str | None = None) -> list[dict[str, str]]:
    """Build the final sorted subdistrict table."""

    prefixes = list(CURATED_PREFIXES)

    if amap_key:
        print("Fetching from Amap API...")
        try:
            amap_prefixes = fetch_from_amap(amap_key)

            # Add Amap-sourced prefixes (dedup by prefix+name)
            existing = {(p["prefix"], p["name"]) for p in prefixes}
            for p in amap_prefixes:
                key = (p["prefix"], p["name"])
                if key not in existing:
                    prefixes.append(p)
                    existing.add(key)

            print(f"Total prefixes after Amap merge: {len(prefixes)}")
        except Exception as exc:
            print(f"Amap API error (using curated only): {exc}", file=sys.stderr)

    # Sort: longest prefix first → shorter prefixes
    prefixes.sort(key=lambda p: (-len(p["prefix"]), p["name"]))

    return prefixes


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Shanghai Pudong subdistrict lookup table")
    parser.add_argument("--amap-key", type=str, help="Amap API key for live fetch")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    prefixes = build_table(amap_key=args.amap_key)

    table = {
        "district": "浦东新区",
        "source": "amap_api" if args.amap_key else "curated",
        "generated_at": datetime.now(UTC).isoformat(),
        "total_prefixes": len(prefixes),
        "known_prefixes": prefixes,
    }

    OUTPUT_PATH.write_text(
        json.dumps(table, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Written: {OUTPUT_PATH} ({len(prefixes)} entries)")
    print(f"Source: {table['source']}")


if __name__ == "__main__":
    main()
