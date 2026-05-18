import pytest

from app.services.stock_detail_insight_service import (
    StockDetailInsightService,
    calculate_magic_nine,
    is_a_share_stock,
    normalize_code6,
)


def _bars(closes):
    return [
        {"trade_date": f"202605{idx + 1:02d}", "close": close}
        for idx, close in enumerate(closes)
    ]


def test_normalize_code6_strips_suffix_and_pads():
    assert normalize_code6("688049.SH") == "688049"
    assert normalize_code6("1") == "000001"


def test_calculate_magic_nine_up_signal():
    bars = _bars([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "up"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "up"
    assert result["latest_signal"]["count"] == 9
    assert result["latest_signal"]["date"] == "20260513"


def test_calculate_magic_nine_down_signal():
    bars = _bars([20, 20, 20, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11])

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "down"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "down"


def test_calculate_magic_nine_insufficient_data():
    result = calculate_magic_nine(_bars([1, 2, 3, 4]))

    assert result["status"] == "insufficient_data"
    assert result["required_bars"] == 13


def test_calculate_magic_nine_non_zero_padded_dates_sorted_chronologically():
    bars = [
        {"trade_date": f"2026-05-{idx}", "close": close}
        for idx, close in enumerate([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], start=1)
    ]

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "up"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "up"
    assert result["latest_signal"]["count"] == 9
    assert result["latest_signal"]["date"] == "2026-05-13"


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self._limit = None

    def sort(self, field, direction=1):
        reverse = direction == -1
        self.docs.sort(
            key=lambda item: (item.get(field) is None, item.get(field)),
            reverse=reverse,
        )
        return self

    def limit(self, limit):
        self._limit = limit
        return self

    async def to_list(self, length=None):
        docs = self.docs
        if self._limit is not None:
            docs = docs[: self._limit]
        if length is not None:
            docs = docs[:length]
        return docs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.updated = []

    @staticmethod
    def _matches(doc, query):
        if not query:
            return True
        for key, expected in query.items():
            if key == "$or":
                return any(FakeCollection._matches(doc, item) for item in expected)
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                else:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _project(doc, projection):
        if projection is None:
            return dict(doc)

        include_keys = [key for key, flag in projection.items() if flag and key != "_id"]
        if include_keys:
            return {key: doc.get(key) for key in include_keys if key in doc}

        excluded = {key for key, flag in projection.items() if not flag}
        return {key: value for key, value in doc.items() if key not in excluded}

    def find(self, query=None, projection=None):
        matched = [doc for doc in self.docs if self._matches(doc, query)]
        projected = [self._project(doc, projection) for doc in matched]
        return FakeCursor(projected)

    async def update_one(self, query, update, upsert=False):
        self.updated.append((query, update, upsert))


class FindOneCollection(FakeCollection):
    def __init__(self, doc):
        super().__init__([])
        self.doc = doc

    async def find_one(self, *_args, **_kwargs):
        return self.doc


class FakeDb(dict):
    def __getitem__(self, name):
        return super().__getitem__(name)


@pytest.mark.asyncio
async def test_get_financial_detail_uses_cache_without_refresh():
    db = FakeDb(
        {
            "stock_financial_data": FakeCollection(
                [
                    {
                        "symbol": "688049",
                        "report_period": "20251231",
                        "data_source": "tushare",
                        "updated_at": "2026-05-18T20:00:00+08:00",
                        "raw_data": {
                            "income_statement": [{"end_date": "20251231", "revenue": 100}],
                            "balance_sheet": [{"end_date": "20251231", "total_assets": 200}],
                            "cashflow_statement": [{"end_date": "20251231", "n_cashflow_act": 30}],
                            "financial_indicators": [{"end_date": "20251231", "roe": 9.5}],
                            "main_business": [{"end_date": "20251231", "bz_item": "产品A"}],
                        },
                    }
                ]
            )
        }
    )
    service = StockDetailInsightService(db=db)

    result = await service.get_financial_detail("688049", periods=8, refresh=False)

    assert result["status"] == "ok"
    assert result["is_cached"] is True
    assert result["source"] == "mongodb"
    assert result["income_statement"][0]["revenue"] == 100
    assert result["main_business"][0]["bz_item"] == "产品A"


@pytest.mark.asyncio
async def test_get_financial_detail_unsupported_etf():
    service = StockDetailInsightService(db=FakeDb({"stock_financial_data": FakeCollection([])}))

    result = await service.get_financial_detail("588000")

    assert result["status"] == "unsupported"
    assert "ETF" in result["message"]


@pytest.mark.parametrize("code", ["200001", "900901", "110031", "400001", "800001"])
def test_is_a_share_stock_rejects_non_ordinary_a_share(code):
    assert is_a_share_stock(code) is False


@pytest.mark.parametrize("code", ["000001", "002027", "300750", "600519", "688049", "920001"])
def test_is_a_share_stock_accepts_supported_ordinary_a_share(code):
    assert is_a_share_stock(code) is True


@pytest.mark.asyncio
async def test_get_financial_detail_refresh_success_uses_tushare_source():
    initial_doc = {
        "symbol": "688049",
        "report_period": "20241231",
        "updated_at": "2026-05-01T00:00:00+08:00",
        "raw_data": {
            "income_statement": [{"revenue": 10}],
            "balance_sheet": [],
            "cashflow_statement": [],
            "financial_indicators": [],
            "main_business": [],
        },
    }
    refreshed_doc = {
        "symbol": "688049",
        "report_period": "20251231",
        "updated_at": "2026-05-18T21:00:00+08:00",
        "raw_data": {
            "income_statement": [{"revenue": 999}],
            "balance_sheet": [],
            "cashflow_statement": [],
            "financial_indicators": [],
            "main_business": [],
        },
    }
    db = FakeDb({"stock_financial_data": FakeCollection([initial_doc])})

    class RefreshSuccessService(StockDetailInsightService):
        async def _refresh_tushare_financial(self, code6: str, periods: int) -> bool:
            self.db["stock_financial_data"].docs = [refreshed_doc]
            return True

        async def _refresh_akshare_financial(self, code6: str) -> bool:
            return False

    service = RefreshSuccessService(db=db)
    result = await service.get_financial_detail("688049", refresh=True)

    assert result["status"] == "ok"
    assert result["source"] == "tushare"
    assert result["is_cached"] is False
    assert result["income_statement"][0]["revenue"] == 999


@pytest.mark.asyncio
async def test_get_financial_detail_refresh_failure_with_cache_returns_warning():
    cached_doc = {
        "symbol": "688049",
        "report_period": "20251231",
        "updated_at": "2026-05-18T20:00:00+08:00",
        "raw_data": {
            "income_statement": [{"revenue": 88}],
            "balance_sheet": [],
            "cashflow_statement": [],
            "financial_indicators": [],
            "main_business": [],
        },
    }
    db = FakeDb({"stock_financial_data": FakeCollection([cached_doc])})

    class RefreshFailService(StockDetailInsightService):
        async def _refresh_tushare_financial(self, code6: str, periods: int) -> bool:
            return False

        async def _refresh_akshare_financial(self, code6: str) -> bool:
            return False

    service = RefreshFailService(db=db)
    result = await service.get_financial_detail("688049", refresh=True)

    assert result["status"] == "ok"
    assert result["source"] == "mongodb"
    assert result["is_cached"] is True
    assert "warning" in result


@pytest.mark.asyncio
async def test_get_financial_detail_refresh_failure_without_cache_returns_empty():
    db = FakeDb({"stock_financial_data": FakeCollection([])})

    class RefreshFailNoCacheService(StockDetailInsightService):
        async def _refresh_tushare_financial(self, code6: str, periods: int) -> bool:
            return False

        async def _refresh_akshare_financial(self, code6: str) -> bool:
            return False

    service = RefreshFailNoCacheService(db=db)
    result = await service.get_financial_detail("688049", refresh=True)

    assert result["status"] == "empty"
    assert result["income_statement"] == []
    assert result["balance_sheet"] == []
    assert result["cashflow_statement"] == []
    assert result["financial_indicators"] == []
    assert result["main_business"] == []
    assert result["summary"] == {}
    assert result["source"] is None
    assert result["last_updated"] is None
    assert result["is_cached"] is False


@pytest.mark.asyncio
async def test_get_financial_detail_summary_preserves_zero_values():
    doc = {
        "symbol": "688049",
        "report_period": "20251231",
        "revenue_ttm": 0,
        "net_profit_ttm": 0,
        "updated_at": "2026-05-18T20:00:00+08:00",
        "raw_data": {
            "income_statement": [{"n_income": 0}],
            "balance_sheet": [{"debt_to_assets": 55}],
            "cashflow_statement": [],
            "financial_indicators": [{"debt_to_assets": 0}],
            "main_business": [],
        },
    }
    service = StockDetailInsightService(db=FakeDb({"stock_financial_data": FakeCollection([doc])}))
    result = await service.get_financial_detail("688049", refresh=False)

    assert result["summary"]["revenue_ttm"] == 0
    assert result["summary"]["net_profit"] == 0
    assert result["summary"]["net_profit_ttm"] == 0
    assert result["summary"]["debt_to_assets"] == 0


@pytest.mark.asyncio
async def test_get_financial_detail_akshare_flattened_cache_summary_only():
    doc = {
        "symbol": "688049",
        "report_period": "20251231",
        "data_source": "akshare",
        "updated_at": "2026-05-18T20:00:00+08:00",
        "revenue": 123.0,
        "net_income": 45.0,
        "total_assets": 1000.0,
        "total_liab": 400.0,
        "total_equity": 600.0,
        "cash_and_equivalents": 80.0,
        "roe": 9.2,
        "debt_to_assets": 40.0,
    }
    service = StockDetailInsightService(db=FakeDb({"stock_financial_data": FakeCollection([doc])}))

    result = await service.get_financial_detail("688049", refresh=False)

    assert result["status"] == "ok"
    assert result["message"] == "summary_only"
    assert result["detail_available"] is False
    assert result["summary"]["revenue"] == 123.0
    assert result["summary"]["net_income"] == 45.0
    assert result["summary"]["total_assets"] == 1000.0
    assert result["summary"]["total_liab"] == 400.0
    assert result["summary"]["total_equity"] == 600.0
    assert result["summary"]["cash_and_equivalents"] == 80.0
    assert result["summary"]["roe"] == 9.2
    assert result["summary"]["debt_to_assets"] == 40.0


@pytest.mark.asyncio
async def test_get_financial_detail_refresh_tushare_noop_result_returns_cached_warning(monkeypatch):
    import sys
    import types

    cached_doc = {
        "symbol": "688049",
        "report_period": "20251231",
        "updated_at": "2026-05-18T20:00:00+08:00",
        "raw_data": {
            "income_statement": [{"revenue": 88}],
            "balance_sheet": [],
            "cashflow_statement": [],
            "financial_indicators": [],
            "main_business": [],
        },
    }
    db = FakeDb({"stock_financial_data": FakeCollection([cached_doc])})

    class NoopTushareService(StockDetailInsightService):
        async def _refresh_akshare_financial(self, code6: str) -> bool:
            return False

    class FakeTushareSyncService:
        async def sync_financial_data(self, symbols=None, limit=20):
            return {"success_count": 0, "error_count": 0}

    async def fake_get_tushare_sync_service():
        return FakeTushareSyncService()

    fake_module = types.SimpleNamespace(get_tushare_sync_service=fake_get_tushare_sync_service)
    monkeypatch.setitem(sys.modules, "app.worker.tushare_sync_service", fake_module)

    service = NoopTushareService(db=db)
    result = await service.get_financial_detail("688049", refresh=True)

    assert result["status"] == "ok"
    assert result["source"] == "mongodb"
    assert result["is_cached"] is True
    assert "warning" in result


@pytest.mark.asyncio
async def test_get_industry_comparison_computes_rank_and_percentile():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "roe": 12, "pb": 2.0, "pe": 20, "total_mv": 100},
                    {"symbol": "600001", "report_period": "20251231", "roe": 8, "pb": 1.5, "pe": 18, "total_mv": 80},
                    {"symbol": "600002", "report_period": "20251231", "roe": 16, "pb": 2.5, "pe": 22, "total_mv": 120},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["industry"] == "电气设备"
    assert result["sample_count"] == 3
    assert result["metrics"]["roe"]["stock_value"] == 12
    assert result["metrics"]["roe"]["industry_median"] == 12
    assert result["metrics"]["roe"]["rank"] == 2


@pytest.mark.asyncio
async def test_get_industry_comparison_sample_insufficient():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "roe": 12},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "sample_insufficient"
    assert result["sample_count"] == 1
    assert result["metrics"]["roe"]["stock_value"] == 12
    assert result["metrics"]["roe"]["industry_median"] is None
    assert result["metrics"]["roe"]["rank"] is None
    assert result["metrics"]["roe"]["percentile"] is None


@pytest.mark.asyncio
async def test_get_industry_comparison_two_metric_values_computes_statistics():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "roe": 12},
                    {"symbol": "600001", "report_period": "20251231", "roe": 8},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "sample_insufficient"
    assert result["sample_count"] == 2
    assert result["metrics"]["roe"]["stock_value"] == 12
    assert result["metrics"]["roe"]["industry_median"] == 10
    assert result["metrics"]["roe"]["rank"] == 1
    assert result["metrics"]["roe"]["percentile"] == 100


@pytest.mark.asyncio
async def test_get_industry_comparison_reads_code_only_financial_docs():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"code": "688049", "report_period": "20251231", "roe": 12},
                    {"code": "600001", "report_period": "20251231", "roe": 8},
                    {"code": "600002", "report_period": "20251231", "roe": 16},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["sample_count"] == 3
    assert result["metrics"]["roe"]["stock_value"] == 12
    assert result["metrics"]["roe"]["industry_median"] == 12
    assert result["metrics"]["roe"]["rank"] == 2


@pytest.mark.asyncio
async def test_get_industry_comparison_gross_margin_uses_grossprofit_margin_alias():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "grossprofit_margin": 35.0},
                    {"symbol": "600001", "report_period": "20251231", "grossprofit_margin": 30.0},
                    {"symbol": "600002", "report_period": "20251231", "grossprofit_margin": 40.0},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["metrics"]["gross_margin"]["stock_value"] == 35.0
    assert result["metrics"]["gross_margin"]["industry_median"] == 35.0
    assert result["metrics"]["gross_margin"]["rank"] == 2


@pytest.mark.asyncio
async def test_get_industry_comparison_dedupes_duplicate_sources_prefers_tushare():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "data_source": "akshare", "roe": 5},
                    {"symbol": "688049", "report_period": "20251231", "data_source": "tushare", "roe": 12},
                    {"symbol": "600001", "report_period": "20251231", "data_source": "tushare", "roe": 8},
                    {"symbol": "600002", "report_period": "20251231", "data_source": "tushare", "roe": 16},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["sample_count"] == 3
    assert result["metrics"]["roe"]["stock_value"] == 12
    assert result["metrics"]["roe"]["industry_median"] == 12
    assert result["metrics"]["roe"]["rank"] == 2


@pytest.mark.asyncio
async def test_get_industry_comparison_period_filters_exact_report_period():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20241231", "roe": 4, "data_source": "tushare"},
                    {"symbol": "688049", "report_period": "20251231", "roe": 12, "data_source": "tushare"},
                    {"symbol": "600001", "report_period": "20241231", "roe": 2, "data_source": "tushare"},
                    {"symbol": "600001", "report_period": "20251231", "roe": 8, "data_source": "tushare"},
                    {"symbol": "600002", "report_period": "20241231", "roe": 6, "data_source": "tushare"},
                    {"symbol": "600002", "report_period": "20251231", "roe": 16, "data_source": "tushare"},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049", period="20241231")

    assert result["status"] == "ok"
    assert result["period"] == "20241231"
    assert result["sample_count"] == 3
    assert result["metrics"]["roe"]["stock_value"] == 4
    assert result["metrics"]["roe"]["industry_median"] == 4
    assert result["metrics"]["roe"]["rank"] == 2


@pytest.mark.asyncio
async def test_get_industry_comparison_target_stock_financial_missing_returns_empty():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "600001", "report_period": "20251231", "roe": 8},
                    {"symbol": "600002", "report_period": "20251231", "roe": 16},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "empty"
    assert result["message"] == "未找到目标股票财务数据"
    assert result["sample_count"] == 2
    assert result["metrics"] == {}


@pytest.mark.asyncio
async def test_get_industry_comparison_preserves_zero_metric_stock_value():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "roe": 0},
                    {"symbol": "600001", "report_period": "20251231", "roe": 3},
                    {"symbol": "600002", "report_period": "20251231", "roe": 6},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["metrics"]["roe"]["stock_value"] == 0
    assert result["metrics"]["roe"]["industry_median"] == 3
    assert result["metrics"]["roe"]["rank"] == 3


@pytest.mark.asyncio
async def test_get_industry_comparison_missing_stock_metric_suppresses_statistics():
    db = FakeDb(
        {
            "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
            "stock_financial_data": FakeCollection(
                [
                    {"symbol": "688049", "report_period": "20251231", "pb": 2.0},
                    {"symbol": "600001", "report_period": "20251231", "roe": 8},
                    {"symbol": "600002", "report_period": "20251231", "roe": 16},
                ]
            ),
        }
    )
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049", "600001", "600002"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "ok"
    assert result["metrics"]["roe"]["stock_value"] is None
    assert result["metrics"]["roe"]["industry_median"] is None
    assert result["metrics"]["roe"]["rank"] is None
    assert result["metrics"]["roe"]["percentile"] is None


@pytest.mark.asyncio
async def test_get_technical_factors_returns_magic_nine_and_core_factors():
    closes = [10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    bars = [
        {
            "symbol": "688049",
            "period": "daily",
            "trade_date": f"202605{idx + 1:02d}",
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + idx,
            "turnover_rate": 1.5 + idx * 0.01,
        }
        for idx, close in enumerate(closes)
    ]
    db = FakeDb({"stock_daily_quotes": FakeCollection(bars)})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "ok"
    assert result["source"] == "mongodb"
    assert result["is_cached"] is True
    assert result["magic_nine"]["current_direction"] == "up"
    for key in [
        "ma_5",
        "ma_20",
        "ema_12",
        "ema_26",
        "macd",
        "rsi_14",
        "boll",
        "kdj",
        "atr_14",
        "volume_ma_5",
        "turnover_summary",
    ]:
        assert key in result["factors"]
    assert result["factors"]["turnover_summary"]["latest"] is not None


@pytest.mark.asyncio
async def test_get_technical_factors_prefers_daily_or_none_period_bars():
    daily_up = [
        {
            "symbol": "688049",
            "period": "daily",
            "trade_date": f"202605{idx + 1:02d}",
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + idx,
        }
        for idx, close in enumerate([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
    ]
    weekly_down = [
        {
            "symbol": "688049",
            "period": "weekly",
            "trade_date": f"202605{idx + 1:02d}",
            "open": close + 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 2000 + idx,
        }
        for idx, close in enumerate([20, 20, 20, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11])
    ]
    db = FakeDb({"stock_daily_quotes": FakeCollection(daily_up + weekly_down)})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "ok"
    assert result["magic_nine"]["current_direction"] == "up"


@pytest.mark.asyncio
async def test_get_technical_factors_no_kline_data_returns_insufficient_data():
    db = FakeDb({"stock_daily_quotes": FakeCollection([])})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "insufficient_data"
    assert result["message"] == "本地K线数据不足，请先同步历史行情"


@pytest.mark.asyncio
async def test_get_technical_factors_unusable_close_values_return_insufficient_data():
    bars = [
        {
            "symbol": "688049",
            "period": "daily",
            "trade_date": f"202605{idx + 1:02d}",
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": 1000,
        }
        for idx in range(13)
    ]
    db = FakeDb({"stock_daily_quotes": FakeCollection(bars)})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "insufficient_data"
    assert result["available_bars"] == 0
    assert result["factors"] == {}
    assert result["magic_nine"]["status"] == "insufficient_data"


@pytest.mark.asyncio
async def test_get_technical_factors_preserves_zero_value_signals():
    bars = [
        {
            "symbol": "688049",
            "period": None,
            "trade_date": f"202605{idx + 1:02d}",
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 0,
            "volume": 0,
        }
        for idx in range(13)
    ]
    db = FakeDb({"stock_daily_quotes": FakeCollection(bars)})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "ok"
    assert result["factors"]["ma_5"]["latest"] == 0
    assert result["factors"]["ma_5"]["signal"] == "多头"
