"""
Favorite stock source-feature refresh and scheduled analysis jobs.

This service keeps a compact latest snapshot for each favorite A-share.  The
snapshot is used both by the favorites API and by analysis prompts, so the UI
and reports are grounded in the same source data.
"""

from __future__ import annotations

import asyncio
import logging
import math
import multiprocessing
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId

from app.core.config import settings
from app.core.database import get_mongo_db
from app.models.analysis import AnalysisParameters, BatchAnalysisRequest
from app.services.china_external_data_service import (
    AkshareNewsService,
    ChinaQuoteService,
    ChinaResearchReportService,
    CninfoAnnouncementService,
    IfindQuantApiService,
    MootdxDeepMarketService,
    THSHotspotService,
    ThemeTagService,
)
from app.services.favorites_service import calculate_amplitude
from app.services.stock_shareholder_service import fetch_tushare_shareholder_rows_sync

logger = logging.getLogger(__name__)


SNAPSHOT_COLLECTION = "favorite_stock_data_snapshots"


def _code6(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _is_a_share(code: str) -> bool:
    code6 = _code6(code)
    return bool(re.fullmatch(r"\d{6}", code6)) and code6.startswith(
        ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689", "920")
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _limit(rows: Iterable[Dict[str, Any]], size: int) -> List[Dict[str, Any]]:
    return [row for row in rows or [] if isinstance(row, dict)][: max(size, 0)]


def _clean_value(value: Any) -> Any:
    """Make third-party rows safe and reasonably small for MongoDB."""
    if value is None or isinstance(value, (str, int, bool, datetime)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {_clean_key(key): _clean_value(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value]
    try:
        import pandas as pd  # type: ignore

        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _clean_key(key: Any) -> str:
    text = str(key)
    if text.startswith("$"):
        text = "_" + text[1:]
    return text.replace(".", "_")


def _source_error(status: Dict[str, Any], key: str, exc: Exception) -> None:
    status[key] = {"ok": False, "error": str(exc)[:300]}


def _process_worker(queue: Any, func: Any, args: tuple, kwargs: Dict[str, Any]) -> None:
    try:
        queue.put({"ok": True, "value": func(*args, **kwargs)})
    except Exception as exc:
        queue.put({"ok": False, "error": str(exc)})


def _call_in_process(func: Any, args: tuple = (), kwargs: Optional[Dict[str, Any]] = None, timeout: int = 20, default: Any = None) -> Any:
    """Run a slow third-party call in a child process so it can be terminated."""
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_process_worker, args=(queue, func, args, kwargs or {}))
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(2)
        return default
    if queue.empty():
        return default
    payload = queue.get()
    if payload.get("ok"):
        return payload.get("value")
    return {"__error__": payload.get("error") or "unknown error"}


def _timeout_status(source: str, seconds: int) -> Dict[str, Any]:
    return {"ok": False, "error": f"{source} timeout after {seconds}s"}


class FavoriteStockDataService:
    """Refresh connected-source feature data for favorite stocks."""

    def __init__(self) -> None:
        self.db = None

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def ensure_indexes(self) -> None:
        db = await self._get_db()
        try:
            await db[SNAPSHOT_COLLECTION].create_index(
                [("user_id", 1), ("code", 1)],
                unique=True,
                name="user_code_unique",
                background=True,
            )
            await db[SNAPSHOT_COLLECTION].create_index(
                [("code", 1), ("refreshed_at", -1)],
                name="code_refreshed",
                background=True,
            )
        except Exception as exc:
            logger.warning("创建自选股数据源快照索引失败: %s", exc)

    async def list_user_favorite_groups(self) -> List[Dict[str, Any]]:
        db = await self._get_db()
        groups: List[Dict[str, Any]] = []
        cursor = db.user_favorites.find({}, {"_id": 0, "user_id": 1, "favorites": 1})
        async for doc in cursor:
            favorites = [fav for fav in doc.get("favorites") or [] if _is_a_share(fav.get("stock_code"))]
            if favorites:
                groups.append({"user_id": str(doc.get("user_id") or ""), "favorites": favorites})
        return groups

    async def refresh_all_favorite_stock_data(self, max_concurrency: int = 3) -> Dict[str, Any]:
        await self.ensure_indexes()
        groups = await self.list_user_favorite_groups()
        if not groups:
            return {"users": 0, "stocks": 0, "success_count": 0, "failed_count": 0, "message": "没有A股自选股需要更新"}

        global_timeout = int(getattr(settings, "FAVORITE_FEATURE_GLOBAL_TIMEOUT_SECONDS", 12))
        global_context = await asyncio.to_thread(
            _call_in_process,
            self._fetch_global_context_sync,
            (),
            {},
            global_timeout,
            {"cls_flash": [], "global_news": [], "hotspots": [], "status": {"global_context": _timeout_status("global context", global_timeout)}},
        )
        totals = {"users": len(groups), "stocks": 0, "success_count": 0, "failed_count": 0, "details": []}
        for group in groups:
            result = await self.refresh_user_favorite_stock_data(
                group["user_id"],
                group["favorites"],
                global_context=global_context,
                max_concurrency=max_concurrency,
            )
            totals["stocks"] += result.get("total", 0)
            totals["success_count"] += result.get("success_count", 0)
            totals["failed_count"] += result.get("failed_count", 0)
            totals["details"].append(result)
        return totals

    async def refresh_user_favorite_stock_data(
        self,
        user_id: str,
        favorites: Optional[List[Dict[str, Any]]] = None,
        global_context: Optional[Dict[str, Any]] = None,
        max_concurrency: int = 3,
    ) -> Dict[str, Any]:
        db = await self._get_db()
        if favorites is None:
            doc = await db.user_favorites.find_one({"user_id": user_id})
            favorites = list((doc or {}).get("favorites") or [])

        favorites = [fav for fav in favorites if _is_a_share(fav.get("stock_code"))]
        codes = sorted({_code6(fav.get("stock_code")) for fav in favorites if _code6(fav.get("stock_code"))})
        if not codes:
            return {"user_id": user_id, "total": 0, "success_count": 0, "failed_count": 0}

        quotes = await asyncio.to_thread(ChinaQuoteService().get_quotes, codes)
        if not global_context:
            global_timeout = int(getattr(settings, "FAVORITE_FEATURE_GLOBAL_TIMEOUT_SECONDS", 12))
            global_context = await asyncio.to_thread(
                _call_in_process,
                self._fetch_global_context_sync,
                (),
                {},
                global_timeout,
                {"cls_flash": [], "global_news": [], "hotspots": [], "status": {"global_context": _timeout_status("global context", global_timeout)}},
            )
        favorite_by_code = {_code6(fav.get("stock_code")): fav for fav in favorites}
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def fetch_one(code: str) -> Dict[str, Any]:
            async with semaphore:
                return await asyncio.to_thread(
                    self._fetch_stock_snapshot_sync,
                    code,
                    favorite_by_code.get(code, {}),
                    quotes.get(code) or {},
                    global_context,
                )

        snapshots = await asyncio.gather(*(fetch_one(code) for code in codes), return_exceptions=True)
        snapshot_docs: List[Dict[str, Any]] = []
        failed: List[str] = []
        refreshed_at = _now()

        for code, snapshot in zip(codes, snapshots):
            if isinstance(snapshot, Exception):
                logger.warning("自选股数据源快照失败 %s/%s: %s", user_id, code, snapshot)
                failed.append(code)
                continue
            doc = _clean_value(
                {
                    **snapshot,
                    "user_id": user_id,
                    "code": code,
                    "symbol": code,
                    "refreshed_at": refreshed_at,
                    "updated_at": refreshed_at,
                }
            )
            snapshot_docs.append(doc)
            await db[SNAPSHOT_COLLECTION].update_one(
                {"user_id": user_id, "code": code},
                {"$set": doc, "$setOnInsert": {"created_at": refreshed_at}},
                upsert=True,
            )

        compact_by_code = {doc["code"]: doc.get("compact", {}) for doc in snapshot_docs}
        refreshed_favorites = []
        for fav in favorites:
            code = _code6(fav.get("stock_code"))
            updated = dict(fav)
            if code in compact_by_code:
                updated["source_data"] = compact_by_code[code]
                updated["source_data_refreshed_at"] = refreshed_at.isoformat()
                updated["data_sources"] = {
                    **dict(updated.get("data_sources") or {}),
                    **dict(compact_by_code[code].get("data_sources") or {}),
                }
            refreshed_favorites.append(updated)

        original = await db.user_favorites.find_one({"user_id": user_id}, {"favorites": 1})
        original_favorites = list((original or {}).get("favorites") or [])
        refreshed_map = {_code6(fav.get("stock_code")): fav for fav in refreshed_favorites}
        merged = [refreshed_map.get(_code6(fav.get("stock_code")), fav) for fav in original_favorites]
        await db.user_favorites.update_one(
            {"user_id": user_id},
            {"$set": {"favorites": merged, "source_data_updated_at": refreshed_at, "updated_at": refreshed_at}},
        )

        return {
            "user_id": user_id,
            "total": len(codes),
            "success_count": len(snapshot_docs),
            "failed_count": len(failed),
            "failed_symbols": failed,
        }

    def _fetch_global_context_sync(self) -> Dict[str, Any]:
        context: Dict[str, Any] = {"cls_flash": [], "global_news": [], "hotspots": [], "status": {}}
        if getattr(settings, "AKSHARE_NEWS_ENABLED", True):
            news = AkshareNewsService()
            try:
                context["cls_flash"] = _limit(news.get_cls_flash(limit=20), 20)
                context["status"]["cls_flash"] = {"ok": True, "count": len(context["cls_flash"])}
            except Exception as exc:
                _source_error(context["status"], "cls_flash", exc)
            try:
                context["global_news"] = _limit(news.get_global_news(limit=20), 20)
                context["status"]["global_news"] = {"ok": True, "count": len(context["global_news"])}
            except Exception as exc:
                _source_error(context["status"], "global_news", exc)

        if getattr(settings, "THS_HOTSPOT_ENABLED", True):
            try:
                hotspot = THSHotspotService().get_hotspots(limit=80)
                context["hotspots"] = _limit(hotspot.get("items") or [], 80)
                context["status"]["ths_hotspots"] = {
                    "ok": bool(hotspot.get("available")),
                    "count": len(context["hotspots"]),
                    "reason": hotspot.get("reason"),
                }
            except Exception as exc:
                _source_error(context["status"], "ths_hotspots", exc)
        return context

    def _fetch_stock_snapshot_sync(
        self,
        code: str,
        favorite: Dict[str, Any],
        quote: Dict[str, Any],
        global_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        status: Dict[str, Any] = {}
        stock_name = favorite.get("stock_name") or quote.get("name") or ""
        compact: Dict[str, Any] = {
            "code": code,
            "stock_name": stock_name,
            "data_sources": {},
            "source_status": status,
        }

        quote_doc = dict(quote or {})
        if quote_doc:
            quote_doc.setdefault("amplitude", calculate_amplitude(quote_doc))
            compact["quote"] = {
                "price": quote_doc.get("close"),
                "pct_chg": quote_doc.get("pct_chg"),
                "volume": quote_doc.get("volume"),
                "amount": quote_doc.get("amount"),
                "trade_date": quote_doc.get("trade_date"),
                "source": quote_doc.get("source") or "external_quotes",
            }
            compact["tencent_metrics"] = {
                "pe_ttm": quote_doc.get("pe_ttm"),
                "pb": quote_doc.get("pb"),
                "total_mv": quote_doc.get("total_mv"),
                "float_mv": quote_doc.get("float_mv"),
                "turnover_rate": quote_doc.get("turnover_rate"),
                "amplitude": quote_doc.get("amplitude"),
                "limit_up": quote_doc.get("limit_up"),
                "limit_down": quote_doc.get("limit_down"),
            }
            compact["data_sources"]["quote"] = quote_doc.get("source") or "external_quotes"
            compact["data_sources"]["metrics"] = "tencent_finance"
            status["quote"] = {"ok": True}
        else:
            status["quote"] = {"ok": False, "error": "Tencent/mootdx quote unavailable"}

        optional_timeout = int(getattr(settings, "FAVORITE_FEATURE_STOCK_OPTIONAL_TIMEOUT_SECONDS", 20))
        optional = _call_in_process(
            self._fetch_stock_optional_sources_sync,
            (code, global_context),
            {},
            optional_timeout,
            {"source_status": {"optional_sources": _timeout_status("stock optional sources", optional_timeout)}},
        )
        if isinstance(optional, dict) and optional.get("__error__"):
            optional = {"source_status": {"optional_sources": {"ok": False, "error": optional["__error__"]}}}
        if not isinstance(optional, dict):
            optional = {}

        status.update(optional.get("source_status") or {})
        compact.update(optional.get("compact") or {})
        compact["source_status"] = status

        return {
            "stock_name": stock_name,
            "quote": quote_doc,
            "ifind": optional.get("ifind") or {},
            "mootdx_deep": optional.get("mootdx_deep") or {},
            "research_reports": optional.get("research_reports") or [],
            "theme_tags": optional.get("theme_tags") or {},
            "hotspots": optional.get("hotspots") or [],
            "news": optional.get("news") or {"stock_news": [], "cls_flash": [], "global_news": []},
            "announcements": optional.get("announcements") or [],
            "shareholders": optional.get("shareholders") or {"top10": [], "float_top10": []},
            "compact": compact,
            "source_status": status,
        }

    def _fetch_stock_optional_sources_sync(
        self,
        code: str,
        global_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        status: Dict[str, Any] = {}
        compact: Dict[str, Any] = {"data_sources": {}}
        ifind: Dict[str, Any] = {}
        if str(os.getenv("IFIND_ENABLED", str(getattr(settings, "IFIND_ENABLED", True)))).strip().lower() not in {"0", "false", "no", "off", ""}:
            try:
                ifind = IfindQuantApiService().get_stock_features(code, limit=5)
                status["ifind"] = {
                    "ok": bool(ifind.get("available")),
                    "reason": ifind.get("reason"),
                    "basic_fields": len((ifind.get("basic_data") or {}).keys()),
                    "query_count": len(ifind.get("queries") or []),
                }
                compact["ifind"] = {
                    "available": bool(ifind.get("available")),
                    "basic_data": ifind.get("basic_data") or {},
                    "queries": ifind.get("queries") or [],
                    "reason": ifind.get("reason"),
                }
                compact["data_sources"]["ifind"] = "ifind_quantapi"
            except Exception as exc:
                _source_error(status, "ifind", exc)

        mootdx = MootdxDeepMarketService()
        deep: Dict[str, Any] = {}
        if getattr(settings, "MOOTDX_DEEP_MARKET_ENABLED", True):
            for key, fetch in (
                ("order_book", lambda: mootdx.get_order_book(code)),
                ("transactions", lambda: mootdx.get_transactions(code, limit=30)),
                ("finance_snapshot", lambda: mootdx.get_finance_snapshot(code)),
                ("f10_company", lambda: mootdx.get_f10(code, category="公司概况")),
                ("f10_latest", lambda: mootdx.get_f10(code, category="最新提示")),
            ):
                try:
                    deep[key] = fetch()
                    status[f"mootdx_{key}"] = {"ok": True, "count": len(deep[key]) if isinstance(deep[key], list) else 1}
                except Exception as exc:
                    deep[key] = [] if key in {"order_book", "transactions"} else {}
                    _source_error(status, f"mootdx_{key}", exc)
            compact["mootdx_deep"] = {
                "order_book_count": len(deep.get("order_book") or []),
                "transactions_count": len(deep.get("transactions") or []),
                "finance_fields": len(deep.get("finance_snapshot") or {}),
                "f10_categories": [key for key in ("f10_company", "f10_latest") if deep.get(key)],
            }
            compact["data_sources"]["deep_market"] = "mootdx"

        reports: List[Dict[str, Any]] = []
        if getattr(settings, "EASTMONEY_REPORTAPI_ENABLED", True):
            try:
                reports = ChinaResearchReportService().get_reports(code, limit=8)
                status["eastmoney_reports"] = {"ok": True, "count": len(reports)}
                compact["research_reports"] = {
                    "count": len(reports),
                    "latest": reports[0] if reports else None,
                    "eps_forecast": (reports[0].get("eps_forecast") if reports else None),
                }
                compact["data_sources"]["research"] = "eastmoney_reportapi"
            except Exception as exc:
                _source_error(status, "eastmoney_reports", exc)

        tags: Dict[str, Any] = {}
        if getattr(settings, "THS_TAGS_ENABLED", True):
            try:
                tags = ThemeTagService().get_tags(code, limit=20)
                status["iwencai_ths_tags"] = {
                    "ok": bool(tags.get("available")),
                    "count": len(tags.get("tags") or []),
                    "reason": tags.get("reason"),
                }
                compact["theme_tags"] = tags.get("tags") or []
                compact["data_sources"]["theme_tags"] = "iwencai_pywencai_cookie"
            except Exception as exc:
                _source_error(status, "iwencai_ths_tags", exc)

        matching_hotspots = [
            item for item in global_context.get("hotspots") or [] if _code6(item.get("symbol")) == code
        ]
        compact["hotspots"] = _limit(matching_hotspots, 5)
        if matching_hotspots:
            compact["data_sources"]["hotspots"] = "ths_hotspot_pywencai"

        news: Dict[str, Any] = {"stock_news": [], "cls_flash": [], "global_news": []}
        if getattr(settings, "AKSHARE_NEWS_ENABLED", True):
            try:
                stock_news = AkshareNewsService().get_stock_news(code, limit=12)
                news["stock_news"] = _limit(stock_news, 12)
                news["cls_flash"] = _limit(global_context.get("cls_flash") or [], 10)
                news["global_news"] = _limit(global_context.get("global_news") or [], 10)
                status["akshare_news"] = {"ok": True, "stock_news_count": len(news["stock_news"])}
                compact["news"] = {
                    "stock_news_count": len(news["stock_news"]),
                    "cls_flash_count": len(news["cls_flash"]),
                    "global_news_count": len(news["global_news"]),
                    "latest_stock_news": news["stock_news"][0] if news["stock_news"] else None,
                }
                compact["data_sources"]["news"] = "akshare_news_trio"
            except Exception as exc:
                _source_error(status, "akshare_news", exc)

        announcements: List[Dict[str, Any]] = []
        if getattr(settings, "CNINFO_ANNOUNCEMENTS_ENABLED", True):
            try:
                announcements = CninfoAnnouncementService().get_announcements(code, limit=12)
                status["cninfo_announcements"] = {"ok": True, "count": len(announcements)}
                compact["announcements"] = {
                    "count": len(announcements),
                    "latest": announcements[0] if announcements else None,
                }
                compact["data_sources"]["announcements"] = "cninfo_akshare"
            except Exception as exc:
                _source_error(status, "cninfo_announcements", exc)

        shareholders = self._fetch_shareholders_sync(code, status)
        compact["shareholders"] = {
            "top10_count": len(shareholders.get("top10") or []),
            "float_top10_count": len(shareholders.get("float_top10") or []),
            "data_source": "tushare",
        }
        compact["data_sources"]["shareholders"] = "tushare"

        return {
            "mootdx_deep": deep,
            "ifind": ifind,
            "research_reports": reports,
            "theme_tags": tags,
            "hotspots": _limit(matching_hotspots, 5),
            "news": news,
            "announcements": announcements,
            "shareholders": shareholders,
            "compact": compact,
            "source_status": status,
        }

    def _fetch_shareholders_sync(self, code: str, status: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {"top10": [], "float_top10": []}
        for scope in ("top10", "float_top10"):
            try:
                rows = fetch_tushare_shareholder_rows_sync(code, scope)
                result[scope] = _limit(rows, 30)
                status[f"tushare_{scope}"] = {"ok": True, "count": len(result[scope])}
            except Exception as exc:
                _source_error(status, f"tushare_{scope}", exc)
        return result

    async def run_weekly_favorite_analysis(self) -> Dict[str, Any]:
        refresh_result = await self.refresh_all_favorite_stock_data()
        groups = await self.list_user_favorite_groups()
        if not groups:
            return {
                "users": 0,
                "batches": 0,
                "symbols": 0,
                "refresh": refresh_result,
                "message": "没有A股自选股需要分析",
            }

        params = AnalysisParameters(
            market_type="A股",
            research_depth="深度",
            selected_analysts=["market", "fundamentals", "news", "social"],
            include_sentiment=True,
            include_risk=True,
            quick_analysis_model=settings.FAVORITE_WEEKLY_QUICK_ANALYSIS_MODEL,
            deep_analysis_model=settings.FAVORITE_WEEKLY_DEEP_ANALYSIS_MODEL,
            positive_side_model=settings.FAVORITE_WEEKLY_POSITIVE_SIDE_MODEL,
            negative_side_model=settings.FAVORITE_WEEKLY_NEGATIVE_SIDE_MODEL,
            bull_researcher_model=settings.FAVORITE_WEEKLY_POSITIVE_SIDE_MODEL,
            risky_analyst_model=settings.FAVORITE_WEEKLY_POSITIVE_SIDE_MODEL,
            bear_researcher_model=settings.FAVORITE_WEEKLY_NEGATIVE_SIDE_MODEL,
            safe_analyst_model=settings.FAVORITE_WEEKLY_NEGATIVE_SIDE_MODEL,
        )
        from app.services.analysis_service import get_analysis_service

        service = get_analysis_service()
        today = datetime.now().strftime("%Y-%m-%d")
        submitted: List[Dict[str, Any]] = []

        for group in groups:
            user_id = group["user_id"]
            if not self._analysis_user_id_supported(user_id):
                logger.warning("跳过无法提交分析任务的自选股用户ID: %s", user_id)
                continue
            codes = sorted({_code6(fav.get("stock_code")) for fav in group["favorites"] if _code6(fav.get("stock_code"))})
            for index in range(0, len(codes), 10):
                chunk = codes[index : index + 10]
                request = BatchAnalysisRequest(
                    title=f"自选股周五定时分析 {today} 第{index // 10 + 1}批",
                    description="系统每周五19:00自动发起，使用自选股数据源特色快照作为分析上下文。",
                    symbols=chunk,
                    parameters=params,
                )
                try:
                    result = await service.submit_batch_analysis(user_id, request)
                    submitted.append({"user_id": user_id, "symbols": chunk, "result": result})
                except Exception as exc:
                    logger.error("提交周五自选股分析失败 user=%s symbols=%s: %s", user_id, chunk, exc, exc_info=True)

        return {
            "users": len(groups),
            "batches": len(submitted),
            "symbols": sum(len(item["symbols"]) for item in submitted),
            "refresh": refresh_result,
            "submitted": submitted,
        }

    @staticmethod
    def _analysis_user_id_supported(user_id: str) -> bool:
        if user_id == "admin":
            return True
        try:
            ObjectId(user_id)
            return True
        except Exception:
            return False


favorite_stock_data_service = FavoriteStockDataService()
