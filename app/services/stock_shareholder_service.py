from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


VALID_SCOPES = {"top10", "float_top10"}


def normalize_code6(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def is_a_share_stock(code: str) -> bool:
    code6 = normalize_code6(code)
    if not re.fullmatch(r"\d{6}", code6):
        return False
    return code6.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689", "920"))


def to_ts_code(code: str) -> str:
    code6 = normalize_code6(code)
    if code6.startswith(("60", "68", "90")):
        return f"{code6}.SH"
    if code6.startswith(("43", "83", "87", "88", "92")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _safe_int(value: Any) -> Optional[int]:
    number = _safe_float(value)
    if number is None:
        return None
    return int(number)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_holder_name(name: Any) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


class StockShareholderService:
    collection_name = "stock_shareholders"

    def __init__(self, db):
        self.db = db

    async def ensure_indexes(self) -> None:
        collection = self.db[self.collection_name]
        try:
            await collection.create_index(
                [("code", 1), ("holder_scope", 1), ("end_date", 1), ("rank", 1)],
                unique=True,
                name="code_scope_period_rank_unique",
                background=True,
            )
            await collection.create_index(
                [("code", 1), ("holder_scope", 1), ("end_date", -1)],
                name="code_scope_period",
                background=True,
            )
            await collection.create_index(
                [("code", 1), ("holder_scope", 1), ("holder_name_normalized", 1)],
                name="code_scope_holder",
                background=True,
            )
            await collection.create_index(
                [("code", 1), ("holder_scope", 1), ("updated_at", -1)],
                name="code_scope_updated",
                background=True,
            )
        except Exception as exc:
            logger.warning("创建股东结构索引失败: %s", exc)

    @staticmethod
    def normalize_tushare_row(row: Dict[str, Any], scope: str, rank: int) -> Dict[str, Any]:
        ts_code = str(row.get("ts_code") or "")
        holder_name = row.get("holder_name") or row.get("holder_name_new") or row.get("holder") or ""
        return {
            "code": normalize_code6(row.get("code") or row.get("symbol") or ts_code),
            "ts_code": ts_code,
            "holder_scope": scope,
            "end_date": str(row.get("end_date") or row.get("report_date") or ""),
            "ann_date": str(row.get("ann_date") or ""),
            "rank": _safe_int(row.get("rank")) or rank,
            "holder_name": str(holder_name).strip(),
            "holder_name_normalized": _normalize_holder_name(holder_name),
            "hold_amount": _safe_float(row.get("hold_amount") or row.get("hold_num") or row.get("持股数")),
            "hold_ratio": _safe_float(row.get("hold_ratio") or row.get("hold_ratio_total") or row.get("持股比例")),
            "hold_change": _safe_float(row.get("hold_change") or row.get("change") or row.get("本期变化")),
            "source": "tushare",
        }

    @staticmethod
    def normalize_akshare_row(row: Dict[str, Any], code: str, scope: str, rank: int) -> Dict[str, Any]:
        holder_name = (
            row.get("股东名称")
            or row.get("股东名")
            or row.get("holder_name")
            or row.get("名称")
            or ""
        )
        return {
            "code": normalize_code6(code),
            "ts_code": to_ts_code(code),
            "holder_scope": scope,
            "end_date": str(row.get("公告日期") or row.get("截止日期") or row.get("end_date") or ""),
            "ann_date": str(row.get("公告日期") or row.get("ann_date") or ""),
            "rank": _safe_int(row.get("排名") or row.get("rank")) or rank,
            "holder_name": str(holder_name).strip(),
            "holder_name_normalized": _normalize_holder_name(holder_name),
            "hold_amount": _safe_float(row.get("持股数") or row.get("持股数量") or row.get("hold_amount")),
            "hold_ratio": _safe_float(row.get("持股比例") or row.get("持股占总股本比例") or row.get("hold_ratio")),
            "hold_change": _safe_float(row.get("持股变动") or row.get("hold_change")),
            "source": "akshare",
        }

    async def _load_cached(self, code6: str, scope: str, periods: int) -> List[Dict[str, Any]]:
        collection = self.db[self.collection_name]
        cursor = collection.find({"code": code6, "holder_scope": scope}, {"_id": 0}).sort("end_date", -1)
        docs = await cursor.to_list(length=None)
        docs = docs if isinstance(docs, list) else []
        wanted_periods = []
        seen = set()
        for doc in docs:
            period = str(doc.get("end_date") or "")
            if period and period not in seen:
                seen.add(period)
                wanted_periods.append(period)
            if len(wanted_periods) >= periods:
                break
        wanted = set(wanted_periods)
        result = [doc for doc in docs if str(doc.get("end_date") or "") in wanted]
        result.sort(key=lambda item: (str(item.get("end_date") or ""), -(item.get("rank") or 999)), reverse=True)
        return result

    async def _save_rows(self, rows: List[Dict[str, Any]]) -> None:
        collection = self.db[self.collection_name]
        now = _now_iso()
        for row in rows:
            record = dict(row)
            record.setdefault("created_at", now)
            record["updated_at"] = now
            await collection.replace_one(
                {
                    "code": record["code"],
                    "holder_scope": record["holder_scope"],
                    "end_date": record["end_date"],
                    "rank": record["rank"],
                },
                record,
                upsert=True,
            )

    async def _fetch_tushare(self, code6: str, scope: str) -> List[Dict[str, Any]]:
        try:
            from tradingagents.dataflows.providers.china.tushare import get_tushare_provider
        except Exception as exc:
            logger.warning("Tushare 股东数据提供器不可用: %s", exc)
            return []

        provider = get_tushare_provider()
        api = getattr(provider, "api", None)
        if api is None:
            logger.warning("Tushare 股东数据 API 未初始化")
            return []

        ts_code = to_ts_code(code6)
        method_name = "top10_holders" if scope == "top10" else "top10_floatholders"

        def fetch():
            method = getattr(api, method_name)
            return method(ts_code=ts_code)

        try:
            df = await asyncio.to_thread(fetch)
        except Exception as exc:
            logger.warning("Tushare %s 获取 %s 失败: %s", method_name, code6, exc)
            return []

        if df is None or getattr(df, "empty", True):
            return []

        rows: List[Dict[str, Any]] = []
        for idx, raw in enumerate(df.to_dict("records"), start=1):
            row = self.normalize_tushare_row(raw, scope=scope, rank=idx)
            if row["holder_name"] and row["end_date"]:
                rows.append(row)
        return rows

    async def _fetch_akshare(self, code6: str, scope: str) -> List[Dict[str, Any]]:
        try:
            import akshare as ak
        except Exception as exc:
            logger.info("AKShare 股东数据不可用: %s", exc)
            return []

        candidate_names = (
            ["stock_gdfx_top_10_em", "stock_gdfx_free_top_10_em"]
            if scope == "top10"
            else ["stock_gdfx_free_top_10_em", "stock_gdfx_top_10_em"]
        )
        func = None
        for name in candidate_names:
            func = getattr(ak, name, None)
            if callable(func):
                break
        if not callable(func):
            logger.info("当前 AKShare 未暴露可用股东结构接口")
            return []

        def fetch():
            try:
                return func(symbol=code6)
            except TypeError:
                return func(code6)

        try:
            df = await asyncio.to_thread(fetch)
        except Exception as exc:
            logger.warning("AKShare 股东数据获取 %s 失败: %s", code6, exc)
            return []

        if df is None or getattr(df, "empty", True):
            return []

        rows: List[Dict[str, Any]] = []
        for idx, raw in enumerate(df.to_dict("records"), start=1):
            row = self.normalize_akshare_row(raw, code=code6, scope=scope, rank=idx)
            if row["holder_name"] and row["end_date"]:
                rows.append(row)
        return rows

    def _build_payload(
        self,
        code6: str,
        scope: str,
        docs: List[Dict[str, Any]],
        source: str,
        is_cached: bool,
        warning: Optional[str] = None,
    ) -> Dict[str, Any]:
        periods: List[str] = []
        for doc in docs:
            period = str(doc.get("end_date") or "")
            if period and period not in periods:
                periods.append(period)

        if not periods:
            return {
                "status": "empty",
                "code": code6,
                "scope": scope,
                "latest_period": None,
                "previous_period": None,
                "source": source,
                "last_updated": None,
                "is_cached": is_cached,
                "latest": [],
                "changes": self._empty_changes("无可对比报告期"),
                "history": [],
                "message": "暂无股东结构数据",
                **({"warning": warning} if warning else {}),
            }

        latest_period = periods[0]
        previous_period = periods[1] if len(periods) > 1 else None
        by_period = {
            period: sorted(
                [doc for doc in docs if str(doc.get("end_date") or "") == period],
                key=lambda item: item.get("rank") or 999,
            )
            for period in periods
        }
        latest = by_period.get(latest_period, [])
        previous = by_period.get(previous_period, []) if previous_period else []
        changes = self._calculate_changes(latest, previous)
        last_updated = max((str(doc.get("updated_at") or "") for doc in docs), default=None)

        payload = {
            "status": "ok",
            "code": code6,
            "scope": scope,
            "latest_period": latest_period,
            "previous_period": previous_period,
            "source": source,
            "last_updated": last_updated,
            "is_cached": is_cached,
            "latest": latest,
            "changes": changes,
            "history": [{"period": period, "items": by_period[period]} for period in periods],
        }
        if warning:
            payload["warning"] = warning
        return payload

    @staticmethod
    def _empty_changes(message: str = "") -> Dict[str, Any]:
        return {
            "new_count": 0,
            "exited_count": 0,
            "increased_count": 0,
            "decreased_count": 0,
            "rank_changed_count": 0,
            "items": [],
            "message": message,
        }

    def _calculate_changes(self, latest: List[Dict[str, Any]], previous: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not previous:
            items = [{**item, "change_type": "no_previous", "rank_change": None} for item in latest]
            changes = self._empty_changes("无可对比报告期")
            changes["items"] = items
            return changes

        prev_map = {item.get("holder_name_normalized"): item for item in previous if item.get("holder_name_normalized")}
        latest_map = {item.get("holder_name_normalized"): item for item in latest if item.get("holder_name_normalized")}
        items: List[Dict[str, Any]] = []
        counts = {"new": 0, "exited": 0, "increased": 0, "decreased": 0, "rank_changed": 0}

        for key, item in latest_map.items():
            prev = prev_map.get(key)
            if prev is None:
                counts["new"] += 1
                items.append({**item, "change_type": "new", "previous": None, "rank_change": None})
                continue

            amount_delta = self._delta(item.get("hold_amount"), prev.get("hold_amount"))
            ratio_delta = self._delta(item.get("hold_ratio"), prev.get("hold_ratio"))
            rank_change = self._delta(prev.get("rank"), item.get("rank"))
            if rank_change not in (None, 0):
                counts["rank_changed"] += 1

            if self._is_positive(amount_delta) or self._is_positive(ratio_delta):
                change_type = "increased"
                counts["increased"] += 1
            elif self._is_negative(amount_delta) or self._is_negative(ratio_delta):
                change_type = "decreased"
                counts["decreased"] += 1
            else:
                change_type = "unchanged"

            items.append(
                {
                    **item,
                    "change_type": change_type,
                    "amount_delta": amount_delta,
                    "ratio_delta": ratio_delta,
                    "rank_change": rank_change,
                    "previous": prev,
                }
            )

        for key, prev in prev_map.items():
            if key not in latest_map:
                counts["exited"] += 1
                items.append({**prev, "change_type": "exited", "previous": prev, "rank_change": None})

        return {
            "new_count": counts["new"],
            "exited_count": counts["exited"],
            "increased_count": counts["increased"],
            "decreased_count": counts["decreased"],
            "rank_changed_count": counts["rank_changed"],
            "items": items,
        }

    @staticmethod
    def _delta(current: Any, previous: Any) -> Optional[float]:
        current_num = _safe_float(current)
        previous_num = _safe_float(previous)
        if current_num is None or previous_num is None:
            return None
        return current_num - previous_num

    @staticmethod
    def _is_positive(value: Optional[float]) -> bool:
        return value is not None and value > 0

    @staticmethod
    def _is_negative(value: Optional[float]) -> bool:
        return value is not None and value < 0

    async def get_shareholders(
        self,
        code: str,
        scope: str = "top10",
        periods: int = 4,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        code6 = normalize_code6(code)
        if scope not in VALID_SCOPES:
            raise ValueError(f"unsupported shareholder scope: {scope}")
        if not is_a_share_stock(code6):
            return self._build_payload(code6, scope, [], source="unsupported", is_cached=False)

        await self.ensure_indexes()
        cached_docs = await self._load_cached(code6, scope, periods)
        if cached_docs and not refresh:
            return self._build_payload(code6, scope, cached_docs, source="mongodb", is_cached=True)

        rows = await self._fetch_tushare(code6, scope)
        source = "tushare"
        if not rows:
            rows = await self._fetch_akshare(code6, scope)
            source = "akshare" if rows else "mongodb"

        warning = None
        if rows:
            await self._save_rows(rows)
        else:
            warning = "股东结构外部刷新失败，返回缓存数据" if cached_docs else None

        reloaded_docs = await self._load_cached(code6, scope, periods)
        if reloaded_docs:
            return self._build_payload(
                code6,
                scope,
                reloaded_docs,
                source=source if rows else "mongodb",
                is_cached=not bool(rows),
                warning=warning,
            )

        return self._build_payload(code6, scope, [], source=source, is_cached=False)
