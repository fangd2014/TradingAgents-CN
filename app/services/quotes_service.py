"""
QuotesService: 提供A股批量实时快照获取，带内存TTL缓存。
- 优先使用 Tencent Finance / mootdx 增强行情。
- 仅用于筛选返回前对 items 进行行情富集。
"""
from __future__ import annotations

import asyncio
import time
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
            # 刷新缓存（阻塞IO放到线程）。行情层只走 Tencent/mootdx，
            # 避免高频触发 AKShare/东财行情接口。
            data = await asyncio.to_thread(self._fetch_external_quotes, codes)
            self._cache = data
            self._cache_ts = time.time()
            return {c: q for c, q in self._cache.items() if c in codes and q}

    def _fetch_external_quotes(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """通过 Tencent Finance / mootdx 拉取请求股票的实时快照。"""
        try:
            from app.services.china_external_data_service import ChinaQuoteService

            data = ChinaQuoteService(timeout_seconds=5).get_quotes(codes)
            if data:
                logger.info(f"外部行情增强拉取完成: {len(data)} 条")
            return data
        except Exception as e:
            logger.warning(f"外部行情增强失败: {e}")
            return {}


_quotes_service: Optional[QuotesService] = None


def get_quotes_service() -> QuotesService:
    global _quotes_service
    if _quotes_service is None:
        _quotes_service = QuotesService(ttl_seconds=30)
    return _quotes_service
