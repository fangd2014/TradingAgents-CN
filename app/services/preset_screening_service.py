"""
预设条件选股服务。

用于股票筛选页的“趋势启动”预设：按板块、流通市值、调整横盘、均线、
换手、放量价位和筹码控盘代理指标逐步过滤，并返回完整筛选漏斗。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


HOT_INDUSTRY_KEYWORDS = (
    "半导体",
    "电子",
    "通信",
    "计算机",
    "软件",
    "互联网",
    "机器人",
    "航天",
    "军工",
    "卫星",
    "有色",
    "金属",
    "化工",
    "煤炭",
    "电池",
    "储能",
    "风电",
    "航运",
    "造船",
    "银行",
    "证券",
    "保险",
)


DEFAULT_FLOAT_CAP_LIMIT = 500.0
DEFAULT_MIN_TURNOVER_RATE = 5.0
DEFAULT_MIN_FIVE_DAY_TURNOVER = DEFAULT_MIN_TURNOVER_RATE
DEFAULT_VOLUME_BREAKOUT_MULTIPLIER = 4.0
DEFAULT_RUBBING_BODY_RATIO = 0.15
DEFAULT_RUBBING_LONG_SHADOW_RATIO = 0.50
DEFAULT_RUBBING_SHORT_SHADOW_RATIO = 0.25
DEFAULT_RUBBING_COMBINED_BODY_RATIO = 0.15
DEFAULT_RUBBING_VOLUME_RATIO = 0.70
PULLBACK_LOOKBACK_DAYS = 60
PULLBACK_MIN_RATIO = 0.15
SIDEWAYS_LOOKBACK_DAYS = 20
SIDEWAYS_RANGE_LIMIT = 0.15
SHRINK_VOLUME_LOOKBACK_DAYS = 10
VOLUME_SHRINK_RATIO = 0.70
ABNORMAL_VOLUME_MULTIPLIER = 2.0
SKIP_PRICE_CONSOLIDATION_FILTER = False
SKIP_MA_UP_FILTER = False


PRESET_TREND_START_DESCRIPTION = [
    "先限定当前热门板块或手动指定板块，再筛选流通市值小于阈值的中小盘股票。",
    "最近60个交易日出现冲高回落，当前处于缩量横盘整理，且横盘期间无放量异动。",
    "5日、10日、20日均线同步向上。",
    "上一有效交易日的换手率达到阈值，换手率来自 Tushare daily_basic.turnover_rate_f。",
    "要求前3个交易日内出现放量上涨，放量倍数达到阈值；随后下跌缩量，股价不跌破放量上涨实体一半。",
    "用筹码峰代理指标判断主力控盘状态，优先吸筹、拉升、洗盘、锁仓，排除抛售和诱多。",
]

TREND_START_TRACE_STAGES = [
    (
        "price_consolidation",
        "冲高回落+缩量横盘",
        "近60日高点回落不低于15%，近20日振幅不超过15%，近10日均量低于20日均量0.7倍且递减，并排除横盘期放量异动。",
    ),
    (
        "ma_up",
        "5/10/20日均线向上",
        "5日、10日、20日均线均较上一交易日上行。",
    ),
    (
        "turnover_5d",
        "上一交易日换手达标",
        "使用 Tushare daily_basic.turnover_rate_f，并通过交易日历取上一有效交易日以避开节假日。",
    ),
    (
        "volume_price_breakout",
        "3日内放量上涨与回踩不破",
        "前3个交易日内有上涨日成交量达到前5日均量的配置倍数；后续下跌缩量，低点不破上涨实体一半。",
    ),
    (
        "chip_control",
        "筹码峰与主力控盘代理",
        "综合OBV、上涨成交额占比、回调缩量、价格守住放量半分位和波动收敛，判断吸筹/拉升/洗盘/锁仓，排除抛售/诱多。",
    ),
]

TREND_START_STAGE_LABELS = {
    key: label for key, label, _ in TREND_START_TRACE_STAGES
}

PRESET_POSITIVE_RUBBING_LINE_DESCRIPTION = [
    "扫描最近两根日K线：先出现倒T字线（长上影线），后出现T字线（长下影线）。",
    "两根K线实体都必须很小，默认实体不超过当日振幅的15%。",
    "倒T字线要求上影线足够长、下影线较短；T字线要求下影线足够长、上影线较短。",
    "两根K线组合后的开收差很小，形态等效于一根十字线。",
    "后一根K线成交量默认不高于其前5个交易日平均成交量的70%，体现缩量。",
]

RUBBING_LINE_TRACE_STAGES = [
    (
        "history_ready",
        "日线数据充足",
        "至少需要最近6根日K线，用于两日形态和最新K线此前5日均量计算。",
    ),
    (
        "inverted_t",
        "首日倒T字线",
        "倒数第2根K线必须为小实体、长上影线、短下影线。",
    ),
    (
        "t_line",
        "次日T字线",
        "最新K线必须为小实体、长下影线、短上影线。",
    ),
    (
        "combined_doji",
        "两日合成十字线",
        "以首日开盘价和次日收盘价计算，合成实体必须很小。",
    ),
    (
        "volume_shrink",
        "缩量到5日均量7成",
        "最新K线成交量不高于此前5个交易日均量的配置比例。",
    ),
]

RUBBING_LINE_STAGE_LABELS = {
    key: label for key, label, _ in RUBBING_LINE_TRACE_STAGES
}


@dataclass
class HistoryLoadResult:
    data: pd.DataFrame
    source: str
    mongo_rows: int = 0
    tushare_rows: int = 0
    error: Optional[str] = None


class PresetScreeningService:
    """预设条件选股服务。"""

    async def run_trend_start_preset(
        self,
        limit: int = 50,
        candidate_limit: int = 300,
        industries: Optional[Sequence[str]] = None,
        float_cap_limit: float = DEFAULT_FLOAT_CAP_LIMIT,
        min_five_day_turnover: float = DEFAULT_MIN_FIVE_DAY_TURNOVER,
        volume_breakout_multiplier: float = DEFAULT_VOLUME_BREAKOUT_MULTIPLIER,
    ) -> Dict[str, Any]:
        start_time = datetime.now()
        params = {
            "float_cap_limit": float_cap_limit,
            "min_five_day_turnover": min_five_day_turnover,
            "volume_breakout_multiplier": volume_breakout_multiplier,
        }
        trace: Dict[str, Any] = {
            "parameters": {
                "limit": limit,
                "candidate_limit": candidate_limit,
                "industries": list(industries or []),
                "industry_mode": "手动行业" if industries else "默认热点行业关键词",
                **params,
            },
            "steps": [],
            "failure_reasons": {},
            "sample_rejections": [],
        }
        turnover_snapshot = await self._load_latest_tushare_turnover_rate_f(trace)
        candidates = await self._load_candidates(
            candidate_limit=candidate_limit,
            industries=industries,
            float_cap_limit=float_cap_limit,
            trace=trace,
        )

        items: List[Dict[str, Any]] = []
        stage_stats = self._create_stage_stats()
        for candidate in candidates:
            code = str(candidate.get("code") or "").zfill(6)
            if not code:
                continue

            try:
                history_result = await self._load_recent_daily_history(code, days=90)
                item, diagnostic = self._evaluate_trend_start_candidate_with_trace(
                    candidate,
                    history_result.data,
                    params=params,
                    turnover_snapshot=turnover_snapshot,
                )
                diagnostic["metrics"].update(
                    {
                        "history_source": history_result.source,
                        "history_mongo_rows": history_result.mongo_rows,
                        "history_tushare_rows": history_result.tushare_rows,
                    }
                )
                if history_result.error:
                    diagnostic["metrics"]["history_load_error"] = history_result.error
                self._record_diagnostic(trace, stage_stats, diagnostic)
                if item:
                    items.append(item)
            except Exception as exc:
                logger.debug("预设选股候选计算失败: %s %s", code, exc)
                self._record_error(trace, candidate, exc)

        items.sort(
            key=lambda item: (
                item.get("five_day_change_pct") is None,
                item.get("five_day_change_pct") or 0,
                item.get("amount") or 0,
            ),
            reverse=True,
        )

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        trace["steps"].extend(self._build_stage_steps(stage_stats))
        trace["matched_count"] = len(items)
        trace["returned_count"] = len(items[:limit])
        trace["took_ms"] = elapsed_ms
        return {
            "preset": "trend_start",
            "title": "趋势启动预设",
            "description": PRESET_TREND_START_DESCRIPTION,
            "total": len(items),
            "items": items[:limit],
            "took_ms": elapsed_ms,
            "trace": trace,
        }

    async def run_positive_rubbing_line_preset(
        self,
        limit: int = 50,
        candidate_limit: int = 1000,
        industries: Optional[Sequence[str]] = None,
        body_ratio: float = DEFAULT_RUBBING_BODY_RATIO,
        long_shadow_ratio: float = DEFAULT_RUBBING_LONG_SHADOW_RATIO,
        short_shadow_ratio: float = DEFAULT_RUBBING_SHORT_SHADOW_RATIO,
        combined_body_ratio: float = DEFAULT_RUBBING_COMBINED_BODY_RATIO,
        volume_ratio: float = DEFAULT_RUBBING_VOLUME_RATIO,
    ) -> Dict[str, Any]:
        """Scan for 缩量正揉搓线 in the latest two daily bars."""
        start_time = datetime.now()
        params = {
            "body_ratio": body_ratio,
            "long_shadow_ratio": long_shadow_ratio,
            "short_shadow_ratio": short_shadow_ratio,
            "combined_body_ratio": combined_body_ratio,
            "volume_ratio": volume_ratio,
        }
        trace: Dict[str, Any] = {
            "parameters": {
                "limit": limit,
                "candidate_limit": candidate_limit,
                "industries": list(industries or []),
                "industry_mode": "手动行业" if industries else "全部行业",
                **params,
            },
            "steps": [],
            "failure_reasons": {},
            "sample_rejections": [],
        }
        candidates = await self._load_pattern_candidates(
            candidate_limit=candidate_limit,
            industries=industries,
            trace=trace,
        )

        items: List[Dict[str, Any]] = []
        stage_stats = self._create_stage_stats(RUBBING_LINE_TRACE_STAGES)
        for candidate in candidates:
            code = str(candidate.get("code") or "").zfill(6)
            if not code:
                continue
            try:
                history_result = await self._load_recent_daily_history(code, days=30, required_rows=6)
                item, diagnostic = self._evaluate_positive_rubbing_line_candidate(
                    candidate,
                    history_result.data,
                    params=params,
                )
                diagnostic["metrics"].update(
                    {
                        "history_source": history_result.source,
                        "history_mongo_rows": history_result.mongo_rows,
                        "history_tushare_rows": history_result.tushare_rows,
                    }
                )
                if history_result.error:
                    diagnostic["metrics"]["history_load_error"] = history_result.error
                self._record_diagnostic(
                    trace,
                    stage_stats,
                    diagnostic,
                    stage_labels=RUBBING_LINE_STAGE_LABELS,
                )
                if item:
                    items.append(item)
            except Exception as exc:
                logger.debug("缩量正揉搓线候选计算失败: %s %s", code, exc)
                self._record_error(trace, candidate, exc)

        items.sort(
            key=lambda item: (
                item.get("pattern_date") or "",
                item.get("volume_shrink_ratio") is None,
                -(item.get("volume_shrink_ratio") or 999),
                item.get("amount") or 0,
            ),
            reverse=True,
        )

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        trace["steps"].extend(self._build_stage_steps(stage_stats, RUBBING_LINE_TRACE_STAGES))
        trace["matched_count"] = len(items)
        trace["returned_count"] = len(items[:limit])
        trace["took_ms"] = elapsed_ms
        return {
            "preset": "positive_rubbing_line",
            "title": "缩量正揉搓线",
            "description": PRESET_POSITIVE_RUBBING_LINE_DESCRIPTION,
            "total": len(items),
            "items": items[:limit],
            "took_ms": elapsed_ms,
            "trace": trace,
        }

    async def _load_candidates(
        self,
        candidate_limit: int,
        industries: Optional[Sequence[str]] = None,
        float_cap_limit: float = DEFAULT_FLOAT_CAP_LIMIT,
        trace: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        collection = db["stock_screening_view"]

        market_cap_query: Dict[str, Any] = {
            "$or": [
                {"circ_mv": {"$gt": 0, "$lt": float_cap_limit}},
                {
                    "$and": [
                        {"$or": [{"circ_mv": {"$exists": False}}, {"circ_mv": None}, {"circ_mv": 0}]},
                        {"total_mv": {"$gt": 0, "$lt": float_cap_limit}},
                    ]
                },
            ],
            "close": {"$gt": 0},
        }
        query: Dict[str, Any] = dict(market_cap_query)

        selected_industries = [industry for industry in (industries or []) if industry]
        if selected_industries:
            industry_query = {"industry": {"$in": selected_industries}}
        else:
            industry_query = {"$or": [{"industry": {"$regex": keyword}} for keyword in HOT_INDUSTRY_KEYWORDS]}
        query = {"$and": [market_cap_query, industry_query]}

        projection = {
            "_id": 0,
            "code": 1,
            "name": 1,
            "industry": 1,
            "market": 1,
            "total_mv": 1,
            "circ_mv": 1,
            "close": 1,
            "pct_chg": 1,
            "amount": 1,
            "turnover_rate": 1,
            "turnover_rate_f": 1,
            "volume_ratio": 1,
            "source": 1,
        }
        if trace is not None:
            await self._append_candidate_filter_steps(
                trace=trace,
                collection=collection,
                market_cap_query=market_cap_query,
                industry_query=industry_query,
                selected_industries=selected_industries,
                float_cap_limit=float_cap_limit,
            )

        matched_count = await collection.count_documents(query)
        cursor = collection.find(query, projection).sort([("amount", -1)]).limit(candidate_limit)
        candidates = await cursor.to_list(length=candidate_limit)
        logger.info(
            "[preset_screening] 候选池市值样本: matched=%s returned=%s samples=%s",
            matched_count,
            len(candidates),
            [self._format_market_cap_sample(candidate, float_cap_limit) for candidate in candidates[:10]],
        )
        if trace is not None:
            trace["steps"].append(
                {
                    "key": "candidate_pool",
                    "label": "数据库候选池",
                    "description": (
                        "从 stock_screening_view 按市值、成交额、换手率和行业范围筛出初始候选，"
                        "再按成交额倒序取前 candidate_limit 只进入技术形态计算。"
                    ),
                    "checked": matched_count,
                    "pass_count": len(candidates),
                    "fail_count": max(matched_count - len(candidates), 0),
                    "remaining_count": len(candidates),
                    "details": {
                        "query": query,
                        "candidate_limit": candidate_limit,
                        "limited_by_candidate_limit": matched_count > len(candidates),
                    },
                }
        )
        return candidates

    async def _load_pattern_candidates(
        self,
        candidate_limit: int,
        industries: Optional[Sequence[str]] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        collection = db["stock_screening_view"]
        base_query: Dict[str, Any] = {"close": {"$gt": 0}}
        selected_industries = [industry for industry in (industries or []) if industry]
        query: Dict[str, Any] = dict(base_query)
        if selected_industries:
            query = {"$and": [base_query, {"industry": {"$in": selected_industries}}]}

        projection = {
            "_id": 0,
            "code": 1,
            "name": 1,
            "industry": 1,
            "market": 1,
            "board": 1,
            "total_mv": 1,
            "circ_mv": 1,
            "close": 1,
            "pct_chg": 1,
            "amount": 1,
            "turnover_rate": 1,
            "turnover_rate_f": 1,
            "volume_ratio": 1,
            "source": 1,
        }
        matched_count = await collection.count_documents(query)
        cursor = collection.find(query, projection).sort([("amount", -1)]).limit(candidate_limit)
        candidates = await cursor.to_list(length=candidate_limit)
        if trace is not None:
            trace["steps"].append(
                {
                    "key": "candidate_pool",
                    "label": "数据库候选池",
                    "description": "从 stock_screening_view 取股价有效且符合行业范围的A股，按成交额倒序进入形态计算。",
                    "checked": matched_count,
                    "pass_count": len(candidates),
                    "fail_count": max(matched_count - len(candidates), 0),
                    "remaining_count": len(candidates),
                    "details": {
                        "query": query,
                        "candidate_limit": candidate_limit,
                        "industry_mode": "手动行业" if selected_industries else "全部行业",
                        "limited_by_candidate_limit": matched_count > len(candidates),
                    },
                }
            )
        return candidates

    async def _append_candidate_filter_steps(
        self,
        trace: Dict[str, Any],
        collection: Any,
        market_cap_query: Dict[str, Any],
        industry_query: Dict[str, Any],
        selected_industries: Sequence[str],
        float_cap_limit: float,
    ) -> None:
        filters = [
            (
                "screening_view_total",
                "筛选视图总样本",
                "stock_screening_view 中可用于筛选的记录总数。",
                {},
            ),
            (
                "base_close",
                "股价有效",
                "收盘价必须大于0。",
                {"close": {"$gt": 0}},
            ),
            (
                "base_float_cap",
                "流通市值小于阈值",
                f"流通市值必须大于0且小于{float_cap_limit:g}亿元。",
                market_cap_query,
            ),
            (
                "industry_scope",
                "行业范围",
                "继续按手动行业或默认热点行业关键词过滤。",
                {"$and": [market_cap_query, industry_query]},
            ),
        ]

        previous_count: Optional[int] = None
        for key, label, description, query in filters:
            count = await collection.count_documents(query)
            fail_count = 0 if previous_count is None else max(previous_count - count, 0)
            details: Dict[str, Any] = {
                "industry_mode": "手动行业" if selected_industries else "默认热点行业关键词",
            }
            if key == "base_float_cap":
                details.update(
                    await self._build_market_cap_diagnostics(
                        collection=collection,
                        float_cap_limit=float_cap_limit,
                        pass_query=query,
                    )
                )
            trace["steps"].append(
                {
                    "key": key,
                    "label": label,
                    "description": description,
                    "checked": previous_count if previous_count is not None else count,
                    "pass_count": count,
                    "fail_count": fail_count,
                    "remaining_count": count,
                    "details": details,
                }
            )
            previous_count = count

    async def _build_market_cap_diagnostics(
        self,
        collection: Any,
        float_cap_limit: float,
        pass_query: Dict[str, Any],
    ) -> Dict[str, Any]:
        base_query = {"close": {"$gt": 0}}
        rejected_query = {
            "close": {"$gt": 0},
            "$nor": [pass_query],
        }

        projection = {
            "_id": 0,
            "code": 1,
            "name": 1,
            "industry": 1,
            "source": 1,
            "total_mv": 1,
            "circ_mv": 1,
            "close": 1,
            "amount": 1,
        }
        pass_samples = await collection.find(pass_query, projection).sort("total_mv", 1).limit(20).to_list(length=20)
        rejected_samples = await collection.find(rejected_query, projection).sort("total_mv", 1).limit(20).to_list(length=20)
        largest_rejected_samples = await collection.find(rejected_query, projection).sort("total_mv", -1).limit(10).to_list(length=10)

        circ_agg = await collection.aggregate(
            [
                {"$match": {"circ_mv": {"$gt": 0}}},
                {
                    "$group": {
                        "_id": None,
                        "min": {"$min": "$circ_mv"},
                        "max": {"$max": "$circ_mv"},
                        "avg": {"$avg": "$circ_mv"},
                    }
                },
            ]
        ).to_list(length=1)
        total_agg = await collection.aggregate(
            [
                {"$match": {"total_mv": {"$gt": 0}}},
                {
                    "$group": {
                        "_id": None,
                        "min": {"$min": "$total_mv"},
                        "max": {"$max": "$total_mv"},
                        "avg": {"$avg": "$total_mv"},
                    }
                },
            ]
        ).to_list(length=1)

        summary = {
            "float_cap_limit": float_cap_limit,
            "base_count": await collection.count_documents(base_query),
            "circ_exists_count": await collection.count_documents({"circ_mv": {"$exists": True}}),
            "circ_missing_count": await collection.count_documents({"circ_mv": {"$exists": False}}),
            "circ_null_count": await collection.count_documents({"circ_mv": {"$type": "null"}}),
            "circ_zero_count": await collection.count_documents({"circ_mv": 0}),
            "circ_positive_count": await collection.count_documents({"circ_mv": {"$gt": 0}}),
            "circ_under_limit_count": await collection.count_documents({"circ_mv": {"$gt": 0, "$lt": float_cap_limit}}),
            "total_positive_count": await collection.count_documents({"total_mv": {"$gt": 0}}),
            "total_under_limit_count": await collection.count_documents({"total_mv": {"$gt": 0, "$lt": float_cap_limit}}),
            "circ_mv_distribution": circ_agg[0] if circ_agg else None,
            "total_mv_distribution": total_agg[0] if total_agg else None,
            "pass_samples": [self._format_market_cap_sample(sample, float_cap_limit) for sample in pass_samples],
            "rejected_samples": [self._format_market_cap_sample(sample, float_cap_limit) for sample in rejected_samples],
            "largest_rejected_samples": [
                self._format_market_cap_sample(sample, float_cap_limit) for sample in largest_rejected_samples
            ],
        }
        logger.info(
            "[preset_screening] 市值字段诊断: limit=%s base=%s circ_exists=%s circ_missing=%s circ_null=%s circ_zero=%s circ_positive=%s circ_under=%s total_positive=%s total_under=%s circ_dist=%s total_dist=%s",
            float_cap_limit,
            summary["base_count"],
            summary["circ_exists_count"],
            summary["circ_missing_count"],
            summary["circ_null_count"],
            summary["circ_zero_count"],
            summary["circ_positive_count"],
            summary["circ_under_limit_count"],
            summary["total_positive_count"],
            summary["total_under_limit_count"],
            summary["circ_mv_distribution"],
            summary["total_mv_distribution"],
        )
        logger.info(
            "[preset_screening] 市值通过样本(total_mv/circ_mv/effective): %s",
            summary["pass_samples"][:5],
        )
        logger.info(
            "[preset_screening] 市值拦截样本(total_mv/circ_mv/effective): %s",
            summary["rejected_samples"][:5],
        )
        logger.info(
            "[preset_screening] 市值最大拦截样本(total_mv/circ_mv/effective): %s",
            summary["largest_rejected_samples"][:5],
        )
        return {"market_cap_diagnostics": summary}

    def _format_market_cap_sample(self, sample: Dict[str, Any], float_cap_limit: float) -> Dict[str, Any]:
        circ_mv = self._safe_float(sample.get("circ_mv"))
        total_mv = self._safe_float(sample.get("total_mv"))
        effective_mv = circ_mv if circ_mv is not None and circ_mv > 0 else total_mv
        source = "circ_mv" if circ_mv is not None and circ_mv > 0 else "total_mv_fallback"
        return {
            "code": sample.get("code"),
            "name": sample.get("name"),
            "industry": sample.get("industry"),
            "source": sample.get("source"),
            "total_mv": total_mv,
            "circ_mv": circ_mv,
            "effective_mv": effective_mv,
            "effective_mv_source": source,
            "float_cap_limit": float_cap_limit,
            "passed": effective_mv is not None and 0 < effective_mv < float_cap_limit,
            "close": self._safe_float(sample.get("close")),
            "amount": self._safe_float(sample.get("amount")),
        }

    async def _load_recent_daily_history(
        self,
        code: str,
        days: int = 90,
        required_rows: int = PULLBACK_LOOKBACK_DAYS,
    ) -> HistoryLoadResult:
        mongo_history = await self._load_recent_daily_history_from_mongo(code, days)
        mongo_rows = len(mongo_history)
        if mongo_rows >= required_rows:
            return HistoryLoadResult(data=mongo_history, source="mongodb", mongo_rows=mongo_rows)

        logger.info(
            "[preset_screening] MongoDB历史日线不足，跳过在线回退: code=%s mongo_rows=%s required=%s",
            code,
            mongo_rows,
            required_rows,
        )
        return HistoryLoadResult(
            data=mongo_history,
            source="mongodb_short",
            mongo_rows=mongo_rows,
            error=f"MongoDB历史日线不足，请先执行A股全量数据预热或单股同步: {mongo_rows}/{required_rows}",
        )

    async def _load_recent_daily_history_from_mongo(self, code: str, days: int = 90) -> pd.DataFrame:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        collection = db["stock_daily_quotes"]
        cursor = (
            collection.find(
                {"symbol": code, "period": "daily"},
                {
                    "_id": 0,
                    "trade_date": 1,
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                    "vol": 1,
                    "amount": 1,
                    "pct_chg": 1,
                },
            )
            .sort("trade_date", -1)
            .limit(days)
        )
        docs = await cursor.to_list(length=days)
        if not docs:
            return pd.DataFrame()
        return pd.DataFrame(reversed(docs))

    def _load_recent_daily_history_from_tushare(self, code: str, days: int = 180) -> pd.DataFrame:
        from app.services.data_sources.tushare_adapter import TushareAdapter

        adapter = TushareAdapter()
        if not adapter.is_available():
            return pd.DataFrame()

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        provider = getattr(adapter, "_provider", None)
        api = getattr(provider, "api", None)
        if api is None:
            return pd.DataFrame()

        ts_code = provider._normalize_ts_code(code) if hasattr(provider, "_normalize_ts_code") else code
        df = api.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg",
        )
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={"vol": "volume"})
        df["trade_date"] = df["trade_date"].astype(str).map(self._format_trade_date)
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000
        return df.sort_values("trade_date").tail(days).reset_index(drop=True)

    async def _load_latest_tushare_turnover_rate_f(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "trade_date": None,
            "source": "tushare.daily_basic.turnover_rate_f",
            "values": {},
            "error": None,
        }
        try:
            from app.services.data_sources.tushare_adapter import TushareAdapter

            adapter = TushareAdapter()
            trade_date = await asyncio.to_thread(adapter.find_latest_trade_date)
            if not trade_date:
                result["error"] = "未能通过 Tushare 交易日历获取上一有效交易日"
                logger.warning("[preset_screening] %s", result["error"])
                return result

            result["trade_date"] = str(trade_date)
            df = await asyncio.to_thread(
                self._fetch_tushare_daily_basic_turnover_rate_f,
                adapter,
                str(trade_date),
            )
            if df is None or df.empty:
                result["error"] = f"Tushare daily_basic 在 {trade_date} 未返回 turnover_rate_f 数据"
                logger.warning("[preset_screening] %s", result["error"])
                return result

            values: Dict[str, float] = {}
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code") or "")
                if not ts_code:
                    continue
                code = ts_code.split(".")[0].zfill(6)
                turnover_rate_f = self._safe_float(row.get("turnover_rate_f"))
                if turnover_rate_f is not None:
                    values[code] = turnover_rate_f

            result["values"] = values
            logger.info(
                "[preset_screening] Tushare turnover_rate_f 快照: trade_date=%s count=%s",
                trade_date,
                len(values),
            )
            return result
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("[preset_screening] 获取 Tushare turnover_rate_f 快照失败: %s", exc)
            return result
        finally:
            trace["parameters"]["turnover_rate_trade_date"] = result.get("trade_date")
            trace["parameters"]["turnover_rate_source"] = result.get("source")
            if result.get("error"):
                trace["parameters"]["turnover_rate_error"] = result.get("error")

    def _fetch_tushare_daily_basic_turnover_rate_f(
        self,
        adapter: Any,
        trade_date: str,
    ) -> Optional[pd.DataFrame]:
        if not adapter.is_available():
            return None
        provider = getattr(adapter, "_provider", None)
        api = getattr(provider, "api", None)
        if api is None:
            return None
        return api.daily_basic(
            trade_date=trade_date,
            fields="ts_code,turnover_rate_f",
        )

    def _evaluate_trend_start_candidate(
        self,
        candidate: Dict[str, Any],
        history: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        item, _ = self._evaluate_trend_start_candidate_with_trace(candidate, history)
        return item

    def _evaluate_trend_start_candidate_with_trace(
        self,
        candidate: Dict[str, Any],
        history: pd.DataFrame,
        params: Optional[Dict[str, float]] = None,
        turnover_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        params = params or {}
        float_cap_limit = params.get("float_cap_limit", DEFAULT_FLOAT_CAP_LIMIT)
        min_turnover_rate = params.get("min_five_day_turnover", DEFAULT_MIN_FIVE_DAY_TURNOVER)
        volume_breakout_multiplier = params.get(
            "volume_breakout_multiplier",
            DEFAULT_VOLUME_BREAKOUT_MULTIPLIER,
        )
        code = str(candidate.get("code") or "").zfill(6)
        diagnostic: Dict[str, Any] = {
            "code": code,
            "name": candidate.get("name") or code,
            "industry": candidate.get("industry"),
            "stage_results": {},
            "metrics": {},
            "failed_stage": None,
            "failed_reason": None,
        }

        if history is None or len(history) < 60:
            diagnostic["stage_results"]["price_consolidation"] = False
            diagnostic["metrics"]["history_rows"] = 0 if history is None else len(history)
            diagnostic["failed_stage"] = "price_consolidation"
            diagnostic["failed_reason"] = "历史日线不足60条"
            return None, diagnostic

        df = self._normalize_history(history)
        if len(df) < 60:
            diagnostic["stage_results"]["price_consolidation"] = False
            diagnostic["metrics"]["history_rows"] = len(df)
            diagnostic["failed_stage"] = "price_consolidation"
            diagnostic["failed_reason"] = "历史日线清洗后不足60条"
            return None, diagnostic
        diagnostic["metrics"]["history_rows"] = len(df)

        raw_circ_mv = self._safe_float(candidate.get("circ_mv"))
        fallback_total_mv = self._safe_float(candidate.get("total_mv"))
        circ_mv = raw_circ_mv if raw_circ_mv is not None and raw_circ_mv > 0 else fallback_total_mv
        circ_mv_source = "circ_mv" if raw_circ_mv is not None and raw_circ_mv > 0 else "total_mv_fallback"
        if circ_mv is None or circ_mv >= float_cap_limit:
            diagnostic["stage_results"]["price_consolidation"] = False
            diagnostic["metrics"]["circ_mv"] = circ_mv
            diagnostic["metrics"]["circ_mv_source"] = circ_mv_source
            diagnostic["failed_stage"] = "price_consolidation"
            diagnostic["failed_reason"] = f"流通市值为空或不小于{float_cap_limit:g}亿元"
            return None, diagnostic

        latest = df.iloc[-1]
        previous = df.iloc[-2]
        last5 = df.tail(5)
        sideways_window = df.tail(SIDEWAYS_LOOKBACK_DAYS)
        shrink_window = df.tail(SHRINK_VOLUME_LOOKBACK_DAYS)
        pullback_window = df.tail(PULLBACK_LOOKBACK_DAYS)

        sideways_low = sideways_window["low"].min()
        sideways_high = sideways_window["high"].max()
        if sideways_low <= 0:
            diagnostic["stage_results"]["price_consolidation"] = False
            diagnostic["metrics"]["sideways_range_pct"] = None
            diagnostic["failed_stage"] = "price_consolidation"
            diagnostic["failed_reason"] = "横盘区间最低价无效"
            return None, diagnostic

        sixty_high = pullback_window["high"].max()
        sixty_high_idx = pullback_window["high"].idxmax()
        sixty_high_date = pullback_window.loc[sixty_high_idx, "trade_date"]
        pullback_from_high_pct = (sixty_high - latest["close"]) / sixty_high if sixty_high else 0
        sideways_range_pct = (sideways_high - sideways_low) / sideways_low
        avg_volume_10d = shrink_window["volume"].mean()
        avg_volume_20d = sideways_window["volume"].mean()
        recent_volume_declining = (
            len(shrink_window) >= 2
            and shrink_window["volume"].tail(5).mean() <= shrink_window["volume"].head(5).mean()
        )
        abnormal_volume_days = sideways_window[
            sideways_window["volume"] >= avg_volume_20d * ABNORMAL_VOLUME_MULTIPLIER
        ]
        shrinking_sideways = (
            avg_volume_20d > 0
            and avg_volume_10d <= avg_volume_20d * VOLUME_SHRINK_RATIO
            and recent_volume_declining
        )
        no_abnormal_volume = abnormal_volume_days.empty
        price_consolidation = (
            pullback_from_high_pct >= PULLBACK_MIN_RATIO
            and sideways_range_pct <= SIDEWAYS_RANGE_LIMIT
            and shrinking_sideways
            and no_abnormal_volume
        )
        diagnostic["metrics"].update(
            {
                "circ_mv": circ_mv,
                "circ_mv_source": circ_mv_source,
                "total_mv": fallback_total_mv,
                "sixty_day_high": self._safe_float(sixty_high),
                "sixty_day_high_date": sixty_high_date,
                "pullback_from_high_pct": self._safe_float(pullback_from_high_pct * 100),
                "sideways_range_pct": self._safe_float(sideways_range_pct * 100),
                "sideways_low": self._safe_float(sideways_low),
                "sideways_high": self._safe_float(sideways_high),
                "avg_volume_10d": self._safe_float(avg_volume_10d),
                "avg_volume_20d": self._safe_float(avg_volume_20d),
                "volume_shrink_ratio": self._safe_float(avg_volume_10d / avg_volume_20d if avg_volume_20d else None),
                "recent_volume_declining": bool(recent_volume_declining),
                "abnormal_volume_days": int(len(abnormal_volume_days)),
            }
        )
        if SKIP_PRICE_CONSOLIDATION_FILTER:
            diagnostic["stage_results"]["price_consolidation"] = True
            diagnostic["metrics"]["price_consolidation_skipped"] = True
            diagnostic["metrics"]["price_consolidation_original_passed"] = bool(price_consolidation)
        else:
            diagnostic["stage_results"]["price_consolidation"] = bool(price_consolidation)
        if not SKIP_PRICE_CONSOLIDATION_FILTER and not price_consolidation:
            diagnostic["failed_stage"] = "price_consolidation"
            diagnostic["failed_reason"] = "未同时满足冲高回落、缩量横盘和无放量异动"
            return None, diagnostic

        ma5 = df["close"].rolling(5).mean().iloc[-1]
        ma5_prev = df["close"].rolling(5).mean().iloc[-2]
        ma10 = df["close"].rolling(10).mean().iloc[-1]
        ma10_prev = df["close"].rolling(10).mean().iloc[-2]
        ma20 = df["close"].rolling(20).mean().iloc[-1]
        ma20_prev = df["close"].rolling(20).mean().iloc[-2]
        ma_up = ma5 > ma5_prev and ma10 > ma10_prev and ma20 > ma20_prev
        diagnostic["metrics"].update(
            {
                "ma5": self._safe_float(ma5),
                "ma5_prev": self._safe_float(ma5_prev),
                "ma10": self._safe_float(ma10),
                "ma10_prev": self._safe_float(ma10_prev),
                "ma20": self._safe_float(ma20),
                "ma20_prev": self._safe_float(ma20_prev),
            }
        )
        if SKIP_MA_UP_FILTER:
            diagnostic["stage_results"]["ma_up"] = True
            diagnostic["metrics"]["ma_up_skipped"] = True
            diagnostic["metrics"]["ma_up_original_passed"] = bool(ma_up)
        else:
            diagnostic["stage_results"]["ma_up"] = bool(ma_up)
        if not SKIP_MA_UP_FILTER and not ma_up:
            diagnostic["failed_stage"] = "ma_up"
            diagnostic["failed_reason"] = "5日、10日、20日均线未同步向上"
            return None, diagnostic

        turnover_rate = self._get_turnover_rate_f(code, candidate, turnover_snapshot)
        turnover_5d = turnover_rate is not None and turnover_rate >= min_turnover_rate
        diagnostic["stage_results"]["turnover_5d"] = bool(turnover_5d)
        diagnostic["metrics"]["turnover_rate_f"] = self._safe_float(turnover_rate)
        diagnostic["metrics"]["turnover_rate_trade_date"] = (turnover_snapshot or {}).get("trade_date")
        diagnostic["metrics"]["turnover_rate_source"] = (turnover_snapshot or {}).get(
            "source",
            "tushare.daily_basic.turnover_rate_f",
        )
        if not turnover_5d:
            diagnostic["failed_stage"] = "turnover_5d"
            diagnostic["failed_reason"] = f"上一交易日换手率低于{min_turnover_rate:g}%或缺失"
            return None, diagnostic

        breakout = self._find_recent_breakout(df, volume_breakout_multiplier)
        diagnostic["stage_results"]["volume_price_breakout"] = bool(breakout["passed"])
        diagnostic["metrics"].update(breakout["metrics"])
        if not breakout["passed"]:
            diagnostic["failed_stage"] = "volume_price_breakout"
            diagnostic["failed_reason"] = breakout["reason"]
            return None, diagnostic

        chip = self._evaluate_chip_control(df, breakout)
        diagnostic["stage_results"]["chip_control"] = bool(chip["passed"])
        diagnostic["metrics"].update(chip["metrics"])
        diagnostic["chip_analysis"] = chip
        if not chip["passed"]:
            diagnostic["failed_stage"] = "chip_control"
            diagnostic["failed_reason"] = chip["reason"]
            return None, diagnostic

        first5 = last5.iloc[0]
        five_day_change = (
            (latest["close"] / first5["close"] - 1) * 100
            if first5["close"]
            else None
        )
        day_change_pct = (latest["close"] / previous["close"] - 1) * 100 if previous["close"] else 0
        amount = self._safe_float(candidate.get("amount")) or self._safe_float(latest.get("amount"))

        recent_rows = []
        for _, row in last5.iterrows():
            recent_rows.append(
                {
                    "trade_date": row["trade_date"],
                    "close": self._safe_float(row.get("close")),
                    "pct_chg": self._safe_float(row.get("pct_chg")),
                    "amount": self._safe_float(row.get("amount")),
                    "volume": self._safe_float(row.get("volume")),
                }
            )

        diagnostic["matched"] = True
        return {
            "code": str(candidate.get("code") or "").zfill(6),
            "symbol": str(candidate.get("code") or "").zfill(6),
            "name": candidate.get("name") or candidate.get("code"),
            "market": "A股",
            "industry": candidate.get("industry"),
            "board": candidate.get("board") or candidate.get("market"),
            "total_mv": fallback_total_mv,
            "circ_mv": circ_mv,
            "circ_mv_source": circ_mv_source,
            "close": self._safe_float(latest.get("close")),
            "pct_chg": self._safe_float(latest.get("pct_chg")) or day_change_pct,
            "amount": amount,
            "turnover_rate": self._safe_float(turnover_rate),
            "turnover_rate_f": self._safe_float(turnover_rate),
            "turnover_rate_date": (turnover_snapshot or {}).get("trade_date"),
            "turnover_rate_source": (turnover_snapshot or {}).get(
                "source",
                "tushare.daily_basic.turnover_rate_f",
            ),
            "five_day_change_pct": self._safe_float(five_day_change),
            "five_day_total_mv": self._safe_float(candidate.get("total_mv")),
            "recent_5d": recent_rows,
            "chip_control": chip,
            "matched_conditions": {
                "price_consolidation": bool(price_consolidation),
                "price_consolidation_skipped": SKIP_PRICE_CONSOLIDATION_FILTER,
                "ma_up": bool(ma_up),
                "ma_up_skipped": SKIP_MA_UP_FILTER,
                "turnover_5d": True,
                "volume_price_breakout": True,
                "chip_control": True,
            },
        }, diagnostic

    def _evaluate_positive_rubbing_line_candidate(
        self,
        candidate: Dict[str, Any],
        history: pd.DataFrame,
        params: Optional[Dict[str, float]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        params = params or {}
        body_ratio = float(params.get("body_ratio", DEFAULT_RUBBING_BODY_RATIO))
        long_shadow_ratio = float(params.get("long_shadow_ratio", DEFAULT_RUBBING_LONG_SHADOW_RATIO))
        short_shadow_ratio = float(params.get("short_shadow_ratio", DEFAULT_RUBBING_SHORT_SHADOW_RATIO))
        combined_body_ratio = float(params.get("combined_body_ratio", DEFAULT_RUBBING_COMBINED_BODY_RATIO))
        volume_ratio_limit = float(params.get("volume_ratio", DEFAULT_RUBBING_VOLUME_RATIO))
        code = str(candidate.get("code") or "").zfill(6)
        diagnostic: Dict[str, Any] = {
            "code": code,
            "name": candidate.get("name") or code,
            "industry": candidate.get("industry"),
            "stage_results": {},
            "metrics": {},
            "failed_stage": None,
            "failed_reason": None,
        }

        if history is None or len(history) < 6:
            diagnostic["stage_results"]["history_ready"] = False
            diagnostic["metrics"]["history_rows"] = 0 if history is None else len(history)
            diagnostic["failed_stage"] = "history_ready"
            diagnostic["failed_reason"] = "历史日线不足6条"
            return None, diagnostic

        df = self._normalize_history(history)
        if len(df) < 6:
            diagnostic["stage_results"]["history_ready"] = False
            diagnostic["metrics"]["history_rows"] = len(df)
            diagnostic["failed_stage"] = "history_ready"
            diagnostic["failed_reason"] = "历史日线清洗后不足6条"
            return None, diagnostic

        diagnostic["stage_results"]["history_ready"] = True
        diagnostic["metrics"]["history_rows"] = len(df)
        upper_day = df.iloc[-2]
        lower_day = df.iloc[-1]
        upper_metrics = self._candle_shadow_metrics(upper_day)
        lower_metrics = self._candle_shadow_metrics(lower_day)
        diagnostic["metrics"].update(
            {
                "upper_shadow_date": upper_day.get("trade_date"),
                "lower_shadow_date": lower_day.get("trade_date"),
                "upper_body_ratio": upper_metrics.get("body_ratio_pct"),
                "upper_shadow_ratio": upper_metrics.get("upper_shadow_ratio_pct"),
                "upper_lower_shadow_ratio": upper_metrics.get("lower_shadow_ratio_pct"),
                "lower_body_ratio": lower_metrics.get("body_ratio_pct"),
                "lower_shadow_ratio": lower_metrics.get("lower_shadow_ratio_pct"),
                "lower_upper_shadow_ratio": lower_metrics.get("upper_shadow_ratio_pct"),
                "latest_open": self._safe_float(lower_day.get("open")),
                "latest_close": self._safe_float(lower_day.get("close")),
                "latest_volume": self._safe_float(lower_day.get("volume")),
            }
        )

        inverted_t = (
            bool(upper_metrics.get("valid"))
            and upper_metrics["body_ratio"] <= body_ratio
            and upper_metrics["upper_shadow_ratio"] >= long_shadow_ratio
            and upper_metrics["lower_shadow_ratio"] <= short_shadow_ratio
        )
        diagnostic["stage_results"]["inverted_t"] = bool(inverted_t)
        if not inverted_t:
            diagnostic["failed_stage"] = "inverted_t"
            diagnostic["failed_reason"] = "首日未满足小实体、长上影、短下影的倒T字线"
            return None, diagnostic

        t_line = (
            bool(lower_metrics.get("valid"))
            and lower_metrics["body_ratio"] <= body_ratio
            and lower_metrics["lower_shadow_ratio"] >= long_shadow_ratio
            and lower_metrics["upper_shadow_ratio"] <= short_shadow_ratio
        )
        diagnostic["stage_results"]["t_line"] = bool(t_line)
        if not t_line:
            diagnostic["failed_stage"] = "t_line"
            diagnostic["failed_reason"] = "次日未满足小实体、长下影、短上影的T字线"
            return None, diagnostic

        combined_high = max(float(upper_day["high"]), float(lower_day["high"]))
        combined_low = min(float(upper_day["low"]), float(lower_day["low"]))
        combined_range = combined_high - combined_low
        combined_body = abs(float(lower_day["close"]) - float(upper_day["open"]))
        combined_ratio = combined_body / combined_range if combined_range > 0 else 1.0
        combined_doji = combined_range > 0 and combined_ratio <= combined_body_ratio
        diagnostic["metrics"].update(
            {
                "combined_high": self._safe_float(combined_high),
                "combined_low": self._safe_float(combined_low),
                "combined_body_ratio": self._safe_float(combined_ratio * 100),
            }
        )
        diagnostic["stage_results"]["combined_doji"] = bool(combined_doji)
        if not combined_doji:
            diagnostic["failed_stage"] = "combined_doji"
            diagnostic["failed_reason"] = "两日合成实体过大，未等效十字线"
            return None, diagnostic

        volume_base = df.iloc[-6:-1]["volume"].mean()
        latest_volume = float(lower_day["volume"])
        volume_shrink_ratio = latest_volume / volume_base if volume_base > 0 else None
        volume_shrink = volume_shrink_ratio is not None and volume_shrink_ratio <= volume_ratio_limit
        diagnostic["metrics"].update(
            {
                "avg_volume_prev5": self._safe_float(volume_base),
                "volume_shrink_ratio": self._safe_float(volume_shrink_ratio),
                "volume_shrink_ratio_pct": self._safe_float(volume_shrink_ratio * 100 if volume_shrink_ratio is not None else None),
                "volume_ratio_limit": self._safe_float(volume_ratio_limit),
            }
        )
        diagnostic["stage_results"]["volume_shrink"] = bool(volume_shrink)
        if not volume_shrink:
            diagnostic["failed_stage"] = "volume_shrink"
            diagnostic["failed_reason"] = f"最新成交量未缩至此前5日均量的{volume_ratio_limit * 100:g}%以内"
            return None, diagnostic

        recent_rows = []
        for _, row in df.tail(5).iterrows():
            recent_rows.append(
                {
                    "trade_date": row["trade_date"],
                    "close": self._safe_float(row.get("close")),
                    "pct_chg": self._safe_float(row.get("pct_chg")),
                    "amount": self._safe_float(row.get("amount")),
                    "volume": self._safe_float(row.get("volume")),
                }
            )

        day_change_pct = (
            (float(lower_day["close"]) / float(df.iloc[-2]["close"]) - 1) * 100
            if float(df.iloc[-2]["close"]) else 0
        )
        diagnostic["matched"] = True
        return {
            "code": code,
            "symbol": code,
            "name": candidate.get("name") or code,
            "market": "A股",
            "industry": candidate.get("industry"),
            "board": candidate.get("board") or candidate.get("market"),
            "total_mv": self._safe_float(candidate.get("total_mv")),
            "circ_mv": self._safe_float(candidate.get("circ_mv")),
            "close": self._safe_float(lower_day.get("close")),
            "pct_chg": self._safe_float(lower_day.get("pct_chg")) or self._safe_float(day_change_pct),
            "amount": self._safe_float(candidate.get("amount")) or self._safe_float(lower_day.get("amount")),
            "turnover_rate": self._safe_float(candidate.get("turnover_rate")),
            "turnover_rate_f": self._safe_float(candidate.get("turnover_rate_f")),
            "pattern": "缩量正揉搓线",
            "pattern_date": lower_day.get("trade_date"),
            "upper_shadow_date": upper_day.get("trade_date"),
            "lower_shadow_date": lower_day.get("trade_date"),
            "upper_body_ratio": upper_metrics.get("body_ratio_pct"),
            "upper_shadow_ratio": upper_metrics.get("upper_shadow_ratio_pct"),
            "lower_body_ratio": lower_metrics.get("body_ratio_pct"),
            "lower_shadow_ratio": lower_metrics.get("lower_shadow_ratio_pct"),
            "combined_body_ratio": self._safe_float(combined_ratio * 100),
            "avg_volume_prev5": self._safe_float(volume_base),
            "latest_volume": self._safe_float(latest_volume),
            "volume_shrink_ratio": self._safe_float(volume_shrink_ratio),
            "recent_5d": recent_rows,
            "matched_conditions": {
                "history_ready": True,
                "inverted_t": True,
                "t_line": True,
                "combined_doji": True,
                "volume_shrink": True,
            },
        }, diagnostic

    def _candle_shadow_metrics(self, row: pd.Series) -> Dict[str, Any]:
        open_price = self._safe_float(row.get("open"))
        high = self._safe_float(row.get("high"))
        low = self._safe_float(row.get("low"))
        close = self._safe_float(row.get("close"))
        if open_price is None or high is None or low is None or close is None:
            return {"valid": False}
        candle_range = high - low
        if candle_range <= 0:
            return {"valid": False, "range": candle_range}
        body = abs(close - open_price)
        upper_shadow = high - max(open_price, close)
        lower_shadow = min(open_price, close) - low
        body_ratio = body / candle_range
        upper_shadow_ratio = max(upper_shadow, 0) / candle_range
        lower_shadow_ratio = max(lower_shadow, 0) / candle_range
        return {
            "valid": True,
            "range": self._safe_float(candle_range),
            "body": self._safe_float(body),
            "upper_shadow": self._safe_float(max(upper_shadow, 0)),
            "lower_shadow": self._safe_float(max(lower_shadow, 0)),
            "body_ratio": body_ratio,
            "upper_shadow_ratio": upper_shadow_ratio,
            "lower_shadow_ratio": lower_shadow_ratio,
            "body_ratio_pct": self._safe_float(body_ratio * 100),
            "upper_shadow_ratio_pct": self._safe_float(upper_shadow_ratio * 100),
            "lower_shadow_ratio_pct": self._safe_float(lower_shadow_ratio * 100),
        }

    def _get_turnover_rate_f(
        self,
        code: str,
        candidate: Dict[str, Any],
        turnover_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[float]:
        snapshot_values = (turnover_snapshot or {}).get("values") or {}
        snapshot_turnover = self._safe_float(snapshot_values.get(code))
        if snapshot_turnover is not None:
            return snapshot_turnover
        return self._safe_float(candidate.get("turnover_rate_f"))

    def _find_recent_breakout(
        self,
        df: pd.DataFrame,
        volume_breakout_multiplier: float,
    ) -> Dict[str, Any]:
        recent = df.tail(3)
        best: Optional[Dict[str, Any]] = None

        for idx, row in recent.iterrows():
            pos = df.index.get_loc(idx)
            if pos < 5:
                continue
            baseline = df.iloc[pos - 5:pos]["volume"].mean()
            if baseline <= 0:
                continue
            volume_ratio = row["volume"] / baseline
            is_up = row["close"] > row["open"]
            if not (is_up and volume_ratio >= volume_breakout_multiplier):
                continue

            half_price = row["open"] + (row["close"] - row["open"]) * 0.5
            after = df.iloc[pos + 1:]
            if after.empty:
                down_shrink_ok = True
                half_price_ok = row["low"] >= half_price
            else:
                down_rows = after[after["close"] < after["open"]]
                down_shrink_ok = bool(
                    down_rows.empty or (down_rows["volume"] <= row["volume"] * 0.7).all()
                )
                half_price_ok = bool(after["low"].min() >= half_price)

            candidate = {
                "passed": bool(down_shrink_ok and half_price_ok),
                "reason": "放量后下跌未缩量或股价跌破放量上涨实体一半",
                "index": idx,
                "metrics": {
                    "breakout_date": row.get("trade_date"),
                    "breakout_volume_ratio": self._safe_float(volume_ratio),
                    "breakout_half_price": self._safe_float(half_price),
                    "breakout_close": self._safe_float(row.get("close")),
                    "post_down_shrink_ok": bool(down_shrink_ok),
                    "post_half_price_ok": bool(half_price_ok),
                },
            }
            if candidate["passed"]:
                return candidate
            if best is None or volume_ratio > best["metrics"].get("breakout_volume_ratio", 0):
                best = candidate

        if best:
            return best
        return {
            "passed": False,
            "reason": f"前3个交易日内未出现放量{volume_breakout_multiplier:g}倍以上的上涨日",
            "index": None,
            "metrics": {"breakout_volume_ratio": None},
        }

    def _evaluate_chip_control(self, df: pd.DataFrame, breakout: Dict[str, Any]) -> Dict[str, Any]:
        recent20 = df.tail(20).copy()
        recent10 = df.tail(10).copy()
        close_position = (
            (recent20["close"].iloc[-1] - recent20["low"].min())
            / (recent20["high"].max() - recent20["low"].min())
            if recent20["high"].max() > recent20["low"].min()
            else 0
        )
        signed_volume = recent20.apply(
            lambda row: row["volume"] if row["close"] >= row["open"] else -row["volume"],
            axis=1,
        )
        obv_slope = signed_volume.tail(10).sum() / recent20["volume"].tail(10).sum()
        up_amount = recent20.loc[recent20["close"] >= recent20["open"], "amount"].sum()
        total_amount = recent20["amount"].sum()
        up_amount_ratio = up_amount / total_amount if total_amount else 0
        volatility_contract = (
            recent10["close"].pct_change().std()
            <= recent20["close"].pct_change().std()
            if recent20["close"].pct_change().std()
            else False
        )
        breakout_half_ok = bool((breakout.get("metrics") or {}).get("post_half_price_ok"))
        distribution_risk = obv_slope < -0.05 or (up_amount_ratio < 0.45 and close_position < 0.45)
        bull_trap_risk = close_position > 0.85 and obv_slope < 0 and up_amount_ratio < 0.5

        positive_flags = [
            obv_slope > 0.05,
            up_amount_ratio >= 0.52,
            close_position >= 0.45,
            breakout_half_ok,
            bool(volatility_contract),
        ]
        score = sum(1 for flag in positive_flags if flag)

        if distribution_risk:
            phase = "抛售"
        elif bull_trap_risk:
            phase = "诱多"
        elif close_position < 0.55 and obv_slope > 0:
            phase = "吸筹"
        elif close_position >= 0.7 and obv_slope > 0:
            phase = "拉升"
        elif breakout_half_ok and volatility_contract:
            phase = "洗盘"
        else:
            phase = "锁仓"

        passed = score >= 3 and phase not in {"抛售", "诱多"}
        reason = "筹码控盘代理指标不足，或存在抛售/诱多风险"
        return {
            "passed": passed,
            "phase": phase,
            "score": score,
            "reason": "" if passed else reason,
            "basis": [
                "OBV近10日斜率为正" if obv_slope > 0 else "OBV近10日斜率偏弱",
                "上涨日成交额占比达标" if up_amount_ratio >= 0.52 else "上涨日成交额占比不足",
                "价格守在20日区间中上部" if close_position >= 0.45 else "价格处于20日区间低位",
                "放量上涨后未跌破半分位" if breakout_half_ok else "放量上涨后半分位支撑不足",
                "波动收敛" if volatility_contract else "波动未明显收敛",
            ],
            "metrics": {
                "chip_phase": phase,
                "chip_score": score,
                "obv_slope_10d": self._safe_float(obv_slope),
                "up_amount_ratio_20d": self._safe_float(up_amount_ratio * 100),
                "close_position_20d": self._safe_float(close_position * 100),
                "distribution_risk": bool(distribution_risk),
                "bull_trap_risk": bool(bull_trap_risk),
            },
        }

    def _create_stage_stats(
        self,
        stages: Sequence[Tuple[str, str, str]] = TREND_START_TRACE_STAGES,
    ) -> Dict[str, Dict[str, Any]]:
        return {
            key: {
                "checked": 0,
                "pass_count": 0,
                "fail_count": 0,
                "pass_samples": [],
                "rejected_samples": [],
            }
            for key, _, _ in stages
        }

    def _record_diagnostic(
        self,
        trace: Dict[str, Any],
        stage_stats: Dict[str, Dict[str, int]],
        diagnostic: Dict[str, Any],
        stage_labels: Optional[Dict[str, str]] = None,
    ) -> None:
        stage_labels = stage_labels or TREND_START_STAGE_LABELS
        stage_results = diagnostic.get("stage_results") or {}
        for stage_key, passed in stage_results.items():
            if stage_key not in stage_stats:
                continue
            stage_stats[stage_key]["checked"] += 1
            if passed:
                stage_stats[stage_key]["pass_count"] += 1
                samples = stage_stats[stage_key]["pass_samples"]
            else:
                stage_stats[stage_key]["fail_count"] += 1
                samples = stage_stats[stage_key]["rejected_samples"]
            if len(samples) < 20:
                samples.append(self._build_stage_sample(diagnostic, stage_key, bool(passed)))

        if diagnostic.get("matched"):
            return

        failed_stage = diagnostic.get("failed_stage") or "unknown"
        label = stage_labels.get(failed_stage, failed_stage)
        failure_reasons = trace.setdefault("failure_reasons", {})
        failure_reasons[label] = failure_reasons.get(label, 0) + 1

        sample_rejections = trace.setdefault("sample_rejections", [])
        if len(sample_rejections) < 20:
            sample_rejections.append(
                {
                    "code": diagnostic.get("code"),
                    "name": diagnostic.get("name"),
                    "industry": diagnostic.get("industry"),
                    "failed_stage": failed_stage,
                    "failed_stage_label": label,
                    "failed_reason": diagnostic.get("failed_reason"),
                    "metrics": diagnostic.get("metrics") or {},
                }
            )

    def _record_error(self, trace: Dict[str, Any], candidate: Dict[str, Any], exc: Exception) -> None:
        failure_reasons = trace.setdefault("failure_reasons", {})
        failure_reasons["计算异常"] = failure_reasons.get("计算异常", 0) + 1
        sample_rejections = trace.setdefault("sample_rejections", [])
        if len(sample_rejections) < 20:
            code = str(candidate.get("code") or "").zfill(6)
            sample_rejections.append(
                {
                    "code": code,
                    "name": candidate.get("name") or code,
                    "industry": candidate.get("industry"),
                    "failed_stage": "error",
                    "failed_stage_label": "计算异常",
                    "failed_reason": str(exc),
                    "metrics": {},
                }
            )

    def _build_stage_steps(
        self,
        stage_stats: Dict[str, Dict[str, Any]],
        stages: Sequence[Tuple[str, str, str]] = TREND_START_TRACE_STAGES,
    ) -> List[Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []
        for key, label, description in stages:
            if (
                stages == TREND_START_TRACE_STAGES
                and (
                    (key == "price_consolidation" and SKIP_PRICE_CONSOLIDATION_FILTER)
                    or (key == "ma_up" and SKIP_MA_UP_FILTER)
                )
            ):
                continue
            stats = stage_stats[key]
            steps.append(
                {
                    "key": key,
                    "label": label,
                    "description": description,
                    "checked": stats["checked"],
                    "pass_count": stats["pass_count"],
                    "fail_count": stats["fail_count"],
                    "remaining_count": stats["pass_count"],
                    "details": {
                        "stage_diagnostics": {
                            "pass_samples": stats.get("pass_samples", []),
                            "rejected_samples": stats.get("rejected_samples", []),
                        }
                    },
                }
            )
        return steps

    def _build_stage_sample(self, diagnostic: Dict[str, Any], stage_key: str, passed: bool) -> Dict[str, Any]:
        metrics = diagnostic.get("metrics") or {}
        metric_keys = {
            "price_consolidation": [
                "history_source",
                "history_rows",
                "history_mongo_rows",
                "history_tushare_rows",
                "history_load_error",
                "sixty_day_high",
                "sixty_day_high_date",
                "pullback_from_high_pct",
                "sideways_range_pct",
                "volume_shrink_ratio",
                "recent_volume_declining",
                "abnormal_volume_days",
            ],
            "ma_up": [
                "ma5",
                "ma5_prev",
                "ma10",
                "ma10_prev",
                "ma20",
                "ma20_prev",
            ],
            "turnover_5d": [
                "turnover_rate_f",
                "turnover_rate_trade_date",
                "turnover_rate_source",
                "circ_mv",
                "total_mv",
            ],
            "volume_price_breakout": [
                "breakout_date",
                "breakout_volume_ratio",
                "breakout_half_price",
                "breakout_close",
                "post_down_shrink_ok",
                "post_half_price_ok",
            ],
            "chip_control": [
                "chip_phase",
                "chip_score",
                "obv_slope_10d",
                "up_amount_ratio_20d",
                "close_position_20d",
                "distribution_risk",
                "bull_trap_risk",
            ],
            "history_ready": [
                "history_source",
                "history_rows",
                "history_mongo_rows",
                "history_tushare_rows",
                "history_load_error",
            ],
            "inverted_t": [
                "upper_shadow_date",
                "upper_body_ratio",
                "upper_shadow_ratio",
                "upper_lower_shadow_ratio",
            ],
            "t_line": [
                "lower_shadow_date",
                "lower_body_ratio",
                "lower_shadow_ratio",
                "lower_upper_shadow_ratio",
            ],
            "combined_doji": [
                "combined_high",
                "combined_low",
                "combined_body_ratio",
            ],
            "volume_shrink": [
                "latest_volume",
                "avg_volume_prev5",
                "volume_shrink_ratio",
                "volume_shrink_ratio_pct",
                "volume_ratio_limit",
            ],
        }.get(stage_key, [])
        return {
            "code": diagnostic.get("code"),
            "name": diagnostic.get("name"),
            "industry": diagnostic.get("industry"),
            "passed": passed,
            "failed_reason": diagnostic.get("failed_reason") if not passed else None,
            "metrics": {
                key: metrics.get(key)
                for key in metric_keys
                if key in metrics and metrics.get(key) is not None
            },
        }

    def _normalize_history(self, history: pd.DataFrame) -> pd.DataFrame:
        df = history.copy()
        column_map = {
            "date": "trade_date",
            "vol": "volume",
        }
        df = df.rename(columns={key: value for key, value in column_map.items() if key in df.columns})

        for column in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")

        if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
            df["pct_chg"] = df["close"].pct_change() * 100

        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        df = df.sort_values("trade_date")
        return df

    def _format_trade_date(self, value: Any) -> str:
        text = str(value or "")
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return text

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


_preset_screening_service: Optional[PresetScreeningService] = None


def get_preset_screening_service() -> PresetScreeningService:
    global _preset_screening_service
    if _preset_screening_service is None:
        _preset_screening_service = PresetScreeningService()
    return _preset_screening_service
