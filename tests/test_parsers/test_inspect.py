from rentalscout.inspect import summarize_html


def test_summarize_html_extracts_title_and_links() -> None:
    body = """
    <html>
      <head><title>上海租房</title></head>
      <body>
        <a href="/zufang/abc.html">房源 A</a>
        <a href="https://example.com/detail">房源 B</a>
        <a href="/zufang/abc.html">重复链接</a>
      </body>
    </html>
    """

    summary = summarize_html(body, "https://sh.zu.ke.com/zufang")

    assert summary.title == "上海租房"
    assert summary.link_count == 2
    assert summary.links[0] == "https://sh.zu.ke.com/zufang/abc.html"
    assert summary.body_size > 0


def test_summarize_html_detects_frontend_data_marker() -> None:
    summary = summarize_html("<script>window.__NUXT__={}</script>", "https://example.com")

    assert summary.contains_next_data
