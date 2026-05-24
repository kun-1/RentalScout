import json

from rentalscout.parsers.wellcee import (
    canonical_wellcee_url,
    extract_subdistrict,
    extract_wellcee_listing_id,
    parse_detail_html,
    parse_detail_jsonld,
    parse_wellcee_listings,
)

REAL_DETAIL_JSON_LD = {
    "@context": "https://schema.org",
    "@type": "RealEstateListing",
    "url": "https://www.wellcee.com/rent-apartment/1778645121786374",
    "name": "潍坊九村社区",
    "description": "潍坊九村一室整租\n房东直租",
    "image": ["https://example.com/a.jpg"],
    "datePosted": "2026-05-24T10:26:49.342Z",
    "offers": {
        "@type": "Offer",
        "price": "5000",
        "priceCurrency": "RMB",
        "availability": "https://schema.org/InStock",
    },
    "address": {
        "@type": "PostalAddress",
        "addressLocality": "上海",
        "addressRegion": "浦东",
        "streetAddress": "潍坊九村社区",
        "addressCountry": "CN",
    },
    "numberOfRooms": 1,
    "numberOfBathroomsTotal": 1,
    "floorSize": {"@type": "QuantitativeValue", "value": "30", "unitCode": "FTK"},
    "geo": {
        "@type": "GeoCoordinates",
        "latitude": 31.22189806965146,
        "longitude": 121.52704408318158,
    },
    "amenityFeature": [
        {"@type": "LocationFeatureSpecification", "name": "洗衣机", "value": True},
        {"@type": "LocationFeatureSpecification", "name": "空调", "value": True},
    ],
}

DETAIL_HTML_STUB = """<div class="mb-[24px] flex flex-col gap-[20px]">
  <div class="flex gap-[20px] w-full">
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[30px]">
      <span class="text-[16px] text-[#666]">押金</span>
      <span class="text-[16px] font-medium text-[#111]">5000RMB</span>
    </div>
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[30px]">
      <span class="text-[16px] text-[#666]">类型</span>
      <span class="text-[16px] font-medium text-[#111]">整租/长租</span>
    </div>
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[30px]">
      <span class="text-[16px] text-[#666]">房间</span>
      <span class="text-[16px] font-medium text-[#111]">1卧室/1洗手间</span>
    </div>
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[30px]">
      <span class="text-[16px] text-[#666]">楼层</span>
      <span class="text-[16px] font-medium text-[#111]">2</span>
    </div>
  </div>
  <div class="flex gap-[20px]">
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[30px]">
      <span class="text-[16px] text-[#666]">面积</span>
      <span class="text-[16px] font-medium text-[#111]">30m²</span>
    </div>
    <div class="flex h-[60px] rounded-[8px] bg-[#fbfbfb] px-[33px]">
      <span class="text-[16px] text-[#666]">地铁</span>
      <span class="text-[16px] font-medium text-[#111]">4号线、9号线、6号线、2号线</span>
    </div>
  </div>
</div>"""


def test_parse_wellcee_json_ld_list() -> None:
    payload = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "item": {
                    "@type": "RealEstateListing",
                    "url": "https://www.wellcee.com/rent-apartment/shanghai/1",
                    "name": "浦东 测试小区",
                    "image": "https://example.com/a.jpg",
                    "datePosted": "2026-05-24",
                    "offers": {"price": "4000"},
                },
            }
        ],
    }
    body = f'<script type="application/ld+json">{json.dumps(payload)}</script>'

    listings = parse_wellcee_listings(body)

    assert len(listings) == 1
    assert listings[0].source_listing_id == "1"
    assert str(listings[0].source_url) == "https://www.wellcee.com/rent-apartment/1"
    assert listings[0].rent_price == 4000
    assert listings[0].district == "浦东"


def test_wellcee_listing_id_and_canonical_url() -> None:
    listing_id = extract_wellcee_listing_id(
        "https://www.wellcee.com/rent-apartment/shanghai/1776264233300648"
    )

    assert listing_id == "1776264233300648"
    assert (
        canonical_wellcee_url(listing_id)
        == "https://www.wellcee.com/rent-apartment/1776264233300648"
    )


def test_parse_detail_jsonld_extracts_all_fields() -> None:
    body = f'<script type="application/ld+json">{json.dumps(REAL_DETAIL_JSON_LD)}</script>'
    result = parse_detail_jsonld(body)

    assert result is not None
    assert result["community_name"] == "潍坊九村社区"
    assert result["description"] == "潍坊九村一室整租\n房东直租"
    assert result["published_at"] is not None
    assert result["rent_price"] == 5000
    assert result["currency"] == "RMB"
    assert result["city"] == "上海"
    assert result["district"] == "浦东"
    assert result["street_address"] == "潍坊九村社区"
    assert result["room_count"] == 1
    assert result["bathroom_count"] == 1
    assert result["area_sqm"] == 30.0
    assert result["latitude"] == 31.22189806965146
    assert result["longitude"] == 121.52704408318158
    assert "洗衣机" in result["features"]
    assert "空调" in result["features"]
    assert len(result["image_urls"]) == 1


def test_parse_detail_jsonld_returns_none_for_wrong_type() -> None:
    payload = {"@type": "ItemList", "itemListElement": []}
    body = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    assert parse_detail_jsonld(body) is None


def test_parse_detail_jsonld_returns_none_for_no_jsonld() -> None:
    assert parse_detail_jsonld("<html><body>no jsonld</body></html>") is None


def test_parse_detail_html_extracts_all_fields() -> None:
    result = parse_detail_html(DETAIL_HTML_STUB)

    assert result["deposit"] == "5000RMB"
    assert result["listing_type_detail"] == "整租/长租"
    assert result["layout_detail"] == "1卧室/1洗手间"
    assert result["floor"] == "2"
    assert result["area_text"] == "30m²"
    assert result["subway_info"] == "4号线、9号线、6号线、2号线"


def test_parse_detail_html_returns_empty_for_no_cards() -> None:
    result = parse_detail_html("<html><body>no cards</body></html>")
    assert result == {}


def test_extract_subdistrict_typical_community() -> None:
    assert extract_subdistrict("潍坊九村社区") == ("潍坊新村街道", 0.9)
    assert extract_subdistrict("崂山四村-58幢") == ("潍坊新村街道", 0.9)
    assert extract_subdistrict("上钢五村") == ("上钢新村街道", 0.9)


def test_extract_subdistrict_various_patterns() -> None:
    name, conf = extract_subdistrict("晶耀名邸3期")
    assert name == "晶耀"
    assert conf == 0.5

    name, conf = extract_subdistrict("碧云东壹栋")
    assert name is not None

    name, conf = extract_subdistrict(None)
    assert name is None
    assert conf == 0.0

    name, conf = extract_subdistrict("")
    assert name is None
    assert conf == 0.0
