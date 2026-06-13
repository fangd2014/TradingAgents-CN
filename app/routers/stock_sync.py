"""
股票数据同步API路由
支持单个股票或批量股票的历史数据和财务数据同步
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import uuid

from app.routers.auth_db import get_current_user
from app.core.response import ok
from app.core.database import get_mongo_db
from app.worker.tushare_sync_service import get_tushare_sync_service
from app.worker.akshare_sync_service import get_akshare_sync_service
from app.worker.financial_data_sync_service import get_financial_sync_service
from app.services.a_share_preload_service import get_a_share_preload_service
from app.utils.timezone import to_config_tz
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/stock-sync", tags=["股票数据同步"])

AUTO_REALTIME_SOURCES = ["external_quotes"]
AUTO_HISTORICAL_SOURCES = ["mootdx", "tushare", "akshare"]
AUTO_FINANCIAL_SOURCES = ["mootdx", "tushare", "akshare"]
AUTO_BASIC_SOURCES = ["mootdx_tencent", "tushare", "akshare"]


def _source_plan(requested_source: str, priority: List[str]) -> List[str]:
    requested = str(requested_source or "auto").strip().lower()
    if requested in {"auto", "latest", "latest_sources", "external_quotes"}:
        return list(priority)
    return [requested]


def _first_value(row: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _is_china_etf_code(symbol: str) -> bool:
    try:
        from tradingagents.utils.stock_utils import StockUtils
        return StockUtils.is_china_etf(symbol)
    except Exception:
        code = str(symbol or "").strip()
        return len(code) == 6 and (
            code.startswith("159")
            or code.startswith("51")
            or code.startswith("56")
            or code.startswith("58")
        )


def _serialize_task_timezones(value):
    """Serialize MongoDB datetimes as configured timezone ISO strings."""
    if isinstance(value, datetime):
        converted = to_config_tz(value)
        return converted.isoformat() if converted else None
    if isinstance(value, dict):
        return {key: _serialize_task_timezones(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_task_timezones(item) for item in value]
    return value


async def _sync_etf_latest_to_market_quotes(symbol: str) -> dict:
    """同步单只A股ETF实时行情到 market_quotes。"""
    from app.services.quotes_service import get_quotes_service

    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)
    quote = (await get_quotes_service().get_quotes([symbol6])).get(symbol6)
    if not quote:
        return {"success": False, "error": "未找到ETF实时行情"}

    quote_doc = {
        "code": symbol6,
        "symbol": symbol6,
        "name": quote.get("name"),
        "market": "A股ETF",
        "instrument_type": "etf",
        "close": quote.get("close"),
        "price": quote.get("close"),
        "current_price": quote.get("close"),
        "pct_chg": quote.get("pct_chg"),
        "change_percent": quote.get("pct_chg"),
        "amount": quote.get("amount"),
        "volume": quote.get("volume"),
        "data_source": quote.get("source") or "akshare_fund_etf_spot_em",
        "updated_at": datetime.utcnow(),
    }
    await db.market_quotes.update_one(
        {"code": symbol6},
        {"$set": quote_doc},
        upsert=True,
    )
    return {"success": True, "quote": quote_doc}


async def _sync_latest_to_market_quotes(symbol: str) -> None:
    """
    将 stock_daily_quotes 中的最新数据同步到 market_quotes

    智能判断逻辑：
    - 如果 market_quotes 中已有更新的数据（trade_date 更新），则不覆盖
    - 如果 market_quotes 中没有数据或数据较旧，则更新

    Args:
        symbol: 股票代码（6位）
    """
    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)

    # 从 stock_daily_quotes 获取最新数据
    latest_doc = await db.stock_daily_quotes.find_one(
        {"symbol": symbol6},
        sort=[("trade_date", -1)]
    )

    if not latest_doc:
        logger.warning(f"⚠️ {symbol6}: stock_daily_quotes 中没有数据")
        return

    historical_trade_date = latest_doc.get("trade_date")

    # 🔥 检查 market_quotes 中是否已有更新的数据
    existing_quote = await db.market_quotes.find_one({"code": symbol6})

    if existing_quote:
        existing_trade_date = existing_quote.get("trade_date")

        # 如果 market_quotes 中的数据日期更新或相同，则不覆盖
        if existing_trade_date and historical_trade_date:
            # 比较日期字符串（格式：YYYY-MM-DD 或 YYYYMMDD）
            existing_date_str = str(existing_trade_date).replace("-", "")
            historical_date_str = str(historical_trade_date).replace("-", "")

            if existing_date_str >= historical_date_str:
                # 🔥 日期相同或更新时，都不覆盖（避免用历史数据覆盖实时数据）
                logger.info(
                    f"⏭️ {symbol6}: market_quotes 中的数据日期 >= 历史数据日期 "
                    f"(market_quotes: {existing_trade_date}, historical: {historical_trade_date})，跳过覆盖"
                )
                return

    # 提取需要的字段
    quote_data = {
        "code": symbol6,
        "symbol": symbol6,
        "close": latest_doc.get("close"),
        "open": latest_doc.get("open"),
        "high": latest_doc.get("high"),
        "low": latest_doc.get("low"),
        "volume": latest_doc.get("volume"),  # 已经转换过单位
        "amount": latest_doc.get("amount"),  # 已经转换过单位
        "pct_chg": latest_doc.get("pct_chg"),
        "pre_close": latest_doc.get("pre_close"),
        "trade_date": latest_doc.get("trade_date"),
        "updated_at": datetime.utcnow()
    }

    # 🔥 日志：记录同步的成交量
    logger.info(
        f"📊 [同步到market_quotes] {symbol6} - "
        f"volume={quote_data['volume']}, amount={quote_data['amount']}, trade_date={quote_data['trade_date']}"
    )

    # 更新 market_quotes
    await db.market_quotes.update_one(
        {"code": symbol6},
        {"$set": quote_data},
        upsert=True
    )


async def _sync_external_quote_to_market_quotes(symbol: str) -> Dict[str, Any]:
    from app.services.quotes_service import get_quotes_service

    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)
    quote = (await get_quotes_service().get_quotes([symbol6])).get(symbol6)
    if not quote:
        return {"success": False, "error": "external_quotes 未返回实时行情"}

    quote_doc = {
        "code": symbol6,
        "symbol": symbol6,
        "name": quote.get("name"),
        "market": "A股ETF" if _is_china_etf_code(symbol6) else "A股",
        "instrument_type": "etf" if _is_china_etf_code(symbol6) else "stock",
        "close": quote.get("close"),
        "price": quote.get("close"),
        "current_price": quote.get("close"),
        "pct_chg": quote.get("pct_chg"),
        "change_percent": quote.get("pct_chg"),
        "amount": quote.get("amount"),
        "volume": quote.get("volume"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "pre_close": quote.get("pre_close"),
        "source": quote.get("source") or "external_quotes",
        "data_source": quote.get("source") or "external_quotes",
        "updated_at": datetime.utcnow(),
    }
    for field in ("pe_ttm", "pb", "total_mv", "float_mv", "turnover_rate", "limit_up", "limit_down"):
        if quote.get(field) is not None:
            quote_doc[field] = quote.get(field)

    await db.market_quotes.update_one(
        {"code": symbol6},
        {"$set": quote_doc},
        upsert=True,
    )
    return {"success": True, "quote": quote_doc, "records": 1}


async def _sync_mootdx_historical_to_db(symbol: str, days: int) -> Dict[str, Any]:
    from app.services.china_external_data_service import MootdxDeepMarketService

    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)
    limit = max(1, min(int(days or 30), 1000))
    rows = await asyncio.to_thread(MootdxDeepMarketService().get_kline, symbol6, "day", limit)
    if not rows:
        return {"success": False, "error": "mootdx 未返回K线数据", "records": 0}

    saved = 0
    for row in rows:
        raw_date = _first_value(row, ["datetime", "date", "trade_date", "time"])
        trade_date = str(raw_date or "").split(" ")[0]
        if not trade_date:
            continue
        doc = {
            "symbol": symbol6,
            "code": symbol6,
            "trade_date": trade_date,
            "period": "daily",
            "open": _safe_float(_first_value(row, ["open", "开盘"])),
            "high": _safe_float(_first_value(row, ["high", "最高"])),
            "low": _safe_float(_first_value(row, ["low", "最低"])),
            "close": _safe_float(_first_value(row, ["close", "收盘", "price"])),
            "volume": _safe_float(_first_value(row, ["volume", "vol", "成交量"])),
            "amount": _safe_float(_first_value(row, ["amount", "成交额"])),
            "data_source": "mootdx",
            "source": "mootdx",
            "updated_at": datetime.utcnow(),
            "raw_data": row,
        }
        await db.stock_daily_quotes.update_one(
            {"symbol": symbol6, "trade_date": trade_date, "period": "daily", "data_source": "mootdx"},
            {"$set": doc},
            upsert=True,
        )
        saved += 1

    return {"success": saved > 0, "records": saved, "message": f"mootdx同步了 {saved} 条K线"}


async def _sync_mootdx_financial_to_db(symbol: str) -> Dict[str, Any]:
    from app.services.china_external_data_service import MootdxDeepMarketService

    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)
    snapshot = await asyncio.to_thread(MootdxDeepMarketService().get_finance_snapshot, symbol6)
    if not snapshot:
        return {"success": False, "error": "mootdx 未返回财务快照"}

    report_period = str(_first_value(snapshot, ["report_period", "报告期", "date", "datetime"]) or datetime.utcnow().strftime("%Y%m%d"))
    doc = {
        "symbol": symbol6,
        "code": symbol6,
        "market": "A股",
        "data_source": "mootdx",
        "source": "mootdx",
        "report_period": report_period,
        "report_type": "snapshot",
        "raw_data": snapshot,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    for key, value in snapshot.items():
        if isinstance(key, str) and key not in doc:
            doc[key] = value

    await db.stock_financial_data.update_one(
        {"symbol": symbol6, "data_source": "mootdx", "report_period": report_period, "report_type": "snapshot"},
        {"$set": doc},
        upsert=True,
    )
    return {"success": True, "records": 1, "message": "mootdx财务快照同步成功"}


async def _sync_latest_basic_to_db(symbol: str) -> Dict[str, Any]:
    from app.services.china_external_data_service import ChinaQuoteService, MootdxDeepMarketService

    db = get_mongo_db()
    symbol6 = str(symbol).zfill(6)
    quote = await asyncio.to_thread(ChinaQuoteService().get_quotes, [symbol6])
    quote_data = quote.get(symbol6) if isinstance(quote, dict) else {}
    finance = await asyncio.to_thread(MootdxDeepMarketService().get_finance_snapshot, symbol6)
    if not quote_data and not finance:
        return {"success": False, "error": "mootdx/腾讯未返回基础或指标数据"}

    doc = {
        "code": symbol6,
        "symbol": symbol6,
        "name": (quote_data or {}).get("name"),
        "source": "mootdx_tencent",
        "data_source": "mootdx_tencent",
        "sse": "上海证券交易所" if symbol6.startswith(("60", "68", "90")) else "深圳证券交易所",
        "market": "ETF" if _is_china_etf_code(symbol6) else "-",
        "updated_at": datetime.utcnow(),
    }
    for field in ("pe_ttm", "pb", "total_mv", "float_mv", "turnover_rate", "limit_up", "limit_down"):
        if (quote_data or {}).get(field) is not None:
            doc[field] = quote_data.get(field)
    if finance:
        doc["finance_snapshot"] = finance

    await db.stock_basic_info.update_one(
        {"code": symbol6, "source": "mootdx_tencent"},
        {"$set": doc},
        upsert=True,
    )
    return {"success": True, "records": 1, "message": "mootdx/腾讯基础信息同步成功"}


class SingleStockSyncRequest(BaseModel):
    """单股票同步请求"""
    symbol: str = Field(..., description="股票代码（6位）")
    sync_realtime: bool = Field(False, description="是否同步实时行情")
    sync_historical: bool = Field(True, description="是否同步历史数据")
    sync_financial: bool = Field(True, description="是否同步财务数据")
    sync_basic: bool = Field(False, description="是否同步基础数据")
    data_source: str = Field("auto", description="数据源: auto按优先级尝试，或指定 tushare/akshare/mootdx")
    days: int = Field(30, description="历史数据天数", ge=1, le=3650)


class BatchStockSyncRequest(BaseModel):
    """批量股票同步请求"""
    symbols: List[str] = Field(..., description="股票代码列表")
    sync_historical: bool = Field(True, description="是否同步历史数据")
    sync_financial: bool = Field(True, description="是否同步财务数据")
    sync_basic: bool = Field(False, description="是否同步基础数据")
    data_source: str = Field("auto", description="数据源: auto按优先级尝试，或指定 tushare/akshare/mootdx")
    days: int = Field(30, description="历史数据天数", ge=1, le=3650)


class ASharePreloadRequest(BaseModel):
    """A股全量数据预热请求"""
    days: int = Field(365, description="行情数据回溯天数", ge=1, le=3650)
    sync_basic: bool = Field(True, description="是否同步基础数据")
    sync_historical: bool = Field(True, description="是否同步历史行情")
    sync_financial: bool = Field(True, description="是否同步财务数据")
    financial_limit: int = Field(20, description="财务数据期数", ge=1, le=80)
    limit_symbols: Optional[int] = Field(None, description="调试用：限制同步股票数量", ge=1, le=6000)
    history_sleep_seconds: Optional[float] = Field(
        None,
        description="历史行情每只股票请求后的休眠秒数；为空时按数据源配置的调用频率自动计算",
        ge=0,
        le=30,
    )
    financial_sleep_seconds: Optional[float] = Field(
        None,
        description="财务数据每只股票请求后的休眠秒数；为空时按数据源配置的调用频率自动计算",
        ge=0,
        le=30,
    )


@router.post("/single")
async def sync_single_stock(
    request: SingleStockSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    同步单个股票的历史数据、财务数据和实时行情

    - **symbol**: 股票代码（6位）
    - **sync_realtime**: 是否同步实时行情
    - **sync_historical**: 是否同步历史数据
    - **sync_financial**: 是否同步财务数据
    - **data_source**: 数据源（tushare/akshare）
    - **days**: 历史数据天数
    """
    try:
        logger.info(f"📊 开始同步单个股票: {request.symbol} (数据源: {request.data_source})")

        result = {
            "symbol": request.symbol,
            "realtime_sync": None,
            "historical_sync": None,
            "financial_sync": None,
            "basic_sync": None
        }
        is_china_etf = _is_china_etf_code(request.symbol)

        # 同步实时行情
        if request.sync_realtime:
            try:
                attempted_sources = []
                realtime_result = None
                for source in _source_plan(request.data_source, AUTO_REALTIME_SOURCES):
                    attempted_sources.append(source)
                    if source != "external_quotes":
                        realtime_result = {"success": False, "error": f"实时行情不支持数据源 {source}"}
                        continue
                    realtime_result = await _sync_external_quote_to_market_quotes(request.symbol)
                    if realtime_result.get("success"):
                        break

                db = get_mongo_db()
                latest_quote = await db.market_quotes.find_one(
                    {"code": str(request.symbol).zfill(6)},
                    {"_id": 0, "code": 1, "trade_date": 1, "updated_at": 1, "close": 1, "data_source": 1, "source": 1}
                )
                success = bool(realtime_result and realtime_result.get("success"))
                result["realtime_sync"] = {
                    "success": success,
                    "message": f"实时行情同步{'成功' if success else '失败'}",
                    "data_source_used": "external_quotes" if success else None,
                    "attempted_sources": attempted_sources,
                    "market_quote_available": latest_quote is not None,
                    "market_quote_snapshot": latest_quote,
                    "error": None if success else (realtime_result or {}).get("error"),
                }
                logger.info(f"✅ {request.symbol} 实时行情同步完成: {success}, attempted={attempted_sources}")

            except Exception as e:
                logger.error(f"❌ {request.symbol} 实时行情同步失败: {e}")
                result["realtime_sync"] = {
                    "success": False,
                    "error": str(e)
                }
        
        # 同步历史数据
        if request.sync_historical and not is_china_etf:
            try:
                attempted_sources = []
                errors = {}
                hist_result = None
                data_source_used = None
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=request.days)).strftime('%Y-%m-%d')

                for source in _source_plan(request.data_source, AUTO_HISTORICAL_SOURCES):
                    attempted_sources.append(source)
                    try:
                        if source == "mootdx":
                            candidate = await _sync_mootdx_historical_to_db(request.symbol, request.days)
                            if candidate.get("success"):
                                hist_result = {"success_count": 1, "total_records": candidate.get("records", 0)}
                                data_source_used = source
                                break
                            errors[source] = candidate.get("error") or "mootdx返回空数据"
                            continue

                        if source == "tushare":
                            service = await get_tushare_sync_service()
                        elif source == "akshare":
                            service = await get_akshare_sync_service()
                        else:
                            errors[source] = f"不支持的数据源: {source}"
                            continue

                        candidate = await service.sync_historical_data(
                            symbols=[request.symbol],
                            start_date=start_date,
                            end_date=end_date,
                            incremental=False
                        )
                        if candidate.get("success_count", 0) > 0:
                            hist_result = candidate
                            data_source_used = source
                            break
                        errors[source] = candidate.get("error") or candidate.get("errors") or "未同步到历史数据"
                    except Exception as source_exc:
                        errors[source] = str(source_exc)

                success = bool(hist_result and hist_result.get("success_count", 0) > 0)
                result["historical_sync"] = {
                    "success": success,
                    "records": (hist_result or {}).get("total_records", 0),
                    "message": f"同步了 {(hist_result or {}).get('total_records', 0)} 条历史记录" if success else "历史数据同步失败",
                    "data_source_used": data_source_used,
                    "attempted_sources": attempted_sources,
                    "errors": errors,
                }
                logger.info(f"✅ {request.symbol} 历史数据同步完成: {result['historical_sync']}")

                # 🔥 同步最新历史数据到 market_quotes
                if success:
                    try:
                        await _sync_latest_to_market_quotes(request.symbol)
                        logger.info(f"✅ {request.symbol} 最新数据已同步到 market_quotes")
                    except Exception as e:
                        logger.warning(f"⚠️ {request.symbol} 同步到 market_quotes 失败: {e}")

                # 🔥 【已禁用】如果没有勾选实时行情，但在交易时间内，自动同步实时行情
                # 用户反馈：不希望自动同步实时行情，应该严格按照用户的选择
                # if not request.sync_realtime:
                #     from app.utils.trading_time import is_trading_time
                #     if is_trading_time():
                #         logger.info(f"📊 {request.symbol} 当前在交易时间内，自动同步实时行情")
                #         try:
                #             realtime_result = await service.sync_realtime_quotes(
                #                 symbols=[request.symbol],
                #                 force=True
                #             )
                #             if realtime_result.get("success_count", 0) > 0:
                #                 logger.info(f"✅ {request.symbol} 实时行情自动同步成功")
                #                 result["realtime_sync"] = {
                #                     "success": True,
                #                     "message": "实时行情自动同步成功（交易时间内）"
                #                 }
                #         except Exception as e:
                #             logger.warning(f"⚠️ {request.symbol} 实时行情自动同步失败: {e}")

            except Exception as e:
                logger.error(f"❌ {request.symbol} 历史数据同步失败: {e}")
                result["historical_sync"] = {
                    "success": False,
                    "error": str(e)
                }
        
        # 同步财务数据
        if request.sync_financial and not is_china_etf:
            try:
                attempted_sources = []
                errors = {}
                success = False
                data_source_used = None

                for source in _source_plan(request.data_source, AUTO_FINANCIAL_SOURCES):
                    attempted_sources.append(source)
                    try:
                        if source == "mootdx":
                            candidate = await _sync_mootdx_financial_to_db(request.symbol)
                            if candidate.get("success"):
                                success = True
                                data_source_used = source
                                break
                            errors[source] = candidate.get("error") or "mootdx未返回财务快照"
                            continue

                        if source not in {"tushare", "akshare"}:
                            errors[source] = f"不支持的数据源: {source}"
                            continue

                        financial_service = await get_financial_sync_service()
                        candidate = await financial_service.sync_single_stock(
                            symbol=request.symbol,
                            data_sources=[source]
                        )
                        if candidate.get(source, False):
                            success = True
                            data_source_used = source
                            break
                        errors[source] = candidate.get("error") or "财务同步未成功"
                    except Exception as source_exc:
                        errors[source] = str(source_exc)

                result["financial_sync"] = {
                    "success": success,
                    "message": "财务数据同步成功" if success else "财务数据同步失败",
                    "data_source_used": data_source_used,
                    "attempted_sources": attempted_sources,
                    "errors": errors,
                }
                logger.info(f"✅ {request.symbol} 财务数据同步完成: {result['financial_sync']}")
                
            except Exception as e:
                logger.error(f"❌ {request.symbol} 财务数据同步失败: {e}")
                result["financial_sync"] = {
                    "success": False,
                    "error": str(e)
                }

        # 同步基础数据
        if request.sync_basic:
            try:
                # 🔥 同步单个股票的基础数据
                # 参考 basics_sync_service 的实现逻辑
                if str(request.data_source or "auto").lower() in {"auto", "latest", "latest_sources", "external_quotes"}:
                    attempted_sources = []
                    errors = {}
                    success = False
                    data_source_used = None

                    for source in AUTO_BASIC_SOURCES:
                        attempted_sources.append(source)
                        try:
                            if source == "mootdx_tencent":
                                candidate = await _sync_latest_basic_to_db(request.symbol)
                                if candidate.get("success"):
                                    success = True
                                    data_source_used = source
                                    break
                                errors[source] = candidate.get("error") or "mootdx/腾讯未返回基础数据"
                                continue

                            # 旧同步分支很重，auto 模式下只作为显式错误提示，不自动全量抓取。
                            errors[source] = "低优先级旧基础源未在auto模式自动触发"
                        except Exception as source_exc:
                            errors[source] = str(source_exc)

                    result["basic_sync"] = {
                        "success": success,
                        "message": "基础数据同步成功" if success else "基础数据同步失败",
                        "data_source_used": data_source_used,
                        "attempted_sources": attempted_sources,
                        "errors": errors,
                    }
                    logger.info(f"✅ {request.symbol} 基础数据同步完成: {result['basic_sync']}")

                elif request.data_source == "tushare":
                    from app.services.basics_sync import (
                        fetch_stock_basic_df,
                        find_latest_trade_date,
                        fetch_daily_basic_mv_map,
                        fetch_latest_roe_map,
                    )

                    db = get_mongo_db()
                    symbol6 = str(request.symbol).zfill(6)

                    # Step 1: 获取股票基础信息
                    stock_df = await asyncio.to_thread(fetch_stock_basic_df)
                    if stock_df is None or stock_df.empty:
                        result["basic_sync"] = {
                            "success": False,
                            "error": "Tushare 返回空数据"
                        }
                    else:
                        # 筛选出目标股票
                        stock_row = None
                        for _, row in stock_df.iterrows():
                            ts_code = row.get("ts_code", "")
                            if isinstance(ts_code, str) and ts_code.startswith(symbol6):
                                stock_row = row
                                break

                        if stock_row is None:
                            result["basic_sync"] = {
                                "success": False,
                                "error": f"未找到股票 {symbol6} 的基础信息"
                            }
                        else:
                            # Step 2: 获取最新交易日和财务指标
                            latest_trade_date = await asyncio.to_thread(find_latest_trade_date)
                            daily_data_map = await asyncio.to_thread(fetch_daily_basic_mv_map, latest_trade_date)
                            roe_map = await asyncio.to_thread(fetch_latest_roe_map)

                            # Step 3: 构建文档（参考 basics_sync_service 的逻辑）
                            # 🔥 先获取当前时间，避免作用域问题
                            now_iso = datetime.utcnow().isoformat()

                            name = stock_row.get("name") or ""
                            area = stock_row.get("area") or ""
                            industry = stock_row.get("industry") or ""
                            market = stock_row.get("market") or ""
                            list_date = stock_row.get("list_date") or ""
                            ts_code = stock_row.get("ts_code") or ""

                            # 提取6位代码
                            if isinstance(ts_code, str) and "." in ts_code:
                                code = ts_code.split(".")[0]
                            else:
                                code = symbol6

                            # 判断交易所
                            if isinstance(ts_code, str):
                                if ts_code.endswith(".SH"):
                                    sse = "上海证券交易所"
                                elif ts_code.endswith(".SZ"):
                                    sse = "深圳证券交易所"
                                elif ts_code.endswith(".BJ"):
                                    sse = "北京证券交易所"
                                else:
                                    sse = "未知"
                            else:
                                sse = "未知"

                            # 生成 full_symbol
                            full_symbol = ts_code

                            # 提取财务指标
                            daily_metrics = {}
                            if isinstance(ts_code, str) and ts_code in daily_data_map:
                                daily_metrics = daily_data_map[ts_code]

                            # 市值转换（万元 -> 亿元）
                            total_mv_yi = None
                            circ_mv_yi = None
                            if "total_mv" in daily_metrics:
                                try:
                                    total_mv_yi = float(daily_metrics["total_mv"]) / 10000.0
                                except Exception:
                                    pass
                            if "circ_mv" in daily_metrics:
                                try:
                                    circ_mv_yi = float(daily_metrics["circ_mv"]) / 10000.0
                                except Exception:
                                    pass

                            # 构建文档
                            doc = {
                                "code": code,
                                "symbol": code,
                                "name": name,
                                "area": area,
                                "industry": industry,
                                "market": market,
                                "list_date": list_date,
                                "sse": sse,
                                "sec": "stock_cn",
                                "source": "tushare",
                                "updated_at": now_iso,
                                "full_symbol": full_symbol,
                            }

                            # 添加市值
                            if total_mv_yi is not None:
                                doc["total_mv"] = total_mv_yi
                            if circ_mv_yi is not None:
                                doc["circ_mv"] = circ_mv_yi

                            # 添加估值指标
                            for field in ["pe", "pb", "ps", "pe_ttm", "pb_mrq", "ps_ttm"]:
                                if field in daily_metrics:
                                    doc[field] = daily_metrics[field]

                            # 添加财务指标快照
                            if isinstance(ts_code, str) and ts_code in roe_map:
                                for field, value in roe_map[ts_code].items():
                                    if value is not None:
                                        doc[field] = value

                            # 添加交易指标
                            for field in ["turnover_rate", "volume_ratio"]:
                                if field in daily_metrics:
                                    doc[field] = daily_metrics[field]

                            # 添加股本信息
                            for field in ["total_share", "float_share"]:
                                if field in daily_metrics:
                                    doc[field] = daily_metrics[field]

                            # Step 4: 更新数据库
                            await db.stock_basic_info.update_one(
                                {"code": code, "source": "tushare"},
                                {"$set": doc},
                                upsert=True
                            )

                            result["basic_sync"] = {
                                "success": True,
                                "message": "基础数据同步成功"
                            }
                            logger.info(f"✅ {request.symbol} 基础数据同步完成")

                elif request.data_source == "akshare":
                    # 🔥 AKShare 数据源的基础数据同步
                    db = get_mongo_db()
                    symbol6 = str(request.symbol).zfill(6)

                    # 获取 AKShare 同步服务
                    service = await get_akshare_sync_service()

                    # 获取股票基础信息
                    basic_info = await service.provider.get_stock_basic_info(symbol6)

                    if basic_info:
                        # 转换为字典格式
                        if hasattr(basic_info, 'model_dump'):
                            basic_data = basic_info.model_dump()
                        elif hasattr(basic_info, 'dict'):
                            basic_data = basic_info.dict()
                        else:
                            basic_data = basic_info

                        # 确保必要字段
                        basic_data["code"] = symbol6
                        basic_data["symbol"] = symbol6
                        basic_data["source"] = "akshare"
                        basic_data["updated_at"] = datetime.utcnow().isoformat()

                        # 更新到数据库
                        await db.stock_basic_info.update_one(
                            {"code": symbol6, "source": "akshare"},
                            {"$set": basic_data},
                            upsert=True
                        )

                        result["basic_sync"] = {
                            "success": True,
                            "message": "基础数据同步成功"
                        }
                        logger.info(f"✅ {request.symbol} 基础数据同步完成 (AKShare)")
                    else:
                        result["basic_sync"] = {
                            "success": False,
                            "error": "未获取到基础数据"
                        }
                else:
                    result["basic_sync"] = {
                        "success": False,
                        "error": f"基础数据同步仅支持 Tushare/AKShare 数据源，当前数据源: {request.data_source}"
                    }

            except Exception as e:
                logger.error(f"❌ {request.symbol} 基础数据同步失败: {e}")
                result["basic_sync"] = {
                    "success": False,
                    "error": str(e)
                }

        # 判断整体是否成功
        overall_success = (
            (not request.sync_realtime or bool(result["realtime_sync"] and result["realtime_sync"].get("success", False))) and
            (not request.sync_historical or bool(result["historical_sync"] and result["historical_sync"].get("success", False))) and
            (not request.sync_financial or bool(result["financial_sync"] and result["financial_sync"].get("success", False))) and
            (not request.sync_basic or bool(result["basic_sync"] and result["basic_sync"].get("success", False)))
        )

        # 添加整体成功标志到结果中
        result["overall_success"] = overall_success

        logger.info("📋 单股同步汇总 %s: %s", request.symbol, result)

        return ok(
            data=result,
            message=f"股票 {request.symbol} 数据同步{'成功' if overall_success else '部分失败'}"
        )
        
    except Exception as e:
        logger.error(f"❌ 同步单个股票失败: {e}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.post("/batch")
async def sync_batch_stocks(
    request: BatchStockSyncRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    批量同步多个股票的历史数据和财务数据
    
    - **symbols**: 股票代码列表
    - **sync_historical**: 是否同步历史数据
    - **sync_financial**: 是否同步财务数据
    - **data_source**: 数据源（tushare/akshare）
    - **days**: 历史数据天数
    """
    try:
        logger.info(f"📊 开始批量同步 {len(request.symbols)} 只股票 (数据源: {request.data_source})")
        
        result = {
            "total": len(request.symbols),
            "symbols": request.symbols,
            "historical_sync": None,
            "financial_sync": None,
            "basic_sync": None
        }
        
        # 同步历史数据
        if request.sync_historical:
            try:
                attempted_sources = []
                errors = {}
                source_results = {}
                remaining_symbols = [str(symbol).zfill(6) for symbol in request.symbols]
                total_records = 0
                success_symbols = set()
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=request.days)).strftime('%Y-%m-%d')

                for source in _source_plan(request.data_source, AUTO_HISTORICAL_SOURCES):
                    if not remaining_symbols:
                        break
                    attempted_sources.append(source)
                    try:
                        if source == "mootdx":
                            source_success = 0
                            source_records = 0
                            still_remaining = []
                            for symbol in remaining_symbols:
                                candidate = await _sync_mootdx_historical_to_db(symbol, request.days)
                                if candidate.get("success"):
                                    source_success += 1
                                    source_records += candidate.get("records", 0)
                                    success_symbols.add(symbol)
                                else:
                                    still_remaining.append(symbol)
                            remaining_symbols = still_remaining
                            total_records += source_records
                            source_results[source] = {"success_count": source_success, "total_records": source_records}
                            continue

                        if source == "tushare":
                            service = await get_tushare_sync_service()
                        elif source == "akshare":
                            service = await get_akshare_sync_service()
                        else:
                            errors[source] = f"不支持的数据源: {source}"
                            continue

                        candidate = await service.sync_historical_data(
                            symbols=remaining_symbols,
                            start_date=start_date,
                            end_date=end_date,
                            incremental=False
                        )
                        source_success = candidate.get("success_count", 0)
                        total_records += candidate.get("total_records", 0)
                        source_results[source] = candidate
                        if source_success > 0:
                            success_symbols.update(remaining_symbols[:source_success])
                            if source_success >= len(remaining_symbols):
                                remaining_symbols = []
                            else:
                                remaining_symbols = remaining_symbols[source_success:]
                        else:
                            errors[source] = candidate.get("error") or candidate.get("errors") or "未同步到历史数据"
                    except Exception as source_exc:
                        errors[source] = str(source_exc)
                
                result["historical_sync"] = {
                    "success_count": len(success_symbols),
                    "error_count": len(request.symbols) - len(success_symbols),
                    "total_records": total_records,
                    "attempted_sources": attempted_sources,
                    "source_results": source_results,
                    "errors": errors,
                    "message": f"成功同步 {len(success_symbols)}/{len(request.symbols)} 只股票，共 {total_records} 条记录"
                }
                logger.info(f"✅ 批量历史数据同步完成: {result['historical_sync']}")
                
            except Exception as e:
                logger.error(f"❌ 批量历史数据同步失败: {e}")
                result["historical_sync"] = {
                    "success_count": 0,
                    "error_count": len(request.symbols),
                    "error": str(e)
                }
        
        # 同步财务数据
        if request.sync_financial:
            try:
                attempted_sources = []
                errors = {}
                source_results = {}
                remaining_symbols = [str(symbol).zfill(6) for symbol in request.symbols]
                success_symbols = set()

                for source in _source_plan(request.data_source, AUTO_FINANCIAL_SOURCES):
                    if not remaining_symbols:
                        break
                    attempted_sources.append(source)
                    try:
                        if source == "mootdx":
                            source_success = 0
                            still_remaining = []
                            for symbol in remaining_symbols:
                                candidate = await _sync_mootdx_financial_to_db(symbol)
                                if candidate.get("success"):
                                    source_success += 1
                                    success_symbols.add(symbol)
                                else:
                                    still_remaining.append(symbol)
                            remaining_symbols = still_remaining
                            source_results[source] = {"success_count": source_success}
                            continue

                        if source not in {"tushare", "akshare"}:
                            errors[source] = f"不支持的数据源: {source}"
                            continue

                        financial_service = await get_financial_sync_service()
                        fin_results = await financial_service.sync_financial_data(
                            symbols=remaining_symbols,
                            data_sources=[source],
                            batch_size=10
                        )
                        source_stats = fin_results.get(source)
                        if source_stats:
                            source_success = source_stats.success_count
                            source_results[source] = {
                                "success_count": source_stats.success_count,
                                "error_count": source_stats.error_count,
                                "total_symbols": source_stats.total_symbols,
                            }
                            if source_success > 0:
                                success_symbols.update(remaining_symbols[:source_success])
                                remaining_symbols = remaining_symbols[source_success:]
                        else:
                            errors[source] = "财务数据同步失败"
                    except Exception as source_exc:
                        errors[source] = str(source_exc)

                result["financial_sync"] = {
                    "success_count": len(success_symbols),
                    "error_count": len(request.symbols) - len(success_symbols),
                    "total_symbols": len(request.symbols),
                    "attempted_sources": attempted_sources,
                    "source_results": source_results,
                    "errors": errors,
                    "message": f"成功同步 {len(success_symbols)}/{len(request.symbols)} 只股票的财务数据"
                }
                logger.info(f"✅ 批量财务数据同步完成: {result['financial_sync']['success_count']}/{len(request.symbols)}")
                
            except Exception as e:
                logger.error(f"❌ 批量财务数据同步失败: {e}")
                result["financial_sync"] = {
                    "success_count": 0,
                    "error_count": len(request.symbols),
                    "error": str(e)
                }

        # 同步基础数据
        if request.sync_basic:
            try:
                # 🔥 批量同步基础数据
                # 注意：基础数据同步服务目前只支持 Tushare 数据源
                if str(request.data_source or "auto").lower() in {"auto", "latest", "latest_sources", "external_quotes"}:
                    attempted_sources = list(AUTO_BASIC_SOURCES)
                    errors = {}
                    success_count = 0
                    error_count = 0

                    for symbol in request.symbols:
                        candidate = await _sync_latest_basic_to_db(symbol)
                        if candidate.get("success"):
                            success_count += 1
                        else:
                            error_count += 1
                            errors[str(symbol).zfill(6)] = candidate.get("error") or "基础数据同步失败"

                    result["basic_sync"] = {
                        "success_count": success_count,
                        "error_count": error_count,
                        "total_symbols": len(request.symbols),
                        "attempted_sources": attempted_sources,
                        "data_source_used": "mootdx_tencent" if success_count else None,
                        "errors": errors,
                        "message": f"成功同步 {success_count}/{len(request.symbols)} 只股票的基础数据"
                    }
                    logger.info(f"✅ 批量基础数据同步完成: {result['basic_sync']}")

                elif request.data_source == "tushare":
                    from tradingagents.dataflows.providers.china.tushare import TushareProvider

                    tushare_provider = TushareProvider()
                    if tushare_provider.is_available():
                        success_count = 0
                        error_count = 0

                        for symbol in request.symbols:
                            try:
                                basic_info = await tushare_provider.get_stock_basic_info(symbol)

                                if basic_info:
                                    # 保存到 MongoDB
                                    db = get_mongo_db()
                                    symbol6 = str(symbol).zfill(6)

                                    # 添加必要字段
                                    basic_info["code"] = symbol6
                                    basic_info["source"] = "tushare"
                                    basic_info["updated_at"] = datetime.utcnow()

                                    await db.stock_basic_info.update_one(
                                        {"code": symbol6, "source": "tushare"},
                                        {"$set": basic_info},
                                        upsert=True
                                    )

                                    success_count += 1
                                    logger.info(f"✅ {symbol} 基础数据同步成功")
                                else:
                                    error_count += 1
                                    logger.warning(f"⚠️ {symbol} 未获取到基础数据")
                            except Exception as e:
                                error_count += 1
                                logger.error(f"❌ {symbol} 基础数据同步失败: {e}")

                        result["basic_sync"] = {
                            "success_count": success_count,
                            "error_count": error_count,
                            "total_symbols": len(request.symbols),
                            "message": f"成功同步 {success_count}/{len(request.symbols)} 只股票的基础数据"
                        }
                        logger.info(f"✅ 批量基础数据同步完成: {success_count}/{len(request.symbols)}")
                    else:
                        result["basic_sync"] = {
                            "success_count": 0,
                            "error_count": len(request.symbols),
                            "error": "Tushare 数据源不可用"
                        }
                else:
                    result["basic_sync"] = {
                        "success_count": 0,
                        "error_count": len(request.symbols),
                        "error": f"基础数据同步仅支持 Tushare 数据源，当前数据源: {request.data_source}"
                    }

            except Exception as e:
                logger.error(f"❌ 批量基础数据同步失败: {e}")
                result["basic_sync"] = {
                    "success_count": 0,
                    "error_count": len(request.symbols),
                    "error": str(e)
                }

        # 判断整体是否成功
        hist_success = result["historical_sync"].get("success_count", 0) if request.sync_historical else 0
        fin_success = result["financial_sync"].get("success_count", 0) if request.sync_financial else 0
        basic_success = result["basic_sync"].get("success_count", 0) if request.sync_basic else 0
        total_success = max(hist_success, fin_success, basic_success)

        # 添加统计信息到结果中
        result["total_success"] = total_success
        result["total_symbols"] = len(request.symbols)

        return ok(
            data=result,
            message=f"批量同步完成: {total_success}/{len(request.symbols)} 只股票成功"
        )
        
    except Exception as e:
        logger.error(f"❌ 批量同步失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量同步失败: {str(e)}")


@router.post("/preload-a-share")
async def preload_a_share_data(
    request: ASharePreloadRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    一次性预热A股全市场数据到MongoDB。

    后台依次同步：
    - stock_basic_info：基础数据和估值基础指标
    - stock_daily_quotes：最近 N 天日线行情
    - stock_financial_data：财务数据
    - market_quotes：由最新日线回填行情快照
    """
    try:
        task_id = str(uuid.uuid4())
        user_id = str(current_user.get("id") or current_user.get("_id") or current_user.get("username") or "admin")
        service = get_a_share_preload_service()

        # 先写入任务，让任务中心和状态接口马上可见。
        await service._update_task(
            task_id,
            user_id,
            status="running",
            progress=1,
            message="A股数据预热任务已提交，等待后台执行",
            current_step="queued",
            extra={
                "parameters": request.model_dump(),
            },
        )

        background_tasks.add_task(
            service.run_preload,
            task_id,
            user_id,
            days=request.days,
            sync_basic=request.sync_basic,
            sync_historical=request.sync_historical,
            sync_financial=request.sync_financial,
            financial_limit=request.financial_limit,
            limit_symbols=request.limit_symbols,
            history_sleep_seconds=request.history_sleep_seconds,
            financial_sleep_seconds=request.financial_sleep_seconds,
        )

        return ok(
            data={
                "task_id": task_id,
                "status": "running",
                "task_type": "data_preload",
                "parameters": request.model_dump(),
            },
            message="A股全量数据预热任务已添加到任务中心"
        )
    except Exception as e:
        logger.error(f"❌ 创建A股预热任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建A股预热任务失败: {str(e)}")


@router.get("/preload-a-share/{task_id}")
async def get_preload_a_share_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """查询A股预热任务状态。"""
    try:
        db = get_mongo_db()
        task = await db.data_preload_tasks.find_one({"task_id": task_id}, {"_id": 0})
        if not task:
            task = await db.analysis_tasks.find_one({"task_id": task_id}, {"_id": 0})
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return ok(data=_serialize_task_timezones(task))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询A股预热任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询A股预热任务失败: {str(e)}")


@router.get("/status/{symbol}")
async def get_sync_status(
    symbol: str,
    current_user: dict = Depends(get_current_user)
):
    """
    获取股票的同步状态
    
    返回最后同步时间、数据条数等信息
    """
    try:
        from app.core.database import get_mongo_db
        
        db = get_mongo_db()
        
        symbol6 = str(symbol).zfill(6)

        # 查询历史数据最后同步时间
        hist_doc = await db.stock_daily_quotes.find_one(
            {"symbol": symbol6, "period": "daily"},
            sort=[("trade_date", -1)]
        )
        
        # 查询财务数据最后同步时间
        fin_doc = await db.stock_financial_data.find_one(
            {"symbol": symbol6},
            sort=[("updated_at", -1)]
        )
        
        # 统计历史数据条数
        hist_count = await db.stock_daily_quotes.count_documents({"symbol": symbol6, "period": "daily"})
        
        # 统计财务数据条数
        fin_count = await db.stock_financial_data.count_documents({"symbol": symbol6})
        
        return ok(data={
            "symbol": symbol6,
            "historical_data": {
                "last_sync": hist_doc.get("updated_at") if hist_doc else None,
                "last_date": hist_doc.get("trade_date") if hist_doc else None,
                "total_records": hist_count
            },
            "financial_data": {
                "last_sync": fin_doc.get("updated_at") if fin_doc else None,
                "last_report_period": fin_doc.get("report_period") if fin_doc else None,
                "total_records": fin_count
            }
        })
        
    except Exception as e:
        logger.error(f"❌ 获取同步状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取同步状态失败: {str(e)}")
