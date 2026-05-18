# Stock Detail Financial And Technical Insights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add detailed financial reports, industry comparison, technical factors, magic-nine signals, and quick-action anchors to the existing stock detail page.

**Architecture:** Add a focused backend service, `StockDetailInsightService`, with three independent API surfaces for financial detail, industry comparison, and technical factors. The service reads MongoDB first, refreshes from Tushare only on cache miss or explicit refresh, falls back to AKShare only for financial data, and computes technical factors from local K-line data. The Vue stock detail page adds a “深度数据” card with lazy-loaded tabs plus three right-sidebar shortcut buttons.

**Tech Stack:** FastAPI, Motor/MongoDB, Tushare, AKShare fallback, pandas, Vue 3, TypeScript, Element Plus, Docker Compose.

---

## File Structure

- Create `app/services/stock_detail_insight_service.py`
  - Owns financial-detail reads, industry comparison, magic-nine calculation, technical factor calculation, MongoDB cache access, and provider refresh logic.
- Modify `app/routers/stocks.py`
  - Adds `financial-detail`, `industry-comparison`, and `technical-factors` endpoints under the existing `/api/stocks/{code}` router.
- Modify `frontend/src/api/stocks.ts`
  - Adds TypeScript interfaces and API methods for the three new backend endpoints.
- Modify `frontend/src/views/Stocks/Detail.vue`
  - Adds “深度数据” tabs below K-line and above news.
  - Adds `详细财报` / `技术因子` / `神奇九转` buttons in the right “快捷操作” card.
  - Adds lazy loading, refresh, error states, and anchor scrolling.
- Add `tests/services/test_stock_detail_insight_service.py`
  - Tests pure normalization, industry ranking, magic-nine, technical factors, and no-data statuses.
- Add `tests/test_stock_detail_insight_api.py`
  - Tests endpoint response envelopes and unsupported symbol behavior.
- Add `frontend/src/views/Stocks/detailInsightShortcuts.ts`
  - Provides a small typed helper for shortcut-to-tab/anchor mapping.
- Add `frontend/src/views/Stocks/__tests__/detailInsightShortcuts.test.ts`
  - Documents the helper behavior; run only if the local frontend test runner is available.
- Modify `docs/features/stock-detail/README.md` or create it if missing.
  - Documents the new stock detail deep data area and data-source behavior.
- Modify or add `docs/deployment/docker/stock-detail-insights-hot-deploy.md`
  - Documents the required hot-deploy command and MongoDB preservation rule.

---

## Task 1: Backend Pure Calculations

**Files:**
- Create: `app/services/stock_detail_insight_service.py`
- Test: `tests/services/test_stock_detail_insight_service.py`

- [ ] **Step 1: Write failing tests for magic-nine calculation**

Add this to `tests/services/test_stock_detail_insight_service.py`:

```python
from app.services.stock_detail_insight_service import (
    calculate_magic_nine,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: import failure because `app.services.stock_detail_insight_service` does not exist.

- [ ] **Step 3: Implement minimal pure functions**

Create `app/services/stock_detail_insight_service.py` with:

```python
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


def normalize_code6(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _bar_date(bar: Dict[str, Any]) -> str:
    return str(bar.get("trade_date") or bar.get("date") or bar.get("time") or "")


def calculate_magic_nine(bars: List[Dict[str, Any]], lookback: int = 4, target_count: int = 9) -> Dict[str, Any]:
    required_bars = lookback + target_count
    cleaned = [
        {"date": _bar_date(bar), "close": _safe_float(bar.get("close"))}
        for bar in bars
        if _safe_float(bar.get("close")) is not None
    ]
    cleaned.sort(key=lambda item: item["date"])

    if len(cleaned) < required_bars:
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - close.shift(1)).abs()
        low_prev_close = (df["low"] - close.shift(1)).abs()
        true_range = pd.concat([high_low.abs(), high_prev_close, low_prev_close], axis=1).max(axis=1)
        atr_14 = true_range.rolling(window=14, min_periods=14).mean()
        low_9 = df["low"].rolling(window=9, min_periods=9).min()
        high_9 = df["high"].rolling(window=9, min_periods=9).max()
        rsv = (close - low_9) / (high_9 - low_9).replace(0, pd.NA) * 100
        kdj_k = rsv.ewm(com=2, adjust=False).mean()
        kdj_d = kdj_k.ewm(com=2, adjust=False).mean()
        kdj_j = 3 * kdj_k - 2 * kdj_d

        latest_k = _safe_float(kdj_k.iloc[-1])
        latest_d = _safe_float(kdj_d.iloc[-1])
        latest_atr = _safe_float(atr_14.iloc[-1])

        return {
            "status": "insufficient_data",
            "required_bars": required_bars,
            "available_bars": len(cleaned),
            "current_direction": "none",
            "current_count": 0,
            "latest_signal": None,
            "sequence": [],
        }

    up_count = 0
    down_count = 0
    sequence: List[Dict[str, Any]] = []
    latest_signal = None

    for idx, item in enumerate(cleaned):
        if idx < lookback:
            sequence.append({
                "date": item["date"],
                "close": item["close"],
                "direction": "none",
                "count": 0,
                "signal": None,
            })
            continue

        prior_close = cleaned[idx - lookback]["close"]
        direction = "none"
        count = 0
        signal = None

        if item["close"] > prior_close:
            up_count += 1
            down_count = 0
            direction = "up"
            count = up_count
        elif item["close"] < prior_close:
            down_count += 1
            up_count = 0
            direction = "down"
            count = down_count
        else:
            up_count = 0
            down_count = 0

        if count >= target_count:
            signal = {"direction": direction, "count": count, "date": item["date"]}
            latest_signal = signal

        sequence.append({
            "date": item["date"],
            "close": item["close"],
            "direction": direction,
            "count": count,
            "signal": signal,
        })

    last = sequence[-1]
    return {
        "status": "ok",
        "required_bars": required_bars,
        "available_bars": len(cleaned),
        "current_direction": last["direction"],
        "current_count": last["count"],
        "latest_signal": latest_signal,
        "sequence": sequence[-30:],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_detail_insight_service.py tests/services/test_stock_detail_insight_service.py
git commit -m "Add stock detail insight calculations" \
  -m "Magic-nine and code normalization are pure calculations, so they are introduced first with focused tests before wiring database or provider access." \
  -m "Tested: pytest tests/services/test_stock_detail_insight_service.py -q" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow"
```

---

## Task 2: Financial Detail Service

**Files:**
- Modify: `app/services/stock_detail_insight_service.py`
- Test: `tests/services/test_stock_detail_insight_service.py`

- [ ] **Step 1: Add failing financial detail tests**

Append:

```python
import pytest

from app.services.stock_detail_insight_service import StockDetailInsightService


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, _limit):
        return self

    async def to_list(self, length=None):
        return self.docs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.updated = []

    def find(self, *_args, **_kwargs):
        return FakeCursor(self.docs)

    async def update_one(self, query, update, upsert=False):
        self.updated.append((query, update, upsert))


class FakeDb(dict):
    def __getitem__(self, name):
        return super().__getitem__(name)


@pytest.mark.asyncio
async def test_get_financial_detail_uses_cache_without_refresh():
    db = FakeDb({
        "stock_financial_data": FakeCollection([
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
        ])
    })
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: failure because `StockDetailInsightService` is not defined.

- [ ] **Step 3: Implement service class and financial cache read**

Add this below the pure functions in `app/services/stock_detail_insight_service.py`:

```python
def is_a_share_stock(code: str) -> bool:
    code6 = normalize_code6(code)
    return len(code6) == 6 and code6.isdigit() and not (
        code6.startswith("159")
        or code6.startswith("51")
        or code6.startswith("56")
        or code6.startswith("58")
    )


class StockDetailInsightService:
    def __init__(self, db):
        self.db = db

    def _unsupported_response(self, code: str) -> Dict[str, Any]:
        return {
            "code": normalize_code6(code),
            "status": "unsupported",
            "message": "当前深度数据仅支持A股普通股票，暂不支持ETF、港股或美股",
        }

    async def _financial_cache(self, code6: str, periods: int) -> List[Dict[str, Any]]:
        cursor = (
            self.db["stock_financial_data"]
            .find({"symbol": code6}, {"_id": 0})
            .sort("report_period", -1)
            .limit(periods)
        )
        return await cursor.to_list(length=None)

    def _financial_payload(self, code6: str, docs: List[Dict[str, Any]], source: str, is_cached: bool) -> Dict[str, Any]:
        latest = docs[0] if docs else {}
        raw = latest.get("raw_data") or {}
        return {
            "code": code6,
            "status": "ok" if docs else "empty",
            "periods": [doc.get("report_period") for doc in docs if doc.get("report_period")],
            "income_statement": raw.get("income_statement", []),
            "balance_sheet": raw.get("balance_sheet", []),
            "cashflow_statement": raw.get("cashflow_statement", raw.get("cash_flow", [])),
            "financial_indicators": raw.get("financial_indicators", []),
            "main_business": raw.get("main_business", []),
            "summary": {
                "report_period": latest.get("report_period"),
                "ann_date": latest.get("ann_date"),
                "revenue": latest.get("revenue"),
                "revenue_ttm": latest.get("revenue_ttm"),
                "net_profit": latest.get("net_profit"),
                "net_profit_ttm": latest.get("net_profit_ttm"),
                "roe": latest.get("roe"),
                "roa": latest.get("roa"),
                "gross_margin": latest.get("gross_margin"),
                "netprofit_margin": latest.get("netprofit_margin"),
                "debt_to_assets": latest.get("debt_to_assets"),
                "current_ratio": latest.get("current_ratio"),
                "quick_ratio": latest.get("quick_ratio"),
            },
            "source": source,
            "last_updated": latest.get("updated_at"),
            "is_cached": is_cached,
        }

    async def get_financial_detail(self, code: str, periods: int = 8, refresh: bool = False) -> Dict[str, Any]:
        code6 = normalize_code6(code)
        if not is_a_share_stock(code6):
            return self._unsupported_response(code6)

        cached_docs = await self._financial_cache(code6, periods)
        if cached_docs and not refresh:
            return self._financial_payload(code6, cached_docs, source="mongodb", is_cached=True)

        if refresh or not cached_docs:
            refreshed = await self._refresh_tushare_financial(code6, periods)
            if refreshed:
                cached_docs = await self._financial_cache(code6, periods)
                return self._financial_payload(code6, cached_docs, source="tushare", is_cached=False)

        if cached_docs:
            payload = self._financial_payload(code6, cached_docs, source="mongodb", is_cached=True)
            payload["warning"] = "刷新失败，已返回缓存数据"
            return payload

        return {
            "code": code6,
            "status": "empty",
            "message": "未获取到详细财报数据",
            "periods": [],
            "income_statement": [],
            "balance_sheet": [],
            "cashflow_statement": [],
            "financial_indicators": [],
            "main_business": [],
            "summary": {},
            "source": None,
            "last_updated": None,
            "is_cached": False,
        }

    async def _refresh_tushare_financial(self, code6: str, periods: int) -> bool:
        try:
            from app.worker.tushare_sync_service import get_tushare_sync_service

            service = await get_tushare_sync_service()
            result = await service.sync_financial_data(symbols=[code6], limit=periods)
            return bool(result.get("success_count", 0) > 0)
        except Exception:
            return await self._refresh_akshare_financial(code6)

    async def _refresh_akshare_financial(self, code6: str) -> bool:
        try:
            from app.services.financial_data_service import get_financial_data_service
            from tradingagents.dataflows.providers.china.akshare import AKShareProvider

            provider = AKShareProvider()
            connected = await provider.connect()
            if not connected:
                return False
            financial_data = await provider.get_financial_data(code6)
            if not financial_data:
                return False
            service = await get_financial_data_service()
            saved_count = await service.save_financial_data(
                symbol=code6,
                financial_data=financial_data,
                data_source="akshare",
                market="CN",
                report_type="quarterly",
            )
            return saved_count > 0
        except Exception:
            return False
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_detail_insight_service.py tests/services/test_stock_detail_insight_service.py
git commit -m "Add stock detail financial insight service" \
  -m "Financial detail now has a cache-first service boundary with Tushare refresh and AKShare fallback hooks, keeping the existing fundamentals snapshot lightweight." \
  -m "Tested: pytest tests/services/test_stock_detail_insight_service.py -q" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate"
```

---

## Task 3: Industry Comparison Service

**Files:**
- Modify: `app/services/stock_detail_insight_service.py`
- Test: `tests/services/test_stock_detail_insight_service.py`

- [ ] **Step 1: Add failing tests for industry comparison**

Append:

```python
class FindOneCollection(FakeCollection):
    def __init__(self, doc):
        super().__init__([])
        self.doc = doc

    async def find_one(self, *_args, **_kwargs):
        return self.doc


@pytest.mark.asyncio
async def test_get_industry_comparison_computes_rank_and_percentile():
    db = FakeDb({
        "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
        "stock_financial_data": FakeCollection([
            {"symbol": "688049", "report_period": "20251231", "roe": 12, "pb": 2.0, "pe": 20, "total_mv": 100},
            {"symbol": "600001", "report_period": "20251231", "roe": 8, "pb": 1.5, "pe": 18, "total_mv": 80},
            {"symbol": "600002", "report_period": "20251231", "roe": 16, "pb": 2.5, "pe": 22, "total_mv": 120},
        ]),
    })
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
    db = FakeDb({
        "stock_basic_info": FindOneCollection({"code": "688049", "industry": "电气设备"}),
        "stock_financial_data": FakeCollection([
            {"symbol": "688049", "report_period": "20251231", "roe": 12},
        ]),
    })
    service = StockDetailInsightService(db=db)
    service._industry_codes = lambda industry: ["688049"]

    result = await service.get_industry_comparison("688049")

    assert result["status"] == "sample_insufficient"
    assert result["sample_count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: failures because `get_industry_comparison` is missing.

- [ ] **Step 3: Implement industry comparison methods**

Add methods inside `StockDetailInsightService`:

```python
    async def _stock_basic(self, code6: str) -> Dict[str, Any]:
        doc = await self.db["stock_basic_info"].find_one({"code": code6}, {"_id": 0})
        return doc or {}

    def _industry_codes(self, industry: str) -> List[str]:
        raise RuntimeError("_industry_codes must be called through async wrapper")

    async def _industry_codes_async(self, industry: str) -> List[str]:
        cursor = self.db["stock_basic_info"].find({"industry": industry}, {"_id": 0, "code": 1})
        docs = await cursor.to_list(length=None)
        return [normalize_code6(doc.get("code")) for doc in docs if doc.get("code")]

    async def _financial_docs_for_codes(self, codes: List[str], period: str = "latest") -> List[Dict[str, Any]]:
        cursor = self.db["stock_financial_data"].find({"symbol": {"$in": codes}}, {"_id": 0})
        docs = await cursor.to_list(length=None)
        if period != "latest":
            docs = [doc for doc in docs if doc.get("report_period") == period]
        latest_by_symbol: Dict[str, Dict[str, Any]] = {}
        for doc in sorted(docs, key=lambda item: str(item.get("report_period") or ""), reverse=True):
            latest_by_symbol.setdefault(normalize_code6(doc.get("symbol")), doc)
        return list(latest_by_symbol.values())

    def _metric_value(self, doc: Dict[str, Any], metric: str) -> Optional[float]:
        aliases = {
            "pe": ["pe", "pe_ttm"],
            "pb": ["pb", "pb_mrq"],
            "ps": ["ps", "ps_ttm"],
            "roe": ["roe"],
            "gross_margin": ["gross_margin"],
            "netprofit_margin": ["netprofit_margin"],
            "debt_to_assets": ["debt_to_assets", "debt_ratio"],
            "revenue_growth": ["revenue_yoy", "or_yoy"],
            "net_profit_growth": ["netprofit_yoy", "profit_dedt_yoy"],
            "total_mv": ["total_mv"],
        }
        for key in aliases[metric]:
            value = _safe_float(doc.get(key))
            if value is not None:
                return value
        return None

    def _compare_metric(self, metric: str, stock_doc: Dict[str, Any], docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        values = [
            self._metric_value(doc, metric)
            for doc in docs
        ]
        numeric_values = [value for value in values if value is not None]
        stock_value = self._metric_value(stock_doc, metric)
        if stock_value is None or len(numeric_values) < 2:
            return {
                "stock_value": stock_value,
                "industry_median": None,
                "percentile": None,
                "rank": None,
                "sample_count": len(numeric_values),
            }
        sorted_desc = sorted(numeric_values, reverse=True)
        rank = sorted_desc.index(stock_value) + 1 if stock_value in sorted_desc else None
        lower_or_equal = sum(1 for value in numeric_values if value <= stock_value)
        percentile = round(lower_or_equal / len(numeric_values) * 100, 2)
        return {
            "stock_value": stock_value,
            "industry_median": float(pd.Series(numeric_values).median()),
            "percentile": percentile,
            "rank": rank,
            "sample_count": len(numeric_values),
        }

    async def get_industry_comparison(self, code: str, period: str = "latest", refresh: bool = False) -> Dict[str, Any]:
        code6 = normalize_code6(code)
        if not is_a_share_stock(code6):
            return self._unsupported_response(code6)

        basic = await self._stock_basic(code6)
        industry = basic.get("industry")
        if not industry:
            return {"code": code6, "status": "empty", "message": "未找到行业信息", "metrics": {}}

        try:
            codes = self._industry_codes(industry)
        except RuntimeError:
            codes = await self._industry_codes_async(industry)

        docs = await self._financial_docs_for_codes(codes, period)
        stock_doc = next((doc for doc in docs if normalize_code6(doc.get("symbol")) == code6), {})
        sample_count = len(docs)
        status = "ok" if sample_count >= 3 else "sample_insufficient"

        metric_names = [
            "pe", "pb", "ps", "roe", "gross_margin", "netprofit_margin",
            "debt_to_assets", "revenue_growth", "net_profit_growth", "total_mv",
        ]
        metrics = {
            metric: self._compare_metric(metric, stock_doc, docs)
            for metric in metric_names
        }

        return {
            "code": code6,
            "status": status,
            "industry": industry,
            "period": period,
            "sample_count": sample_count,
            "metrics": metrics,
            "source": "mongodb",
            "last_updated": datetime.now().isoformat(),
            "is_cached": True,
        }
```

- [ ] **Step 4: Run service tests**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_detail_insight_service.py tests/services/test_stock_detail_insight_service.py
git commit -m "Add stock detail industry comparison service" \
  -m "Industry comparison is computed from MongoDB stock basics and financial records so stock detail can show relative valuation and profitability without calling providers on every page view." \
  -m "Tested: pytest tests/services/test_stock_detail_insight_service.py -q" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate"
```

---

## Task 4: Technical Factors Service

**Files:**
- Modify: `app/services/stock_detail_insight_service.py`
- Test: `tests/services/test_stock_detail_insight_service.py`

- [ ] **Step 1: Add failing tests for technical factors**

Append:

```python
@pytest.mark.asyncio
async def test_get_technical_factors_returns_magic_nine_and_factors():
    bars = [
        {"trade_date": f"202605{idx + 1:02d}", "open": close - 0.1, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 1000 + idx}
        for idx, close in enumerate([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21])
    ]
    db = FakeDb({"stock_daily_quotes": FakeCollection(bars)})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "ok"
    assert result["magic_nine"]["current_direction"] == "up"
    assert "ma_5" in result["factors"]
    assert "macd" in result["factors"]


@pytest.mark.asyncio
async def test_get_technical_factors_no_kline_data():
    db = FakeDb({"stock_daily_quotes": FakeCollection([])})
    service = StockDetailInsightService(db=db)

    result = await service.get_technical_factors("688049", limit=120)

    assert result["status"] == "insufficient_data"
    assert result["message"] == "本地K线数据不足，请先同步历史行情"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: failures because `get_technical_factors` is missing.

- [ ] **Step 3: Implement technical factor methods**

Add methods inside `StockDetailInsightService`:

```python
    async def _daily_bars(self, code6: str, limit: int) -> List[Dict[str, Any]]:
        cursor = (
            self.db["stock_daily_quotes"]
            .find({"symbol": code6, "period": {"$in": ["daily", None]}}, {"_id": 0})
            .sort("trade_date", -1)
            .limit(limit)
        )
        docs = await cursor.to_list(length=None)
        if not docs:
            cursor = (
                self.db["stock_daily_quotes"]
                .find({"symbol": code6}, {"_id": 0})
                .sort("trade_date", -1)
                .limit(limit)
            )
            docs = await cursor.to_list(length=None)
        return sorted(docs, key=lambda item: str(item.get("trade_date") or ""))

    def _factor_signal(self, value: Optional[float], high: float, low: float) -> str:
        if value is None:
            return "数据不足"
        if value >= high:
            return "偏强"
        if value <= low:
            return "偏弱"
        return "中性"

    def _technical_factor_payload(self, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        df = pd.DataFrame(bars)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        close = df["close"]
        ma_5 = close.rolling(window=5, min_periods=1).mean()
        ma_20 = close.rolling(window=20, min_periods=1).mean()
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        dif = ema_12 - ema_26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = dif - dea
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=1).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, pd.NA))
        boll_mid = ma_20
        boll_std = close.rolling(window=20, min_periods=1).std().fillna(0)
        boll_upper = boll_mid + 2 * boll_std
        boll_lower = boll_mid - 2 * boll_std
        volume_ma_5 = df["volume"].rolling(window=5, min_periods=1).mean() if "volume" in df else pd.Series([])
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - close.shift(1)).abs()
        low_prev_close = (df["low"] - close.shift(1)).abs()
        true_range = pd.concat([high_low.abs(), high_prev_close, low_prev_close], axis=1).max(axis=1)
        atr_14 = true_range.rolling(window=14, min_periods=14).mean()
        low_9 = df["low"].rolling(window=9, min_periods=9).min()
        high_9 = df["high"].rolling(window=9, min_periods=9).max()
        rsv = (close - low_9) / (high_9 - low_9).replace(0, pd.NA) * 100
        kdj_k = rsv.ewm(com=2, adjust=False).mean()
        kdj_d = kdj_k.ewm(com=2, adjust=False).mean()
        kdj_j = 3 * kdj_k - 2 * kdj_d

        latest_close = _safe_float(close.iloc[-1])
        latest_ma_5 = _safe_float(ma_5.iloc[-1])
        latest_ma_20 = _safe_float(ma_20.iloc[-1])
        latest_rsi = _safe_float(rsi.iloc[-1])
        latest_k = _safe_float(kdj_k.iloc[-1])
        latest_d = _safe_float(kdj_d.iloc[-1])
        latest_atr = _safe_float(atr_14.iloc[-1])

        return {
            "ma_5": {"latest": latest_ma_5, "signal": "多头" if latest_close and latest_ma_5 and latest_close >= latest_ma_5 else "空头"},
            "ma_20": {"latest": latest_ma_20, "signal": "多头" if latest_close and latest_ma_20 and latest_close >= latest_ma_20 else "空头"},
            "ema_12": {"latest": _safe_float(ema_12.iloc[-1]), "signal": "参考"},
            "ema_26": {"latest": _safe_float(ema_26.iloc[-1]), "signal": "参考"},
            "macd": {
                "dif": _safe_float(dif.iloc[-1]),
                "dea": _safe_float(dea.iloc[-1]),
                "hist": _safe_float(macd_hist.iloc[-1]),
                "signal": "金叉偏强" if _safe_float(dif.iloc[-1]) and _safe_float(dea.iloc[-1]) and dif.iloc[-1] >= dea.iloc[-1] else "死叉偏弱",
            },
            "rsi_14": {"latest": latest_rsi, "signal": self._factor_signal(latest_rsi, high=70, low=30)},
            "boll": {
                "upper": _safe_float(boll_upper.iloc[-1]),
                "middle": _safe_float(boll_mid.iloc[-1]),
                "lower": _safe_float(boll_lower.iloc[-1]),
                "signal": "突破上轨" if latest_close and latest_close > boll_upper.iloc[-1] else ("跌破下轨" if latest_close and latest_close < boll_lower.iloc[-1] else "轨道内"),
            },
            "kdj": {
                "k": latest_k,
                "d": latest_d,
                "j": _safe_float(kdj_j.iloc[-1]),
                "signal": "金叉偏强" if latest_k is not None and latest_d is not None and latest_k >= latest_d else "死叉偏弱",
            },
            "atr": {"latest": latest_atr, "signal": "波动参考"},
            "volume_ma_5": {"latest": _safe_float(volume_ma_5.iloc[-1]) if len(volume_ma_5) else None, "signal": "参考"},
            "turnover_summary": {"latest": None, "signal": "本接口暂未获取换手率序列"},
        }

    async def get_technical_factors(self, code: str, limit: int = 120, refresh: bool = False) -> Dict[str, Any]:
        code6 = normalize_code6(code)
        if not is_a_share_stock(code6):
            return self._unsupported_response(code6)

        bars = await self._daily_bars(code6, limit)
        if len(bars) < 13:
            return {
                "code": code6,
                "status": "insufficient_data",
                "message": "本地K线数据不足，请先同步历史行情",
                "required_bars": 13,
                "available_bars": len(bars),
                "magic_nine": calculate_magic_nine(bars),
                "factors": {},
                "series": [],
                "source": "mongodb",
                "last_updated": None,
                "is_cached": True,
            }

        return {
            "code": code6,
            "status": "ok",
            "magic_nine": calculate_magic_nine(bars),
            "factors": self._technical_factor_payload(bars),
            "series": bars[-60:],
            "source": "mongodb",
            "last_updated": bars[-1].get("updated_at"),
            "is_cached": True,
        }
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_detail_insight_service.py tests/services/test_stock_detail_insight_service.py
git commit -m "Add stock detail technical factor service" \
  -m "Technical factors and magic-nine are computed from local daily quotes so stock detail can show signals without provider calls during page load." \
  -m "Tested: pytest tests/services/test_stock_detail_insight_service.py -q" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate"
```

---

## Task 5: Stock Detail API Endpoints

**Files:**
- Modify: `app/routers/stocks.py`
- Test: `tests/test_stock_detail_insight_api.py`

- [ ] **Step 1: Add API tests**

Create `tests/test_stock_detail_insight_api.py`:

```python
import pytest

from app.routers import stocks


@pytest.mark.asyncio
async def test_financial_detail_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_financial_detail(self, code, periods=8, refresh=False):
            return {"code": code, "status": "ok", "periods": ["20251231"]}

    monkeypatch.setattr(stocks, "get_stock_detail_insight_service", lambda: FakeService())

    response = await stocks.get_financial_detail("688049", periods=8, refresh=False, current_user={"id": "u1"})

    assert response["success"] is True
    assert response["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_technical_factors_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_technical_factors(self, code, limit=120, refresh=False):
            return {"code": code, "status": "ok", "magic_nine": {}}

    monkeypatch.setattr(stocks, "get_stock_detail_insight_service", lambda: FakeService())

    response = await stocks.get_technical_factors("688049", limit=120, refresh=False, current_user={"id": "u1"})

    assert response["success"] is True
    assert response["data"]["magic_nine"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_stock_detail_insight_api.py -q
```

Expected: failures because endpoint functions do not exist.

- [ ] **Step 3: Add endpoint factory and routes**

In `app/routers/stocks.py`, add near imports:

```python
def get_stock_detail_insight_service():
    from app.services.stock_detail_insight_service import StockDetailInsightService

    return StockDetailInsightService(db=get_mongo_db())
```

Add routes before `/{code}/quote` if route order requires avoiding dynamic capture conflicts; otherwise add before the file end:

```python
@router.get("/{code}/financial-detail", response_model=dict)
async def get_financial_detail(
    code: str,
    periods: int = Query(8, ge=1, le=20, description="返回最近多少期财报"),
    refresh: bool = Query(False, description="是否强制刷新外部数据源"),
    current_user: dict = Depends(get_current_user),
):
    service = get_stock_detail_insight_service()
    data = await service.get_financial_detail(code, periods=periods, refresh=refresh)
    return ok(data=data)


@router.get("/{code}/industry-comparison", response_model=dict)
async def get_industry_comparison(
    code: str,
    period: str = Query("latest", description="报告期，默认latest"),
    refresh: bool = Query(False, description="是否强制刷新外部数据源"),
    current_user: dict = Depends(get_current_user),
):
    service = get_stock_detail_insight_service()
    data = await service.get_industry_comparison(code, period=period, refresh=refresh)
    return ok(data=data)


@router.get("/{code}/technical-factors", response_model=dict)
async def get_technical_factors(
    code: str,
    limit: int = Query(120, ge=13, le=300, description="用于计算的日K数量"),
    refresh: bool = Query(False, description="保留参数，技术因子当前只读本地K线"),
    current_user: dict = Depends(get_current_user),
):
    service = get_stock_detail_insight_service()
    data = await service.get_technical_factors(code, limit=limit, refresh=refresh)
    return ok(data=data)
```

- [ ] **Step 4: Run API tests and compile router**

Run:

```bash
pytest tests/test_stock_detail_insight_api.py -q
python -m py_compile app/routers/stocks.py app/services/stock_detail_insight_service.py
```

Expected: tests pass and compile succeeds.

- [ ] **Step 5: Commit**

```bash
git add app/routers/stocks.py app/services/stock_detail_insight_service.py tests/test_stock_detail_insight_api.py
git commit -m "Expose stock detail insight APIs" \
  -m "Financial detail, industry comparison, and technical factors are exposed as independent stock detail endpoints so each module can load and fail separately." \
  -m "Tested: pytest tests/test_stock_detail_insight_api.py -q; python -m py_compile app/routers/stocks.py app/services/stock_detail_insight_service.py" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate"
```

---

## Task 6: Frontend API And Detail Page UI

**Files:**
- Modify: `frontend/src/api/stocks.ts`
- Modify: `frontend/src/views/Stocks/Detail.vue`
- Create: `frontend/src/views/Stocks/detailInsightShortcuts.ts`
- Test: `frontend/src/views/Stocks/__tests__/detailInsightShortcuts.test.ts`

- [ ] **Step 1: Add front-end shortcut helper and tests**

Create `frontend/src/views/Stocks/detailInsightShortcuts.ts`:

```typescript
export type StockDetailInsightShortcut = 'financial' | 'technical' | 'magic-nine'
export type StockDetailInsightTab = 'financial' | 'industry' | 'technical'

export interface StockDetailInsightTarget {
  tab: StockDetailInsightTab
  anchor: 'stock-detail-insights' | 'magic-nine-section'
}

export function targetForInsightShortcut(action: StockDetailInsightShortcut): StockDetailInsightTarget {
  if (action === 'financial') return { tab: 'financial', anchor: 'stock-detail-insights' }
  if (action === 'technical') return { tab: 'technical', anchor: 'stock-detail-insights' }
  return { tab: 'technical', anchor: 'magic-nine-section' }
}
```

Create `frontend/src/views/Stocks/__tests__/detailInsightShortcuts.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { targetForInsightShortcut } from '../detailInsightShortcuts'

describe('stock detail insight shortcuts', () => {
  it('maps financial shortcut to financial tab', () => {
    expect(targetForInsightShortcut('financial')).toEqual({ tab: 'financial', anchor: 'stock-detail-insights' })
  })

  it('maps magic-nine shortcut to technical tab and magic-nine anchor', () => {
    expect(targetForInsightShortcut('magic-nine')).toEqual({ tab: 'technical', anchor: 'magic-nine-section' })
  })
})
```

If `npx vitest --version` fails because Vitest is not installed, do not add a new dependency. The helper is still verified by `npm run type-check`.

- [ ] **Step 2: Add TypeScript API interfaces and methods**

In `frontend/src/api/stocks.ts`, add interfaces:

```typescript
export interface FinancialDetailResponse {
  code: string
  status: string
  periods: string[]
  income_statement: Record<string, any>[]
  balance_sheet: Record<string, any>[]
  cashflow_statement: Record<string, any>[]
  financial_indicators: Record<string, any>[]
  main_business: Record<string, any>[]
  summary?: Record<string, any>
  source?: string
  last_updated?: string
  is_cached?: boolean
  message?: string
  warning?: string
}

export interface IndustryComparisonResponse {
  code: string
  status: string
  industry?: string
  period?: string
  sample_count?: number
  metrics: Record<string, {
    stock_value: number | null
    industry_median: number | null
    percentile: number | null
    rank: number | null
    sample_count: number
  }>
  source?: string
  last_updated?: string
  is_cached?: boolean
  message?: string
}

export interface TechnicalFactorsResponse {
  code: string
  status: string
  magic_nine: Record<string, any>
  factors: Record<string, any>
  series: Record<string, any>[]
  source?: string
  last_updated?: string
  is_cached?: boolean
  message?: string
}
```

Add methods inside `stocksApi`:

```typescript
  async getFinancialDetail(symbol: string, periods = 8, refresh = false) {
    return ApiClient.get<FinancialDetailResponse>(`/api/stocks/${symbol}/financial-detail`, { periods, refresh })
  },

  async getIndustryComparison(symbol: string, period = 'latest', refresh = false) {
    return ApiClient.get<IndustryComparisonResponse>(`/api/stocks/${symbol}/industry-comparison`, { period, refresh })
  },

  async getTechnicalFactors(symbol: string, limit = 120, refresh = false) {
    return ApiClient.get<TechnicalFactorsResponse>(`/api/stocks/${symbol}/technical-factors`, { limit, refresh })
  }
```

- [ ] **Step 3: Add Detail.vue state and loaders**

In `frontend/src/views/Stocks/Detail.vue`, add reactive state in `<script setup>`:

```typescript
import { targetForInsightShortcut, type StockDetailInsightShortcut } from './detailInsightShortcuts'

const insightTab = ref<'financial' | 'industry' | 'technical'>('financial')
const financialDetail = ref<any | null>(null)
const industryComparison = ref<any | null>(null)
const technicalFactors = ref<any | null>(null)
const insightLoading = reactive({ financial: false, industry: false, technical: false })
const insightError = reactive({ financial: '', industry: '', technical: '' })
const loadedInsightTabs = reactive({ financial: false, industry: false, technical: false })

async function loadFinancialDetail(refresh = false) {
  insightLoading.financial = true
  insightError.financial = ''
  try {
    const res = await stocksApi.getFinancialDetail(code.value, 8, refresh)
    financialDetail.value = (res as any)?.data || {}
    loadedInsightTabs.financial = true
  } catch (error: any) {
    insightError.financial = error?.message || '详细财报加载失败'
  } finally {
    insightLoading.financial = false
  }
}

async function loadIndustryComparison(refresh = false) {
  insightLoading.industry = true
  insightError.industry = ''
  try {
    const res = await stocksApi.getIndustryComparison(code.value)
    industryComparison.value = (res as any)?.data || {}
    loadedInsightTabs.industry = true
  } catch (error: any) {
    insightError.industry = error?.message || '行业对比加载失败'
  } finally {
    insightLoading.industry = false
  }
}

async function loadTechnicalFactors(refresh = false) {
  insightLoading.technical = true
  insightError.technical = ''
  try {
    const res = await stocksApi.getTechnicalFactors(code.value, 120, refresh)
    technicalFactors.value = (res as any)?.data || {}
    loadedInsightTabs.technical = true
  } catch (error: any) {
    insightError.technical = error?.message || '技术因子加载失败'
  } finally {
    insightLoading.technical = false
  }
}

async function ensureInsightTabLoaded(tab: typeof insightTab.value) {
  if (tab === 'financial' && !loadedInsightTabs.financial) await loadFinancialDetail()
  if (tab === 'industry' && !loadedInsightTabs.industry) await loadIndustryComparison()
  if (tab === 'technical' && !loadedInsightTabs.technical) await loadTechnicalFactors()
}

watch(insightTab, (tab) => { ensureInsightTabLoaded(tab) })

function jumpToInsight(target: StockDetailInsightShortcut) {
  const destination = targetForInsightShortcut(target)
  insightTab.value = destination.tab
  ensureInsightTabLoaded(insightTab.value)
  requestAnimationFrame(() => {
    document.getElementById(destination.anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}
```

Also call `loadFinancialDetail()` in `loadPageData()` after `fetchSyncStatus()` or let it lazy-load when the default tab renders. Use lazy-load if page load becomes slow.

- [ ] **Step 4: Add the “深度数据” card template**

Insert below the K-line card and above the analysis/news cards:

```vue
<el-card shadow="hover" class="insights-card" id="stock-detail-insights">
  <template #header>
    <div class="card-hd">
      <div>深度数据</div>
      <el-button text size="small" :icon="Refresh" @click="ensureInsightTabLoaded(insightTab)">刷新</el-button>
    </div>
  </template>

  <el-tabs v-model="insightTab">
    <el-tab-pane label="详细财报" name="financial">
      <el-alert v-if="insightError.financial" type="warning" :title="insightError.financial" show-icon />
      <el-skeleton v-else-if="insightLoading.financial" :rows="6" animated />
      <div v-else-if="financialDetail">
        <div class="insight-meta">
          来源：{{ financialDetail.source || '-' }} · 更新时间：{{ financialDetail.last_updated || '-' }}
          <el-tag v-if="financialDetail.is_cached" size="small" type="info">缓存</el-tag>
        </div>
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="ROE">{{ fmtPercent(financialDetail.summary?.roe) }}</el-descriptions-item>
          <el-descriptions-item label="ROA">{{ fmtPercent(financialDetail.summary?.roa) }}</el-descriptions-item>
          <el-descriptions-item label="毛利率">{{ fmtPercent(financialDetail.summary?.gross_margin) }}</el-descriptions-item>
          <el-descriptions-item label="净利率">{{ fmtPercent(financialDetail.summary?.netprofit_margin) }}</el-descriptions-item>
          <el-descriptions-item label="资产负债率">{{ fmtPercent(financialDetail.summary?.debt_to_assets) }}</el-descriptions-item>
          <el-descriptions-item label="流动比率">{{ financialDetail.summary?.current_ratio ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="速动比率">{{ financialDetail.summary?.quick_ratio ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="报告期">{{ financialDetail.summary?.report_period || '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-tabs class="statement-tabs">
          <el-tab-pane label="利润表">
            <el-table :data="financialDetail.income_statement || []" size="small" height="260">
              <el-table-column prop="end_date" label="报告期" width="110" />
              <el-table-column prop="revenue" label="营业收入" />
              <el-table-column prop="n_income_attr_p" label="归母净利润" />
              <el-table-column prop="oper_profit" label="营业利润" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="资产负债表">
            <el-table :data="financialDetail.balance_sheet || []" size="small" height="260">
              <el-table-column prop="end_date" label="报告期" width="110" />
              <el-table-column prop="total_assets" label="总资产" />
              <el-table-column prop="total_liab" label="总负债" />
              <el-table-column prop="money_cap" label="货币资金" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="现金流量表">
            <el-table :data="financialDetail.cashflow_statement || []" size="small" height="260">
              <el-table-column prop="end_date" label="报告期" width="110" />
              <el-table-column prop="n_cashflow_act" label="经营现金流" />
              <el-table-column prop="n_cashflow_inv_act" label="投资现金流" />
              <el-table-column prop="n_cashflow_fin_act" label="筹资现金流" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="主营业务">
            <el-table :data="financialDetail.main_business || []" size="small" height="260">
              <el-table-column prop="end_date" label="报告期" width="110" />
              <el-table-column prop="bz_item" label="项目" />
              <el-table-column prop="bz_sales" label="收入" />
              <el-table-column prop="bz_profit" label="毛利" />
              <el-table-column prop="bz_cost" label="成本" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-tab-pane>

    <el-tab-pane label="行业对比" name="industry">
      <el-alert v-if="insightError.industry" type="warning" :title="insightError.industry" show-icon />
      <el-skeleton v-else-if="insightLoading.industry" :rows="6" animated />
      <el-table v-else :data="Object.entries(industryComparison?.metrics || {}).map(([key, value]) => ({ key, ...(value as any) }))" size="small">
        <el-table-column prop="key" label="指标" />
        <el-table-column prop="stock_value" label="当前股票" />
        <el-table-column prop="industry_median" label="行业中位数" />
        <el-table-column prop="rank" label="行业排名" />
        <el-table-column prop="percentile" label="行业分位" />
        <el-table-column prop="sample_count" label="样本数" />
      </el-table>
    </el-tab-pane>

    <el-tab-pane label="技术面因子" name="technical">
      <el-alert v-if="insightError.technical" type="warning" :title="insightError.technical" show-icon />
      <el-skeleton v-else-if="insightLoading.technical" :rows="6" animated />
      <div v-else-if="technicalFactors">
        <div id="magic-nine-section" class="magic-nine-section">
          <h3>神奇九转</h3>
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="方向">{{ technicalFactors.magic_nine?.current_direction || '-' }}</el-descriptions-item>
            <el-descriptions-item label="计数">{{ technicalFactors.magic_nine?.current_count ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ technicalFactors.magic_nine?.status || '-' }}</el-descriptions-item>
            <el-descriptions-item label="最近信号">{{ technicalFactors.magic_nine?.latest_signal?.date || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <el-table :data="Object.entries(technicalFactors.factors || {}).map(([key, value]) => ({ key, ...(value as any) }))" size="small" class="factor-table">
          <el-table-column prop="key" label="因子" />
          <el-table-column prop="latest" label="最新值" />
          <el-table-column prop="signal" label="信号" />
        </el-table>
      </div>
    </el-tab-pane>
  </el-tabs>
</el-card>
```

- [ ] **Step 5: Add quick action buttons**

In the existing quick actions card, below the current three buttons, add:

```vue
<el-button type="info" :icon="Document" plain @click="jumpToInsight('financial')">详细财报</el-button>
<el-button type="warning" :icon="TrendCharts" plain @click="jumpToInsight('technical')">技术因子</el-button>
<el-button type="danger" :icon="TrendCharts" plain @click="jumpToInsight('magic-nine')">神奇九转</el-button>
```

- [ ] **Step 6: Add focused styles**

At the bottom of `Detail.vue`, add styles matching the existing card density:

```css
.insights-card {
  margin-top: 16px;
}

.insight-meta {
  color: #606266;
  font-size: 13px;
  margin-bottom: 12px;
}

.statement-tabs {
  margin-top: 12px;
}

.magic-nine-section {
  margin-bottom: 16px;
}

.factor-table {
  margin-top: 12px;
}
```

- [ ] **Step 7: Run front-end checks**

Run:

```bash
cd frontend
npx vitest --version
npx vitest run src/views/Stocks/__tests__/detailInsightShortcuts.test.ts
npm run type-check
npm run build
```

Expected: If Vitest is installed, the shortcut test passes. If `npx vitest --version` reports that Vitest is unavailable, skip the Vitest command and record that gap. `npm run type-check` and `npm run build` must pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/stocks.ts frontend/src/views/Stocks/Detail.vue frontend/src/views/Stocks/detailInsightShortcuts.ts frontend/src/views/Stocks/__tests__/detailInsightShortcuts.test.ts
git commit -m "Add stock detail deep insight UI" \
  -m "The stock detail page now has lazy-loaded deep data tabs and sidebar shortcuts for detailed financials, technical factors, and magic-nine without adding routes." \
  -m "Tested: cd frontend && npm run type-check && npm run build" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate"
```

---

## Task 7: Integration Verification And Documentation

**Files:**
- Create or modify: `docs/features/stock-detail/README.md`
- Create: `docs/deployment/docker/stock-detail-insights-hot-deploy.md`

- [ ] **Step 1: Add feature documentation**

Create `docs/features/stock-detail/README.md` if it does not exist. Add:

```markdown
# 股票详情页深度数据

股票详情页在 K 线下方提供“深度数据”区域，包含三个页签：

- 详细财报：展示利润表、资产负债表、现金流量表、财务指标和主营业务构成。
- 行业对比：展示 PE、PB、PS、ROE、毛利率、净利率、资产负债率、营收增速、净利润增速和总市值的行业中位数、分位和排名。
- 技术面因子：展示神奇九转、MA、EMA、MACD、RSI、BOLL、KDJ、ATR、成交量均线和换手率摘要。

数据策略：

- 详细财报优先读取 MongoDB `stock_financial_data`。
- 缓存缺失或手动刷新时优先从 Tushare 获取。
- Tushare 财务数据失败时尝试 AKShare 兜底。
- 技术面因子只从本地 `stock_daily_quotes` 计算，不在页面加载时访问外部行情源。
- 行业对比基于 `stock_basic_info.industry` 和本地财务数据计算。

右侧“快捷操作”提供三个入口：

- 详细财报
- 技术因子
- 神奇九转

这些入口只做当前页面内滚动和页签切换，不新增路由。
```

- [ ] **Step 2: Add hot deploy documentation**

Create `docs/deployment/docker/stock-detail-insights-hot-deploy.md`:

```markdown
# 股票详情深度数据热部署

本功能涉及 backend 和 frontend 镜像。热部署时必须保留 MongoDB image 和 volume，不要删除 `tradingagents-mongodb` 容器数据卷。

推荐命令：

```bash
docker compose build backend frontend
docker compose up -d backend frontend
docker compose ps
```

验证：

```bash
curl -f http://localhost:8000/api/health
curl -f http://localhost:3000/health
```

页面验证：

- 打开 `http://localhost:3000/stocks/688049`
- 确认右侧“快捷操作”存在 `详细财报`、`技术因子`、`神奇九转`
- 点击三个按钮，确认页面滚动和页签切换正常
```

- [ ] **Step 3: Run documentation check**

Run:

```bash
test -f docs/features/stock-detail/README.md
test -f docs/deployment/docker/stock-detail-insights-hot-deploy.md
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit**

```bash
git add docs/features/stock-detail/README.md docs/deployment/docker/stock-detail-insights-hot-deploy.md
git commit -m "Document stock detail deep insights" \
  -m "Operators and users need the data-source behavior, sidebar shortcuts, and Docker hot-deploy commands recorded with the feature." \
  -m "Tested: test -f docs/features/stock-detail/README.md; test -f docs/deployment/docker/stock-detail-insights-hot-deploy.md" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow"
```

---

## Task 8: End-To-End Verification And Docker Hot Deploy

**Files:**
- No source edits expected unless verification reveals a defect.

- [ ] **Step 1: Run backend tests**

Run:

```bash
pytest tests/services/test_stock_detail_insight_service.py tests/test_stock_detail_insight_api.py -q
python -m py_compile app/services/stock_detail_insight_service.py app/routers/stocks.py
```

Expected: tests pass and compile succeeds.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd frontend
npm run type-check
npm run build
```

Expected: both commands pass.

- [ ] **Step 3: Hot deploy Docker without touching MongoDB**

Run from repository root:

```bash
docker compose build backend frontend
docker compose up -d backend frontend
docker compose ps
```

Expected:

- `tradingagents-backend` is running or healthy.
- `tradingagents-frontend` is running or healthy.
- `tradingagents-mongodb` remains present and its image remains `mongo:4.4`.

- [ ] **Step 4: Verify APIs in Docker**

Run:

```bash
curl -f http://localhost:8000/api/health
curl -f "http://localhost:8000/api/stocks/688049/technical-factors?limit=120" -H "Authorization: Bearer ${TOKEN:-}"
```

Expected:

- Health endpoint returns success.
- If auth token is required and `${TOKEN}` is empty, stock endpoint may return 401. That is acceptable; verify through the logged-in browser in Step 5.

- [ ] **Step 5: Verify in browser**

Use the in-app browser at:

```text
http://localhost:3000/stocks/688049
```

Expected:

- Page loads without console-breaking UI errors.
- K-line, basic snapshot, quick actions, and news still render.
- Right quick action card shows `详细财报`、`技术因子`、`神奇九转`.
- Clicking `详细财报` scrolls to “深度数据” and activates that tab.
- Clicking `技术因子` activates the technical tab.
- Clicking `神奇九转` activates the technical tab and scrolls to the magic-nine section.

- [ ] **Step 6: Final commit if verification fixes were needed**

If verification required fixes, commit them:

```bash
git add <fixed-files>
git commit -m "Stabilize stock detail deep insight verification" \
  -m "Verification found issues in the stock detail insight flow, so this captures the final fixes before handoff." \
  -m "Tested: pytest tests/services/test_stock_detail_insight_service.py tests/test_stock_detail_insight_api.py -q; cd frontend && npm run type-check && npm run build; docker compose build backend frontend; docker compose up -d backend frontend" \
  -m "Confidence: medium" \
  -m "Scope-risk: narrow"
```

---

## Self-Review Notes

- Spec coverage:
  - Detailed financial reports: Tasks 2, 5, 6, 7, 8.
  - Industry comparison: Tasks 3, 5, 6, 7, 8.
  - Magic-nine: Tasks 1, 4, 5, 6, 7, 8.
  - Technical factors: Tasks 4, 5, 6, 7, 8.
  - Sidebar quick buttons: Task 6.
  - Docs and Docker hot deploy: Tasks 7 and 8.
- No new route is added; all UI remains inside `frontend/src/views/Stocks/Detail.vue`.
- MongoDB image and data are preserved by only rebuilding and recreating backend/frontend services.
- Tushare calls are routed through existing provider and sync services, which already use system data-source configuration and rate limiting.
