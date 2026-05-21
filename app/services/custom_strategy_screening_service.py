"""Custom strategy screening service.

DeepSeek is used only to generate a constrained JSON DSL. The DSL is interpreted
by this service with a fixed allowlist of condition types; arbitrary generated
code is never executed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.services.preset_screening_service import HOT_INDUSTRY_KEYWORDS, PresetScreeningService

logger = logging.getLogger(__name__)


DEFAULT_CUSTOM_STRATEGY_DSL: Dict[str, Any] = {
    "name": "筹码锁定的缩量横盘",
    "description": "横盘缩量期间观察底部筹码锁定，排除放量破位风险，并标记放量突破信号。",
    "candidate_limit": 500,
    "limit": 100,
    "industries": [],
    "conditions": [
        {
            "id": "sideways_range",
            "label": "20日横盘振幅不超过12%",
            "type": "sideways_range",
            "lookback": 20,
            "max_range_pct": 12,
        },
        {
            "id": "volume_shrink_stable",
            "label": "5日均量低于20日前5日均量50%",
            "type": "volume_shrink",
            "recent_ma": 5,
            "ref_offset": 20,
            "max_ratio": 0.5,
        },
        {
            "id": "bottom_chip_locked",
            "label": "底部筹码锁定",
            "type": "bottom_chip_locked",
            "lower_price_ratio": 0.85,
            "upper_price_ratio": 0.92,
            "max_band_share": 0.1,
        },
        {
            "id": "no_breakdown_distribution",
            "label": "无连续破位放量风险",
            "type": "no_breakdown_distribution",
            "lookback": 20,
            "break_days": 2,
            "volume_multiplier": 1.2,
        },
    ],
    "signals": [
        {
            "id": "breakout_signal",
            "label": "放量阳线突破横盘高点",
            "type": "breakout_signal",
            "lookback": 20,
            "volume_multiplier": 1.5,
        }
    ],
}


class CustomStrategyScreeningService:
    """Generate and execute custom stock screening strategies."""

    def __init__(self) -> None:
        self.preset = PresetScreeningService()

    async def run_custom_strategy(
        self,
        strategy_text: str,
        limit: int = 100,
        candidate_limit: int = 500,
        industries: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        dsl = await self._generate_strategy_dsl(strategy_text)
        dsl["limit"] = int(limit or dsl.get("limit") or 100)
        dsl["candidate_limit"] = int(candidate_limit or dsl.get("candidate_limit") or 500)
        dsl["industries"] = list(industries or dsl.get("industries") or [])
        dsl = self._sanitize_dsl(dsl)

        trace: Dict[str, Any] = {
            "parameters": {
                "strategy_text": strategy_text,
                "limit": dsl["limit"],
                "candidate_limit": dsl["candidate_limit"],
                "industries": dsl.get("industries") or [],
            },
            "steps": [],
            "failure_reasons": {},
            "sample_rejections": [],
            "dsl": dsl,
            "generated_by": dsl.get("_generated_by", "fallback"),
        }

        candidates = await self.preset._load_candidates(
            candidate_limit=dsl["candidate_limit"],
            industries=dsl.get("industries") or None,
            float_cap_limit=float(dsl.get("float_cap_limit") or 5000),
            trace=trace,
        )

        stage_stats = self._create_stage_stats(dsl)
        items: List[Dict[str, Any]] = []
        for candidate in candidates:
            code = str(candidate.get("code") or "").zfill(6)
            if not code:
                continue
            try:
                history_result = await self.preset._load_recent_daily_history(code, days=120)
                item, diagnostic = self._evaluate_candidate(candidate, history_result.data, dsl)
                diagnostic["metrics"].update(
                    {
                        "history_source": history_result.source,
                        "history_mongo_rows": history_result.mongo_rows,
                        "history_tushare_rows": history_result.tushare_rows,
                    }
                )
                self._record_diagnostic(trace, stage_stats, diagnostic)
                if item:
                    items.append(item)
            except Exception as exc:
                logger.debug("[custom_strategy] 候选计算失败: %s %s", code, exc)
                self._record_error(trace, candidate, str(exc))

        items.sort(
            key=lambda item: (
                item.get("signals", {}).get("breakout_signal") is True,
                item.get("five_day_change_pct") or 0,
                item.get("amount") or 0,
            ),
            reverse=True,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        trace["steps"].extend(self._build_stage_steps(dsl, stage_stats))
        trace["matched_count"] = len(items)
        trace["returned_count"] = len(items[: dsl["limit"]])
        trace["took_ms"] = elapsed_ms
        return {
            "preset": "custom_strategy",
            "title": dsl.get("name") or "自定义策略",
            "description": [dsl.get("description") or "按自定义策略 DSL 解释执行。"],
            "total": len(items),
            "items": items[: dsl["limit"]],
            "took_ms": elapsed_ms,
            "trace": trace,
        }

    async def _generate_strategy_dsl(self, strategy_text: str) -> Dict[str, Any]:
        if not strategy_text or len(strategy_text.strip()) < 8:
            dsl = dict(DEFAULT_CUSTOM_STRATEGY_DSL)
            dsl["_generated_by"] = "fallback"
            return dsl

        try:
            from app.core.config import settings
            from openai import OpenAI

            api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
            if not api_key:
                api_key = self._get_deepseek_api_key_from_db()
            if not api_key:
                raise RuntimeError("未配置 DeepSeek API Key")

            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": self._dsl_system_prompt()},
                    {"role": "user", "content": strategy_text[:6000]},
                ],
                temperature=0.1,
                max_tokens=1800,
            )
            content = response.choices[0].message.content or ""
            dsl = json.loads(self._extract_json(content))
            dsl["_generated_by"] = "deepseek"
            return dsl
        except Exception as exc:
            logger.warning("[custom_strategy] DeepSeek生成DSL失败，使用内置DSL: %s", exc)
            dsl = dict(DEFAULT_CUSTOM_STRATEGY_DSL)
            dsl["_generated_by"] = "fallback"
            return dsl

    def _get_deepseek_api_key_from_db(self) -> Optional[str]:
        try:
            from pymongo import MongoClient
            from app.core.config import settings

            client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
            db = client[settings.MONGO_DB]
            doc = db.llm_providers.find_one({"name": "deepseek"}, {"api_key": 1})
            api_key = (doc or {}).get("api_key")
            client.close()
            if api_key and not str(api_key).startswith("your_"):
                return str(api_key)
        except Exception as exc:
            logger.debug("[custom_strategy] 从数据库读取 DeepSeek Key 失败: %s", exc)
        return None

    def _dsl_system_prompt(self) -> str:
        return """
你是A股量化策略转换器。只输出JSON，不要输出Markdown。
把用户的选股描述转换为受控DSL。禁止生成Python、SQL、JS或任何可执行代码。
只允许以下condition/signal type：
- sideways_range: {id,label,type,lookback,max_range_pct}
- volume_shrink: {id,label,type,recent_ma,ref_offset,max_ratio}
- bottom_chip_locked: {id,label,type,lower_price_ratio,upper_price_ratio,max_band_share}
- no_breakdown_distribution: {id,label,type,lookback,break_days,volume_multiplier}
- breakout_signal: {id,label,type,lookback,volume_multiplier}
输出结构：
{
  "name": "...",
  "description": "...",
  "limit": 100,
  "candidate_limit": 500,
  "industries": [],
  "conditions": [...],
  "signals": [...]
}
如果用户提到筹码锁定/底峰锁定，必须包含 bottom_chip_locked。
如果用户提到缩量横盘，必须包含 sideways_range 与 volume_shrink。
如果用户提到真假横盘或破位风险，必须包含 no_breakdown_distribution。
""".strip()

    def _extract_json(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return text

    def _sanitize_dsl(self, dsl: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "sideways_range",
            "volume_shrink",
            "bottom_chip_locked",
            "no_breakdown_distribution",
        }
        signal_allowed = {"breakout_signal"}
        sanitized = {
            "name": str(dsl.get("name") or "自定义策略")[:80],
            "description": str(dsl.get("description") or "自定义策略")[:300],
            "limit": max(1, min(int(dsl.get("limit") or 100), 200)),
            "candidate_limit": max(20, min(int(dsl.get("candidate_limit") or 500), 1000)),
            "industries": [str(item) for item in (dsl.get("industries") or []) if item],
            "conditions": [],
            "signals": [],
            "_generated_by": dsl.get("_generated_by", "unknown"),
        }
        for condition in dsl.get("conditions") or []:
            if condition.get("type") in allowed:
                sanitized["conditions"].append(self._sanitize_node(condition))
        for signal in dsl.get("signals") or []:
            if signal.get("type") in signal_allowed:
                sanitized["signals"].append(self._sanitize_node(signal))
        if not sanitized["conditions"]:
            fallback = self._sanitize_dsl({**DEFAULT_CUSTOM_STRATEGY_DSL, "_generated_by": "fallback"})
            fallback["name"] = sanitized["name"]
            fallback["description"] = sanitized["description"]
            return fallback
        return sanitized

    def _sanitize_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "id": re.sub(r"[^a-zA-Z0-9_]+", "_", str(node.get("id") or node.get("type")))[:50],
            "label": str(node.get("label") or node.get("type"))[:80],
            "type": node.get("type"),
        }
        numeric_defaults = {
            "lookback": 20,
            "max_range_pct": 12,
            "recent_ma": 5,
            "ref_offset": 20,
            "max_ratio": 0.5,
            "lower_price_ratio": 0.85,
            "upper_price_ratio": 0.92,
            "max_band_share": 0.1,
            "break_days": 2,
            "volume_multiplier": 1.2,
        }
        for key, default in numeric_defaults.items():
            if key in node:
                value = node.get(key)
                try:
                    value = float(value)
                    if key in {"lookback", "recent_ma", "ref_offset", "break_days"}:
                        value = int(value)
                    result[key] = value
                except Exception:
                    result[key] = default
        return result

    def _evaluate_candidate(
        self,
        candidate: Dict[str, Any],
        history: pd.DataFrame,
        dsl: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
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

        if history is None or history.empty:
            diagnostic["failed_stage"] = "history"
            diagnostic["failed_reason"] = "历史日线为空"
            return None, diagnostic

        df = self.preset._normalize_history(history)
        min_rows = max([int(c.get("lookback") or 20) for c in dsl.get("conditions", [])] + [60])
        if len(df) < min_rows:
            diagnostic["metrics"]["history_rows"] = len(df)
            diagnostic["failed_stage"] = "history"
            diagnostic["failed_reason"] = f"历史日线不足{min_rows}条"
            return None, diagnostic
        diagnostic["metrics"]["history_rows"] = len(df)

        for condition in dsl.get("conditions") or []:
            passed, metrics, reason = self._evaluate_condition(df, condition)
            key = condition["id"]
            diagnostic["stage_results"][key] = bool(passed)
            diagnostic["metrics"].update(metrics)
            if not passed:
                diagnostic["failed_stage"] = key
                diagnostic["failed_reason"] = reason
                return None, diagnostic

        signals: Dict[str, Any] = {}
        for signal in dsl.get("signals") or []:
            passed, metrics, _ = self._evaluate_condition(df, signal)
            signals[signal["id"]] = bool(passed)
            diagnostic["metrics"].update(metrics)

        item = self._build_item(candidate, df, diagnostic, signals)
        diagnostic["matched"] = True
        return item, diagnostic

    def _evaluate_condition(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        node_type = node.get("type")
        if node_type == "sideways_range":
            return self._condition_sideways_range(df, node)
        if node_type == "volume_shrink":
            return self._condition_volume_shrink(df, node)
        if node_type == "bottom_chip_locked":
            return self._condition_bottom_chip_locked(df, node)
        if node_type == "no_breakdown_distribution":
            return self._condition_no_breakdown_distribution(df, node)
        if node_type == "breakout_signal":
            return self._condition_breakout_signal(df, node)
        return False, {}, f"不支持的DSL条件: {node_type}"

    def _condition_sideways_range(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        lookback = int(node.get("lookback") or 20)
        max_range_pct = float(node.get("max_range_pct") or 12)
        window = df.tail(lookback)
        low = float(window["low"].min())
        high = float(window["high"].max())
        range_pct = (high - low) / low * 100 if low > 0 else 999
        metrics = {
            f"{node['id']}_range_pct": self.preset._safe_float(range_pct),
            f"{node['id']}_low": self.preset._safe_float(low),
            f"{node['id']}_high": self.preset._safe_float(high),
        }
        return range_pct <= max_range_pct, metrics, f"{lookback}日横盘振幅超过{max_range_pct:g}%"

    def _condition_volume_shrink(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        recent_ma = int(node.get("recent_ma") or 5)
        ref_offset = int(node.get("ref_offset") or 20)
        max_ratio = float(node.get("max_ratio") or 0.5)
        recent = df["volume"].tail(recent_ma).mean()
        ref_start = max(0, len(df) - ref_offset - recent_ma)
        ref_end = max(ref_start + recent_ma, len(df) - ref_offset)
        ref = df["volume"].iloc[ref_start:ref_end].mean()
        ratio = recent / ref if ref and ref > 0 else 999
        metrics = {
            f"{node['id']}_recent_volume_ma": self.preset._safe_float(recent),
            f"{node['id']}_ref_volume_ma": self.preset._safe_float(ref),
            f"{node['id']}_ratio": self.preset._safe_float(ratio),
        }
        return ratio < max_ratio, metrics, f"缩量比例未低于{max_ratio:g}"

    def _condition_bottom_chip_locked(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        lower = float(node.get("lower_price_ratio") or 0.85)
        upper = float(node.get("upper_price_ratio") or 0.92)
        max_band_share = float(node.get("max_band_share") or 0.1)
        close = float(df["close"].iloc[-1])
        v10 = self._winner_proxy(df, close * lower)
        v20 = self._winner_proxy(df, close * upper)
        band_share = max(v20 - v10, 0)
        metrics = {
            f"{node['id']}_winner_lower": self.preset._safe_float(v10),
            f"{node['id']}_winner_upper": self.preset._safe_float(v20),
            f"{node['id']}_band_share": self.preset._safe_float(band_share),
        }
        return band_share < max_band_share, metrics, f"底部筹码带占比不低于{max_band_share:g}"

    def _condition_no_breakdown_distribution(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        lookback = int(node.get("lookback") or 20)
        break_days = int(node.get("break_days") or 2)
        volume_multiplier = float(node.get("volume_multiplier") or 1.2)
        window = df.tail(lookback)
        box_low = float(window["low"].min())
        avg_volume = float(window["volume"].mean())
        recent = window.tail(max(break_days, 2))
        breakdown = recent["close"] < box_low
        high_volume = recent["volume"] > avg_volume * volume_multiplier
        risk = bool((breakdown & high_volume).sum() >= break_days)
        metrics = {
            f"{node['id']}_box_low": self.preset._safe_float(box_low),
            f"{node['id']}_risk_days": int((breakdown & high_volume).sum()),
        }
        return not risk, metrics, "连续破位且放量，存在抛售风险"

    def _condition_breakout_signal(self, df: pd.DataFrame, node: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
        lookback = int(node.get("lookback") or 20)
        volume_multiplier = float(node.get("volume_multiplier") or 1.5)
        prior = df.tail(lookback + 1).head(lookback)
        latest = df.iloc[-1]
        high = float(prior["high"].max())
        avg_volume = float(prior["volume"].mean())
        passed = bool(
            latest["close"] > latest["open"]
            and latest["close"] > high
            and latest["volume"] >= avg_volume * volume_multiplier
        )
        metrics = {
            f"{node['id']}_box_high": self.preset._safe_float(high),
            f"{node['id']}_volume_ratio": self.preset._safe_float(latest["volume"] / avg_volume if avg_volume else None),
        }
        return passed, metrics, "尚未出现放量突破信号"

    def _winner_proxy(self, df: pd.DataFrame, price: float) -> float:
        recent = df.tail(120)
        if recent.empty:
            return 0.0
        weights = recent["volume"].clip(lower=0)
        total = float(weights.sum())
        if total <= 0:
            return float((recent["close"] <= price).mean())
        return float(weights[recent["close"] <= price].sum() / total)

    def _build_item(
        self,
        candidate: Dict[str, Any],
        df: pd.DataFrame,
        diagnostic: Dict[str, Any],
        signals: Dict[str, Any],
    ) -> Dict[str, Any]:
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        last5 = df.tail(5)
        first5 = last5.iloc[0]
        five_day_change = (latest["close"] / first5["close"] - 1) * 100 if first5["close"] else None
        day_change_pct = (latest["close"] / previous["close"] - 1) * 100 if previous["close"] else 0
        chip = {
            "phase": "底峰锁定" if diagnostic["metrics"].get("bottom_chip_locked_band_share", 1) < 0.1 else "观察",
            "score": sum(1 for value in diagnostic.get("stage_results", {}).values() if value),
            "basis": [
                "横盘振幅收敛",
                "成交量明显萎缩",
                "底部筹码带变化较小",
            ],
            "metrics": diagnostic.get("metrics", {}),
        }
        recent_rows = [
            {
                "trade_date": row["trade_date"],
                "close": self.preset._safe_float(row.get("close")),
                "pct_chg": self.preset._safe_float(row.get("pct_chg")),
                "amount": self.preset._safe_float(row.get("amount")),
                "volume": self.preset._safe_float(row.get("volume")),
            }
            for _, row in last5.iterrows()
        ]
        return {
            "code": str(candidate.get("code") or "").zfill(6),
            "symbol": str(candidate.get("code") or "").zfill(6),
            "name": candidate.get("name") or candidate.get("code"),
            "market": "A股",
            "industry": candidate.get("industry"),
            "board": candidate.get("board") or candidate.get("market"),
            "total_mv": self.preset._safe_float(candidate.get("total_mv")),
            "circ_mv": self.preset._safe_float(candidate.get("circ_mv")),
            "close": self.preset._safe_float(latest.get("close")),
            "pct_chg": self.preset._safe_float(latest.get("pct_chg")) or day_change_pct,
            "amount": self.preset._safe_float(candidate.get("amount")) or self.preset._safe_float(latest.get("amount")),
            "five_day_change_pct": self.preset._safe_float(five_day_change),
            "five_day_total_mv": self.preset._safe_float(candidate.get("total_mv")),
            "recent_5d": recent_rows,
            "chip_control": chip,
            "matched_conditions": diagnostic.get("stage_results", {}),
            "signals": signals,
        }

    def _create_stage_stats(self, dsl: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {
            node["id"]: {"checked": 0, "pass_count": 0, "fail_count": 0, "rejected_samples": []}
            for node in dsl.get("conditions", [])
        }

    def _record_diagnostic(
        self,
        trace: Dict[str, Any],
        stage_stats: Dict[str, Dict[str, Any]],
        diagnostic: Dict[str, Any],
    ) -> None:
        for key, passed in (diagnostic.get("stage_results") or {}).items():
            if key not in stage_stats:
                continue
            stage_stats[key]["checked"] += 1
            if passed:
                stage_stats[key]["pass_count"] += 1
            else:
                stage_stats[key]["fail_count"] += 1
                if len(stage_stats[key]["rejected_samples"]) < 10:
                    stage_stats[key]["rejected_samples"].append(
                        {
                            "code": diagnostic.get("code"),
                            "name": diagnostic.get("name"),
                            "industry": diagnostic.get("industry"),
                            "failed_reason": diagnostic.get("failed_reason"),
                            "metrics": diagnostic.get("metrics", {}),
                        }
                    )

        failed_reason = diagnostic.get("failed_reason")
        if failed_reason:
            reasons = trace.setdefault("failure_reasons", {})
            reasons[failed_reason] = reasons.get(failed_reason, 0) + 1
            if len(trace.setdefault("sample_rejections", [])) < 30:
                trace["sample_rejections"].append(
                    {
                        "code": diagnostic.get("code"),
                        "name": diagnostic.get("name"),
                        "industry": diagnostic.get("industry"),
                        "failed_stage": diagnostic.get("failed_stage"),
                        "failed_reason": failed_reason,
                        "metrics": diagnostic.get("metrics", {}),
                    }
                )

    def _build_stage_steps(self, dsl: Dict[str, Any], stage_stats: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        steps = []
        for node in dsl.get("conditions", []):
            stats = stage_stats.get(node["id"], {})
            steps.append(
                {
                    "key": node["id"],
                    "label": node.get("label") or node["id"],
                    "description": f"DSL条件：{node.get('type')}",
                    "checked": stats.get("checked", 0),
                    "pass_count": stats.get("pass_count", 0),
                    "fail_count": stats.get("fail_count", 0),
                    "remaining_count": stats.get("pass_count", 0),
                    "details": {
                        "node": node,
                        "rejected_samples": stats.get("rejected_samples", []),
                    },
                }
            )
        return steps

    def _record_error(self, trace: Dict[str, Any], candidate: Dict[str, Any], error: str) -> None:
        reasons = trace.setdefault("failure_reasons", {})
        reasons[error] = reasons.get(error, 0) + 1
        if len(trace.setdefault("sample_rejections", [])) < 30:
            trace["sample_rejections"].append(
                {
                    "code": candidate.get("code"),
                    "name": candidate.get("name"),
                    "industry": candidate.get("industry"),
                    "failed_stage": "error",
                    "failed_reason": error,
                    "metrics": {},
                }
            )


_custom_strategy_service: Optional[CustomStrategyScreeningService] = None


def get_custom_strategy_screening_service() -> CustomStrategyScreeningService:
    global _custom_strategy_service
    if _custom_strategy_service is None:
        _custom_strategy_service = CustomStrategyScreeningService()
    return _custom_strategy_service
