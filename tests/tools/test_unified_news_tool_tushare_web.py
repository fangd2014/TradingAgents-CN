from tradingagents.tools.unified_news_tool import UnifiedNewsAnalyzer


def test_a_share_news_uses_tushare_provider_before_akshare_sync(monkeypatch):
    analyzer = UnifiedNewsAnalyzer(toolkit=object())
    monkeypatch.setattr(analyzer, "_get_news_from_database", lambda *args, **kwargs: "")

    def fail_akshare_sync(*args, **kwargs):
        raise AssertionError("AkShare sync should not run before Tushare when Tushare returns news")

    monkeypatch.setattr(analyzer, "_sync_news_from_akshare", fail_akshare_sync)

    def fake_tushare_news(symbol, max_news=10, hours_back=24):
        return [
            {
                "title": "600519 Tushare新闻",
                "source": "财联社",
                "publish_time": "2026-05-11 09:30:00",
                "summary": "Tushare新闻接口返回的贵州茅台新闻摘要",
                "url": "",
            }
        ]

    monkeypatch.setattr(
        "tradingagents.tools.unified_news_tool.get_tushare_news_for_unified_tool",
        fake_tushare_news,
    )

    result = analyzer._get_a_share_news("600519", 10)

    assert "Tushare新闻" in result
    assert "600519 Tushare新闻" in result
    assert "财联社" in result


def test_a_share_news_uses_tushare_web_fallback(monkeypatch):
    analyzer = UnifiedNewsAnalyzer(toolkit=object())
    monkeypatch.setattr(analyzer, "_get_news_from_database", lambda *args, **kwargs: "")
    monkeypatch.setattr(analyzer, "_sync_news_from_akshare", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "tradingagents.tools.unified_news_tool.get_tushare_news_for_unified_tool",
        lambda *args, **kwargs: [],
    )

    def fake_tushare_web_news(symbol, limit=10):
        return [
            {
                "title": "600519 官方新闻",
                "source": "Tushare网页",
                "publish_time": "2026-05-11 09:30:00",
                "summary": "贵州茅台新闻摘要",
                "url": "https://tushare.pro/news/1",
            }
        ]

    monkeypatch.setattr(
        "tradingagents.tools.unified_news_tool.get_tushare_web_news_for_unified_tool",
        fake_tushare_web_news,
    )

    result = analyzer._get_a_share_news("600519", 10)

    assert "Tushare网页新闻" in result
    assert "600519 官方新闻" in result
    assert "https://tushare.pro/news/1" in result
