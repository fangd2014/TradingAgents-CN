"""
QuotesService: 提供A股批量实时快照获取（AKShare东方财富 spot 接口），带内存TTL缓存。
- 不使用通达信（TDX）作为兜底数据源。
- 仅用于筛选返回前对 items 进行行情富集。
"""
from __future__ import annotations

import asyncio
import time
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        # 处理字符串中的逗号/百分号/空白
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if s.endswith("%"):
                s = s[:-1]
            if s == "-" or s == "":
                return None
            return float(s)
        # 处理 pandas/numpy 数值
        return float(v)
    except Exception:
        return None


def _normalize_cn_code(code_raw) -> str:
    code_str = str(code_raw).strip()
    if code_str.isdigit():
        code_clean = code_str.lstrip("0") or "0"
        return code_clean.zfill(6)
    return code_str.zfill(6)


def _pick_column(columns, candidates: List[str]) -> Optional[str]:
    return next((c for c in candidates if c in columns), None)


class QuotesService:
    def __init__(self, ttl_seconds: int = 30) -> None:
        self._ttl = ttl_seconds
        self._cache_ts: float = 0.0
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_quotes(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """获取一批股票的近实时快照（最新价、涨跌幅、成交额）。
        - 优先使用缓存；缓存超时或为空则刷新一次全市场快照。
        - 返回仅包含请求的 codes。
        """
        codes = [c.strip() for c in codes if c]
        now = time.time()
        async with self._lock:
            if self._cache and (now - self._cache_ts) < self._ttl:
                return {c: q for c, q in self._cache.items() if c in codes and q}
            # 刷新缓存（阻塞IO放到线程）
            data = await asyncio.to_thread(self._fetch_spot_akshare)
            self._cache = data
            self._cache_ts = time.time()
            return {c: q for c, q in self._cache.items() if c in codes and q}

    def _fetch_spot_akshare(self) -> Dict[str, Dict[str, Any]]:
        """拉取A股与A股ETF实时快照，并标准化为字典。"""
        result = self._fetch_stock_spot_akshare()
        etf_result = self._fetch_etf_spot_akshare()
        result.update(etf_result)
        logger.info(f"AKShare spot 拉取完成: 股票/ETF合计 {len(result)} 条")
        return result

    def _fetch_stock_spot_akshare(self) -> Dict[str, Dict[str, Any]]:
        """通过 AKShare 东方财富A股快照接口拉取行情，并标准化为字典。"""
        try:
            import akshare as ak  # 已在项目中使用，不额外安装
            df = ak.stock_zh_a_spot_em()
            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare A股 spot 返回空数据")
                return {}
            # 兼容常见列名
            code_col = _pick_column(df.columns, ["代码", "代码code", "symbol", "股票代码"])
            name_col = _pick_column(df.columns, ["名称", "股票名称", "name"])
            price_col = _pick_column(df.columns, ["最新价", "现价", "最新价(元)", "price", "最新"])
            pct_col = _pick_column(df.columns, ["涨跌幅", "涨跌幅(%)", "涨幅", "pct_chg"])
            amount_col = _pick_column(df.columns, ["成交额", "成交额(元)", "amount", "成交额(万元)"])
            volume_col = _pick_column(df.columns, ["成交量", "volume", "vol"])

            if not code_col or not price_col:
                logger.error(f"AKShare A股 spot 缺少必要列: code={code_col}, price={price_col}")
                return {}

            result: Dict[str, Dict[str, Any]] = {}
            for _, row in df.iterrows():  # type: ignore
                code_raw = row.get(code_col)
                if not code_raw:
                    continue
                code = _normalize_cn_code(code_raw)
                close = _safe_float(row.get(price_col))
                pct = _safe_float(row.get(pct_col)) if pct_col else None
                amt = _safe_float(row.get(amount_col)) if amount_col else None
                volume = _safe_float(row.get(volume_col)) if volume_col else None
                result[code] = {
                    "close": close,
                    "pct_chg": pct,
                    "amount": amt,
                    "volume": volume,
                    "name": row.get(name_col) if name_col else None,
                    "market": "A股",
                    "instrument_type": "stock",
                    "source": "akshare_stock_spot_em",
                }
            logger.info(f"AKShare A股 spot 拉取完成: {len(result)} 条")
            return result
        except Exception as e:
            logger.error(f"获取AKShare A股实时快照失败: {e}")
            return {}

    def _fetch_etf_spot_akshare(self) -> Dict[str, Dict[str, Any]]:
        """通过 AKShare 东方财富场内ETF快照接口拉取行情，并标准化为字典。"""
        try:
            import akshare as ak  # 已在项目中使用，不额外安装
            df = ak.fund_etf_spot_em()
            if df is None or getattr(df, "empty", True):
                logger.warning("AKShare ETF spot 返回空数据")
                return {}

            code_col = _pick_column(df.columns, ["代码", "基金代码", "symbol", "代码代码"])
            name_col = _pick_column(df.columns, ["名称", "基金名称", "基金简称", "name"])
            price_col = _pick_column(df.columns, ["最新价", "现价", "市价", "最新价(元)", "price", "最新"])
            pct_col = _pick_column(df.columns, ["涨跌幅", "涨跌幅(%)", "涨幅", "增长率", "pct_chg"])
            amount_col = _pick_column(df.columns, ["成交额", "成交额(元)", "amount", "成交额(万元)"])
            volume_col = _pick_column(df.columns, ["成交量", "volume", "vol"])

            if not code_col or not price_col:
                logger.error(f"AKShare ETF spot 缺少必要列: code={code_col}, price={price_col}")
                return {}

            result: Dict[str, Dict[str, Any]] = {}
            for _, row in df.iterrows():  # type: ignore
                code_raw = row.get(code_col)
                if not code_raw:
                    continue
                code = _normalize_cn_code(code_raw)
                result[code] = {
                    "close": _safe_float(row.get(price_col)),
                    "pct_chg": _safe_float(row.get(pct_col)) if pct_col else None,
                    "amount": _safe_float(row.get(amount_col)) if amount_col else None,
                    "volume": _safe_float(row.get(volume_col)) if volume_col else None,
                    "name": row.get(name_col) if name_col else None,
                    "market": "A股ETF",
                    "instrument_type": "etf",
                    "source": "akshare_fund_etf_spot_em",
                }
            logger.info(f"AKShare ETF spot 拉取完成: {len(result)} 条")
            return result
        except Exception as e:
            logger.error(f"获取AKShare ETF实时快照失败: {e}")
            return {}


_quotes_service: Optional[QuotesService] = None


def get_quotes_service() -> QuotesService:
    global _quotes_service
    if _quotes_service is None:
        _quotes_service = QuotesService(ttl_seconds=30)
    return _quotes_service
