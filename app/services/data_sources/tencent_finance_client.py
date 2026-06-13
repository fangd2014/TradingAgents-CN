"""
Tencent Finance quote client.

This module keeps the unofficial Tencent quote endpoint behind a small parser so
the rest of the app works with normalized quote dictionaries.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text == "-":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _code6(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def _market_prefix(code: str) -> str:
    code6 = _code6(code)
    if code6.startswith(("60", "68", "90")):
        return "sh"
    if code6.startswith(("8", "4", "43", "83", "87", "92")):
        return "bj"
    return "sz"


class TencentFinanceClient:
    """Small client for Tencent's qt.gtimg.cn quote endpoint."""

    endpoint = "https://qt.gtimg.cn/q="

    def __init__(self, timeout_seconds: float = 5.0, session: Optional[requests.Session] = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    @staticmethod
    def to_tencent_symbol(code: str) -> str:
        code6 = _code6(code)
        if not code6:
            return ""
        return f"{_market_prefix(code6)}{code6}"

    @staticmethod
    def parse_quote_line(line: str) -> Optional[Dict[str, Any]]:
        if not line or "~" not in line:
            return None

        payload = line.split("=", 1)[1] if "=" in line else line
        payload = payload.strip().strip(";").strip('"')
        fields = payload.split("~")
        if len(fields) < 39:
            return None

        code = _code6(fields[2])
        if not code:
            return None

        return {
            "code": code,
            "name": fields[1],
            "close": _safe_float(fields[3]),
            "pre_close": _safe_float(fields[4]),
            "open": _safe_float(fields[5]),
            "high": _safe_float(fields[33]),
            "low": _safe_float(fields[34]),
            "pct_chg": _safe_float(fields[32]),
            "amount": _safe_float(fields[37]),
            "volume": _safe_float(fields[36]),
            "turnover_rate": _safe_float(fields[38]) if len(fields) > 38 else None,
            "pe_ttm": _safe_float(fields[39]) if len(fields) > 39 else None,
            "pb": _safe_float(fields[44]) if len(fields) > 44 else None,
            "total_mv": _safe_float(fields[45]) if len(fields) > 45 else None,
            "float_mv": _safe_float(fields[46]) if len(fields) > 46 else None,
            "limit_up": _safe_float(fields[49]) if len(fields) > 49 else None,
            "limit_down": _safe_float(fields[50]) if len(fields) > 50 else None,
            "source": "tencent_finance",
        }

    def fetch_quotes(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        symbols = [self.to_tencent_symbol(code) for code in codes]
        symbols = [symbol for symbol in symbols if symbol]
        if not symbols:
            return {}

        quotes: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(symbols), 80):
            batch = symbols[start:start + 80]
            try:
                resp = self.session.get(
                    self.endpoint + ",".join(batch),
                    timeout=self.timeout_seconds,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("Tencent quote batch failed: %s", exc)
                continue

            text = resp.content.decode("gbk", errors="ignore")
            for line in text.splitlines():
                quote = self.parse_quote_line(line)
                if quote:
                    quotes[quote["code"]] = quote

        return quotes


def normalize_code_list(codes: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for raw_code in codes:
        code = _code6(raw_code)
        if code and code not in seen:
            seen.add(code)
            result.append(code)
    return result
