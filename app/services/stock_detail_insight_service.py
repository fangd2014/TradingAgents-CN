from __future__ import annotations

import inspect
import math
import re
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional


def normalize_code6(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def is_a_share_stock(code: str) -> bool:
    code6 = normalize_code6(code)
    if not re.fullmatch(r"\d{6}", code6):
        return False
    allowed_prefixes = (
        "000",
        "001",
        "002",
        "003",
        "300",
        "301",
        "600",
        "601",
        "603",
        "605",
        "688",
        "689",
        "920",
    )
    if code6.startswith(allowed_prefixes):
        return True
    return False


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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _bar_date(bar: Dict[str, Any]) -> str:
    return str(bar.get("trade_date") or bar.get("date") or bar.get("time") or "")


def _date_sort_key(date_text: str) -> tuple:
    text = str(date_text or "").strip()
    compact_match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if compact_match:
        year, month, day = (int(part) for part in compact_match.groups())
        return (0, year, month, day, 0, 0, 0, text)

    separated_match = re.match(
        (
            r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
            r"(?:[T\s](\d{1,2})(?::(\d{1,2})(?::(\d{1,2}))?)?)?"
        ),
        text,
    )
    if separated_match:
        year = int(separated_match.group(1))
        month = int(separated_match.group(2))
        day = int(separated_match.group(3))
        hour = int(separated_match.group(4) or 0)
        minute = int(separated_match.group(5) or 0)
        second = int(separated_match.group(6) or 0)
        return (0, year, month, day, hour, minute, second, text)

    return (1, text)


def calculate_magic_nine(
    bars: List[Dict[str, Any]], lookback: int = 4, target_count: int = 9
) -> Dict[str, Any]:
    required_bars = lookback + target_count
    cleaned = [
        {"date": _bar_date(bar), "close": _safe_float(bar.get("close"))}
        for bar in bars
        if _safe_float(bar.get("close")) is not None
    ]
    cleaned.sort(key=lambda item: _date_sort_key(item["date"]))

    if len(cleaned) < required_bars:
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
            sequence.append(
                {
                    "date": item["date"],
                    "close": item["close"],
                    "direction": "none",
                    "count": 0,
                    "signal": None,
                }
            )
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

        sequence.append(
            {
                "date": item["date"],
                "close": item["close"],
                "direction": direction,
                "count": count,
                "signal": signal,
            }
        )

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


class StockDetailInsightService:
    def __init__(self, db):
        self.db = db

    def _unsupported_response(self, code: str) -> Dict[str, Any]:
        return {
            "status": "unsupported",
            "code": normalize_code6(code),
            "message": "ETF and non A-share symbols are not supported for financial detail.",
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

    def _industry_codes(self, industry: str) -> List[str]:
        raise RuntimeError(f"No synchronous industry code override for industry={industry}")

    async def _stock_basic(self, code6: str) -> Dict[str, Any]:
        collection = self.db["stock_basic_info"]
        doc = await collection.find_one({"code": code6}, {"_id": 0})
        return doc if isinstance(doc, dict) else {}

    async def _industry_codes_async(self, industry: str) -> List[str]:
        hook = getattr(self, "_industry_codes", None)
        if callable(hook):
            try:
                override_codes = hook(industry)
                if inspect.isawaitable(override_codes):
                    override_codes = await override_codes
                if override_codes:
                    deduped: List[str] = []
                    seen = set()
                    for code in override_codes:
                        code6 = normalize_code6(code)
                        if code6 and code6 not in seen:
                            seen.add(code6)
                            deduped.append(code6)
                    return deduped
            except RuntimeError:
                pass

        collection = self.db["stock_basic_info"]
        cursor = collection.find({"industry": industry}, {"_id": 0, "code": 1, "symbol": 1, "ts_code": 1})
        docs = await cursor.to_list(length=None)
        docs = docs if isinstance(docs, list) else []

        codes: List[str] = []
        seen = set()
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            code = normalize_code6(doc.get("code") or doc.get("symbol") or doc.get("ts_code") or "")
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return codes

    async def _financial_docs_for_codes(
        self,
        codes: List[str],
        period: str = "latest",
    ) -> List[Dict[str, Any]]:
        normalized_codes = {normalize_code6(code) for code in codes if code}
        if not normalized_codes:
            return []

        collection = self.db["stock_financial_data"]
        cursor = collection.find({"symbol": {"$in": list(normalized_codes)}}, {"_id": 0}).sort("report_period", -1)
        docs = await cursor.to_list(length=None)
        docs = docs if isinstance(docs, list) else []

        by_symbol: Dict[str, Dict[str, Any]] = {}
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            symbol = normalize_code6(doc.get("symbol") or doc.get("code") or "")
            if symbol not in normalized_codes:
                continue
            report_period = str(doc.get("report_period") or "")
            if period != "latest" and report_period != str(period):
                continue
            doc_copy = dict(doc)
            doc_copy["_code6"] = symbol
            selected = by_symbol.get(symbol)
            if selected is None:
                by_symbol[symbol] = doc_copy
                continue

            selected_period = str(selected.get("report_period") or "")
            current_priority = self._source_priority(doc_copy.get("data_source"))
            selected_priority = self._source_priority(selected.get("data_source"))

            if period == "latest":
                if report_period > selected_period:
                    by_symbol[symbol] = doc_copy
                    continue
                if report_period == selected_period and current_priority < selected_priority:
                    by_symbol[symbol] = doc_copy
            else:
                if current_priority < selected_priority:
                    by_symbol[symbol] = doc_copy

        deduped = list(by_symbol.values())
        deduped.sort(key=lambda item: (str(item.get("report_period") or ""), item.get("_code6", "")), reverse=True)
        return deduped

    @staticmethod
    def _source_priority(source: Any) -> int:
        source_text = str(source or "").lower()
        if source_text == "tushare":
            return 0
        if source_text == "akshare":
            return 1
        if source_text == "baostock":
            return 2
        return 9

    def _metric_value(self, doc: Dict[str, Any], metric: str) -> Optional[float]:
        aliases = {
            "pe": ["pe", "pe_ttm"],
            "pb": ["pb", "pb_mrq"],
            "ps": ["ps", "ps_ttm"],
            "roe": ["roe"],
            "gross_margin": ["gross_margin", "grossprofit_margin"],
            "netprofit_margin": ["netprofit_margin"],
            "debt_to_assets": ["debt_to_assets", "debt_ratio"],
            "revenue_growth": ["revenue_yoy", "or_yoy"],
            "net_profit_growth": ["netprofit_yoy", "profit_dedt_yoy"],
            "total_mv": ["total_mv"],
        }
        for field in aliases.get(metric, [metric]):
            value = _safe_float(doc.get(field))
            if value is not None:
                return value
        return None

    def _compare_metric(
        self,
        metric: str,
        stock_doc: Dict[str, Any],
        docs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        values: List[float] = []
        for doc in docs:
            value = self._metric_value(doc, metric)
            if value is not None:
                values.append(value)

        stock_value = self._metric_value(stock_doc, metric)
        if not values:
            return {
                "stock_value": stock_value,
                "industry_median": None,
                "percentile": None,
                "rank": None,
                "sample_count": 0,
            }

        if len(values) < 3:
            return {
                "stock_value": stock_value,
                "industry_median": None,
                "percentile": None,
                "rank": None,
                "sample_count": len(values),
            }

        industry_median = float(median(values))
        if stock_value is None:
            rank = None
            percentile = None
        else:
            rank = 1 + sum(1 for value in values if value > stock_value)
            percentile = round(100.0 * sum(1 for value in values if value <= stock_value) / len(values), 2)

        return {
            "stock_value": stock_value,
            "industry_median": industry_median,
            "percentile": percentile,
            "rank": rank,
            "sample_count": len(values),
        }

    async def get_industry_comparison(
        self,
        code: str,
        period: str = "latest",
        refresh: bool = False,
    ) -> Dict[str, Any]:
        del refresh  # Reserved for future cache-refresh support.
        code6 = normalize_code6(code)
        if not is_a_share_stock(code6):
            return self._unsupported_response(code6)

        basic_doc = await self._stock_basic(code6)
        industry = (basic_doc or {}).get("industry")
        last_updated = datetime.now(timezone.utc).isoformat()
        if not industry:
            return {
                "status": "empty",
                "code": code6,
                "industry": None,
                "period": period,
                "sample_count": 0,
                "message": "未找到行业信息",
                "metrics": {},
                "source": "mongodb",
                "last_updated": last_updated,
                "is_cached": True,
            }

        industry_codes = await self._industry_codes_async(industry)
        if code6 not in industry_codes:
            industry_codes.append(code6)
        docs = await self._financial_docs_for_codes(industry_codes, period=period)
        sample_count = len(docs)

        stock_doc: Optional[Dict[str, Any]] = None
        for doc in docs:
            if normalize_code6(doc.get("symbol") or doc.get("code") or doc.get("_code6") or "") == code6:
                stock_doc = doc
                break

        if stock_doc is None:
            return {
                "status": "empty",
                "code": code6,
                "industry": industry,
                "period": period,
                "sample_count": sample_count,
                "message": "未找到目标股票财务数据",
                "metrics": {},
                "source": "mongodb",
                "last_updated": last_updated,
                "is_cached": True,
            }

        metric_names = [
            "pe",
            "pb",
            "ps",
            "roe",
            "gross_margin",
            "netprofit_margin",
            "debt_to_assets",
            "revenue_growth",
            "net_profit_growth",
            "total_mv",
        ]
        metrics = {metric: self._compare_metric(metric, stock_doc, docs) for metric in metric_names}

        return {
            "status": "ok" if sample_count >= 3 else "sample_insufficient",
            "code": code6,
            "industry": industry,
            "period": period,
            "sample_count": sample_count,
            "metrics": metrics,
            "source": "mongodb",
            "last_updated": last_updated,
            "is_cached": True,
        }

    async def _financial_cache(self, code6: str, periods: int) -> List[Dict[str, Any]]:
        collection = self.db["stock_financial_data"]
        cursor = collection.find({"symbol": code6}, {"_id": 0}).sort("report_period", -1).limit(periods)
        docs = await cursor.to_list(length=None)
        docs = docs if isinstance(docs, list) else []
        docs.sort(key=lambda item: str(item.get("report_period") or ""), reverse=True)
        return docs

    def _financial_payload(
        self,
        code6: str,
        docs: List[Dict[str, Any]],
        source: Optional[str],
        is_cached: bool,
    ) -> Dict[str, Any]:
        if not docs:
            return {
                "status": "empty",
                "code": code6,
                "message": "No financial detail data found.",
                "income_statement": [],
                "balance_sheet": [],
                "cashflow_statement": [],
                "financial_indicators": [],
                "main_business": [],
                "summary": {},
                "source": source,
                "last_updated": None,
                "is_cached": is_cached,
            }

        latest = docs[0]
        raw_data = latest.get("raw_data") or {}
        income_statement = raw_data.get("income_statement") or []
        balance_sheet = raw_data.get("balance_sheet") or []
        cashflow_statement = raw_data.get("cashflow_statement") or raw_data.get("cash_flow") or []
        financial_indicators = raw_data.get("financial_indicators") or []
        main_business = raw_data.get("main_business") or []
        latest_income = income_statement[0] if income_statement else {}
        latest_balance = balance_sheet[0] if balance_sheet else {}
        latest_indicator = financial_indicators[0] if financial_indicators else {}

        summary = {
            "report_period": latest.get("report_period"),
            "ann_date": _first_present(
                latest.get("ann_date"),
                latest_income.get("ann_date"),
                latest_indicator.get("ann_date"),
            ),
            "revenue": _first_present(
                latest_income.get("revenue"),
                latest.get("revenue"),
            ),
            "revenue_ttm": _first_present(
                latest.get("revenue_ttm"),
                latest_indicator.get("revenue_ttm"),
            ),
            "net_profit": _first_present(
                latest_income.get("n_income"),
                latest_income.get("net_profit"),
                latest.get("net_income"),
                latest.get("net_profit"),
            ),
            "net_profit_ttm": _first_present(
                latest.get("net_profit_ttm"),
                latest_indicator.get("net_profit_ttm"),
            ),
            "roe": _first_present(
                latest_indicator.get("roe"),
                latest.get("roe"),
            ),
            "roa": latest_indicator.get("roa"),
            "gross_margin": latest_indicator.get("grossprofit_margin"),
            "netprofit_margin": latest_indicator.get("netprofit_margin"),
            "debt_to_assets": _first_present(
                latest_indicator.get("debt_to_assets"),
                latest_balance.get("debt_to_assets"),
                latest.get("debt_to_assets"),
            ),
            "current_ratio": latest_indicator.get("current_ratio"),
            "quick_ratio": latest_indicator.get("quick_ratio"),
            "net_income": _first_present(
                latest.get("net_income"),
                latest.get("n_income"),
                latest_income.get("n_income"),
                latest_income.get("net_profit"),
            ),
            "total_assets": _first_present(
                latest.get("total_assets"),
                latest_balance.get("total_assets"),
            ),
            "total_liab": _first_present(
                latest.get("total_liab"),
                latest_balance.get("total_liab"),
            ),
            "total_equity": _first_present(
                latest.get("total_equity"),
                latest_balance.get("total_equity"),
            ),
            "cash_and_equivalents": _first_present(
                latest.get("cash_and_equivalents"),
                latest.get("money_cap"),
            ),
        }

        detail_available = bool(
            income_statement
            or balance_sheet
            or cashflow_statement
            or financial_indicators
            or main_business
        )
        message = "ok" if detail_available else "summary_only"

        return {
            "status": "ok",
            "code": code6,
            "message": message,
            "income_statement": income_statement,
            "balance_sheet": balance_sheet,
            "cashflow_statement": cashflow_statement,
            "financial_indicators": financial_indicators,
            "main_business": main_business,
            "summary": summary,
            "source": source,
            "last_updated": latest.get("updated_at"),
            "is_cached": is_cached,
            "detail_available": detail_available,
        }

    async def get_financial_detail(
        self,
        code: str,
        periods: int = 8,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        code6 = normalize_code6(code)
        if not is_a_share_stock(code6):
            return self._unsupported_response(code6)

        cached_docs = await self._financial_cache(code6, periods)
        if cached_docs and not refresh:
            return self._financial_payload(code6, cached_docs, source="mongodb", is_cached=True)

        refresh_ok = await self._refresh_tushare_financial(code6, periods)
        refresh_source = "tushare" if refresh_ok else None
        if not refresh_ok:
            ak_ok = await self._refresh_akshare_financial(code6)
            refresh_ok = ak_ok
            refresh_source = "akshare" if ak_ok else None

        reloaded_docs = await self._financial_cache(code6, periods)
        if reloaded_docs:
            if refresh_ok:
                return self._financial_payload(code6, reloaded_docs, source=refresh_source, is_cached=False)
            payload = self._financial_payload(code6, reloaded_docs, source="mongodb", is_cached=True)
            payload["warning"] = "Financial refresh failed; returning cached data."
            return payload

        return {
            "status": "empty",
            "code": code6,
            "message": "No financial detail data available after refresh attempt.",
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
            return bool(result and result.get("success_count", 0) > 0)
        except Exception:
            return False

    async def _refresh_akshare_financial(self, code6: str) -> bool:
        try:
            from app.services.financial_data_service import get_financial_data_service
            from tradingagents.dataflows.providers.china.akshare import AKShareProvider

            provider = AKShareProvider()
            if not await provider.connect():
                return False
            financial_data = await provider.get_financial_data(code6)
            if not financial_data:
                return False
            service = await get_financial_data_service()
            saved = await service.save_financial_data(
                symbol=code6,
                financial_data=financial_data,
                data_source="akshare",
                market="CN",
            )
            return saved > 0
        except Exception:
            return False
