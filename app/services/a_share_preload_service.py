#!/usr/bin/env python3
"""
A-share one-shot preload service.

Loads stock basics, last-year daily quotes, latest financial data, and a
market_quotes snapshot into MongoDB so later historical reads can stay local.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pymongo import UpdateOne

from app.core.database import get_mongo_db
from app.services.basics_sync_service import get_basics_sync_service
from app.utils.timezone import now_tz
from app.worker.tushare_sync_service import get_tushare_sync_service

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, Optional[Dict[str, Any]]], Awaitable[None]]


def utc_now_naive() -> datetime:
    """Return a naive UTC datetime for MongoDB task timestamps.

    Other analysis_tasks records are stored this way and converted to the
    configured display timezone when returned by the task-list API.
    """
    return datetime.utcnow()


class ASharePreloadService:
    """Coordinates a full A-share data warmup into MongoDB."""

    def __init__(self) -> None:
        self.db = get_mongo_db()

    async def run_preload(
        self,
        task_id: str,
        user_id: str,
        *,
        days: int = 365,
        sync_basic: bool = True,
        sync_historical: bool = True,
        sync_financial: bool = True,
        financial_limit: int = 20,
        limit_symbols: Optional[int] = None,
        history_sleep_seconds: Optional[float] = None,
        financial_sleep_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Run the preload and persist progress/results in MongoDB."""
        started_at = utc_now_naive()
        result: Dict[str, Any] = {
            "task_id": task_id,
            "days": days,
            "data_source": "tushare",
            "sync_basic": sync_basic,
            "sync_historical": sync_historical,
            "sync_financial": sync_financial,
            "financial_limit": financial_limit,
            "limit_symbols": limit_symbols,
            "history_sleep_seconds": history_sleep_seconds,
            "financial_sleep_seconds": financial_sleep_seconds,
            "basic_sync": None,
            "historical_sync": None,
            "financial_sync": None,
            "market_quotes_backfill": None,
        }

        await self._ensure_indexes()
        await self._update_task(
            task_id,
            user_id,
            status="running",
            progress=1,
            message="A股数据预热任务已启动",
            current_step="preparing",
            extra={"started_at": started_at, "result": result},
        )

        try:
            if sync_basic:
                await self._update_task(task_id, user_id, progress=5, message="正在同步A股基础数据", current_step="basic")
                result["basic_sync"] = await get_basics_sync_service().run_full_sync(force=True)
            else:
                result["basic_sync"] = {"skipped": True}

            symbols = await self._get_a_share_symbols(limit_symbols=limit_symbols)
            result["total_symbols"] = len(symbols)
            if not symbols:
                raise RuntimeError("stock_basic_info 中未找到A股股票列表，无法继续预热")

            tushare_service = await get_tushare_sync_service()
            end_date = now_tz().strftime("%Y-%m-%d")
            start_date = (now_tz() - timedelta(days=days)).strftime("%Y-%m-%d")
            result["start_date"] = start_date
            result["end_date"] = end_date

            progress_state = {"historical": -1, "financial": -1}

            async def history_progress(percent: int, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
                mapped = 10 + int(percent * 0.60)
                if mapped != progress_state["historical"] or percent >= 100:
                    progress_state["historical"] = mapped
                    await self._update_task(
                        task_id,
                        user_id,
                        progress=mapped,
                        message=message,
                        current_step="historical",
                        extra={"result": result, "progress_meta": meta or {}},
                    )

            if sync_historical:
                await self._update_task(
                    task_id,
                    user_id,
                    progress=10,
                    message=f"正在同步最近{days}天A股日线行情",
                    current_step="historical",
                )
                result["historical_sync"] = await tushare_service.sync_historical_data(
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    incremental=False,
                    all_history=False,
                    period="daily",
                    progress_callback=history_progress,
                    sleep_seconds=history_sleep_seconds,
                )
                await self._update_task(task_id, user_id, progress=72, message="正在回填最新行情快照", current_step="market_quotes")
                result["market_quotes_backfill"] = await self._backfill_market_quotes(symbols)
            else:
                result["historical_sync"] = {"skipped": True}
                result["market_quotes_backfill"] = {"skipped": True}

            async def financial_progress(percent: int, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
                mapped = 75 + int(percent * 0.20)
                if mapped != progress_state["financial"] or percent >= 100:
                    progress_state["financial"] = mapped
                    await self._update_task(
                        task_id,
                        user_id,
                        progress=mapped,
                        message=message,
                        current_step="financial",
                        extra={"result": result, "progress_meta": meta or {}},
                    )

            if sync_financial:
                await self._update_task(task_id, user_id, progress=75, message="正在同步A股财务数据", current_step="financial")
                result["financial_sync"] = await tushare_service.sync_financial_data(
                    symbols=symbols,
                    limit=financial_limit,
                    progress_callback=financial_progress,
                    sleep_seconds=financial_sleep_seconds,
                )
            else:
                result["financial_sync"] = {"skipped": True}

            completed_at = utc_now_naive()
            result["completed_at"] = completed_at
            result["execution_time"] = (completed_at - started_at).total_seconds()

            await self._update_task(
                task_id,
                user_id,
                status="completed",
                progress=100,
                message="A股数据预热完成，历史行情后续将直接读取MongoDB",
                current_step="completed",
                extra={"completed_at": completed_at, "result": result, "execution_time": result["execution_time"]},
            )
            logger.info("✅ A股数据预热完成: task_id=%s symbols=%s", task_id, len(symbols))
            return result

        except Exception as exc:
            logger.error("❌ A股数据预热失败: %s", exc, exc_info=True)
            failed_at = utc_now_naive()
            result["error"] = str(exc)
            result["failed_at"] = failed_at
            await self._update_task(
                task_id,
                user_id,
                status="failed",
                progress=0,
                message=f"A股数据预热失败: {exc}",
                current_step="failed",
                extra={"completed_at": failed_at, "result": result, "error": str(exc)},
            )
            return result

    async def _ensure_indexes(self) -> None:
        await self.db.data_preload_tasks.create_index([("task_id", 1)], unique=True, background=True)
        await self.db.data_preload_tasks.create_index([("created_at", -1)], background=True)
        await self.db.analysis_tasks.create_index([("task_id", 1)], background=True)

    async def _get_a_share_symbols(self, limit_symbols: Optional[int] = None) -> List[str]:
        query = {
            "$and": [
                {"code": {"$regex": r"^\d{6}$"}},
                {
                    "$or": [
                        {"source": "tushare"},
                        {"sec": "stock_cn"},
                        {"category": "stock_cn"},
                        {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}},
                    ]
                },
                {
                    "$or": [
                        {"status": {"$ne": "D"}},
                        {"status": {"$exists": False}},
                    ]
                },
            ]
        }
        cursor = self.db.stock_basic_info.find(query, {"code": 1}).sort("code", 1)
        if limit_symbols:
            cursor = cursor.limit(limit_symbols)
        symbols: List[str] = []
        seen = set()
        async for doc in cursor:
            code = str(doc.get("code", "")).zfill(6)
            if len(code) == 6 and code.isdigit() and code not in seen:
                seen.add(code)
                symbols.append(code)
        return symbols

    async def _backfill_market_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        operations: List[UpdateOne] = []
        success_count = 0
        skipped_count = 0
        now = utc_now_naive()

        for symbol in symbols:
            latest_doc = await self.db.stock_daily_quotes.find_one(
                {"symbol": symbol, "period": "daily"},
                sort=[("trade_date", -1)],
            )
            if not latest_doc:
                skipped_count += 1
                continue

            quote_doc = {
                "code": symbol,
                "symbol": symbol,
                "close": latest_doc.get("close"),
                "open": latest_doc.get("open"),
                "high": latest_doc.get("high"),
                "low": latest_doc.get("low"),
                "volume": latest_doc.get("volume"),
                "amount": latest_doc.get("amount"),
                "pct_chg": latest_doc.get("pct_chg"),
                "pre_close": latest_doc.get("pre_close"),
                "trade_date": latest_doc.get("trade_date"),
                "data_source": latest_doc.get("data_source", "tushare"),
                "updated_at": now,
            }
            operations.append(UpdateOne({"code": symbol}, {"$set": quote_doc}, upsert=True))

            if len(operations) >= 500:
                result = await self.db.market_quotes.bulk_write(operations, ordered=False)
                success_count += (result.upserted_count or 0) + (result.modified_count or 0)
                operations = []

        if operations:
            result = await self.db.market_quotes.bulk_write(operations, ordered=False)
            success_count += (result.upserted_count or 0) + (result.modified_count or 0)

        return {
            "total_symbols": len(symbols),
            "success_count": success_count,
            "skipped_count": skipped_count,
        }

    async def _update_task(
        self,
        task_id: str,
        user_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        current_step: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = utc_now_naive()
        update: Dict[str, Any] = {
            "task_id": task_id,
            "user_id": user_id,
            "user": user_id,
            "task_type": "data_preload",
            "title": "A股全量数据预热",
            "stock_code": "A_SHARE_PRELOAD",
            "stock_symbol": "A_SHARE_PRELOAD",
            "stock_name": "A股全量数据预热",
            "updated_at": now,
        }
        if status is not None:
            update["status"] = status
        if progress is not None:
            update["progress"] = progress
        if message is not None:
            update["message"] = message
        if current_step is not None:
            update["current_step"] = current_step
        if extra:
            update.update(extra)

        set_on_insert = {"created_at": now}
        if "started_at" not in update:
            set_on_insert["started_at"] = now
        await self.db.analysis_tasks.update_one(
            {"task_id": task_id},
            {"$set": update, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        await self.db.data_preload_tasks.update_one(
            {"task_id": task_id},
            {"$set": update, "$setOnInsert": set_on_insert},
            upsert=True,
        )


def get_a_share_preload_service() -> ASharePreloadService:
    return ASharePreloadService()
