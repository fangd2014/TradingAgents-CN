from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    params: Optional[Dict[str, Any]] = None


SUPPORTED = {"ma", "ema", "macd", "rsi", "boll", "atr", "kdj"}


def _round_or_none(value: Any, digits: int = 2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _weighted_percentile(values: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    if len(values) == 0 or weights.sum() <= 0:
        return np.nan
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    threshold = percentile / 100.0 * sorted_weights.sum()
    idx = int(np.searchsorted(cumulative, threshold, side="left"))
    idx = max(0, min(len(sorted_values) - 1, idx))
    return float(sorted_values[idx])


def _detect_volume_col(df: pd.DataFrame) -> Optional[str]:
    if "volume" in df.columns:
        return "volume"
    if "vol" in df.columns:
        return "vol"
    return None


def _detect_turnover_col(df: pd.DataFrame) -> Optional[str]:
    for col in ("turnover", "turnover_rate", "换手率"):
        if col in df.columns:
            return col
    return None


def _estimate_daily_turnover(data: pd.DataFrame, volume_col: str, turnover_col: Optional[str]) -> pd.Series:
    if turnover_col:
        turnover = pd.to_numeric(data[turnover_col], errors="coerce").fillna(0.0)
        # A股常见换手率列是百分数；若小于1则视为小数比例。
        if turnover.max() > 1:
            turnover = turnover / 100.0
        return turnover.clip(lower=0.0, upper=1.0)

    volume = pd.to_numeric(data[volume_col], errors="coerce").fillna(0.0)
    rolling_base = volume.rolling(window=120, min_periods=20).sum().replace(0, np.nan)
    turnover = (volume / rolling_base).fillna(volume / max(float(volume.sum()), 1.0))
    return turnover.clip(lower=0.0, upper=0.20)


def _build_daily_distribution(
    low: float,
    high: float,
    close: float,
    turnover_weight: float,
    centers: np.ndarray,
    method: str,
) -> np.ndarray:
    weights = np.zeros(len(centers), dtype=float)
    if high <= low:
        idx = int(np.argmin(np.abs(centers - close)))
        weights[idx] = turnover_weight
        return weights

    mask = (centers >= low) & (centers <= high)
    indices = np.where(mask)[0]
    if len(indices) == 0:
        idx = int(np.argmin(np.abs(centers - close)))
        weights[idx] = turnover_weight
        return weights

    if method == "triangular":
        typical = (high + low + close) / 3.0
        distance = np.abs(centers[indices] - typical)
        half_range = max((high - low) / 2.0, 1e-9)
        local = np.maximum(0.0, 1.0 - distance / half_range)
        if local.sum() <= 0:
            local = np.ones(len(indices), dtype=float)
    else:
        local = np.ones(len(indices), dtype=float)

    weights[indices] = local / local.sum() * turnover_weight
    return weights


def _local_peak_indices(weights: np.ndarray, min_ratio: float = 0.08) -> List[int]:
    if len(weights) == 0 or weights.sum() <= 0:
        return []
    threshold = weights.sum() * min_ratio
    peaks: List[int] = []
    for i, value in enumerate(weights):
        left = weights[i - 1] if i > 0 else -np.inf
        right = weights[i + 1] if i < len(weights) - 1 else -np.inf
        if value >= threshold and value >= left and value >= right:
            peaks.append(i)
    return sorted(peaks, key=lambda idx: weights[idx], reverse=True)


def _classify_peak_shape(weights: np.ndarray) -> str:
    total = float(weights.sum())
    if total <= 0:
        return "数据不足"
    peaks = _local_peak_indices(weights)
    sorted_ratio = np.sort(weights)[::-1]
    top3_ratio = float(sorted_ratio[:3].sum() / total) if len(sorted_ratio) else 0.0
    if len(peaks) <= 1 and top3_ratio >= 0.35:
        return "单峰密集"
    if len(peaks) >= 2:
        return "多峰密集"
    return "发散形态"


def _classify_main_force_behavior(metrics: Dict[str, Any]) -> tuple[str, str]:
    price_percentile = metrics["price_percentile_pct"]
    cost_90 = metrics["cost_90_concentration_pct"]
    winner = metrics["winner_ratio_pct"]
    bottom_retention = metrics["bottom_peak_retention_pct"]
    peak_shift = metrics["peak_shift_pct"]
    recent_volume = metrics["recent_volume_ratio"]
    price_vs_peak = metrics["price_vs_peak_pct"]
    peak_shape = metrics["peak_shape"]

    if (
        price_percentile >= 70
        and bottom_retention < 35
        and recent_volume >= 1.8
        and (winner >= 80 or peak_shift >= 20 or cost_90 >= 18)
    ):
        return "distribution", "高位放量且底部筹码峰快速消失，新高位成本堆积，疑似主力派发/抛售"

    if (
        cost_90 <= 15
        and 1.1 <= recent_volume <= 1.8
        and bottom_retention >= 45
        and abs(peak_shift) <= 8
        and abs(price_vs_peak) <= 6
    ):
        return "accumulation", "低位单峰逐步集中且温和放量，疑似主力建仓吸筹"

    if (
        price_vs_peak > 8
        and bottom_retention >= 55
        and recent_volume <= 0.8
        and cost_90 <= 18
    ):
        return "lockup", "股价脱离底部成本区但底峰稳定且缩量，疑似主力锁仓控盘"

    if (
        peak_shape == "多峰密集"
        and bottom_retention >= 45
        and peak_shift > 3
        and 0.8 <= recent_volume <= 2.2
    ):
        return "relay", "底峰仍在且上方形成新峰，疑似拉升中继"

    if (
        price_vs_peak < -3
        and bottom_retention >= 50
        and recent_volume <= 0.75
    ):
        return "wash", "短期回落缩量但底部筹码峰未明显松动，疑似洗盘"

    return "neutral", "筹码与量价信号未形成明确主力行为结论"


def _require_cols(df: pd.DataFrame, cols: Iterable[str]):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame缺少必要列: {missing}, 现有列: {list(df.columns)[:10]}...")


def ma(close: pd.Series, n: int, min_periods: int = None) -> pd.Series:
    """
    计算移动平均线（Moving Average）

    Args:
        close: 收盘价序列
        n: 周期
        min_periods: 最小周期数，默认为1（允许前期数据不足时也计算）

    Returns:
        移动平均线序列
    """
    if min_periods is None:
        min_periods = 1  # 默认为1，与现有代码保持一致
    return close.rolling(window=int(n), min_periods=min_periods).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    """
    计算指数移动平均线（Exponential Moving Average）

    Args:
        close: 收盘价序列
        n: 周期

    Returns:
        指数移动平均线序列
    """
    return close.ewm(span=int(n), adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    计算MACD指标（Moving Average Convergence Divergence）

    Args:
        close: 收盘价序列
        fast: 快线周期，默认12
        slow: 慢线周期，默认26
        signal: 信号线周期，默认9

    Returns:
        包含 dif, dea, macd_hist 的 DataFrame
        - dif: 快线与慢线的差值（DIF）
        - dea: DIF的信号线（DEA）
        - macd_hist: MACD柱状图（DIF - DEA）
    """
    dif = ema(close, fast) - ema(close, slow)
    dea = dif.ewm(span=int(signal), adjust=False).mean()
    hist = dif - dea
    return pd.DataFrame({"dif": dif, "dea": dea, "macd_hist": hist})


def rsi(close: pd.Series, n: int = 14, method: str = 'ema') -> pd.Series:
    """
    计算RSI指标（Relative Strength Index）

    Args:
        close: 收盘价序列
        n: 周期，默认14
        method: 计算方法
            - 'ema': 指数移动平均（国际标准，Wilder's方法）
            - 'sma': 简单移动平均
            - 'china': 中国式SMA（同花顺/通达信风格）

    Returns:
        RSI序列（0-100）

    说明：
        - 'ema': 使用 ewm(alpha=1/n, adjust=False)，适用于国际市场
        - 'sma': 使用 rolling(window=n).mean()，简单移动平均
        - 'china': 使用 ewm(com=n-1, adjust=True)，与同花顺/通达信一致
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    if method == 'ema':
        # 国际标准：Wilder's指数移动平均
        avg_gain = gain.ewm(alpha=1 / float(n), adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / float(n), adjust=False).mean()
    elif method == 'sma':
        # 简单移动平均
        avg_gain = gain.rolling(window=int(n), min_periods=1).mean()
        avg_loss = loss.rolling(window=int(n), min_periods=1).mean()
    elif method == 'china':
        # 中国式SMA：同花顺/通达信风格
        # SMA(X, N, 1) = ewm(com=N-1, adjust=True).mean()
        # 参考：https://blog.csdn.net/u011218867/article/details/117427927
        avg_gain = gain.ewm(com=int(n) - 1, adjust=True).mean()
        avg_loss = loss.ewm(com=int(n) - 1, adjust=True).mean()
    else:
        raise ValueError(f"不支持的RSI计算方法: {method}，支持的方法: 'ema', 'sma', 'china'")

    rs = avg_gain / (avg_loss.replace(0, np.nan))
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


def boll(close: pd.Series, n: int = 20, k: float = 2.0, min_periods: int = None) -> pd.DataFrame:
    """
    计算布林带指标（Bollinger Bands）

    Args:
        close: 收盘价序列
        n: 周期，默认20
        k: 标准差倍数，默认2.0
        min_periods: 最小周期数，默认为1（允许前期数据不足时也计算）

    Returns:
        包含 boll_mid, boll_upper, boll_lower 的 DataFrame
        - boll_mid: 中轨（n日移动平均）
        - boll_upper: 上轨（中轨 + k倍标准差）
        - boll_lower: 下轨（中轨 - k倍标准差）
    """
    if min_periods is None:
        min_periods = 1  # 默认为1，与现有代码保持一致
    mid = close.rolling(window=int(n), min_periods=min_periods).mean()
    std = close.rolling(window=int(n), min_periods=min_periods).std()
    upper = mid + k * std
    lower = mid - k * std
    return pd.DataFrame({"boll_mid": mid, "boll_upper": upper, "boll_lower": lower})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=int(n), min_periods=int(n)).mean()


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    lowest_low = low.rolling(window=int(n), min_periods=int(n)).min()
    highest_high = high.rolling(window=int(n), min_periods=int(n)).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    # 处理除零与起始NaN
    rsv = rsv.replace([np.inf, -np.inf], np.nan)

    # 按经典公式递推（初始化 50）
    k = pd.Series(np.nan, index=close.index)
    d = pd.Series(np.nan, index=close.index)
    alpha_k = 1 / float(m1)
    alpha_d = 1 / float(m2)
    last_k = 50.0
    last_d = 50.0
    for i in range(len(close)):
        rv = rsv.iloc[i]
        if np.isnan(rv):
            k.iloc[i] = np.nan
            d.iloc[i] = np.nan
            continue
        curr_k = (1 - alpha_k) * last_k + alpha_k * rv
        curr_d = (1 - alpha_d) * last_d + alpha_d * curr_k
        k.iloc[i] = curr_k
        d.iloc[i] = curr_d
        last_k, last_d = curr_k, curr_d
    j = 3 * k - 2 * d
    return pd.DataFrame({"kdj_k": k, "kdj_d": d, "kdj_j": j})


def compute_indicator(df: pd.DataFrame, spec: IndicatorSpec) -> pd.DataFrame:
    name = spec.name.lower()
    params = spec.params or {}
    out = df.copy()

    if name == "ma":
        _require_cols(df, ["close"])
        n = int(params.get("n", params.get("period", 20)))
        out[f"ma{n}"] = ma(df["close"], n)
        return out

    if name == "ema":
        _require_cols(df, ["close"])
        n = int(params.get("n", params.get("period", 20)))
        out[f"ema{n}"] = ema(df["close"], n)
        return out

    if name == "macd":
        _require_cols(df, ["close"])
        fast = int(params.get("fast", 12))
        slow = int(params.get("slow", 26))
        signal = int(params.get("signal", 9))
        macd_df = macd(df["close"], fast=fast, slow=slow, signal=signal)
        for c in macd_df.columns:
            out[c] = macd_df[c]
        return out

    if name == "rsi":
        _require_cols(df, ["close"])
        n = int(params.get("n", params.get("period", 14)))
        out[f"rsi{n}"] = rsi(df["close"], n)
        return out

    if name == "boll":
        _require_cols(df, ["close"])
        n = int(params.get("n", 20))
        k = float(params.get("k", 2.0))
        boll_df = boll(df["close"], n=n, k=k)
        for c in boll_df.columns:
            out[c] = boll_df[c]
        return out

    if name == "atr":
        _require_cols(df, ["high", "low", "close"])
        n = int(params.get("n", 14))
        out[f"atr{n}"] = atr(df["high"], df["low"], df["close"], n=n)
        return out

    if name == "kdj":
        _require_cols(df, ["high", "low", "close"])
        n = int(params.get("n", 9))
        m1 = int(params.get("m1", 3))
        m2 = int(params.get("m2", 3))
        kdj_df = kdj(df["high"], df["low"], df["close"], n=n, m1=m1, m2=m2)
        for c in kdj_df.columns:
            out[c] = kdj_df[c]
        return out

    raise ValueError(f"不支持的指标: {name}")


def compute_many(df: pd.DataFrame, specs: List[IndicatorSpec]) -> pd.DataFrame:
    if not specs:
        return df.copy()
    # 粗略去重（按 name+sorted(params)）
    def key(s: IndicatorSpec):
        p = s.params or {}
        items = tuple(sorted(p.items()))
        return (s.name.lower(), items)

    unique_specs: List[IndicatorSpec] = []
    seen = set()
    for s in specs:
        k = key(s)
        if k not in seen:
            seen.add(k)
            unique_specs.append(s)

    out = df.copy()
    for s in unique_specs:
        out = compute_indicator(out, s)
    return out


def analyze_chip_peak(
    df: pd.DataFrame,
    lookback: int = 120,
    bins: int = 48,
    decay_coefficient: float = 1.0,
    distribution_method: str = "average",
) -> Dict[str, Any]:
    """
    Estimate chip distribution by aggregating recent traded volume into price bins.

    This is a K-line approximation, not exchange-level holder cost data. It is
    useful for observing recent cost concentration, support/resistance, and
    whether high-volume cost areas are moving up or down.
    """
    if df is None or df.empty:
        return {"available": False, "reason": "无可用K线数据"}

    volume_col = _detect_volume_col(df)
    turnover_col = _detect_turnover_col(df)
    _require_cols(df, ["high", "low", "close"])
    if not volume_col:
        raise ValueError(f"DataFrame缺少成交量列: volume/vol, 现有列: {list(df.columns)[:10]}...")

    data = df.tail(int(lookback)).copy()
    required_cols = ["high", "low", "close", volume_col]
    if turnover_col:
        required_cols.append(turnover_col)
    data = data[required_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["high", "low", "close", volume_col])
    data = data[data[volume_col] > 0]
    if len(data) < 5:
        return {"available": False, "reason": "有效K线或成交量数据不足"}

    low_price = float(data["low"].min())
    high_price = float(data["high"].max())
    current_price = float(data["close"].iloc[-1])
    if high_price <= low_price:
        return {"available": False, "reason": "价格区间无波动，无法形成筹码分布"}

    bin_count = max(16, int(bins))
    edges = np.linspace(low_price, high_price, bin_count + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    distribution = np.zeros(bin_count, dtype=float)
    turnover_series = _estimate_daily_turnover(data, volume_col, turnover_col)
    decay_coefficient = max(0.1, min(float(decay_coefficient), 10.0))
    snapshots: List[np.ndarray] = []

    for i, (_, row) in enumerate(data.iterrows()):
        moved_ratio = min(float(turnover_series.iloc[i]) * decay_coefficient, 1.0)
        daily_distribution = _build_daily_distribution(
            low=float(row["low"]),
            high=float(row["high"]),
            close=float(row["close"]),
            turnover_weight=moved_ratio,
            centers=centers,
            method=distribution_method,
        )
        distribution = distribution * (1.0 - moved_ratio) + daily_distribution
        total = distribution.sum()
        if total > 0:
            distribution = distribution / total
        snapshots.append(distribution.copy())

    total_weight = float(distribution.sum())
    if total_weight <= 0:
        return {"available": False, "reason": "筹码分布权重合计为0"}

    weights = distribution
    peak_idx = int(np.argmax(weights))
    main_peak_price = float(centers[peak_idx])
    main_peak_ratio = float(weights[peak_idx] / total_weight)

    sorted_indices = np.argsort(weights)[::-1]
    secondary_idx = int(sorted_indices[1]) if len(sorted_indices) > 1 and weights[sorted_indices[1]] > 0 else peak_idx
    secondary_peak_price = float(centers[secondary_idx])
    secondary_peak_ratio = float(weights[secondary_idx] / total_weight)

    top3_ratio = float(weights[sorted_indices[:3]].sum() / total_weight)
    winner_ratio = float(weights[centers <= current_price].sum() / total_weight)
    pressure_ratio = float(weights[centers > current_price].sum() / total_weight)
    price_vs_peak_pct = (current_price - main_peak_price) / main_peak_price * 100 if main_peak_price else 0.0
    cost_5 = _weighted_percentile(centers, weights, 5)
    cost_15 = _weighted_percentile(centers, weights, 15)
    cost_50 = _weighted_percentile(centers, weights, 50)
    cost_85 = _weighted_percentile(centers, weights, 85)
    cost_95 = _weighted_percentile(centers, weights, 95)
    cost_90_concentration = (cost_95 - cost_5) / (cost_95 + cost_5) * 100 if (cost_95 + cost_5) else np.nan
    cost_70_concentration = (cost_85 - cost_15) / (cost_85 + cost_15) * 100 if (cost_85 + cost_15) else np.nan
    overlap_denominator = cost_95 - cost_5
    cost_overlap_ratio = (cost_85 - cost_15) / overlap_denominator if overlap_denominator else np.nan
    peak_shape = _classify_peak_shape(weights)
    if cost_90_concentration <= 10 and peak_shape == "发散形态":
        peak_shape = "单峰密集"
    elif cost_90_concentration <= 15 and len(_local_peak_indices(weights, min_ratio=0.04)) <= 2:
        peak_shape = "单峰密集"

    snapshot_idx = max(0, len(snapshots) - max(20, len(snapshots) // 4))
    previous_weights = snapshots[snapshot_idx]
    previous_peak_price = float(centers[int(np.argmax(previous_weights))]) if previous_weights.sum() > 0 else main_peak_price
    peak_shift_pct = (main_peak_price - previous_peak_price) / previous_peak_price * 100 if previous_peak_price else 0.0

    bottom_cutoff = low_price + (high_price - low_price) * 0.35
    bottom_mask = centers <= bottom_cutoff
    previous_bottom = float(previous_weights[bottom_mask].sum()) if previous_weights.sum() > 0 else 0.0
    current_bottom = float(weights[bottom_mask].sum())
    bottom_peak_retention_pct = (current_bottom / previous_bottom * 100) if previous_bottom > 0 else (100.0 if current_bottom > 0 else 0.0)

    recent_window = max(5, min(20, len(data) // 3))
    earlier_volume = float(data[volume_col].iloc[-recent_window * 2:-recent_window].mean()) if len(data) >= recent_window * 2 else float(data[volume_col].head(recent_window).mean())
    recent_volume = float(data[volume_col].tail(recent_window).mean())
    recent_volume_ratio = recent_volume / earlier_volume if earlier_volume > 0 else 1.0

    price_percentile_pct = (current_price - low_price) / (high_price - low_price) * 100 if high_price > low_price else 50.0
    behavior_metrics = {
        "price_percentile_pct": price_percentile_pct,
        "cost_90_concentration_pct": cost_90_concentration,
        "winner_ratio_pct": winner_ratio * 100,
        "bottom_peak_retention_pct": bottom_peak_retention_pct,
        "peak_shift_pct": peak_shift_pct,
        "recent_volume_ratio": recent_volume_ratio,
        "price_vs_peak_pct": price_vs_peak_pct,
        "peak_shape": peak_shape,
    }
    behavior_code, signal = _classify_main_force_behavior(behavior_metrics)

    return {
        "available": True,
        "lookback": int(len(data)),
        "decay_coefficient": _round_or_none(decay_coefficient),
        "distribution_method": distribution_method,
        "current_price": _round_or_none(current_price),
        "main_peak_price": _round_or_none(main_peak_price),
        "main_peak_ratio": _round_or_none(main_peak_ratio * 100),
        "secondary_peak_price": _round_or_none(secondary_peak_price),
        "secondary_peak_ratio": _round_or_none(secondary_peak_ratio * 100),
        "chip_concentration_top3": _round_or_none(top3_ratio * 100),
        "peak_shape": peak_shape,
        "winner_ratio": _round_or_none(winner_ratio),
        "winner_ratio_pct": _round_or_none(winner_ratio * 100),
        "pressure_ratio_pct": _round_or_none(pressure_ratio * 100),
        "price_vs_peak_pct": _round_or_none(price_vs_peak_pct),
        "peak_shift_pct": _round_or_none(peak_shift_pct),
        "cost_percentiles": {
            "cost_5": _round_or_none(cost_5),
            "cost_15": _round_or_none(cost_15),
            "cost_50": _round_or_none(cost_50),
            "cost_85": _round_or_none(cost_85),
            "cost_95": _round_or_none(cost_95),
        },
        "cost_70_range": (_round_or_none(cost_15), _round_or_none(cost_85)),
        "cost_90_range": (_round_or_none(cost_5), _round_or_none(cost_95)),
        "cost_70_concentration_pct": _round_or_none(cost_70_concentration),
        "cost_90_concentration_pct": _round_or_none(cost_90_concentration),
        "cost_overlap_ratio": _round_or_none(cost_overlap_ratio),
        "bottom_peak_retention_pct": _round_or_none(bottom_peak_retention_pct),
        "recent_volume_ratio": _round_or_none(recent_volume_ratio),
        "price_percentile_pct": _round_or_none(price_percentile_pct),
        "behavior_code": behavior_code,
        "main_force_signal": signal,
        "support_zone": (
            _round_or_none(main_peak_price * 0.97),
            _round_or_none(main_peak_price * 1.03),
        ),
        "pressure_zone": (
            _round_or_none(secondary_peak_price * 0.97),
            _round_or_none(secondary_peak_price * 1.03),
        ),
        "distribution": [
            {
                "price": _round_or_none(price),
                "weight_pct": _round_or_none(weight * 100),
                "winner": bool(price <= current_price),
            }
            for price, weight in zip(centers, weights)
            if weight > 0
        ],
    }


def render_chip_peak_svg(result: Dict[str, Any], width: int = 720, height: int = 360) -> str:
    if not result.get("available"):
        return ""

    distribution = result.get("distribution") or []
    if not distribution:
        return ""

    left_pad = 96
    right_pad = 118
    top_pad = 42
    bottom_pad = 44
    chart_width = width - left_pad - right_pad
    chart_height = height - top_pad - bottom_pad
    prices = [float(item["price"]) for item in distribution if item.get("price") is not None]
    weights = [float(item["weight_pct"]) for item in distribution if item.get("weight_pct") is not None]
    if not prices or not weights:
        return ""

    min_price = min(prices)
    max_price = max(prices)
    max_weight = max(weights) or 1.0
    bar_gap = 1
    bar_height = max(3, chart_height / len(distribution) - bar_gap)

    def y_for_price(price: float) -> float:
        if max_price == min_price:
            return top_pad + chart_height / 2
        return top_pad + (max_price - price) / (max_price - min_price) * chart_height

    def marker_line(price: Optional[float], label: str, color: str, dash: str = "") -> str:
        if price is None:
            return ""
        y = y_for_price(float(price))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        return (
            f'<line x1="{left_pad}" y1="{y:.1f}" x2="{width - right_pad + 8}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="1.5"{dash_attr}/>'
            f'<text x="{width - right_pad + 14}" y="{y + 4:.1f}" font-size="12" fill="{color}">'
            f'{escape(label)} {float(price):.2f}</text>'
        )

    bars = []
    for item in distribution:
        price = float(item["price"])
        weight = float(item["weight_pct"])
        y = y_for_price(price) - bar_height / 2
        bar_width = weight / max_weight * chart_width
        fill = "#e74c3c" if item.get("winner") else "#3498db"
        bars.append(
            f'<rect x="{left_pad}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
            f'rx="2" fill="{fill}" opacity="0.78"/>'
        )

    cost = result.get("cost_percentiles") or {}
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="筹码峰分布图">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="20" y="24" font-size="18" font-weight="700" fill="#1f2933">筹码峰分布图</text>',
        '<text x="20" y="44" font-size="12" fill="#6b7280">红色=获利筹码，蓝色=套牢筹码；横向长度代表筹码权重</text>',
        f'<line x1="{left_pad}" y1="{top_pad}" x2="{left_pad}" y2="{height - bottom_pad}" stroke="#9aa4b2" stroke-width="1"/>',
        f'<line x1="{left_pad}" y1="{height - bottom_pad}" x2="{width - right_pad}" y2="{height - bottom_pad}" stroke="#9aa4b2" stroke-width="1"/>',
        *bars,
        marker_line(result.get("main_peak_price"), "主峰", "#c0392b"),
        marker_line(result.get("current_price"), "当前价", "#111827", "5 4"),
        marker_line(cost.get("cost_50"), "平均成本", "#f59e0b", "4 3"),
        f'<text x="20" y="{top_pad + 4}" font-size="12" fill="#4b5563">{max_price:.2f}</text>',
        f'<text x="20" y="{height - bottom_pad + 4}" font-size="12" fill="#4b5563">{min_price:.2f}</text>',
        f'<text x="{left_pad}" y="{height - 14}" font-size="12" fill="#6b7280">0%</text>',
        f'<text x="{width - right_pad - 44}" y="{height - 14}" font-size="12" fill="#6b7280">{max_weight:.2f}%</text>',
        f'<text x="20" y="{height - 14}" font-size="12" fill="#374151">主力动向：{escape(str(result.get("main_force_signal", "")))}</text>',
        '</svg>',
    ]
    return "".join(svg_parts)


def format_chip_peak_report(
    df: pd.DataFrame,
    lookback: int = 120,
    bins: int = 48,
    decay_coefficient: float = 1.0,
    distribution_method: str = "average",
) -> str:
    result = analyze_chip_peak(
        df,
        lookback=lookback,
        bins=bins,
        decay_coefficient=decay_coefficient,
        distribution_method=distribution_method,
    )
    if not result.get("available"):
        return f"### 5. 筹码峰分析\n- 暂不可用：{result.get('reason', '数据不足')}\n"

    support_low, support_high = result["support_zone"]
    pressure_low, pressure_high = result["pressure_zone"]
    cost_70_low, cost_70_high = result["cost_70_range"]
    cost_90_low, cost_90_high = result["cost_90_range"]
    svg = render_chip_peak_svg(result)
    return (
        "### 5. 筹码峰分析\n"
        "\n"
        f"{svg}\n\n"
        f"- 样本范围：近 {result['lookback']} 根K线，按换手衰减模型估算筹码分布\n"
        f"- 模型参数：历史换手衰减系数 {result['decay_coefficient']}，当日成本分布={result['distribution_method']}\n"
        f"- 当前价：{result['current_price']}\n"
        f"- 峰型：{result['peak_shape']}；主筹码峰：{result['main_peak_price']}，峰值权重约 {result['main_peak_ratio']}%\n"
        f"- 次筹码峰：{result['secondary_peak_price']}，峰值权重约 {result['secondary_peak_ratio']}%\n"
        f"- 70%成本区间：{cost_70_low} - {cost_70_high}，集中度 {result['cost_70_concentration_pct']}%\n"
        f"- 90%成本区间：{cost_90_low} - {cost_90_high}，集中度 {result['cost_90_concentration_pct']}%\n"
        f"- 区间重合度：{result['cost_overlap_ratio']}；前三峰权重合计约 {result['chip_concentration_top3']}%\n"
        f"- 获利盘比例：约 {result['winner_ratio_pct']}%，上方压力筹码约 {result['pressure_ratio_pct']}%\n"
        f"- 当前价相对主峰：{result['price_vs_peak_pct']}%，近端主峰迁移：{result['peak_shift_pct']}%\n"
        f"- 底部筹码峰保留：{result['bottom_peak_retention_pct']}%，近期量能变化：{result['recent_volume_ratio']}倍\n"
        f"- 主峰支撑区：{support_low} - {support_high}\n"
        f"- 主要压力区：{pressure_low} - {pressure_high}\n"
        f"- 主力动向：{result['main_force_signal']}\n"
        "- 说明：该指标基于K线换手衰减模型近似估算，不等同于真实逐笔持仓成本；需结合量能、K线、基本面和市场环境验证。\n"
    )


def last_values(df: pd.DataFrame, columns: List[str]) -> Dict[str, Any]:
    if df.empty:
        return {c: None for c in columns}
    last = df.iloc[-1]
    return {c: (None if c not in df.columns else (None if pd.isna(last.get(c)) else last.get(c))) for c in columns}


def add_all_indicators(df: pd.DataFrame, close_col: str = 'close',
                       high_col: str = 'high', low_col: str = 'low',
                       rsi_style: str = 'international') -> pd.DataFrame:
    """
    为DataFrame添加所有常用技术指标

    这是一个统一的技术指标计算函数，用于替代各个数据源模块中重复的计算代码。

    Args:
        df: 包含价格数据的DataFrame
        close_col: 收盘价列名，默认'close'
        high_col: 最高价列名，默认'high'（预留，暂未使用）
        low_col: 最低价列名，默认'low'（预留，暂未使用）
        rsi_style: RSI计算风格
            - 'international': 国际标准（RSI14，使用EMA）
            - 'china': 中国风格（RSI6/12/24 + RSI14，使用中国式SMA）

    Returns:
        添加了技术指标列的DataFrame（原地修改）

    添加的指标列：
        - ma5, ma10, ma20, ma60: 移动平均线
        - rsi: RSI指标（14日，国际标准）
        - rsi6, rsi12, rsi24: RSI指标（中国风格，仅当 rsi_style='china' 时）
        - rsi14: RSI指标（14日，简单移动平均，仅当 rsi_style='china' 时）
        - macd_dif, macd_dea, macd: MACD指标
        - boll_mid, boll_upper, boll_lower: 布林带

    示例：
        >>> df = pd.DataFrame({'close': [100, 101, 102, 103, 104]})
        >>> df = add_all_indicators(df)
        >>> print(df[['close', 'ma5', 'rsi']].tail())
        >>>
        >>> # 中国风格
        >>> df = add_all_indicators(df, rsi_style='china')
        >>> print(df[['close', 'rsi6', 'rsi12', 'rsi24']].tail())
    """
    # 检查必要的列
    if close_col not in df.columns:
        raise ValueError(f"DataFrame缺少收盘价列: {close_col}")

    # 计算移动平均线（MA5, MA10, MA20, MA60）
    df['ma5'] = ma(df[close_col], 5, min_periods=1)
    df['ma10'] = ma(df[close_col], 10, min_periods=1)
    df['ma20'] = ma(df[close_col], 20, min_periods=1)
    df['ma60'] = ma(df[close_col], 60, min_periods=1)

    # 计算RSI指标
    if rsi_style == 'china':
        # 中国风格：RSI6, RSI12, RSI24（使用中国式SMA）
        df['rsi6'] = rsi(df[close_col], 6, method='china')
        df['rsi12'] = rsi(df[close_col], 12, method='china')
        df['rsi24'] = rsi(df[close_col], 24, method='china')
        # 保留RSI14作为国际标准参考（使用简单移动平均）
        df['rsi14'] = rsi(df[close_col], 14, method='sma')
        # 为了兼容性，也添加 'rsi' 列（指向 rsi12）
        df['rsi'] = df['rsi12']
    else:
        # 国际标准：RSI14（使用EMA）
        df['rsi'] = rsi(df[close_col], 14, method='ema')

    # 计算MACD
    macd_df = macd(df[close_col], fast=12, slow=26, signal=9)
    df['macd_dif'] = macd_df['dif']
    df['macd_dea'] = macd_df['dea']
    df['macd'] = macd_df['macd_hist'] * 2  # 注意：这里乘以2是为了与通达信/同花顺保持一致

    # 计算布林带（20日，2倍标准差）
    boll_df = boll(df[close_col], n=20, k=2.0, min_periods=1)
    df['boll_mid'] = boll_df['boll_mid']
    df['boll_upper'] = boll_df['boll_upper']
    df['boll_lower'] = boll_df['boll_lower']

    return df
