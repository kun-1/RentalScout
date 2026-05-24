from rentalscout.parsers.beike import parse_beike_listings


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
