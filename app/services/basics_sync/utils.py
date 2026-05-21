"""
与 Tushare 相关的阻塞式工具函数：
- fetch_stock_basic_df：获取股票列表（确保 Tushare 已连接）
- find_latest_trade_date：探测最近可用交易日（YYYYMMDD）
- fetch_daily_basic_mv_map：根据交易日获取日度基础指标映射（市值/估值/交易）
"""
from __future__ import annotations
from datetime import datetime, timedelta
import logging
from typing import Dict


logger = logging.getLogger(__name__)


def _recent_report_periods(now: datetime) -> list[str]:
    """Return recent financial report periods, newest first."""
    quarter_dates: list[str] = []
    for year in (now.year, now.year - 1):
        quarter_dates.extend(
            [
                f"{year}1231",
                f"{year}0930",
                f"{year}0630",
                f"{year}0331",
            ]
        )
    today_text = now.strftime("%Y%m%d")
    return [date for date in quarter_dates if date <= today_text]


def _safe_float(value) -> float | None:
    if value is None or str(value).strip().lower() in {"", "nan", "none"}:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed != parsed:
        return None
    return parsed


def fetch_stock_basic_df():
    """
    从 Tushare 获取股票基础列表（DataFrame格式），要求已正确配置并连接。
    依赖环境变量：TUSHARE_ENABLED=true 且 .env 中提供 TUSHARE_TOKEN。

    注意：这是一个同步函数，会等待 Tushare 连接完成。
    """
    import time
    import logging
    from tradingagents.dataflows.providers.china.tushare import get_tushare_provider
    from app.core.config import settings

    logger = logging.getLogger(__name__)

    # 检查 Tushare 是否启用
    if not settings.TUSHARE_ENABLED:
        logger.error("❌ Tushare 数据源已禁用 (TUSHARE_ENABLED=false)")
        logger.error("💡 请在 .env 文件中设置 TUSHARE_ENABLED=true 或使用多数据源同步服务")
        raise RuntimeError(
            "Tushare is disabled (TUSHARE_ENABLED=false). "
            "Set TUSHARE_ENABLED=true in .env or use MultiSourceBasicsSyncService."
        )

    provider = get_tushare_provider()

    # 等待连接完成（最多等待 5 秒）
    max_wait_seconds = 5
    wait_interval = 0.1
    elapsed = 0.0

    logger.info(f"⏳ 等待 Tushare 连接...")
    while not getattr(provider, "connected", False) and elapsed < max_wait_seconds:
        if elapsed == 0.0:
            try:
                provider.connect_sync()
            except Exception as exc:
                logger.warning(f"⚠️ Tushare 主动连接失败，继续等待: {exc}")
        time.sleep(wait_interval)
        elapsed += wait_interval

    # 检查连接状态和API可用性
    if not getattr(provider, "connected", False) or provider.api is None:
        logger.error(f"❌ Tushare 连接失败（等待 {max_wait_seconds}s 后超时）")
        logger.error(f"💡 请检查：")
        logger.error(f"   1. .env 文件中配置了有效的 TUSHARE_TOKEN")
        logger.error(f"   2. Tushare Token 未过期且有足够的积分")
        logger.error(f"   3. 网络连接正常")
        raise RuntimeError(
            f"Tushare not connected after waiting {max_wait_seconds}s. "
            "Check TUSHARE_TOKEN in .env and ensure it's valid."
        )

    logger.info(f"✅ Tushare 已连接，开始获取股票列表...")

    # 直接调用 Tushare API 获取 DataFrame
    try:
        df = provider.api.stock_basic(
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market,exchange,list_date,is_hs'
        )

        # 🔧 增强错误诊断
        if df is None:
            logger.error(f"❌ Tushare API 返回 None")
            logger.error(f"💡 可能原因：")
            logger.error(f"   1. Tushare Token 无效或过期")
            logger.error(f"   2. API 积分不足")
            logger.error(f"   3. 网络连接问题")
            raise RuntimeError("Tushare API returned None. Check token validity and API credits.")

        if hasattr(df, 'empty') and df.empty:
            logger.error(f"❌ Tushare API 返回空 DataFrame")
            logger.error(f"💡 可能原因：")
            logger.error(f"   1. list_status='L' 参数可能不正确")
            logger.error(f"   2. Tushare 数据源暂时不可用")
            logger.error(f"   3. API 调用限制（请检查积分和调用频率）")
            raise RuntimeError("Tushare API returned empty DataFrame. Check API parameters and data availability.")

        logger.info(f"✅ 成功获取 {len(df)} 条股票数据")
        return df

    except Exception as e:
        logger.error(f"❌ 调用 Tushare API 失败: {e}")
        raise RuntimeError(f"Failed to fetch stock basic DataFrame: {e}")


def find_latest_trade_date() -> str:
    """
    探测最近可用的交易日（YYYYMMDD）。
    - 从今天起回溯最多 5 天；
    - 如都不可用，回退为昨天日期。
    """
    from tradingagents.dataflows.providers.china.tushare import get_tushare_provider

    provider = get_tushare_provider()
    api = provider.api
    if api is None:
        raise RuntimeError("Tushare API unavailable")

    today = datetime.now()
    for delta in range(0, 6):
        d = (today - timedelta(days=delta)).strftime("%Y%m%d")
        try:
            db = api.daily_basic(trade_date=d, fields="ts_code,total_mv")
            if db is not None and not db.empty:
                return d
        except Exception:
            continue
    return (today - timedelta(days=1)).strftime("%Y%m%d")


def fetch_daily_basic_mv_map(trade_date: str) -> Dict[str, Dict[str, float]]:
    """
    根据交易日获取日度基础指标映射。
    覆盖字段：total_mv/circ_mv/pe/pb/ps/turnover_rate/volume_ratio/pe_ttm/pb_mrq/ps_ttm
    """
    from tradingagents.dataflows.providers.china.tushare import get_tushare_provider

    provider = get_tushare_provider()
    api = provider.api
    if api is None:
        raise RuntimeError("Tushare API unavailable")

    # 🔥 新增：添加 ps、ps_ttm、total_share、float_share 字段
    fields = "ts_code,total_mv,circ_mv,pe,pb,ps,turnover_rate,volume_ratio,pe_ttm,pb_mrq,ps_ttm,total_share,float_share"
    db = api.daily_basic(trade_date=trade_date, fields=fields)

    data_map: Dict[str, Dict[str, float]] = {}
    if db is not None and not db.empty:
        for _, row in db.iterrows():  # type: ignore
            ts_code = row.get("ts_code")
            if ts_code is not None:
                try:
                    metrics = {}
                    # 🔥 新增：添加 ps、ps_ttm、total_share、float_share 到字段列表
                    for field in [
                        "total_mv",
                        "circ_mv",
                        "pe",
                        "pb",
                        "ps",
                        "turnover_rate",
                        "volume_ratio",
                        "pe_ttm",
                        "pb_mrq",
                        "ps_ttm",
                        "total_share",
                        "float_share",
                    ]:
                        value = row.get(field)
                        if value is not None and str(value).lower() not in ["nan", "none", ""]:
                            metrics[field] = float(value)
                    if metrics:
                        data_map[str(ts_code)] = metrics
                except Exception:
                    pass
    return data_map




def fetch_latest_roe_map() -> Dict[str, Dict[str, float]]:
    """
    获取最近一个可用财报期的财务指标映射。

    返回格式为 ts_code -> 指标字典，包含 ROE、毛利率、净利率、
    资产负债率、营收同比、净利润同比等行业对比需要的字段。
    优先按最近季度的 end_date 逆序探测，找到第一期非空数据。
    """
    from tradingagents.dataflows.providers.china.tushare import get_tushare_provider

    candidates = _recent_report_periods(datetime.now())
    data_map: Dict[str, Dict[str, float]] = {}

    try:
        provider = get_tushare_provider()
        api = provider.api
        if api is None:
            raise RuntimeError("Tushare API unavailable")

        for end_date in candidates:
            try:
                fields = (
                    "ts_code,end_date,roe,roe_waa,grossprofit_margin,netprofit_margin,"
                    "debt_to_assets,or_yoy,netprofit_yoy,profit_dedt_yoy,dt_netprofit_yoy"
                )
                df = api.fina_indicator(end_date=end_date, fields=fields)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():  # type: ignore
                        ts_code = row.get("ts_code")
                        if ts_code is None:
                            continue
                        metrics: Dict[str, float] = {
                            "financial_indicator_period": str(row.get("end_date") or end_date)
                        }
                        for field in [
                            "roe",
                            "roe_waa",
                            "grossprofit_margin",
                            "netprofit_margin",
                            "debt_to_assets",
                            "or_yoy",
                            "netprofit_yoy",
                            "profit_dedt_yoy",
                            "dt_netprofit_yoy",
                        ]:
                            value = _safe_float(row.get(field))
                            if value is not None:
                                metrics[field] = value
                        if len(metrics) > 1:
                            data_map[str(ts_code)] = metrics
                    if data_map:
                        return data_map  # 找到最近一期即可
            except Exception as exc:
                logger.warning("Tushare fina_indicator 获取 %s 失败: %s", end_date, exc)
                continue
    except Exception as exc:
        logger.warning("Tushare 财务指标快照不可用，尝试 AkShare 降级: %s", exc)

    return fetch_latest_akshare_indicator_map(candidates)


def fetch_latest_akshare_indicator_map(candidates: list[str] | None = None) -> Dict[str, Dict[str, float]]:
    """
    使用 AkShare 东方财富业绩/资产负债表快照补充行业对比财务指标。

    字段映射：
    - 净资产收益率 -> roe
    - 销售毛利率 -> grossprofit_margin
    - 净利润 / 营业总收入 -> netprofit_margin
    - 营业总收入-同比增长 -> or_yoy / revenue_yoy
    - 净利润-同比增长 -> netprofit_yoy
    - 资产负债率 -> debt_to_assets
    """
    import akshare as ak

    data_map: Dict[str, Dict[str, float]] = {}
    report_periods = candidates or _recent_report_periods(datetime.now())

    for end_date in report_periods:
        try:
            yjbb_df = ak.stock_yjbb_em(date=end_date)
            if yjbb_df is None or yjbb_df.empty:
                continue

            for _, row in yjbb_df.iterrows():  # type: ignore
                raw_code = row.get("股票代码")
                code = str(raw_code or "").zfill(6)
                if not code:
                    continue
                ts_code = f"{code}.SH" if code.startswith(("6", "9")) else f"{code}.SZ"
                metrics: Dict[str, float] = {
                    "financial_indicator_period": end_date,
                    "financial_indicator_source": "akshare_stock_yjbb_em",
                }

                field_map = {
                    "roe": row.get("净资产收益率"),
                    "grossprofit_margin": row.get("销售毛利率"),
                    "or_yoy": row.get("营业总收入-同比增长"),
                    "revenue_yoy": row.get("营业总收入-同比增长"),
                    "netprofit_yoy": row.get("净利润-同比增长"),
                    "profit_dedt_yoy": row.get("净利润-同比增长"),
                }
                for field, raw_value in field_map.items():
                    value = _safe_float(raw_value)
                    if value is not None:
                        metrics[field] = value

                net_profit = _safe_float(row.get("净利润-净利润"))
                revenue = _safe_float(row.get("营业总收入-营业总收入"))
                if net_profit is not None and revenue not in (None, 0):
                    metrics["netprofit_margin"] = net_profit / revenue * 100

                if len(metrics) > 2:
                    data_map[ts_code] = metrics

            try:
                balance_df = ak.stock_zcfz_em(date=end_date)
                if balance_df is not None and not balance_df.empty:
                    for _, row in balance_df.iterrows():  # type: ignore
                        raw_code = row.get("股票代码")
                        code = str(raw_code or "").zfill(6)
                        if not code:
                            continue
                        ts_code = f"{code}.SH" if code.startswith(("6", "9")) else f"{code}.SZ"
                        debt_to_assets = _safe_float(row.get("资产负债率"))
                        if debt_to_assets is not None:
                            data_map.setdefault(
                                ts_code,
                                {
                                    "financial_indicator_period": end_date,
                                    "financial_indicator_source": "akshare_stock_zcfz_em",
                                },
                            )
                            data_map[ts_code]["debt_to_assets"] = debt_to_assets
                            data_map[ts_code].setdefault("financial_indicator_source", "akshare_stock_yjbb_em")
            except Exception as exc:
                logger.warning("AkShare stock_zcfz_em 获取 %s 失败: %s", end_date, exc)

            if data_map:
                return data_map
        except Exception as exc:
            logger.warning("AkShare stock_yjbb_em 获取 %s 失败: %s", end_date, exc)
            continue

    return data_map
