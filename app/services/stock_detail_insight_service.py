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
        code_list = list(normalized_codes)
        cursor = collection.find(
            {"$or": [{"symbol": {"$in": code_list}}, {"code": {"$in": code_list}}]},
            {"_id": 0},
        ).sort("report_period", -1)
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

        if len(values) < 2:
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

    async def _daily_bars(self, code6: str, limit: int) -> List[Dict[str, Any]]:
        collection = self.db["stock_daily_quotes"]
        safe_limit = max(int(limit or 0), 1)

        cursor = (
            collection.find({"symbol": code6, "period": {"$in": ["daily", None]}}, {"_id": 0})
            .sort("trade_date", -1)
            .limit(safe_limit)
        )
        docs = await cursor.to_list(length=None)
        docs = docs if isinstance(docs, list) else []

        if not docs:
            cursor = collection.find({"symbol": code6}, {"_id": 0}).sort("trade_date", -1).limit(safe_limit)
            docs = await cursor.to_list(length=None)
            docs = docs if isinstance(docs, list) else []

        docs.sort(key=lambda item: _date_sort_key(_bar_date(item)))
        return docs

    def _factor_signal(self, value: Optional[float], high: float, low: float) -> str:
        if value is None:
            return "数据不足"
        if value >= high:
            return "偏强"
        if value <= low:
            return "偏弱"
        return "中性"

    def _technical_factor_payload(self, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
        closes: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        volumes: List[Optional[float]] = []
        turnovers: List[Optional[float]] = []

        for bar in bars:
            close = _safe_float(bar.get("close"))
            if close is None:
                continue
            high = _safe_float(bar.get("high"))
            low = _safe_float(bar.get("low"))
            highs.append(high if high is not None else close)
            lows.append(low if low is not None else close)
            closes.append(close)
            volumes.append(_safe_float(_first_present(bar.get("volume"), bar.get("vol"))))
            turnovers.append(
                _safe_float(
                    _first_present(
                        bar.get("turnover_rate"),
                        bar.get("turnover"),
                        bar.get("turnoverratio"),
                        bar.get("换手率"),
                    )
                )
            )

        if not closes:
            return {}

        def _sma(values: List[float], window: int) -> Optional[float]:
            if not values:
                return None
            segment = values[-window:]
            if not segment:
                return None
            return sum(segment) / len(segment)

        def _ema_series(values: List[float], span: int) -> List[float]:
            if not values:
                return []
            alpha = 2.0 / (span + 1.0)
            ema_values: List[float] = [values[0]]
            for value in values[1:]:
                ema_values.append(alpha * value + (1.0 - alpha) * ema_values[-1])
            return ema_values

        latest_close = closes[-1]
        ma_5 = _sma(closes, 5)
        ma_20 = _sma(closes, 20)

        ema_12_series = _ema_series(closes, 12)
        ema_26_series = _ema_series(closes, 26)
        dif_series = [a - b for a, b in zip(ema_12_series, ema_26_series)]
        dea_series = _ema_series(dif_series, 9)
        macd_hist_series = [d - e for d, e in zip(dif_series, dea_series)]

        dif_last = _safe_float(dif_series[-1]) if dif_series else None
        dea_last = _safe_float(dea_series[-1]) if dea_series else None
        macd_hist_last = _safe_float(macd_hist_series[-1]) if macd_hist_series else None

        if len(closes) >= 2:
            deltas = [closes[idx] - closes[idx - 1] for idx in range(1, len(closes))]
            delta_window = deltas[-14:] if len(deltas) >= 14 else deltas
            gain_avg = sum(max(delta, 0.0) for delta in delta_window) / len(delta_window) if delta_window else 0.0
            loss_avg = sum(max(-delta, 0.0) for delta in delta_window) / len(delta_window) if delta_window else 0.0
            if loss_avg == 0:
                rsi_14 = 50.0 if gain_avg == 0 else 100.0
            else:
                rs = gain_avg / loss_avg
                rsi_14 = 100.0 - 100.0 / (1.0 + rs)
        else:
            rsi_14 = None
        latest_rsi = _safe_float(rsi_14)

        if ma_20 is None:
            boll_mid = boll_upper = boll_lower = None
        else:
            boll_window = closes[-20:]
            variance = sum((value - ma_20) ** 2 for value in boll_window) / len(boll_window)
            std = math.sqrt(variance)
            boll_mid = ma_20
            boll_upper = ma_20 + 2.0 * std
            boll_lower = ma_20 - 2.0 * std

        k_prev = 50.0
        d_prev = 50.0
        k_val: Optional[float] = None
        d_val: Optional[float] = None
        j_val: Optional[float] = None
        for idx in range(len(closes)):
            start = max(0, idx - 8)
            low_n = min(lows[start : idx + 1])
            high_n = max(highs[start : idx + 1])
            denominator = high_n - low_n
            if denominator == 0:
                rsv = 50.0
            else:
                rsv = (closes[idx] - low_n) / denominator * 100.0
            k_prev = (2.0 * k_prev + rsv) / 3.0
            d_prev = (2.0 * d_prev + k_prev) / 3.0
            j_curr = 3.0 * k_prev - 2.0 * d_prev
            k_val = k_prev
            d_val = d_prev
            j_val = j_curr

        true_ranges: List[float] = []
        for idx in range(len(closes)):
            if idx == 0:
                tr = highs[idx] - lows[idx]
            else:
                tr = max(
                    highs[idx] - lows[idx],
                    abs(highs[idx] - closes[idx - 1]),
                    abs(lows[idx] - closes[idx - 1]),
                )
            true_ranges.append(abs(tr))
        atr_window = true_ranges[-14:] if len(true_ranges) >= 14 else true_ranges
        atr_14 = (sum(atr_window) / len(atr_window)) if atr_window else None

        recent_volumes = [value for value in volumes[-5:] if value is not None]
        volume_ma_5 = (sum(recent_volumes) / len(recent_volumes)) if recent_volumes else None

        latest_turnover = turnovers[-1] if turnovers else None
        recent_turnovers = [value for value in turnovers[-5:] if value is not None]
        turnover_ma_5 = (sum(recent_turnovers) / len(recent_turnovers)) if recent_turnovers else None
        if latest_turnover is None:
            turnover_signal = "暂无换手率数据"
        elif turnover_ma_5 is None:
            turnover_signal = "参考"
        elif latest_turnover >= turnover_ma_5:
            turnover_signal = "活跃度上行"
        else:
            turnover_signal = "活跃度回落"

        if ma_5 is None:
            ma5_signal = "数据不足"
        else:
            ma5_signal = "多头" if latest_close >= ma_5 else "空头"
        if ma_20 is None:
            ma20_signal = "数据不足"
        else:
            ma20_signal = "多头" if latest_close >= ma_20 else "空头"

        if dif_last is None or dea_last is None:
            macd_signal = "数据不足"
        elif dif_last >= dea_last:
            macd_signal = "金叉偏强"
        else:
            macd_signal = "死叉偏弱"

        if boll_upper is None or boll_lower is None:
            boll_signal = "数据不足"
        elif latest_close > boll_upper:
            boll_signal = "突破上轨"
        elif latest_close < boll_lower:
            boll_signal = "跌破下轨"
        else:
            boll_signal = "轨道内"

        latest_k = _safe_float(k_val)
        latest_d = _safe_float(d_val)
        latest_j = _safe_float(j_val)
        if latest_k is None or latest_d is None:
            kdj_signal = "数据不足"
        elif latest_k >= latest_d:
            kdj_signal = "金叉偏强"
        else:
            kdj_signal = "死叉偏弱"

        return {
            "ma_5": {"latest": _safe_float(ma_5), "signal": ma5_signal},
            "ma_20": {"latest": _safe_float(ma_20), "signal": ma20_signal},
            "ema_12": {"latest": _safe_float(ema_12_series[-1]) if ema_12_series else None, "signal": "参考"},
            "ema_26": {"latest": _safe_float(ema_26_series[-1]) if ema_26_series else None, "signal": "参考"},
            "macd": {
                "dif": dif_last,
                "dea": dea_last,
                "hist": macd_hist_last,
                "signal": macd_signal,
            },
            "rsi_14": {"latest": latest_rsi, "signal": self._factor_signal(latest_rsi, high=70, low=30)},
            "boll": {
                "upper": _safe_float(boll_upper),
                "middle": _safe_float(boll_mid),
                "lower": _safe_float(boll_lower),
                "signal": boll_signal,
            },
            "kdj": {
                "k": latest_k,
                "d": latest_d,
                "j": latest_j,
                "signal": kdj_signal,
            },
            "atr_14": {"latest": _safe_float(atr_14), "signal": "波动参考"},
            "volume_ma_5": {"latest": _safe_float(volume_ma_5), "signal": "参考"},
            "turnover_summary": {
                "latest": _safe_float(latest_turnover),
                "ma_5": _safe_float(turnover_ma_5),
                "signal": turnover_signal,
            },
        }

    async def get_technical_factors(
        self,
        code: str,
        limit: int = 120,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        del refresh  # Technical factors rely on local K-line cache only.

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
            "last_updated": _first_present(
                bars[-1].get("updated_at"),
                bars[-1].get("trade_date"),
                bars[-1].get("date"),
            ),
            "is_cached": True,
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
