import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tradingagents"
    / "dataflows"
    / "news"
    / "tushare_web.py"
)
SPEC = importlib.util.spec_from_file_location("tushare_web_under_test", MODULE_PATH)
tushare_web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tushare_web)


def test_parse_tushare_news_html_from_embedded_json():
    html = """
    <html><body>
    <script>
    window.__INITIAL_STATE__ = {"news": [
      {"title": "600519 公司新闻", "content": "贵州茅台业绩增长", "datetime": "2026-05-11 09:30:00", "url": "https://example.com/a"}
    ]};
    </script>
    </body></html>
    """

    items = tushare_web.parse_tushare_news_html(html, symbol="600519", limit=5)

    assert len(items) == 1
    assert items[0]["title"] == "600519 公司新闻"
    assert items[0]["data_source"] == "tushare_web"


def test_parse_tushare_news_html_from_dom():
    html = """
    <html><body>
      <ul class="news-list">
        <li><a href="/news/1">600519 今日市场新闻</a><p>贵州茅台讨论热度提升</p></li>
      </ul>
    </body></html>
    """

    items = tushare_web.parse_tushare_news_html(html, symbol="600519", limit=5)

    assert len(items) == 1
    assert items[0]["title"] == "600519 今日市场新闻"
    assert items[0]["url"] == "https://tushare.pro/news/1"


def test_vue_shell_raises_clear_error():
    class FakeResponse:
        text = '<html><script src="js/chunk-vendors.22249f01.js"></script><body><div id="app"></div></body></html>'

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    try:
        tushare_web.get_tushare_web_news(session=FakeSession())
    except tushare_web.TushareWebNewsError as exc:
        assert "TUSHARE_WEB_COOKIE" in str(exc)
    else:
        raise AssertionError("Expected TushareWebNewsError")


def test_web_crawler_ignores_api_proxy_url():
    class FakeResponse:
        text = """
        <html><body>
          <ul class="news-list">
            <li><a href="/news/1">600519 官方新闻页面</a><p>来自 tushare.pro/news</p></li>
          </ul>
        </body></html>
        """

        def raise_for_status(self):
            return None

    class FakeSession:
        requested_url = None

        def get(self, url, *args, **kwargs):
            self.requested_url = url
            return FakeResponse()

    session = FakeSession()
    items = tushare_web.get_tushare_web_news(
        symbol="600519",
        url="http://42.194.163.97:5000",
        session=session,
    )

    assert session.requested_url == "https://tushare.pro/news"
    assert len(items) == 1
