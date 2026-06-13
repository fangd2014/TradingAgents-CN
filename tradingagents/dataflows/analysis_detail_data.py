"""
Stock-detail data summaries for the analysis agent data flow.

The frontend detail page already exposes shareholder, financial, industry and
technical datasets. This module reuses the same MongoDB-backed services and
formats a compact Markdown context for LLM analysis tools.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from tradingagents.utils.logging_init import get_logger
from tradingagents.utils.stock_utils import StockUtils
from app.services.stock_detail_insight_service import calculate_magic_nine

logger = get_logger("default")
MIN_SHAREHOLDER_ROWS_PER_PERIOD = 5


def normalize_code6(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _is_supported_a_share(code: str) -> bool:
    code6 = normalize_code6(code)
    return bool(code6.isdigit() and len(code6) == 6 and StockUtils.get_market_info(code6).get("is_china"))


def _safe_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _fmt_number(value: Any, digits: int = 2) -> str:
    number = _safe_number(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _fmt_yi(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "-"
    return f"{number / 100000000:.2f}亿元"


def _fmt_percent(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "-"
    return f"{number:.2f}%"


def _fmt_share_amount(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "-"
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿股"
    if abs(number) >= 10000:
        return f"{number / 10000:.2f}万股"
    return f"{number:.0f}股"


def _recent_rows(rows: Iterable[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    cleaned = [row for row in rows or [] if isinstance(row, dict)]
    cleaned.sort(key=lambda item: str(item.get("end_date") or item.get("report_period") or ""), reverse=True)
    return cleaned[:limit]


def _compact_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _get_sync_db():
    try:
        from app.core.database import get_mongo_db_sync

        return get_mongo_db_sync()
    except Exception as exc:
        logger.warning("分析详情数据MongoDB连接不可用: %s", exc)
        return None


def _source_priority(source: Any) -> int:
    source_text = str(source or "").lower()
    if source_text == "tushare":
        return 0
    if source_text == "akshare":
        return 1
    if source_text == "baostock":
        return 2
    return 9


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _find_many(collection, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return [doc for doc in collection.find(query, projection or {"_id": 0}) if isinstance(doc, dict)]


def _get_financial_detail(db, code6: str, periods: int) -> Dict[str, Any]:
    docs = _find_many(db["stock_financial_data"], {"symbol": code6}, {"_id": 0})
    docs.sort(key=lambda item: str(item.get("report_period") or ""), reverse=True)
    docs = docs[:periods]
    if not docs:
        return {"status": "empty", "summary": {}, "income_statement": [], "balance_sheet": [], "cashflow_statement": [], "main_business": []}

    latest = docs[0]
    raw_data = latest.get("raw_data") or {}
    income_statement = raw_data.get("income_statement") or []
    balance_sheet = raw_data.get("balance_sheet") or []
    cashflow_statement = raw_data.get("cashflow_statement") or raw_data.get("cash_flow") or []
    financial_indicators = raw_data.get("financial_indicators") or []
    main_business = raw_data.get("main_business") or []
    latest_income = income_statement[0] if income_statement else {}
    latest_balance = balance_sheet[0] if balance_sheet else {}
    latest_indicator = financial_indicators[0] if financial_indicators else {}

    summary = {
        "report_period": latest.get("report_period"),
        "revenue": _first_present(latest_income.get("revenue"), latest.get("revenue")),
        "net_profit": _first_present(
            latest_income.get("n_income"),
            latest_income.get("net_profit"),
            latest.get("net_income"),
            latest.get("net_profit"),
        ),
        "roe": _first_present(latest_indicator.get("roe"), latest.get("roe")),
        "gross_margin": _first_present(latest_indicator.get("grossprofit_margin"), latest.get("gross_margin")),
        "netprofit_margin": latest_indicator.get("netprofit_margin"),
        "debt_to_assets": _first_present(
            latest_indicator.get("debt_to_assets"),
            latest_balance.get("debt_to_assets"),
            latest.get("debt_to_assets"),
        ),
        "net_income": _first_present(latest.get("net_income"), latest_income.get("n_income"), latest_income.get("net_profit")),
        "total_assets": _first_present(latest.get("total_assets"), latest_balance.get("total_assets")),
        "total_liab": _first_present(latest.get("total_liab"), latest_balance.get("total_liab")),
    }
    return {
        "status": "ok",
        "summary": summary,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cashflow_statement": cashflow_statement,
        "main_business": main_business,
    }


def _normalize_metric_value(doc: Dict[str, Any], metric: str) -> Optional[float]:
    aliases = {
        "pe": ["pe", "pe_ttm"],
        "pb": ["pb", "pb_mrq"],
        "ps": ["ps", "ps_ttm"],
        "roe": ["roe"],
        "gross_margin": ["gross_margin", "grossprofit_margin"],
        "netprofit_margin": ["netprofit_margin"],
        "debt_to_assets": ["debt_to_assets", "debt_ratio"],
        "revenue_growth": ["revenue_yoy", "or_yoy"],
        "net_profit_growth": ["netprofit_yoy", "profit_dedt_yoy"],
        "total_mv": ["total_mv"],
    }
    for field in aliases.get(metric, [metric]):
        value = _safe_number(doc.get(field))
        if value is not None:
            return value
    return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _best_basic_docs(db, codes: List[str]) -> Dict[str, Dict[str, Any]]:
    docs = _find_many(db["stock_basic_info"], {"code": {"$in": codes}}, {"_id": 0})
    by_code: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        code = normalize_code6(doc.get("code") or doc.get("symbol") or doc.get("ts_code") or "")
        if not code:
            continue
        selected = by_code.get(code)
        doc_priority = (0 if str(doc.get("industry") or "").strip() else 1, _source_priority(doc.get("source")))
        selected_priority = (0 if selected and str(selected.get("industry") or "").strip() else 1, _source_priority(selected.get("source") if selected else None))
        if selected is None or doc_priority < selected_priority:
            by_code[code] = doc
    return by_code


def _latest_financial_docs(db, codes: List[str]) -> Dict[str, Dict[str, Any]]:
    docs = _find_many(
        db["stock_financial_data"],
        {"$or": [{"symbol": {"$in": codes}}, {"code": {"$in": codes}}]},
        {"_id": 0},
    )
    by_code: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        code = normalize_code6(doc.get("symbol") or doc.get("code") or "")
        if code not in codes:
            continue
        selected = by_code.get(code)
        selected_period = str(selected.get("report_period") or "") if selected else ""
        current_period = str(doc.get("report_period") or "")
        if selected is None or current_period > selected_period:
            by_code[code] = doc
        elif current_period == selected_period and _source_priority(doc.get("data_source")) < _source_priority(selected.get("data_source")):
            by_code[code] = doc
    return by_code


def _get_industry_comparison(db, code6: str) -> Dict[str, Any]:
    basic = _best_basic_docs(db, [code6]).get(code6, {})
    industry = str(basic.get("industry") or "").strip()
    if not industry:
        return {"status": "empty", "industry": None, "sample_count": 0, "metrics": {}}

    industry_docs = _find_many(db["stock_basic_info"], {"industry": industry}, {"_id": 0, "code": 1, "symbol": 1, "ts_code": 1, "industry": 1, "source": 1, "pe": 1, "pb": 1, "ps": 1, "roe": 1, "total_mv": 1})
    codes = []
    seen = set()
    for doc in industry_docs:
        code = normalize_code6(doc.get("code") or doc.get("symbol") or doc.get("ts_code") or "")
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    if code6 not in seen:
        codes.append(code6)

    merged = _best_basic_docs(db, codes)
    financial_docs = _latest_financial_docs(db, codes)
    for code, financial_doc in financial_docs.items():
        combined = dict(merged.get(code, {}))
        combined.update(financial_doc)
        merged[code] = combined

    docs = list(merged.values())
    stock_doc = merged.get(code6)
    if not stock_doc:
        return {"status": "empty", "industry": industry, "sample_count": len(docs), "metrics": {}}

    metric_names = ["pe", "pb", "ps", "roe", "gross_margin", "netprofit_margin", "debt_to_assets", "revenue_growth", "net_profit_growth", "total_mv"]
    metrics = {}
    for metric in metric_names:
        values = [value for value in (_normalize_metric_value(doc, metric) for doc in docs) if value is not None]
        stock_value = _normalize_metric_value(stock_doc, metric)
        median_value = _median(values)
        metrics[metric] = {
            "stock_value": stock_value,
            "industry_median": median_value,
            "percentile": round(100.0 * sum(1 for value in values if stock_value is not None and value <= stock_value) / len(values), 2) if stock_value is not None and values else None,
            "rank": 1 + sum(1 for value in values if stock_value is not None and value > stock_value) if stock_value is not None and values else None,
            "sample_count": len(values),
        }

    return {"status": "ok", "industry": industry, "sample_count": len(docs), "metrics": metrics}


def _normalize_holder_name(name: Any) -> str:
    import re

    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _calculate_shareholder_changes(latest: List[Dict[str, Any]], previous: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not previous:
        return {"new_count": 0, "exited_count": 0, "increased_count": 0, "decreased_count": 0, "rank_changed_count": 0, "items": latest}

    prev_map = {_normalize_holder_name(item.get("holder_name")): item for item in previous if item.get("holder_name")}
    latest_map = {_normalize_holder_name(item.get("holder_name")): item for item in latest if item.get("holder_name")}
    counts = {"new_count": 0, "exited_count": 0, "increased_count": 0, "decreased_count": 0, "rank_changed_count": 0}
    items = []
    for key, item in latest_map.items():
        prev = prev_map.get(key)
        if prev is None:
            counts["new_count"] += 1
            items.append({**item, "change_type": "new"})
            continue
        amount_delta = (_safe_number(item.get("hold_amount")) or 0) - (_safe_number(prev.get("hold_amount")) or 0)
        ratio_delta = (_safe_number(item.get("hold_ratio")) or 0) - (_safe_number(prev.get("hold_ratio")) or 0)
        rank_delta = (_safe_number(prev.get("rank")) or 0) - (_safe_number(item.get("rank")) or 0)
        if rank_delta:
            counts["rank_changed_count"] += 1
        if amount_delta > 0 or ratio_delta > 0:
            counts["increased_count"] += 1
            change_type = "increased"
        elif amount_delta < 0 or ratio_delta < 0:
            counts["decreased_count"] += 1
            change_type = "decreased"
        else:
            change_type = "unchanged"
        items.append({**item, "change_type": change_type})
    for key, prev in prev_map.items():
        if key not in latest_map:
            counts["exited_count"] += 1
            items.append({**prev, "change_type": "exited"})
    return {**counts, "items": items}


def _get_shareholders(db, code6: str, scope: str, periods: int = 4) -> Dict[str, Any]:
    docs = _find_many(db["stock_shareholders"], {"code": code6, "holder_scope": scope}, {"_id": 0})
    if not docs:
        _refresh_shareholders(db, code6, scope)
        docs = _find_many(db["stock_shareholders"], {"code": code6, "holder_scope": scope}, {"_id": 0})

    docs.sort(key=lambda item: (str(item.get("end_date") or ""), -(item.get("rank") or 999)), reverse=True)
    period_counts: Dict[str, int] = {}
    for doc in docs:
        period = str(doc.get("end_date") or "")
        if period:
            period_counts[period] = period_counts.get(period, 0) + 1
    wanted_periods = []
    for doc in docs:
        period = str(doc.get("end_date") or "")
        if period_counts.get(period, 0) < MIN_SHAREHOLDER_ROWS_PER_PERIOD:
            continue
        if period and period not in wanted_periods:
            wanted_periods.append(period)
        if len(wanted_periods) >= periods:
            break
    wanted = set(wanted_periods)
    docs = [doc for doc in docs if str(doc.get("end_date") or "") in wanted]
    if not wanted_periods:
        return {"status": "empty", "latest": [], "changes": {}, "latest_period": None, "previous_period": None}

    latest_period = wanted_periods[0]
    previous_period = wanted_periods[1] if len(wanted_periods) > 1 else None
    latest = sorted([doc for doc in docs if str(doc.get("end_date") or "") == latest_period], key=lambda item: item.get("rank") or 999)
    previous = sorted([doc for doc in docs if str(doc.get("end_date") or "") == previous_period], key=lambda item: item.get("rank") or 999) if previous_period else []
    return {
        "status": "ok",
        "latest_period": latest_period,
        "previous_period": previous_period,
        "latest": latest,
        "changes": _calculate_shareholder_changes(latest, previous),
    }


def _refresh_shareholders(db, code6: str, scope: str) -> None:
    try:
        from app.services.stock_shareholder_service import fetch_tushare_shareholder_rows_sync

        rows = fetch_tushare_shareholder_rows_sync(code6, scope)
        if not rows:
            return

        now = datetime.now(timezone.utc).isoformat()
        collection = db["stock_shareholders"]
        for row in rows:
            record = dict(row)
            record.setdefault("created_at", now)
            record["updated_at"] = now
            collection.replace_one(
                {
                    "code": record["code"],
                    "holder_scope": record["holder_scope"],
                    "end_date": record["end_date"],
                    "rank": record["rank"],
                },
                record,
                upsert=True,
            )
        logger.info("已刷新 %s %s 股东结构数据: %s 条", code6, scope, len(rows))
    except Exception as exc:
        logger.warning("刷新 %s %s 股东结构数据失败: %s", code6, scope, exc)


def _format_financial_detail(data: Dict[str, Any]) -> str:
    if not data or data.get("status") not in {"ok", "sample_insufficient"}:
        return "## 详细财务数据\n- 暂无可用数据。"

    summary = data.get("summary") or {}
    lines = [
        "## 详细财务数据",
        f"- 报告期: {summary.get('report_period') or '-'}",
        f"- 营业收入: {_fmt_yi(summary.get('revenue'))}",
        f"- 净利润: {_fmt_yi(summary.get('net_profit') or summary.get('net_income'))}",
        f"- 总资产: {_fmt_yi(summary.get('total_assets'))}",
        f"- 总负债: {_fmt_yi(summary.get('total_liab'))}",
        f"- ROE: {_fmt_percent(summary.get('roe'))}",
        f"- 毛利率: {_fmt_percent(summary.get('gross_margin'))}",
        f"- 净利率: {_fmt_percent(summary.get('netprofit_margin'))}",
        f"- 资产负债率: {_fmt_percent(summary.get('debt_to_assets'))}",
    ]

    income_rows = _recent_rows(data.get("income_statement") or [], limit=6)
    income_table = _compact_table(
        ["报告期", "营业收入", "归母净利润", "营业利润"],
        [
            [
                str(row.get("end_date") or "-"),
                _fmt_yi(row.get("revenue")),
                _fmt_yi(row.get("n_income_attr_p")),
                _fmt_yi(row.get("oper_profit")),
            ]
            for row in income_rows
        ],
    )
    if income_table:
        lines.extend(["", "### 利润表摘要", income_table])

    balance_rows = _recent_rows(data.get("balance_sheet") or [], limit=6)
    balance_table = _compact_table(
        ["报告期", "总资产", "总负债", "货币资金"],
        [
            [
                str(row.get("end_date") or "-"),
                _fmt_yi(row.get("total_assets")),
                _fmt_yi(row.get("total_liab")),
                _fmt_yi(row.get("money_cap")),
            ]
            for row in balance_rows
        ],
    )
    if balance_table:
        lines.extend(["", "### 资产负债表摘要", balance_table])

    cash_rows = _recent_rows(data.get("cashflow_statement") or [], limit=6)
    cash_table = _compact_table(
        ["报告期", "经营现金流", "投资现金流", "筹资现金流"],
        [
            [
                str(row.get("end_date") or "-"),
                _fmt_yi(row.get("n_cashflow_act")),
                _fmt_yi(row.get("n_cashflow_inv_act")),
                _fmt_yi(row.get("n_cashflow_fin_act")),
            ]
            for row in cash_rows
        ],
    )
    if cash_table:
        lines.extend(["", "### 现金流量表摘要", cash_table])

    business_rows = _recent_rows(data.get("main_business") or [], limit=8)
    business_table = _compact_table(
        ["报告期", "项目", "收入", "毛利", "成本"],
        [
            [
                str(row.get("end_date") or "-"),
                str(row.get("bz_item") or "-")[:24],
                _fmt_yi(row.get("bz_sales")),
                _fmt_yi(row.get("bz_profit")),
                _fmt_yi(row.get("bz_cost")),
            ]
            for row in business_rows
        ],
    )
    if business_table:
        lines.extend(["", "### 主营业务构成", business_table])

    return "\n".join(lines)


def _format_industry_comparison(data: Dict[str, Any]) -> str:
    if not data or not data.get("metrics"):
        return "## 行业对比\n- 暂无可用数据。"

    labels = {
        "pe": "PE",
        "pb": "PB",
        "ps": "PS",
        "roe": "ROE",
        "gross_margin": "毛利率",
        "netprofit_margin": "净利率",
        "debt_to_assets": "资产负债率",
        "revenue_growth": "营收增速",
        "net_profit_growth": "净利润增速",
        "total_mv": "总市值",
    }
    rows = []
    for key, metric in (data.get("metrics") or {}).items():
        metric = metric or {}
        rows.append(
            [
                labels.get(key, key),
                _fmt_number(metric.get("stock_value")),
                _fmt_number(metric.get("industry_median")),
                _fmt_number(metric.get("percentile")),
                str(metric.get("rank") or "-"),
            ]
        )

    return "\n".join(
        [
            "## 行业对比",
            f"- 行业: {data.get('industry') or '-'}",
            f"- 样本数: {data.get('sample_count') or 0}",
            _compact_table(["指标", "个股", "行业中位数", "百分位", "排名"], rows),
        ]
    )


def _format_technical_factors(data: Dict[str, Any]) -> str:
    factors = data.get("factors") or {}
    magic = data.get("magic_nine") or {}
    if not factors and not magic:
        return "## 技术因子与神奇九转\n- 暂无可用数据。"

    labels = {
        "ma_5": "MA5",
        "ma_20": "MA20",
        "ema_12": "EMA12",
        "ema_26": "EMA26",
        "macd": "MACD",
        "rsi_14": "RSI14",
        "boll": "BOLL",
        "kdj": "KDJ",
        "atr_14": "ATR14",
        "volume_ma_5": "5日均量",
        "turnover_summary": "换手率",
    }
    rows = []
    for key, value in factors.items():
        value = value or {}
        if "latest" in value:
            latest = _fmt_number(value.get("latest"))
        elif key == "macd":
            latest = f"DIF {_fmt_number(value.get('dif'))} / DEA {_fmt_number(value.get('dea'))} / MACD {_fmt_number(value.get('macd'))}"
        elif key == "boll":
            latest = f"{_fmt_number(value.get('lower'))} - {_fmt_number(value.get('upper'))}"
        elif key == "kdj":
            latest = f"K {_fmt_number(value.get('k'))} / D {_fmt_number(value.get('d'))} / J {_fmt_number(value.get('j'))}"
        else:
            latest = "-"
        rows.append([labels.get(key, key), latest, str(value.get("signal") or "-")])

    magic_line = (
        f"- 神奇九转: 状态={magic.get('status') or '-'}, "
        f"方向={magic.get('current_direction') or '-'}, 当前计数={magic.get('current_count') or 0}"
    )
    return "\n".join(
        [
            "## 技术因子与神奇九转",
            magic_line,
            _compact_table(["因子", "最新值", "信号"], rows),
        ]
    )


def _format_shareholders(title: str, data: Dict[str, Any]) -> str:
    if not data or data.get("status") != "ok":
        return f"## {title}\n- 暂无可用数据。"

    changes = data.get("changes") or {}
    latest = data.get("latest") or []
    rows = [
        [
            str(row.get("rank") or "-"),
            str(row.get("holder_name") or "-")[:32],
            _fmt_share_amount(row.get("hold_amount")),
            _fmt_percent(row.get("hold_ratio")),
            str(row.get("change_type") or "-"),
        ]
        for row in latest[:10]
    ]

    return "\n".join(
        [
            f"## {title}",
            f"- 最新期: {data.get('latest_period') or '-'}；对比期: {data.get('previous_period') or '-'}",
            (
                "- 变化: "
                f"新增{changes.get('new_count', 0)}、退出{changes.get('exited_count', 0)}、"
                f"增持{changes.get('increased_count', 0)}、减持{changes.get('decreased_count', 0)}、"
                f"排名变化{changes.get('rank_changed_count', 0)}"
            ),
            _compact_table(["排名", "股东", "持股数量", "持股比例", "状态"], rows),
        ]
    )


def _latest_datasource_snapshot(db, code6: str) -> Dict[str, Any]:
    try:
        doc = db["favorite_stock_data_snapshots"].find_one(
            {"code": code6},
            {"_id": 0},
            sort=[("refreshed_at", -1)],
        )
        return doc or {}
    except Exception as exc:
        logger.warning("读取自选股数据源快照失败 %s: %s", code6, exc)
        return {}


def _fmt_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "-")


def _format_datasource_features(snapshot: Dict[str, Any]) -> str:
    if not snapshot:
        return "## 数据源特色快照\n- 暂无可用数据。"

    compact = snapshot.get("compact") or {}
    quote = compact.get("quote") or snapshot.get("quote") or {}
    metrics = compact.get("tencent_metrics") or {}
    deep = compact.get("mootdx_deep") or {}
    report_summary = compact.get("research_reports") or {}
    latest_report = report_summary.get("latest") or {}
    news_summary = compact.get("news") or {}
    latest_news = news_summary.get("latest_stock_news") or {}
    announcements = compact.get("announcements") or {}
    latest_announcement = announcements.get("latest") or {}
    data_sources = compact.get("data_sources") or {}

    lines = [
        "## 数据源特色快照",
        f"- 快照时间: {_fmt_time(snapshot.get('refreshed_at'))}",
        f"- 数据源覆盖: {', '.join(f'{key}={value}' for key, value in data_sources.items()) or '-'}",
        (
            "- 实时行情: "
            f"价格={_fmt_number(quote.get('price') or quote.get('close'))}，"
            f"涨跌幅={_fmt_percent(quote.get('pct_chg'))}，"
            f"成交额={_fmt_yi(quote.get('amount'))}，"
            f"日期={quote.get('trade_date') or '-'}，来源={quote.get('source') or '-'}"
        ),
        (
            "- 腾讯指标: "
            f"PE(TTM)={_fmt_number(metrics.get('pe_ttm'))}，"
            f"PB={_fmt_number(metrics.get('pb'))}，"
            f"总市值={_fmt_yi(metrics.get('total_mv'))}，"
            f"流通市值={_fmt_yi(metrics.get('float_mv'))}，"
            f"换手率={_fmt_percent(metrics.get('turnover_rate'))}，"
            f"振幅={_fmt_percent(metrics.get('amplitude'))}"
        ),
        (
            "- mootdx深行情: "
            f"盘口快照={deep.get('order_book_count', 0)}，"
            f"逐笔成交={deep.get('transactions_count', 0)}，"
            f"finance字段={deep.get('finance_fields', 0)}，"
            f"F10={', '.join(deep.get('f10_categories') or []) or '-'}"
        ),
        (
            "- 研报/EPS: "
            f"研报数={report_summary.get('count', 0)}，"
            f"最新={latest_report.get('publish_date') or '-'} "
            f"{latest_report.get('institution') or '-'}《{latest_report.get('title') or '-'}》，"
            f"评级={latest_report.get('rating') or '-'}，"
            f"EPS预测={report_summary.get('eps_forecast') or '-'}"
        ),
        f"- 题材tags: {', '.join(compact.get('theme_tags') or []) or '-'}",
        (
            "- 新闻三件套: "
            f"个股新闻={news_summary.get('stock_news_count', 0)}，"
            f"财联社快讯={news_summary.get('cls_flash_count', 0)}，"
            f"全球资讯={news_summary.get('global_news_count', 0)}，"
            f"最新个股新闻={latest_news.get('publish_time') or '-'} {latest_news.get('title') or '-'}"
        ),
        (
            "- 巨潮公告: "
            f"公告数={announcements.get('count', 0)}，"
            f"最新={latest_announcement.get('publish_date') or '-'} {latest_announcement.get('title') or '-'}"
        ),
        (
            "- 股东数据: "
            f"前十大={((compact.get('shareholders') or {}).get('top10_count') or 0)}，"
            f"前十大流通={((compact.get('shareholders') or {}).get('float_top10_count') or 0)}，"
            f"来源={((compact.get('shareholders') or {}).get('data_source') or '-')}"
        ),
    ]

    hotspots = compact.get("hotspots") or []
    if hotspots:
        hotspot_rows = [
            [
                str(item.get("name") or item.get("symbol") or "-"),
                ", ".join(item.get("tags") or [])[:32] or "-",
                str(item.get("reason") or "-")[:48],
            ]
            for item in hotspots[:5]
        ]
        lines.extend(["", "### 同花顺热点归因", _compact_table(["名称", "题材", "归因"], hotspot_rows)])

    reports = snapshot.get("research_reports") or []
    if reports:
        report_rows = [
            [
                str(row.get("publish_date") or "-"),
                str(row.get("institution") or "-")[:16],
                str(row.get("rating") or "-"),
                str(row.get("title") or "-")[:42],
            ]
            for row in reports[:5]
        ]
        lines.extend(["", "### 最近研报", _compact_table(["日期", "机构", "评级", "标题"], report_rows)])

    source_status = snapshot.get("source_status") or compact.get("source_status") or {}
    failed = [
        f"{key}: {value.get('error') or value.get('reason') or '不可用'}"
        for key, value in source_status.items()
        if isinstance(value, dict) and not value.get("ok", False)
    ]
    if failed:
        lines.extend(["", "### 暂不可用数据源", "\n".join(f"- {item}" for item in failed[:8])])

    return "\n".join(lines)


def get_stock_datasource_feature_context(ticker: str) -> str:
    """Return latest connected-source feature snapshot for favorite A-shares."""
    code6 = normalize_code6(ticker)
    if not _is_supported_a_share(code6):
        return ""

    db = _get_sync_db()
    if db is None:
        return ""

    try:
        return "\n\n".join(["# 自选股数据源特色数据", _format_datasource_features(_latest_datasource_snapshot(db, code6))]).strip()
    except Exception as exc:
        logger.warning("获取自选股数据源特色数据失败: %s", exc)
        return ""


def get_stock_fundamental_detail_context(ticker: str, periods: int = 40) -> str:
    """Return compact shareholder, financial and industry context for A-share analysis."""
    code6 = normalize_code6(ticker)
    if not _is_supported_a_share(code6):
        return ""

    db = _get_sync_db()
    if db is None:
        return ""

    try:
        financial = _get_financial_detail(db, code6, periods=periods)
        industry = _get_industry_comparison(db, code6)
        top10 = _get_shareholders(db, code6, scope="top10", periods=4)
        float_top10 = _get_shareholders(db, code6, scope="float_top10", periods=4)
        datasource_features = _format_datasource_features(_latest_datasource_snapshot(db, code6))

        sections = [
            "# 股票深度基本面数据",
            datasource_features,
            _format_financial_detail(financial),
            _format_industry_comparison(industry),
            _format_shareholders("前十大股东", top10),
            _format_shareholders("前十大流通股东", float_top10),
        ]
        return "\n\n".join(section for section in sections if section).strip()
    except Exception as exc:
        logger.warning("获取股票深度基本面数据失败: %s", exc)
        return ""


def get_stock_technical_detail_context(ticker: str, limit: int = 160) -> str:
    """Return compact technical factor and magic-nine context for A-share analysis."""
    code6 = normalize_code6(ticker)
    if not _is_supported_a_share(code6):
        return ""

    db = _get_sync_db()
    if db is None:
        return ""

    try:
        from app.services.stock_detail_insight_service import StockDetailInsightService

        bars = _find_many(
            db["stock_daily_quotes"],
            {"symbol": code6, "period": {"$in": ["daily", None]}},
            {"_id": 0},
        )
        if not bars:
            bars = _find_many(db["stock_daily_quotes"], {"symbol": code6}, {"_id": 0})
        bars.sort(key=lambda item: str(item.get("trade_date") or item.get("date") or ""))
        bars = bars[-max(int(limit or 0), 1):]

        insight_service = StockDetailInsightService(db=db)
        technical = {
            "status": "ok" if len(bars) >= 13 else "insufficient_data",
            "magic_nine": calculate_magic_nine(bars),
            "factors": insight_service._technical_factor_payload(bars) if len(bars) >= 13 else {},
        }
        return "\n\n".join(["# 股票技术面因子数据", _format_technical_factors(technical)]).strip()
    except Exception as exc:
        logger.warning("获取股票技术面因子数据失败: %s", exc)
        return ""
