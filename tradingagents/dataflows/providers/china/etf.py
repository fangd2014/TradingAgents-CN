"""
A股ETF数据工具。

优先使用 AKShare 的场内 ETF 接口，输出适合多智能体分析的文本报告。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from tradingagents.tools.analysis.indicators import IndicatorSpec, compute_many
from tradingagents.utils.logging_manager import get_logger

logger = get_logger("agents")


def _load_akshare() -> Any:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("akshare 未安装，无法获取A股ETF数据") from exc
    return ak


def _format_ak_date(date_text: str | None) -> str:
    if not date_text:
        return datetime.now().strftime("%Y%m%d")
    return str(date_text).replace("-", "")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_row_by_code(df: pd.DataFrame, code: str) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None

    code_text = str(code).zfill(6)
    for column in ("代码", "基金代码", "symbol", "代码代码"):
        if column not in df.columns:
            continue
        normalized = df[column].astype(str).str.extract(r"(\d{6})", expand=False)
        matches = df[normalized == code_text]
        if not matches.empty:
            return matches.iloc[0]

    return None


def _standardize_etf_history(df: pd.DataFrame, code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    colmap = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "vol",
        "volume": "vol",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }
    out = df.rename(columns={column: colmap.get(column, column) for column in df.columns}).copy()
    out["code"] = str(code).zfill(6)

    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"]).sort_values("date")

    for column in ("open", "close", "high", "low", "vol", "amount", "pct_change", "turnover"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")

    if "pct_change" not in out.columns and "close" in out.columns:
        out["pct_change"] = out["close"].pct_change() * 100

    return out


def _sina_symbol_for_etf(code: str) -> str:
    code_text = str(code).zfill(6)
    prefix = "sh" if code_text.startswith(("51", "56", "58")) else "sz"
    return f"{prefix}{code_text}"


def get_china_etf_history_dataframe(
    code: str,
    start_date: str | None,
    end_date: str | None,
    adjust: str = "",
) -> pd.DataFrame:
    """获取并标准化A股ETF历史行情。"""
    ak = _load_akshare()
    code_text = str(code).zfill(6)

    try:
        df = ak.fund_etf_hist_em(
            symbol=code_text,
            period="daily",
            start_date=_format_ak_date(start_date),
            end_date=_format_ak_date(end_date),
            adjust=adjust,
        )
        return _standardize_etf_history(df, code_text)
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 东方财富ETF历史行情获取失败，尝试新浪备用接口: {code_text}, {exc}")

    df = ak.fund_etf_hist_sina(symbol=_sina_symbol_for_etf(code_text))
    history = _standardize_etf_history(df, code_text)
    if history.empty or "date" not in history.columns:
        return history

    if start_date:
        start_dt = pd.to_datetime(start_date, errors="coerce")
        if not pd.isna(start_dt):
            history = history[history["date"] >= start_dt]
    if end_date:
        end_dt = pd.to_datetime(end_date, errors="coerce")
        if not pd.isna(end_dt):
            history = history[history["date"] <= end_dt]

    return history


def get_china_etf_lightweight_spot_row(code: str) -> Optional[pd.Series]:
    """从轻量接口获取ETF基础行情行。"""
    code_text = str(code).zfill(6)
    ak = _load_akshare()

    try:
        ths_df = ak.fund_etf_spot_ths()
        row = _find_row_by_code(ths_df, code_text)
        if row is not None:
            return row.rename(
                {
                    "基金名称": "名称",
                    "基金代码": "代码",
                    "当前-单位净值": "最新价",
                    "增长率": "涨跌幅",
                }
            )
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 同花顺ETF行情备用接口获取失败: {code_text}, {exc}")

    try:
        daily_df = ak.fund_etf_fund_daily_em()
        row = _find_row_by_code(daily_df, code_text)
        if row is not None:
            renamed = row.rename({"基金简称": "名称", "基金代码": "代码", "市价": "最新价", "增长率": "涨跌幅"})
            return renamed
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 天天基金ETF行情备用接口获取失败: {code_text}, {exc}")

    return None


def get_china_etf_fallback_spot_row(code: str) -> Optional[pd.Series]:
    """向后兼容的备用ETF基础行情入口。"""
    return get_china_etf_lightweight_spot_row(code)



def _format_realtime_row(row: Optional[pd.Series]) -> str:
    if row is None:
        return "- 实时行情：暂不可用\n"

    fields = [
        ("基金名称", ("名称", "基金名称")),
        ("最新价", ("最新价", "现价")),
        ("涨跌幅", ("涨跌幅",)),
        ("成交量", ("成交量",)),
        ("成交额", ("成交额",)),
        ("换手率", ("换手率",)),
        ("总市值", ("总市值",)),
        ("流通市值", ("流通市值",)),
    ]

    lines = []
    for label, candidates in fields:
        for column in candidates:
            if column in row.index and not pd.isna(row[column]):
                value = row[column]
                suffix = "%" if label in {"涨跌幅", "换手率"} and "%" not in str(value) else ""
                lines.append(f"- {label}: {value}{suffix}")
                break

    return "\n".join(lines) + ("\n" if lines else "- 实时行情：暂不可用\n")


def _get_etf_spot_row(code: str) -> Optional[pd.Series]:
    try:
        ak = _load_akshare()
        spot_df = ak.fund_etf_spot_em()
        row = _find_row_by_code(spot_df, code)
        if row is not None:
            return row
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 实时行情获取失败，尝试备用接口: {code}, {exc}")

    return get_china_etf_fallback_spot_row(code)


def get_china_etf_market_data(code: str, start_date: str, end_date: str) -> str:
    """获取A股ETF市场行情和技术指标报告。"""
    code_text = str(code).zfill(6)
    history = get_china_etf_history_dataframe(code_text, start_date, end_date)
    spot_row = _get_etf_spot_row(code_text)

    if history.empty:
        return f"❌ 未能获取{code_text}的A股ETF历史行情数据"

    enriched = compute_many(
        history,
        [
            IndicatorSpec("ma", {"n": 5}),
            IndicatorSpec("ma", {"n": 10}),
            IndicatorSpec("ma", {"n": 20}),
            IndicatorSpec("ma", {"n": 60}),
            IndicatorSpec("macd"),
            IndicatorSpec("rsi", {"n": 14}),
            IndicatorSpec("boll", {"n": 20, "k": 2}),
        ],
    )
    latest = enriched.iloc[-1]
    display = enriched.tail(10)

    def fmt_price(column: str) -> str:
        value = _safe_float(latest.get(column))
        return "N/A" if value is None else f"¥{value:.3f}"

    def fmt_pct(column: str) -> str:
        value = _safe_float(latest.get(column))
        return "N/A" if value is None else f"{value:+.2f}%"

    def fmt_number(column: str) -> str:
        value = _safe_float(latest.get(column))
        return "N/A" if value is None else f"{value:.2f}"

    rows = []
    for _, row in display.iterrows():
        rows.append(
            "| {date} | {open_} | {high} | {low} | {close} | {pct} | {vol} |".format(
                date=row.get("date").strftime("%Y-%m-%d") if hasattr(row.get("date"), "strftime") else row.get("date"),
                open_=f"{_safe_float(row.get('open')):.3f}" if _safe_float(row.get("open")) is not None else "N/A",
                high=f"{_safe_float(row.get('high')):.3f}" if _safe_float(row.get("high")) is not None else "N/A",
                low=f"{_safe_float(row.get('low')):.3f}" if _safe_float(row.get("low")) is not None else "N/A",
                close=f"{_safe_float(row.get('close')):.3f}" if _safe_float(row.get("close")) is not None else "N/A",
                pct=f"{_safe_float(row.get('pct_change')):+.2f}%" if _safe_float(row.get("pct_change")) is not None else "N/A",
                vol=f"{_safe_float(row.get('vol')):,.0f}" if _safe_float(row.get("vol")) is not None else "N/A",
            )
        )

    return f"""# {code_text} A股ETF市场数据

## 实时行情
{_format_realtime_row(spot_row)}
## 技术指标
- 最新收盘价: {fmt_price("close")}
- 最新涨跌幅: {fmt_pct("pct_change")}
- MA5 / MA10 / MA20 / MA60: {fmt_price("ma5")} / {fmt_price("ma10")} / {fmt_price("ma20")} / {fmt_price("ma60")}
- MACD DIF / DEA / 柱: {fmt_price("dif")} / {fmt_price("dea")} / {fmt_price("macd_hist")}
- RSI14: {fmt_number("rsi14")}
- BOLL上/中/下轨: {fmt_price("boll_upper")} / {fmt_price("boll_mid")} / {fmt_price("boll_lower")}

## 最近交易日行情
| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌幅 | 成交量 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## ETF分析关注点
- ETF价格主要受跟踪指数、成分资产、申赎套利和折溢价影响，不适用普通上市公司财报估值框架。
- 重点关注成交额、流动性、跟踪标的走势、基金规模、费率和持仓集中度。

*数据来源: AKShare 东方财富场内ETF接口*
"""


def get_china_etf_fundamentals_data(code: str, curr_date: str | None = None) -> str:
    """获取A股ETF基础资料、规模净值和持仓相关信息。"""
    code_text = str(code).zfill(6)
    as_of_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    spot_row = _get_etf_spot_row(code_text)

    sections = [f"# {code_text} A股ETF基础分析", f"**分析日期**: {as_of_date}", ""]
    sections.append("## 交易与规模概览")
    sections.append(_format_realtime_row(spot_row))

    ak = _load_akshare()

    try:
        info_df = ak.fund_etf_fund_info_em(
            fund=code_text,
            start_date="20000101",
            end_date=_format_ak_date(as_of_date),
        )
        if info_df is not None and not info_df.empty:
            sections.append("## 基金净值/规模信息")
            sections.append(info_df.tail(8).to_markdown(index=False))
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 基金净值信息获取失败: {code_text}, {exc}")
        sections.append(f"## 基金净值/规模信息\n- 暂不可用: {exc}")

    try:
        index_df = ak.fund_info_index_em(symbol="全部", indicator="全部")
        index_row = _find_row_by_code(index_df, code_text)
        if index_row is not None:
            fields = []
            for column in ("基金名称", "跟踪标的", "跟踪方式", "手续费", "成立来", "近1年", "近6月", "近3月"):
                if column in index_row.index and not pd.isna(index_row[column]):
                    fields.append(f"- {column}: {index_row[column]}")
            if fields:
                sections.append("## 跟踪标的与业绩概览")
                sections.append("\n".join(fields))
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 指数基金概览获取失败: {code_text}, {exc}")

    try:
        today = datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        today = datetime.now()

    try:
        history = get_china_etf_history_dataframe(
            code_text,
            (today - timedelta(days=30)).strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
        )
        if not history.empty:
            latest = history.iloc[-1]
            first = history.iloc[0]
            latest_close = _safe_float(latest.get("close"))
            first_close = _safe_float(first.get("close"))
            interval_return = None
            if latest_close is not None and first_close not in (None, 0):
                interval_return = (latest_close / first_close - 1) * 100

            sections.append("## 近30日表现")
            sections.append(f"- 最新收盘价: {'N/A' if latest_close is None else f'¥{latest_close:.3f}'}")
            if interval_return is not None:
                sections.append(f"- 区间涨跌幅: {interval_return:+.2f}%")
            if "amount" in history.columns:
                amount = history["amount"].dropna()
                if not amount.empty:
                    sections.append(f"- 日均成交额: ¥{amount.mean():,.0f}")
    except Exception as exc:
        logger.warning(f"⚠️ [A股ETF] 近30日表现计算失败: {code_text}, {exc}")
        sections.append(f"## 近30日表现\n- 暂不可用: {exc}")

    sections.append("""## ETF基本面分析框架
- 跟踪标的：确认指数或资产类别是否符合投资目标。
- 流动性：优先关注成交额、买卖价差和规模，避免流动性不足导致冲击成本。
- 折溢价：比较二级市场价格与基金净值，警惕持续高溢价。
- 持仓与集中度：行业/主题ETF需关注成分股集中度和再平衡风险。
- 费用与跟踪误差：长期持有时重点比较管理费、托管费和跟踪误差。""")

    sections.append("*数据来源: AKShare 东方财富场内ETF接口*")
    return "\n\n".join(sections)
