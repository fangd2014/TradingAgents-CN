from __future__ import annotations

import math
import re
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
    excluded_prefixes = ("159", "51", "56", "58")
    return not code6.startswith(excluded_prefixes)


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
        latest_cashflow = cashflow_statement[0] if cashflow_statement else {}
        latest_indicator = financial_indicators[0] if financial_indicators else {}

        summary = {
            "report_period": latest.get("report_period"),
            "ann_date": latest.get("ann_date") or latest_income.get("ann_date") or latest_indicator.get("ann_date"),
            "revenue": latest_income.get("revenue"),
            "revenue_ttm": latest.get("revenue_ttm") or latest_indicator.get("revenue_ttm"),
            "net_profit": latest_income.get("n_income") or latest_income.get("net_profit"),
            "net_profit_ttm": latest.get("net_profit_ttm") or latest_indicator.get("net_profit_ttm"),
            "roe": latest_indicator.get("roe"),
            "roa": latest_indicator.get("roa"),
            "gross_margin": latest_indicator.get("grossprofit_margin"),
            "netprofit_margin": latest_indicator.get("netprofit_margin"),
            "debt_to_assets": latest_indicator.get("debt_to_assets") or latest_balance.get("debt_to_assets"),
            "current_ratio": latest_indicator.get("current_ratio"),
            "quick_ratio": latest_indicator.get("quick_ratio"),
        }

        return {
            "status": "ok",
            "code": code6,
            "message": "ok",
            "income_statement": income_statement,
            "balance_sheet": balance_sheet,
            "cashflow_statement": cashflow_statement,
            "financial_indicators": financial_indicators,
            "main_business": main_business,
            "summary": summary,
            "source": source,
            "last_updated": latest.get("updated_at"),
            "is_cached": is_cached,
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
            return bool(result and (result.get("success_count", 0) > 0 or result.get("error_count", 0) == 0))
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
