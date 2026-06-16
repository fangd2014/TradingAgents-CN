"""
China external data services for quotes, research reports, semantic search, and
THS theme tags.
"""
from __future__ import annotations

import logging
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

from app.core.config import settings
from app.services.data_sources.tencent_finance_client import (
    TencentFinanceClient,
    normalize_code_list,
)

logger = logging.getLogger(__name__)


def _get_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _env_or_setting(name: str, default: Any = "") -> Any:
    value = os.getenv(name)
    if value is not None:
        return value
    return _get_setting(name, default)


def _bool_env_or_setting(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return bool(_get_setting(name, default))
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _pick(row: Dict[str, Any], candidates: Iterable[str]) -> Any:
    for key in candidates:
        if key in row and _safe_text(row.get(key)):
            return row.get(key)
    return ""


def _code6(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def _df_records(df: Any, limit: int) -> List[Dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    return df.head(limit).to_dict("records")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _market_id(code: str) -> int:
    code6 = _code6(code)
    return 1 if code6.startswith(("60", "68", "90")) else 0


def _split_tags(value: Any) -> List[str]:
    tags: List[str] = []
    for tag in str(value or "").replace("，", ";").replace(",", ";").split(";"):
        clean = tag.strip()
        if clean and clean not in tags:
            tags.append(clean)
    return tags


@dataclass
class SourceAvailability:
    name: str
    available: bool
    requires_registration: bool
    registration_url: Optional[str] = None
    reason: str = ""


class ChinaQuoteService:
    """Realtime quote facade for Tencent Finance and optional mootdx."""

    def __init__(self, timeout_seconds: Optional[float] = None) -> None:
        timeout = timeout_seconds or float(_get_setting("CHINA_DATA_HTTP_TIMEOUT_SECONDS", 5))
        self.tencent_client = TencentFinanceClient(timeout_seconds=timeout)

    def get_quotes(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        normalized = normalize_code_list(codes)
        if not normalized:
            return {}

        if _get_setting("TENCENT_FINANCE_ENABLED", True):
            data = self.tencent_client.fetch_quotes(normalized)
            if data:
                return data

        if _get_setting("MOOTDX_ENABLED", True):
            data = self._fetch_mootdx_quotes(normalized)
            if data:
                return data

        return {}

    def _fetch_mootdx_quotes(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            from mootdx.quotes import Quotes  # type: ignore
        except Exception as exc:
            logger.info("mootdx unavailable: %s", exc)
            return {}

        try:
            client = Quotes.factory(market="std")
            result: Dict[str, Dict[str, Any]] = {}
            for code in codes:
                try:
                    df = client.quotes([code])
                except Exception as exc:
                    logger.debug("mootdx quote failed for %s: %s", code, exc)
                    continue
                for row in _df_records(df, 1):
                    code6 = _code6(row.get("code") or code)
                    result[code6] = {
                        "code": code6,
                        "name": _safe_text(row.get("name")),
                        "close": row.get("price") or row.get("close"),
                        "pre_close": row.get("last_close"),
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "pct_chg": row.get("涨幅") or row.get("change_percent"),
                        "amount": row.get("amount"),
                        "volume": row.get("vol") or row.get("volume"),
                        "source": "mootdx",
                    }
            return result
        except Exception as exc:
            logger.warning("mootdx quote fetch failed: %s", exc)
            return {}


class MootdxDeepMarketService:
    """mootdx deep quote, K-line, transaction, finance and F10 facade."""

    frequency_map = {
        "5m": 0,
        "15m": 1,
        "30m": 2,
        "60m": 3,
        "day": 9,
        "week": 5,
        "month": 6,
    }

    def __init__(self, client: Any = None, reader: Any = None) -> None:
        self.client = client
        self.reader = reader

    def _client(self) -> Any:
        if self.client is not None:
            return self.client
        from mootdx.quotes import Quotes  # type: ignore

        self.client = Quotes.factory(market="std")
        return self.client

    def _reader(self) -> Any:
        if self.reader is not None:
            return self.reader
        from mootdx.affair import Affair  # type: ignore

        self.reader = Affair()
        return self.reader

    def get_order_book(self, symbol: str) -> List[Dict[str, Any]]:
        code = _code6(symbol)
        if not code:
            return []
        try:
            df = self._client().quotes([code])
            return _df_records(df, 1)
        except Exception as exc:
            logger.warning("mootdx order book failed for %s: %s", code, exc)
            return []

    def get_kline(self, symbol: str, period: str = "day", limit: int = 120) -> List[Dict[str, Any]]:
        code = _code6(symbol)
        if not code:
            return []
        frequency = self.frequency_map.get(period, 9)
        try:
            df = self._client().bars(symbol=code, frequency=frequency, offset=limit)
            return _df_records(df, limit)
        except Exception as exc:
            logger.warning("mootdx kline failed for %s/%s: %s", code, period, exc)
            return []

    def get_transactions(self, symbol: str, start: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        code = _code6(symbol)
        if not code:
            return []
        try:
            df = self._client().transactions(symbol=code, start=start, offset=limit)
            return _df_records(df, limit)
        except Exception as exc:
            logger.warning("mootdx transactions failed for %s: %s", code, exc)
            return []

    def get_finance_snapshot(self, symbol: str) -> Dict[str, Any]:
        code = _code6(symbol)
        if not code:
            return {}
        try:
            reader = self._reader()
            data = reader.finance(code) if hasattr(reader, "finance") else {}
            if isinstance(data, pd.DataFrame):
                rows = _df_records(data, 1)
                return rows[0] if rows else {}
            return dict(data or {})
        except Exception as exc:
            logger.warning("mootdx finance failed for %s: %s", code, exc)
            return {}

    def get_f10(self, symbol: str, category: str = "公司概况") -> Dict[str, Any]:
        code = _code6(symbol)
        if not code:
            return {}
        try:
            reader = self._reader()
            if hasattr(reader, "f10"):
                data = reader.f10(code, category=category)
            elif hasattr(reader, "parse"):
                data = reader.parse(code, category=category)
            else:
                data = {}
            return {"symbol": code, "category": category, "content": data, "source": "mootdx_f10"}
        except Exception as exc:
            logger.warning("mootdx F10 failed for %s/%s: %s", code, category, exc)
            return {}


class EastmoneyReportApiClient:
    """Direct Eastmoney reportapi client with EPS forecast and PDF URL support."""

    endpoint = "https://reportapi.eastmoney.com/report/list"
    pdf_referer = "https://data.eastmoney.com/report/"

    def __init__(self, timeout_seconds: Optional[float] = None, session: Any = None) -> None:
        self.timeout_seconds = timeout_seconds or float(_get_setting("CHINA_DATA_HTTP_TIMEOUT_SECONDS", 5))
        self.session = session or requests.Session()

    @staticmethod
    def parse_jsonp(text: str) -> Dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("{"):
            return json.loads(stripped)
        match = re.search(r"^[^(]*\((.*)\)\s*;?$", stripped, flags=re.S)
        if not match:
            raise ValueError("Invalid Eastmoney reportapi response")
        return json.loads(match.group(1))

    def list_reports(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        if not _get_setting("EASTMONEY_RESEARCH_ENABLED", True):
            return []
        code = _code6(symbol)
        params = {
            "pageNo": 1,
            "pageSize": limit,
            "code": code,
            "sort": "publishDate",
            "order": "desc",
            "source": "WEB",
            "client": "WEB",
        }
        try:
            resp = self.session.get(
                self.endpoint,
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Referer": self.pdf_referer},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = self.parse_jsonp(resp.text)
        except Exception as exc:
            logger.warning("Eastmoney reportapi failed for %s: %s", code, exc)
            return []
        reports = [self.normalize_report(row) for row in payload.get("data", [])[:limit]]
        return [report for report in reports if report["title"]]

    def normalize_report(self, row: Dict[str, Any]) -> Dict[str, Any]:
        symbol = _code6(_pick(row, ["stockCode", "股票代码", "代码", "symbol", "code"]))
        info_code = _safe_text(_pick(row, ["infoCode", "encodeUrl", "info_code"]))
        pdf_url = _safe_text(_pick(row, ["pdfUrl", "attachUrl", "url"]))
        if not pdf_url and info_code:
            pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
        return {
            "symbol": symbol,
            "name": _safe_text(_pick(row, ["stockName", "股票简称", "名称", "name"])),
            "title": _safe_text(_pick(row, ["title", "报告名称", "研报标题", "标题"])),
            "institution": _safe_text(_pick(row, ["orgSName", "orgName", "机构", "机构名称", "institution"])),
            "rating": _safe_text(_pick(row, ["emRatingName", "rating", "评级", "东财评级"])),
            "publish_date": _safe_text(_pick(row, ["publishDate", "日期", "报告日期", "发布时间"]))[:10],
            "eps_forecast": {
                "this_year": _safe_float(row.get("predictThisYearEps")),
                "next_year": _safe_float(row.get("predictNextYearEps")),
                "next_two_year": _safe_float(row.get("predictNextTwoYearEps")),
            },
            "pdf_url": pdf_url,
            "url": pdf_url,
            "info_code": info_code,
            "source": "eastmoney_reportapi",
        }

    def download_pdf(self, pdf_url: str, target_path: str | Path) -> bool:
        try:
            resp = self.session.get(
                pdf_url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": self.pdf_referer},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            Path(target_path).write_bytes(resp.content)
            return True
        except Exception as exc:
            logger.warning("Eastmoney PDF download failed: %s", exc)
            return False


class ChinaResearchReportService:
    """Research reports via direct Eastmoney reportapi."""

    def __init__(self, client: Optional[EastmoneyReportApiClient] = None) -> None:
        self.client = client or EastmoneyReportApiClient()

    def get_reports(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.client.list_reports(symbol, limit=limit)


class IwencaiPywencaiClient:
    """iWenCai semantic search via pywencai and browser Cookie authentication."""

    def __init__(
        self,
        cookie: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        pywencai_module: Any = None,
    ) -> None:
        self.cookie = cookie if cookie is not None else _get_setting("IWENCAI_COOKIE", "")
        self.timeout_seconds = timeout_seconds or float(_get_setting("CHINA_DATA_HTTP_TIMEOUT_SECONDS", 5))
        self.pywencai_module = pywencai_module

    def search(self, query: str, limit: int = 50) -> Dict[str, Any]:
        if not _get_setting("IWENCAI_ENABLED", True):
            return self._unavailable("iwencai disabled")
        if not str(self.cookie or "").strip():
            return self._unavailable("IWENCAI_COOKIE is not configured")

        try:
            pywencai = self.pywencai_module or self._import_pywencai()
            payload = pywencai.get(
                query=query,
                perpage=max(1, min(int(limit or 50), 100)),
                loop=False,
                cookie=self.cookie,
            )
            rows = self._normalize_result(payload, limit=limit)
        except ImportError:
            return self._unavailable("pywencai is not installed; run `pip install pywencai`")
        except Exception as exc:
            return self._unavailable(f"iwencai pywencai query failed: {exc}")

        return {
            "available": True,
            "source": "iwencai",
            "query": query,
            "total_count": len(rows),
            "results": rows[:limit],
        }

    def _import_pywencai(self) -> Any:
        import pywencai  # type: ignore

        return pywencai

    def _normalize_result(self, payload: Any, limit: int) -> List[Dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, pd.DataFrame):
            return _df_records(payload, limit)
        if isinstance(payload, list):
            rows = []
            for item in payload[:limit]:
                rows.append(item if isinstance(item, dict) else {"value": item})
            return rows
        if isinstance(payload, dict):
            for key in ("data", "result", "results"):
                if key in payload:
                    return self._normalize_result(payload[key], limit=limit)

            rows: List[Dict[str, Any]] = []
            for section, value in payload.items():
                if isinstance(value, pd.DataFrame):
                    for row in _df_records(value, limit):
                        row.setdefault("section", section)
                        rows.append(row)
                elif isinstance(value, list):
                    rows.extend(self._normalize_result(value, limit=limit))
            if rows:
                return rows[:limit]
            return [payload]
        return [{"value": payload}]

    def _unavailable(self, reason: str) -> Dict[str, Any]:
        return {
            "available": False,
            "source": "iwencai",
            "reason": reason,
            "results": [],
            "total_count": 0,
        }


class SemanticSearchService:
    """iWenCai semantic search facade."""

    def __init__(self, client: Optional[IwencaiPywencaiClient] = None) -> None:
        self.client = client or IwencaiPywencaiClient()

    def search(self, query: str, limit: int = 50) -> Dict[str, Any]:
        return self.client.search(query, limit=limit)


class ThemeTagService:
    """THS theme/concept tags via iWenCai semantic data."""

    concept_columns = ("所属概念", "概念", "题材", "所属题材", "热点题材", "同花顺概念")

    def __init__(self, client: Optional[Any] = None) -> None:
        self.semantic = client or SemanticSearchService()

    def get_tags(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        if not _get_setting("THS_TAGS_ENABLED", True):
            return {
                "available": False,
                "symbol": _code6(symbol),
                "source": "iwencai_ths_tags",
                "reason": "ths tags disabled",
                "tags": [],
            }
        query = f"{_code6(symbol)} 所属概念 题材 热点归因"
        result = self.semantic.search(query, limit=limit)
        if not result.get("available"):
            return {
                "available": False,
                "symbol": _code6(symbol),
                "source": "iwencai_ths_tags",
                "reason": result.get("reason", "iwencai unavailable"),
                "tags": [],
            }

        tags: List[str] = []
        for row in result.get("results", []):
            for column in self.concept_columns:
                raw_value = row.get(column)
                if not raw_value:
                    continue
                for tag in str(raw_value).replace("，", ";").replace(",", ";").split(";"):
                    clean = tag.strip()
                    if clean and clean not in tags:
                        tags.append(clean)

        return {
            "available": True,
            "symbol": _code6(symbol),
            "source": "iwencai_ths_tags",
            "tags": tags,
            "as_of": datetime.utcnow().isoformat(),
        }


class THSHotspotService:
    """同花顺当日强势股和编辑部题材归因，当前通过 pywencai 查询。"""

    def __init__(self, client: Optional[Any] = None) -> None:
        self.client = client or SemanticSearchService()

    def get_hotspots(self, limit: int = 50) -> Dict[str, Any]:
        query = "同花顺 当日强势股 题材归因 热点概念 涨跌幅"
        result = self.client.search(query, limit=limit)
        if not result.get("available"):
            return {
                "available": False,
                "source": "ths_hotspot_pywencai",
                "query": query,
                "reason": result.get("reason", "iwencai unavailable"),
                "items": [],
            }

        items = []
        for row in result.get("results", [])[:limit]:
            tags = []
            for key in ("题材", "所属概念", "热点题材", "同花顺概念"):
                tags.extend(tag for tag in _split_tags(row.get(key)) if tag not in tags)
            items.append(
                {
                    "symbol": _code6(_pick(row, ["股票代码", "代码", "symbol"])),
                    "name": _safe_text(_pick(row, ["股票简称", "名称", "name"])),
                    "tags": tags,
                    "reason": _safe_text(_pick(row, ["热点归因", "入选理由", "原因", "题材解析"])),
                    "pct_chg": _safe_float(_pick(row, ["涨跌幅", "涨幅", "pct_chg"])),
                    "raw": row,
                }
            )
        return {
            "available": True,
            "source": "ths_hotspot_pywencai",
            "query": query,
            "total_count": len(items),
            "items": items,
        }


class IfindQuantApiService:
    """同花顺 iFinD QuantAPI facade via iFinDPy."""

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        indicators: Optional[str] = None,
        params: Optional[str] = None,
        query_templates: Optional[str] = None,
        include_query: Optional[bool] = None,
        ifind_module: Any = None,
    ) -> None:
        self.username = username if username is not None else _env_or_setting("IFIND_USERNAME", "")
        self.password = password if password is not None else _env_or_setting("IFIND_PASSWORD", "")
        self.indicators = indicators if indicators is not None else _env_or_setting("IFIND_BASIC_INDICATORS", "")
        self.params = params if params is not None else _env_or_setting("IFIND_BASIC_PARAMS", "")
        self.query_templates = query_templates if query_templates is not None else _env_or_setting("IFIND_QUERY_TEMPLATES", "")
        self.include_query = _bool_env_or_setting("IFIND_INCLUDE_QUERY", True) if include_query is None else bool(include_query)
        self.ifind_module = ifind_module

    def get_stock_features(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        code = _code6(symbol)
        if not _bool_env_or_setting("IFIND_ENABLED", True):
            return self._unavailable(code, "ifind disabled")
        if not str(self.username or "").strip() or not str(self.password or "").strip():
            return self._unavailable(code, "IFIND_USERNAME/IFIND_PASSWORD is not configured")

        try:
            module = self.ifind_module or self._import_ifind()
        except ImportError:
            return self._unavailable(code, "iFinDPy is not installed; install the iFinD QuantAPI Python package")

        login_result = self._login(module)
        if not self._is_success(login_result):
            return self._unavailable(code, f"THS_iFinDLogin failed: {self._brief(login_result)}")

        status: Dict[str, Any] = {"login": {"ok": True}}
        basic: Dict[str, Any] = {}
        if self.indicators:
            try:
                basic_result = getattr(module, "THS_BD")(self._ifind_code(code), self.indicators, self.params or "")
                basic = self._normalize_result(basic_result, limit=limit)
                status["basic_data"] = {"ok": True, "indicator_count": len([item for item in self.indicators.split(";") if item.strip()])}
            except Exception as exc:
                status["basic_data"] = {"ok": False, "error": str(exc)[:300]}

        queries: List[Dict[str, Any]] = []
        if self.include_query and self.query_templates:
            query_fn = self._query_function(module)
            if query_fn is None:
                status["queries"] = {"ok": False, "error": "No iFinD query function found on iFinDPy module"}
            else:
                for template in self._query_template_lines()[:limit]:
                    question = template.format(code=code, ifind_code=self._ifind_code(code))
                    try:
                        result = query_fn(question)
                        queries.append({"query": question, "result": self._normalize_result(result, limit=limit)})
                    except Exception as exc:
                        queries.append({"query": question, "error": str(exc)[:300]})
                status["queries"] = {"ok": True, "count": len(queries)}

        return {
            "available": True,
            "symbol": code,
            "ifind_code": self._ifind_code(code),
            "source": "ifind_quantapi",
            "basic_data": basic,
            "queries": queries,
            "status": status,
            "as_of": datetime.utcnow().isoformat(),
        }

    def _import_ifind(self) -> Any:
        import importlib

        return importlib.import_module("iFinDPy")

    def _login(self, module: Any) -> Any:
        login = getattr(module, "THS_iFinDLogin")
        return login(str(self.username).strip(), str(self.password).strip())

    def _query_function(self, module: Any) -> Optional[Any]:
        for name in ("THS_WC", "THS_Query", "THS_SmartQuery"):
            fn = getattr(module, name, None)
            if callable(fn):
                return fn
        return None

    def _query_template_lines(self) -> List[str]:
        lines: List[str] = []
        for line in str(self.query_templates or "").replace("；", "\n").splitlines():
            clean = line.strip()
            if clean and clean not in lines:
                lines.append(clean)
        return lines

    @staticmethod
    def _ifind_code(code: str) -> str:
        code6 = _code6(code)
        if code6.startswith(("60", "68", "90")):
            return f"{code6}.SH"
        if code6.startswith(("43", "83", "87", "88", "92")):
            return f"{code6}.BJ"
        return f"{code6}.SZ"

    def _normalize_result(self, payload: Any, limit: int = 5) -> Dict[str, Any]:
        if payload is None:
            return {"raw": None}
        if isinstance(payload, pd.DataFrame):
            return {"records": _df_records(payload, limit)}
        if isinstance(payload, dict):
            return {str(key): self._normalize_value(value, limit=limit) for key, value in payload.items()}

        data = {}
        for attr in ("errorcode", "errmsg", "data", "tables", "time", "codes", "indicators"):
            if hasattr(payload, attr):
                data[attr] = self._normalize_value(getattr(payload, attr), limit=limit)
        if data:
            return data
        return {"raw": self._normalize_value(payload, limit=limit)}

    def _normalize_value(self, value: Any, limit: int = 5) -> Any:
        if isinstance(value, pd.DataFrame):
            return _df_records(value, limit)
        if isinstance(value, list):
            return [self._normalize_value(item, limit=limit) for item in value[:limit]]
        if isinstance(value, tuple):
            return [self._normalize_value(item, limit=limit) for item in value[:limit]]
        if isinstance(value, dict):
            return {str(key): self._normalize_value(item, limit=limit) for key, item in value.items()}
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _is_success(result: Any) -> bool:
        if result in (0, "0", True):
            return True
        if isinstance(result, dict):
            code = result.get("errorcode") or result.get("code")
            return str(code) in {"0", "None", ""}
        if hasattr(result, "errorcode"):
            return str(getattr(result, "errorcode")) == "0"
        return False

    @staticmethod
    def _brief(value: Any) -> str:
        text = str(value)
        return text[:300]

    def _unavailable(self, code: str, reason: str) -> Dict[str, Any]:
        return {
            "available": False,
            "symbol": code,
            "ifind_code": self._ifind_code(code) if code else "",
            "source": "ifind_quantapi",
            "reason": reason,
            "basic_data": {},
            "queries": [],
            "status": {"ifind": {"ok": False, "error": reason}},
        }


class AkshareNewsService:
    """AKShare news trio: Eastmoney stock news, CLS flash, and Eastmoney global news."""

    def _ak(self) -> Any:
        import akshare as ak  # type: ignore

        return ak

    def get_stock_news(self, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            df = self._ak().stock_news_em(symbol=_code6(symbol))
        except Exception as exc:
            logger.warning("AKShare stock_news_em failed for %s: %s", symbol, exc)
            return []
        return [
            {
                "symbol": _code6(symbol),
                "title": _safe_text(_pick(row, ["新闻标题", "标题", "title"])),
                "source": _safe_text(_pick(row, ["文章来源", "来源", "source"])) or "eastmoney",
                "publish_time": _safe_text(_pick(row, ["发布时间", "时间", "publish_time"])),
                "url": _safe_text(_pick(row, ["新闻链接", "链接", "url"])),
                "content": _safe_text(_pick(row, ["新闻内容", "内容", "content"])),
                "type": "stock_news",
                "data_source": "akshare_stock_news_em",
            }
            for row in _df_records(df, limit)
        ]

    def get_cls_flash(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            df = self._ak().stock_info_global_cls()
        except Exception as exc:
            logger.warning("AKShare stock_info_global_cls failed: %s", exc)
            return []
        return [
            {
                "title": _safe_text(_pick(row, ["标题", "title"])),
                "source": "财联社",
                "publish_time": _safe_text(_pick(row, ["发布时间", "时间", "publish_time"])),
                "url": _safe_text(_pick(row, ["链接", "url"])),
                "content": _safe_text(_pick(row, ["内容", "摘要", "content"])),
                "type": "cls_flash",
                "data_source": "akshare_stock_info_global_cls",
            }
            for row in _df_records(df, limit)
        ]

    def get_global_news(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            df = self._ak().stock_info_global_em()
        except Exception as exc:
            logger.warning("AKShare stock_info_global_em failed: %s", exc)
            return []
        return [
            {
                "title": _safe_text(_pick(row, ["标题", "title"])),
                "source": _safe_text(_pick(row, ["来源", "source"])) or "东方财富",
                "publish_time": _safe_text(_pick(row, ["发布时间", "时间", "publish_time"])),
                "url": _safe_text(_pick(row, ["链接", "url"])),
                "content": _safe_text(_pick(row, ["内容", "摘要", "content"])),
                "type": "global_news",
                "data_source": "akshare_stock_info_global_em",
            }
            for row in _df_records(df, limit)
        ]


class CninfoAnnouncementService:
    """Cninfo disclosure facade through AKShare's original cninfo wrapper."""

    def get_announcements(
        self,
        symbol: str,
        keyword: str = "",
        category: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        code = _code6(symbol)
        market = "沪市" if code.startswith(("60", "68", "90")) else "深市"
        try:
            import akshare as ak  # type: ignore

            fetcher = getattr(ak, "stock_zh_a_disclosure_report_cninfo")
            df = fetcher(
                symbol=code,
                market=market,
                keyword=keyword,
                category=category,
                start_date=start_date,
                end_date=end_date,
            )
        except TypeError:
            try:
                df = fetcher(symbol=code, market=market)
            except Exception as exc:
                logger.warning("Cninfo disclosure failed for %s: %s", code, exc)
                return []
        except Exception as exc:
            logger.warning("Cninfo disclosure failed for %s: %s", code, exc)
            return []

        return [
            {
                "symbol": code,
                "title": _safe_text(_pick(row, ["公告标题", "标题", "announcementTitle"])),
                "publish_date": _safe_text(_pick(row, ["公告时间", "公告日期", "发布时间", "date"])),
                "url": _safe_text(_pick(row, ["公告链接", "链接", "url", "adjunctUrl"])),
                "category": _safe_text(_pick(row, ["公告类型", "类型", "category"])),
                "source": "cninfo_akshare",
            }
            for row in _df_records(df, limit)
        ]


def get_source_availability() -> List[Dict[str, Any]]:
    sources = [
        SourceAvailability(
            name="mootdx",
            available=_can_import("mootdx"),
            requires_registration=False,
            registration_url=None,
            reason="Python package optional; no account is required for public TDX servers.",
        ),
        SourceAvailability(
            name="tencent_finance",
            available=True,
            requires_registration=False,
            registration_url=None,
            reason="Uses public qt.gtimg.cn quote endpoint; no official SDK contract.",
        ),
        SourceAvailability(
            name="ifind",
            available=_bool_env_or_setting("IFIND_ENABLED", True)
            and bool(_env_or_setting("IFIND_USERNAME", ""))
            and bool(_env_or_setting("IFIND_PASSWORD", ""))
            and _can_import("iFinDPy"),
            requires_registration=True,
            registration_url="https://quantapi.51ifind.com/gwstatic/static/ds_web/super-command-web/index.html#/BasicData",
            reason="Requires a licensed THS iFinD account/password and the iFinDPy QuantAPI package.",
        ),
        SourceAvailability(
            name="eastmoney_reportapi",
            available=True,
            requires_registration=False,
            registration_url=None,
            reason="Direct public Eastmoney reportapi with EPS forecast and PDF URL support.",
        ),
        SourceAvailability(
            name="iwencai",
            available=bool(_get_setting("IWENCAI_COOKIE", "")) and _can_import("pywencai"),
            requires_registration=True,
            registration_url="https://www.iwencai.com/",
            reason="Requires pywencai plus IWENCAI_COOKIE copied from a logged-in browser request.",
        ),
        SourceAvailability(
            name="ths_hotspot_tags",
            available=bool(_get_setting("IWENCAI_COOKIE", "")) and _can_import("pywencai"),
            requires_registration=True,
            registration_url="https://www.iwencai.com/",
            reason="Hotspot attribution is derived from THS/iWenCai semantic data via pywencai Cookie auth.",
        ),
        SourceAvailability(
            name="akshare_news_trio",
            available=_can_import("akshare"),
            requires_registration=False,
            registration_url=None,
            reason="Uses stock_news_em, stock_info_global_cls, and stock_info_global_em.",
        ),
        SourceAvailability(
            name="cninfo_announcements",
            available=_can_import("akshare"),
            requires_registration=False,
            registration_url=None,
            reason="Uses AKShare cninfo disclosure wrapper for official announcements.",
        ),
    ]
    return [source.__dict__ for source in sources]


def _can_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False
