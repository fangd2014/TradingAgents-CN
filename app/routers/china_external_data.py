"""
China external data API routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.china_external_data_service import (
    AkshareNewsService,
    CninfoAnnouncementService,
    ChinaQuoteService,
    ChinaResearchReportService,
    EastmoneyReportApiClient,
    MootdxDeepMarketService,
    SemanticSearchService,
    THSHotspotService,
    ThemeTagService,
    get_source_availability,
)

router = APIRouter(prefix="/api/china-data", tags=["china-data"])


@router.get("/source-status", response_model=dict)
async def source_status(current_user: dict = Depends(get_current_user)):
    return ok(
        data={"sources": get_source_availability()},
        message="中国外部数据源状态查询成功",
    )


@router.get("/quotes", response_model=dict)
async def get_quotes(
    codes: str = Query(..., description="逗号分隔的股票代码，例如 000001,600000"),
    current_user: dict = Depends(get_current_user),
):
    code_list = [code.strip() for code in codes.split(",") if code.strip()]
    quotes = ChinaQuoteService().get_quotes(code_list)
    return ok(
        data={"codes": code_list, "total_count": len(quotes), "quotes": quotes},
        message=f"获取行情成功，返回 {len(quotes)} 条",
    )


@router.get("/mootdx/{symbol}/order-book", response_model=dict)
async def mootdx_order_book(
    symbol: str,
    current_user: dict = Depends(get_current_user),
):
    items = MootdxDeepMarketService().get_order_book(symbol)
    return ok(data={"symbol": symbol, "items": items}, message="mootdx盘口查询完成")


@router.get("/mootdx/{symbol}/kline", response_model=dict)
async def mootdx_kline(
    symbol: str,
    period: str = Query("day", description="day/week/month/5m/15m/30m/60m"),
    limit: int = Query(120, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    items = MootdxDeepMarketService().get_kline(symbol, period=period, limit=limit)
    return ok(data={"symbol": symbol, "period": period, "items": items}, message="mootdx K线查询完成")


@router.get("/mootdx/{symbol}/transactions", response_model=dict)
async def mootdx_transactions(
    symbol: str,
    start: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
    current_user: dict = Depends(get_current_user),
):
    items = MootdxDeepMarketService().get_transactions(symbol, start=start, limit=limit)
    return ok(data={"symbol": symbol, "items": items}, message="mootdx逐笔成交查询完成")


@router.get("/mootdx/{symbol}/finance", response_model=dict)
async def mootdx_finance(
    symbol: str,
    current_user: dict = Depends(get_current_user),
):
    data = MootdxDeepMarketService().get_finance_snapshot(symbol)
    return ok(data={"symbol": symbol, "finance": data}, message="mootdx财务快照查询完成")


@router.get("/mootdx/{symbol}/f10", response_model=dict)
async def mootdx_f10(
    symbol: str,
    category: str = Query("公司概况"),
    current_user: dict = Depends(get_current_user),
):
    data = MootdxDeepMarketService().get_f10(symbol, category=category)
    return ok(data=data, message="mootdx F10查询完成")


@router.get("/research-reports/{symbol}", response_model=dict)
async def get_research_reports(
    symbol: str,
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    reports = ChinaResearchReportService().get_reports(symbol, limit=limit)
    return ok(
        data={"symbol": symbol, "total_count": len(reports), "reports": reports},
        message=f"获取研报成功，返回 {len(reports)} 条",
    )


@router.get("/research-reports/{symbol}/pdf-meta", response_model=dict)
async def get_report_pdf_meta(
    symbol: str,
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    reports = EastmoneyReportApiClient().list_reports(symbol, limit=limit)
    return ok(
        data={"symbol": symbol, "reports": [{"title": r["title"], "pdf_url": r["pdf_url"]} for r in reports]},
        message="研报PDF元数据查询完成",
    )


@router.get("/semantic-search", response_model=dict)
async def semantic_search(
    q: str = Query(..., description="i问财自然语言查询"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    result = SemanticSearchService().search(q, limit=limit)
    return ok(data=result, message="语义搜索完成")


@router.get("/hotspots", response_model=dict)
async def hotspots(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    current_user: dict = Depends(get_current_user),
):
    result = THSHotspotService().get_hotspots(limit=limit)
    return ok(data=result, message="同花顺热点归因查询完成")


@router.get("/theme-tags/{symbol}", response_model=dict)
async def theme_tags(
    symbol: str,
    limit: int = Query(20, ge=1, le=100, description="问财返回行数限制"),
    current_user: dict = Depends(get_current_user),
):
    result = ThemeTagService().get_tags(symbol, limit=limit)
    return ok(data=result, message="题材tags查询完成")


@router.get("/news/{symbol}", response_model=dict)
async def stock_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    items = AkshareNewsService().get_stock_news(symbol, limit=limit)
    return ok(data={"symbol": symbol, "items": items}, message="个股新闻查询完成")


@router.get("/news/cls-flash/latest", response_model=dict)
async def cls_flash(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    items = AkshareNewsService().get_cls_flash(limit=limit)
    return ok(data={"items": items}, message="财联社快讯查询完成")


@router.get("/news/global/latest", response_model=dict)
async def global_news(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    items = AkshareNewsService().get_global_news(limit=limit)
    return ok(data={"items": items}, message="全球资讯查询完成")


@router.get("/announcements/{symbol}", response_model=dict)
async def announcements(
    symbol: str,
    keyword: str = Query(""),
    category: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    items = CninfoAnnouncementService().get_announcements(
        symbol,
        keyword=keyword,
        category=category,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return ok(data={"symbol": symbol, "items": items}, message="巨潮公告查询完成")
