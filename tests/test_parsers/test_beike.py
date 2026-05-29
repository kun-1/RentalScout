from rentalscout.parsers.beike import parse_beike_detail, parse_beike_listings


def test_parse_beike_listing_card() -> None:
    body = """
    <div class="content__list--item" data-house_code="SH1">
      <a class="content__list--item--aside" href="/zufang/SH1.html" title="整租·测试小区 1室1厅 南">
        <img data-src="https://example.com/a.jpg">
      </a>
      <div class="content__list--item--main">
        <p class="content__list--item--title">
          <a class="twoline" target="_blank" href="/zufang/SH1.html">整租·测试小区 1室1厅 南</a>
        </p>
        <p class="content__list--item--des">
          <a>浦东</a>-<a>张江</a>-<a title="测试小区">测试小区</a>
          <i>/</i> 45.5㎡ <i>/</i>南 <i>/</i> 1室1厅1卫
        </p>
        <span class="content__list--item-price"><em>4500</em> 元/月</span>
      </div>
    </div>
    <div class="content__pg"></div>
    """

    listings = parse_beike_listings(body, "https://sh.zu.ke.com/zufang/")

    assert len(listings) == 1
    assert listings[0].source_listing_id == "SH1"
    assert listings[0].rent_price == 4500
    assert listings[0].district == "浦东"
    assert listings[0].layout == "1室1厅"
    assert listings[0].area_sqm == 45.5


def test_parse_beike_detail_page() -> None:
    body = """
    <html>
      <head>
        <meta name="description" content="贝壳上海租房网,提供整租·世华锦城 1室1厅
        南出租房源信息,此房源位于上海浦东杨思前滩的世华锦城,1室54.00㎡5250元.">
      </head>
      <body>
        <p class="content__title">整租·世华锦城 1室1厅 南</p>
        <div class="content__aside--title"><span>5250</span>元/月</div>
        <p class="content__aside--tags">
          <i class="content__item__tag--is_subway_house">近地铁</i>
          <i class="content__item__tag--decoration">精装</i>
        </p>
        <ul class="content__aside__list">
          <li><span class="label">租赁方式\uff1a</span>整租</li>
          <li><span class="label">房屋类型\uff1a</span>1室1厅1卫 54.00㎡ 精装修</li>
          <li class="floor"><span class="label">朝向楼层\uff1a</span><span>南 高楼层/6层</span></li>
        </ul>
        <div class="content__article__info" id="info">
          <ul>
            <li class="fl oneline">面积\uff1a54.00㎡</li>
            <li class="fl oneline">朝向\uff1a南</li>
            <li class="fl oneline">维护\uff1a今天</li>
            <li class="fl oneline">入住\uff1a2026-06-25</li>
            <li class="fl oneline">楼层\uff1a高楼层/6层</li>
          </ul>
        </div>
        <img src="https://ke-image.ljcdn.com/lease-image/house/a.jpg.780x439.jpg">
        <script>
          g_conf.coord = {
            longitude: '121.506876',
            latitude: '31.166856'
          };
          g_conf.subway = [{"distance":506,"lines":["8号线"],"name":"杨思"}];
          g_conf.name = '世华锦城';
          g_conf.houseCode = 'SH2037753126613680128';
          g_conf.houseConditionName = '杨思前滩'
        </script>
      </body>
    </html>
    """

    listing = parse_beike_detail(
        body,
        "https://sh.zu.ke.com/zufang/SH2037753126613680128.html",
    )

    assert listing is not None
    assert listing.source_listing_id == "SH2037753126613680128"
    assert listing.rent_price == 5250
    assert listing.area_sqm == 54
    assert listing.layout == "1室1厅"
    assert listing.district == "浦东"
    assert listing.subdistrict == "杨思前滩"
    assert listing.community_name == "世华锦城"
    assert listing.longitude == 121.506876
    assert listing.latitude == 31.166856
    assert listing.floor == "高楼层/6层"
    assert listing.orientation == "南"
    assert listing.subway_info == "杨思(8号线, 506m)"
