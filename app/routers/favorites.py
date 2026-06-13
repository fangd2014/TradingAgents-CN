"""
自选股管理API路由
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import logging

from app.routers.auth_db import get_current_user
from app.models.user import User, FavoriteStock
from app.services.favorites_service import calculate_amplitude, favorites_service
from app.core.response import ok

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/favorites", tags=["自选股管理"])


def _is_china_etf_code(stock_code: str) -> bool:
    try:
        from tradingagents.utils.stock_utils import StockUtils
        return StockUtils.is_china_etf(stock_code)
    except Exception:
        code = str(stock_code or "").strip()
        return len(code) == 6 and (
            code.startswith("159")
            or code.startswith("51")
            or code.startswith("56")
            or code.startswith("58")
        )


async def _sync_external_realtime_quotes(symbols: List[str]) -> dict:
    """通过 Tencent/mootdx 外部增强行情同步自选股到 market_quotes。"""
    if not symbols:
        return {"success_count": 0, "failed_count": 0, "symbols": []}

    from datetime import datetime
    from app.core.database import get_mongo_db
    from app.services.quotes_service import get_quotes_service

    db = get_mongo_db()
    quotes = await get_quotes_service().get_quotes(symbols)
    success_count = 0
    failed_symbols = []

    for symbol in symbols:
        code = str(symbol).zfill(6)
        quote = quotes.get(code)
        if not quote:
            failed_symbols.append(code)
            continue

        quote_doc = {
            "code": code,
            "symbol": code,
            "name": quote.get("name"),
            "market": "A股ETF" if _is_china_etf_code(code) else "A股",
            "instrument_type": "etf" if _is_china_etf_code(code) else "stock",
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
            "amplitude": calculate_amplitude(quote),
            "source": quote.get("source") or "external_quotes",
            "data_source": quote.get("source") or "external_quotes",
            "datetime": quote.get("datetime"),
            "trade_date": quote.get("trade_date"),
            "updated_at": datetime.utcnow(),
        }
        for field in ("pe_ttm", "pb", "total_mv", "float_mv", "turnover_rate", "limit_up", "limit_down"):
            if quote.get(field) is not None:
                quote_doc[field] = quote.get(field)

        await db["market_quotes"].update_one(
            {"code": code},
            {"$set": quote_doc},
            upsert=True,
        )
        success_count += 1

    return {
        "success_count": success_count,
        "failed_count": len(failed_symbols),
        "symbols": symbols,
        "failed_symbols": failed_symbols,
    }


class AddFavoriteRequest(BaseModel):
    """添加自选股请求"""
    stock_code: str
    stock_name: str
    market: str = "A股"
    tags: List[str] = []
    notes: str = ""
    alert_price_high: Optional[float] = None
    alert_price_low: Optional[float] = None


class UpdateFavoriteRequest(BaseModel):
    """更新自选股请求"""
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    alert_price_high: Optional[float] = None
    alert_price_low: Optional[float] = None


class FavoriteStockResponse(BaseModel):
    """自选股响应"""
    stock_code: str
    stock_name: str
    market: str
    added_at: str
    tags: List[str]
    notes: str
    alert_price_high: Optional[float]
    alert_price_low: Optional[float]
    # 实时数据
    current_price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None


@router.get("/", response_model=dict)
async def get_favorites(
    current_user: dict = Depends(get_current_user)
):
    """获取用户自选股列表"""
    try:
        favorites = await favorites_service.get_user_favorites(current_user["id"])
        return ok(favorites)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取自选股失败: {str(e)}"
        )


@router.post("/", response_model=dict)
async def add_favorite(
    request: AddFavoriteRequest,
    current_user: dict = Depends(get_current_user)
):
    """添加股票到自选股"""
    import logging
    logger = logging.getLogger("webapi")

    try:
        logger.info(f"📝 添加自选股请求: user_id={current_user['id']}, stock_code={request.stock_code}, stock_name={request.stock_name}")

        # 检查是否已存在
        is_fav = await favorites_service.is_favorite(current_user["id"], request.stock_code)
        logger.info(f"🔍 检查是否已存在: {is_fav}")

        if is_fav:
            logger.warning(f"⚠️ 股票已在自选股中: {request.stock_code}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该股票已在自选股中"
            )

        # 添加到自选股
        logger.info(f"➕ 开始添加自选股...")
        success = await favorites_service.add_favorite(
            user_id=current_user["id"],
            stock_code=request.stock_code,
            stock_name=request.stock_name,
            market=request.market,
            tags=request.tags,
            notes=request.notes,
            alert_price_high=request.alert_price_high,
            alert_price_low=request.alert_price_low
        )

        logger.info(f"✅ 添加结果: success={success}")

        if success:
            return ok({"stock_code": request.stock_code}, "添加成功")
        else:
            logger.error(f"❌ 添加失败: success=False")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="添加失败"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加自选股失败: {str(e)}"
        )


@router.put("/{stock_code}", response_model=dict)
async def update_favorite(
    stock_code: str,
    request: UpdateFavoriteRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新自选股信息"""
    try:
        success = await favorites_service.update_favorite(
            user_id=current_user["id"],
            stock_code=stock_code,
            tags=request.tags,
            notes=request.notes,
            alert_price_high=request.alert_price_high,
            alert_price_low=request.alert_price_low
        )

        if success:
            return ok({"stock_code": stock_code}, "更新成功")
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="自选股不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新自选股失败: {str(e)}"
        )


@router.delete("/{stock_code}", response_model=dict)
async def remove_favorite(
    stock_code: str,
    current_user: dict = Depends(get_current_user)
):
    """从自选股中移除股票"""
    try:
        success = await favorites_service.remove_favorite(current_user["id"], stock_code)

        if success:
            return ok({"stock_code": stock_code}, "移除成功")
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="自选股不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"移除自选股失败: {str(e)}"
        )


@router.get("/check/{stock_code}", response_model=dict)
async def check_favorite(
    stock_code: str,
    current_user: dict = Depends(get_current_user)
):
    """检查股票是否在自选股中"""
    try:
        is_favorite = await favorites_service.is_favorite(current_user["id"], stock_code)
        return ok({"stock_code": stock_code, "is_favorite": is_favorite})
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"检查自选股状态失败: {str(e)}"
        )


@router.get("/tags", response_model=dict)
async def get_user_tags(
    current_user: dict = Depends(get_current_user)
):
    """获取用户使用的所有标签"""
    try:
        tags = await favorites_service.get_user_tags(current_user["id"])
        return ok(tags)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取标签失败: {str(e)}"
        )


class SyncFavoritesRequest(BaseModel):
    """同步自选股实时行情请求"""
    data_source: str = "external_quotes"


@router.post("/sync-realtime", response_model=dict)
async def sync_favorites_realtime(
    request: SyncFavoritesRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    同步自选股实时行情

    - **data_source**: 数据源，固定使用 external_quotes (Tencent/mootdx)
    """
    try:
        logger.info(f"📊 开始同步自选股实时行情: user_id={current_user['id']}, data_source={request.data_source}")

        # 获取用户自选股列表
        favorites = await favorites_service.get_user_favorites(current_user["id"])

        if not favorites:
            logger.info("⚠️ 用户没有自选股")
            return ok({
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "message": "没有自选股需要同步"
            })

        # 提取股票代码列表
        symbols = [fav.get("stock_code") or fav.get("symbol") for fav in favorites]
        symbols = [s for s in symbols if s]  # 过滤空值

        logger.info(f"🎯 需要同步的股票: {len(symbols)} 只 - {symbols}")

        if request.data_source != "external_quotes":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="自选股实时行情固定使用 external_quotes (Tencent/mootdx)，不再调用 Tushare/AKShare 行情",
            )

        logger.info("🔄 调用 external_quotes 同步服务...")
        sync_result = await _sync_external_realtime_quotes(symbols)

        success_count = sync_result.get("success_count", 0)
        failed_count = sync_result.get("failed_count", 0)
        etf_symbols = [s for s in symbols if _is_china_etf_code(s)]
        stock_symbols = [s for s in symbols if s not in etf_symbols]

        logger.info(f"✅ 自选股实时行情同步完成: 成功 {success_count}/{len(symbols)} 只")

        return ok({
            "total": len(symbols),
            "success_count": success_count,
            "failed_count": failed_count,
            "symbols": symbols,
            "etf_symbols": etf_symbols,
            "stock_symbols": stock_symbols,
            "data_source": request.data_source,
            "failed_symbols": sync_result.get("failed_symbols", []),
            "message": f"同步完成: 成功 {success_count} 只，失败 {failed_count} 只"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 同步自选股实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"同步失败: {str(e)}"
        )


@router.post("/enrich-latest-sources", response_model=dict)
async def enrich_favorites_latest_sources(
    current_user: dict = Depends(get_current_user)
):
    """用 Tencent/mootdx 最新行情指标补全当前用户自选股信息。"""
    try:
        result = await favorites_service.enrich_user_favorites_latest_sources(current_user["id"])
        return ok(result, message=result.get("message", "自选股信息补全完成"))
    except Exception as e:
        logger.error(f"❌ 自选股信息补全失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"补全失败: {str(e)}"
        )
