import pandas as pd


def test_stock_info_overlays_app_cache_with_direct_latest_quote(monkeypatch):
    from tradingagents.dataflows import data_source_manager as manager_module
    from tradingagents.dataflows.data_source_manager import DataSourceManager

    monkeypatch.setattr(
        "tradingagents.config.runtime_settings.use_app_cache_enabled",
        lambda default=False: True,
    )

    class CacheAdapter:
        @staticmethod
        def get_basics_from_cache(symbol):
            return {
                "code": symbol,
                "name": "远东股份",
                "industry": "电网设备",
                "market": "主板",
                "list_date": "19950915",
            }

        @staticmethod
        def get_market_quote_dataframe(symbol):
            return pd.DataFrame(
                [{"code": symbol, "close": 22.15, "pct_chg": 3.02, "volume": 528603126, "date": "20260612"}]
            )

    monkeypatch.setitem(__import__("sys").modules, "tradingagents.dataflows.cache.app_adapter", CacheAdapter)
    monkeypatch.setattr(
        manager_module,
        "_fetch_latest_external_quote",
        lambda symbol, context="生成分析报告": {
            "close": 23.45,
            "pct_chg": 6.08,
            "volume": 612000000,
            "source": "tencent_finance",
        },
    )

    result = DataSourceManager().get_stock_info("600869")

    assert result["current_price"] == 23.45
    assert result["change_pct"] == 6.08
    assert result["volume"] == 612000000
    assert result["quote_source"] == "tencent_finance"


def test_fundamentals_report_does_not_let_app_cache_override_direct_quote(monkeypatch):
    from tradingagents.dataflows import optimized_china_data
    from tradingagents.dataflows.optimized_china_data import OptimizedChinaDataProvider

    monkeypatch.setattr(
        optimized_china_data,
        "require_latest_external_quote",
        lambda symbol, context="生成分析报告": {
            "close": 23.45,
            "pct_chg": 6.08,
            "volume": 612000000,
            "source": "tencent_finance",
        },
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.interface.get_china_stock_info_unified",
        lambda symbol: "股票代码: 600869\n股票名称: 远东股份\n当前价格: 22.15\n涨跌幅: +3.02%\n成交量: 528603126",
    )
    monkeypatch.setattr(OptimizedChinaDataProvider, "_estimate_financial_metrics", lambda self, symbol, price: {
        "data_source": "test",
        "total_mv": "N/A",
        "pe": "N/A",
        "pe_ttm": "N/A",
        "pb": "N/A",
        "ps": "N/A",
        "dividend_yield": "N/A",
        "roe": "N/A",
        "roa": "N/A",
        "debt_ratio": "N/A",
        "current_ratio": "N/A",
        "quick_ratio": "N/A",
        "cash_ratio": "N/A",
        "revenue": "N/A",
        "net_profit": "N/A",
        "gross_margin": "N/A",
        "net_margin": "N/A",
        "eps": "N/A",
        "fundamental_score": 5,
        "valuation_score": 5,
        "growth_score": 5,
        "risk_level": "中等",
    })

    report = OptimizedChinaDataProvider()._generate_fundamentals_report(
        "600869",
        "股票代码: 600869\n股票名称: 远东股份\n当前价格: 22.15\n涨跌幅: +3.02%\n成交量: 528603126",
    )

    assert "当前股价**: 23.45" in report
    assert "涨跌幅**: +6.08%" in report
    assert "成交量**: 612000000" in report
    assert "当前股价**: 22.15" not in report


def test_latest_quote_requirement_reports_failure_reason(monkeypatch):
    from tradingagents.dataflows import data_source_manager as manager_module
    from tradingagents.dataflows.data_source_manager import LatestQuoteUnavailableError, require_latest_external_quote

    monkeypatch.setattr(
        manager_module,
        "_fetch_latest_external_quote_with_reason",
        lambda symbol: (None, "Tencent Finance/mootdx returned no quote"),
    )

    try:
        require_latest_external_quote("600869", context="生成分析报告")
    except LatestQuoteUnavailableError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected LatestQuoteUnavailableError")

    assert "无法获取600869最新行情数据" in message
    assert "已中断生成分析报告" in message
    assert "Tencent Finance/mootdx returned no quote" in message


def test_stock_data_falls_back_to_mootdx_kline(monkeypatch):
    from tradingagents.dataflows import data_source_manager as manager_module
    from tradingagents.dataflows.data_source_manager import ChinaDataSource, DataSourceManager

    monkeypatch.setattr(DataSourceManager, "_check_mongodb_enabled", lambda self: True)
    monkeypatch.setattr(DataSourceManager, "_get_default_source", lambda self: ChinaDataSource.MONGODB)
    monkeypatch.setattr(DataSourceManager, "_check_available_sources", lambda self: [ChinaDataSource.MOOTDX])
    monkeypatch.setattr(
        DataSourceManager,
        "_get_data_source_priority_order",
        lambda self, symbol=None: [ChinaDataSource.MOOTDX],
    )
    monkeypatch.setattr(
        DataSourceManager,
        "_get_mongodb_data",
        lambda self, symbol, start_date, end_date, period="daily": (
            f"❌ MongoDB中未找到{symbol}的历史行情数据",
            "mongodb",
        ),
    )
    monkeypatch.setattr(
        DataSourceManager,
        "get_stock_info",
        lambda self, symbol: {"code": symbol, "name": "德明利"},
    )

    class FakeMootdxService:
        @staticmethod
        def get_kline(symbol, period="day", limit=120):
            return [
                {"date": "2026-06-08", "open": 600, "high": 620, "low": 590, "close": 610, "volume": 1000},
                {"date": "2026-06-09", "open": 610, "high": 630, "low": 605, "close": 625, "volume": 1200},
                {"date": "2026-06-10", "open": 625, "high": 640, "low": 615, "close": 632, "volume": 1300},
                {"date": "2026-06-11", "open": 632, "high": 664, "low": 620, "close": 632.35, "volume": 1500},
                {"date": "2026-06-12", "open": 662.1, "high": 664, "low": 617.43, "close": 617.43, "volume": 152458},
            ]

    monkeypatch.setattr(
        "app.services.china_external_data_service.MootdxDeepMarketService",
        lambda: FakeMootdxService(),
    )

    result = DataSourceManager().get_stock_data("001309", "2026-06-08", "2026-06-12")

    assert "德明利(001309)" in result
    assert "技术分析数据" in result
    assert "最新价格: ¥617.43" in result
    assert "所有数据源都无法获取" not in result


def test_fundamentals_report_interrupts_when_latest_quote_unavailable(monkeypatch):
    from tradingagents.dataflows import optimized_china_data
    from tradingagents.dataflows.data_source_manager import LatestQuoteUnavailableError
    from tradingagents.dataflows.optimized_china_data import OptimizedChinaDataProvider

    def fail_quote(symbol, context="生成分析报告"):
        raise LatestQuoteUnavailableError(f"无法获取{symbol}最新行情数据，已中断{context}。失败原因: 网络超时")

    monkeypatch.setattr(optimized_china_data, "require_latest_external_quote", fail_quote)

    try:
        OptimizedChinaDataProvider()._generate_fundamentals_report(
            "600869",
            "股票代码: 600869\n股票名称: 远东股份",
        )
    except LatestQuoteUnavailableError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected LatestQuoteUnavailableError")

    assert "已中断生成分析报告" in message
    assert "网络超时" in message
