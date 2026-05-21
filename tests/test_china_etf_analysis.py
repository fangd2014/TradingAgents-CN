import asyncio
from unittest import mock

import pandas as pd

from tradingagents.dataflows.providers.china import etf
from tradingagents.utils.stock_utils import StockUtils


def test_stock_utils_identifies_common_a_share_etfs():
    sh_etf = StockUtils.get_market_info("510300")
    sz_etf = StockUtils.get_market_info("159915")
    sci_etf = StockUtils.get_market_info("588000")

    assert sh_etf["market_name"] == "A股ETF"
    assert sh_etf["is_china"]
    assert sh_etf["is_china_etf"]
    assert sz_etf["market_name"] == "A股ETF"
    assert sz_etf["is_china_etf"]
    assert sci_etf["market_name"] == "A股ETF"
    assert sci_etf["is_china_etf"]

    stock = StockUtils.get_market_info("300750")
    assert stock["market_name"] == "中国A股"
    assert not stock["is_china_etf"]


class FakeAkshare:
    def fund_etf_hist_em(self, symbol, period, start_date, end_date, adjust):
        return pd.DataFrame(
            {
                "日期": pd.date_range("2026-04-01", periods=70, freq="D"),
                "开盘": [1.0 + i * 0.01 for i in range(70)],
                "收盘": [1.01 + i * 0.01 for i in range(70)],
                "最高": [1.02 + i * 0.01 for i in range(70)],
                "最低": [0.99 + i * 0.01 for i in range(70)],
                "成交量": [100000 + i for i in range(70)],
                "成交额": [1000000 + i * 100 for i in range(70)],
                "涨跌幅": [0.1] * 70,
            }
        )

    def fund_etf_spot_em(self):
        return pd.DataFrame(
            {
                "代码": ["510300"],
                "名称": ["沪深300ETF"],
                "最新价": [1.7],
                "涨跌幅": [0.5],
                "成交额": [123456789],
            }
        )

    def fund_etf_fund_info_em(self, fund, start_date, end_date):
        return pd.DataFrame(
            {
                "净值日期": ["2026-05-08"],
                "单位净值": [1.698],
                "累计净值": [1.698],
                "日增长率": [0.42],
            }
        )

    def fund_etf_spot_ths(self):
        return pd.DataFrame(
            {
                "基金代码": ["510300"],
                "基金名称": ["沪深300ETF"],
                "当前-单位净值": [1.7],
                "增长率": [0.5],
            }
        )

    def fund_etf_fund_daily_em(self):
        return pd.DataFrame(
            {
                "基金代码": ["510300"],
                "基金简称": ["沪深300ETF"],
                "市价": [1.7],
                "增长率": ["0.5%"],
            }
        )

    def fund_info_index_em(self, symbol, indicator):
        return pd.DataFrame(
            {
                "基金代码": ["510300"],
                "基金名称": ["沪深300ETF"],
                "跟踪标的": ["沪深300指数"],
                "近1年": ["12.34%"],
            }
        )


class FakeAkshareWithSinaFallback(FakeAkshare):
    def fund_etf_hist_em(self, symbol, period, start_date, end_date, adjust):
        raise ConnectionError("eastmoney disconnected")

    def fund_etf_hist_sina(self, symbol):
        assert symbol == "sh510300"
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-04-01", periods=70, freq="D"),
                "open": [1.0 + i * 0.01 for i in range(70)],
                "high": [1.02 + i * 0.01 for i in range(70)],
                "low": [0.99 + i * 0.01 for i in range(70)],
                "close": [1.01 + i * 0.01 for i in range(70)],
                "volume": [100000 + i for i in range(70)],
                "amount": [1000000 + i * 100 for i in range(70)],
            }
        )


def test_etf_market_data_formats_history_and_indicators_without_live_network():
    with mock.patch.object(etf, "_load_akshare", return_value=FakeAkshare()):
        result = etf.get_china_etf_market_data("510300", "2026-04-01", "2026-05-08")

    assert "# 510300 A股ETF市场数据" in result
    assert "沪深300ETF" in result
    assert "## 技术指标" in result
    assert "MA5 / MA10 / MA20 / MA60" in result
    assert "ETF价格主要受跟踪指数" in result


def test_etf_fundamentals_formats_nav_and_tracking_info_without_live_network():
    with mock.patch.object(etf, "_load_akshare", return_value=FakeAkshare()):
        result = etf.get_china_etf_fundamentals_data("510300", "2026-05-08")

    assert "# 510300 A股ETF基础分析" in result
    assert "基金净值/规模信息" in result
    assert "跟踪标的与业绩概览" in result
    assert "沪深300指数" in result
    assert "ETF基本面分析框架" in result


def test_async_stock_validator_accepts_a_share_etf_without_common_stock_history():
    from tradingagents.utils.stock_validator import prepare_stock_data_async

    async def run_validation():
        return await prepare_stock_data_async(
            stock_code="510300",
            market_type="A股",
            period_days=30,
            analysis_date="2026-05-08",
        )

    with mock.patch.object(etf, "_load_akshare", return_value=FakeAkshare()):
        result = asyncio.run(run_validation())

    assert result.is_valid is True
    assert result.market_type == "A股ETF"
    assert result.has_historical_data is True
    assert result.has_basic_info is True


def test_async_stock_validator_accepts_a_share_etf_with_sina_history_fallback():
    from tradingagents.utils.stock_validator import prepare_stock_data_async

    async def run_validation():
        return await prepare_stock_data_async(
            stock_code="510300",
            market_type="A股",
            period_days=30,
            analysis_date="2026-05-08",
        )

    with mock.patch.object(etf, "_load_akshare", return_value=FakeAkshareWithSinaFallback()):
        result = asyncio.run(run_validation())

    assert result.is_valid is True
    assert result.market_type == "A股ETF"
    assert result.has_historical_data is True
    assert result.has_basic_info is True
