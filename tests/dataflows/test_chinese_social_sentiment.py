import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tradingagents"
    / "dataflows"
    / "news"
    / "chinese_finance.py"
)
SPEC = importlib.util.spec_from_file_location("chinese_finance_under_test", MODULE_PATH)
chinese_finance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chinese_finance)

ChineseFinanceDataAggregator = chinese_finance.ChineseFinanceDataAggregator
get_chinese_social_sentiment = chinese_finance.get_chinese_social_sentiment


def test_forum_sentiment_uses_10jqka_eastmoney_and_xueqiu(monkeypatch):
    aggregator = ChineseFinanceDataAggregator()
    called_sources = []

    def fake_fetch(source, ticker, days):
        called_sources.append(source)
        return [
            {
                "source": source,
                "title": f"{source} 看好 {ticker}",
                "content": "投资者看好，讨论热度上涨",
                "url": f"https://example.com/{source}",
            }
        ]

    monkeypatch.setattr(aggregator, "_fetch_forum_source", fake_fetch)

    sentiment = aggregator._get_stock_forum_sentiment("600519", 7)

    assert called_sources == ["同花顺", "东方财富", "雪球"]
    assert sentiment["discussion_count"] == 3
    assert sentiment["confidence"] > 0
    assert sentiment["source_stats"]["同花顺"]["count"] == 1
    assert sentiment["source_stats"]["东方财富"]["count"] == 1
    assert sentiment["source_stats"]["雪球"]["count"] == 1


def test_chinese_social_report_includes_a_share_forum_sources(monkeypatch):
    def fake_fetch(self, source, ticker, days):
        return [
            {
                "source": source,
                "title": f"{source} 投资者看好 {ticker}",
                "content": "上涨 突破 看好",
                "url": f"https://example.com/{source}",
            }
        ]

    monkeypatch.setattr(ChineseFinanceDataAggregator, "_fetch_forum_source", fake_fetch)
    monkeypatch.setattr(ChineseFinanceDataAggregator, "_search_finance_news", lambda self, term, days: [])

    report = get_chinese_social_sentiment("600519", "2026-05-11")

    assert "💬 投资社区情绪" in report
    assert "同花顺: 1条" in report
    assert "东方财富: 1条" in report
    assert "雪球: 1条" in report
    assert "同花顺 投资者看好 600519" in report


def test_chinese_social_report_marks_forum_failure_and_uses_news_context(monkeypatch):
    def fake_fetch(self, source, ticker, days):
        if source == "同花顺":
            return []
        raise ValueError(f"{source} 返回非JSON/HTML页面")

    def fake_news(self, term, days):
        return [
            {
                "title": f"{term} 获机构买入并上涨",
                "content": "业绩增长，市场看好",
                "source": "东方财富新闻",
            }
        ]

    monkeypatch.setattr(ChineseFinanceDataAggregator, "_fetch_forum_source", fake_fetch)
    monkeypatch.setattr(ChineseFinanceDataAggregator, "_search_finance_news", fake_news)

    report = get_chinese_social_sentiment("001309", "2026-05-20")

    assert "社区讨论源异常，不代表真实市场情绪真空" in report
    assert "已使用财经新闻情绪作为补充参考" in report
    assert "东方财富: 0条 (failed)" in report
    assert "雪球: 0条 (failed)" in report
    assert "新闻数量: 1条" in report
