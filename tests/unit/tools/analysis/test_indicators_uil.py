import math
import pandas as pd
import numpy as np

from tradingagents.tools.analysis.indicators import (
    IndicatorSpec,
    analyze_chip_peak,
    compute_many,
    format_chip_peak_report,
    render_chip_peak_svg,
)


def make_df(n=60, seed=42):
    rng = np.random.default_rng(seed)
    close = pd.Series(np.cumsum(rng.normal(0, 1, n)) + 100)
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    vol = pd.Series(rng.integers(1000, 5000, n))
    amount = vol * close
    return pd.DataFrame({
        'open': close, 'high': high, 'low': low, 'close': close, 'vol': vol, 'amount': amount
    })


def test_compute_many_basic_columns():
    df = make_df(80)
    specs = [
        IndicatorSpec('ma', {'n': 5}),
        IndicatorSpec('ma', {'n': 20}),
        IndicatorSpec('macd'),
        IndicatorSpec('rsi', {'n': 14}),
        IndicatorSpec('boll', {'n': 20, 'k': 2}),
        IndicatorSpec('atr', {'n': 14}),
        IndicatorSpec('kdj', {'n': 9, 'm1': 3, 'm2': 3}),
    ]
    out = compute_many(df, specs)

    # 列存在
    for col in ['ma5','ma20','dif','dea','macd_hist','rsi14','boll_mid','boll_upper','boll_lower','atr14','kdj_k','kdj_d','kdj_j']:
        assert col in out.columns

    # 最后一行应有数值（对应窗口已满足）
    last = out.iloc[-1]
    for col in ['ma5','ma20','dif','dea','macd_hist','rsi14','boll_mid','boll_upper','boll_lower','atr14','kdj_k','kdj_d','kdj_j']:
        assert not pd.isna(last[col]), f"{col} should not be NaN"


def test_no_inplace_modification():
    df = make_df(40)
    out = compute_many(df, [IndicatorSpec('ma', {'n': 5})])
    assert 'ma5' in out.columns and 'ma5' not in df.columns


def test_analyze_chip_peak_detects_upward_main_cost_shift():
    low_cost = pd.DataFrame({
        'open': [10.0] * 30,
        'high': [10.2] * 30,
        'low': [9.8] * 30,
        'close': [10.0] * 30,
        'vol': [1000] * 30,
        'amount': [10000] * 30,
    })
    high_cost = pd.DataFrame({
        'open': [12.0] * 30,
        'high': [12.2] * 30,
        'low': [11.8] * 30,
        'close': [12.1] * 30,
        'vol': [6000] * 30,
        'amount': [72600] * 30,
    })
    df = pd.concat([low_cost, high_cost], ignore_index=True)

    result = analyze_chip_peak(df, lookback=60, bins=32)

    assert 11.7 <= result['main_peak_price'] <= 12.3
    assert result['peak_shape'] in {'单峰密集', '多峰密集'}
    assert result['winner_ratio'] > 0.7
    assert result['behavior_code'] in {'accumulation', 'lockup', 'relay', 'neutral'}


def test_format_chip_peak_report_includes_main_force_fields():
    df = make_df(80)

    report = format_chip_peak_report(df, lookback=60, bins=32)

    assert '### 5. 筹码峰分析' in report
    assert '主筹码峰' in report
    assert '主力动向' in report
    assert '<svg' in report
    assert '筹码峰分布图' in report


def test_render_chip_peak_svg_contains_cost_markers():
    df = make_df(80)
    result = analyze_chip_peak(df, lookback=60, bins=32)

    svg = render_chip_peak_svg(result)

    assert svg.startswith('<svg')
    assert '主峰' in svg
    assert '当前价' in svg
    assert '平均成本' in svg


def test_chip_peak_reports_cost_intervals_and_accumulation_behavior():
    base = pd.DataFrame({
        'open': [10.0] * 80,
        'high': [10.3] * 80,
        'low': [9.7] * 80,
        'close': [10.0] * 80,
        'vol': [1200] * 80,
        'turnover': [1.2] * 80,
    })
    accumulation = pd.DataFrame({
        'open': [10.2] * 25,
        'high': [10.4] * 25,
        'low': [10.0] * 25,
        'close': [10.2] * 25,
        'vol': [1800] * 25,
        'turnover': [2.0] * 25,
    })
    df = pd.concat([base, accumulation], ignore_index=True)

    result = analyze_chip_peak(df, lookback=105, bins=48, decay_coefficient=1.0)

    assert result['cost_90_concentration_pct'] < 15
    assert result['cost_70_concentration_pct'] < result['cost_90_concentration_pct']
    assert result['cost_overlap_ratio'] > 0
    assert result['peak_shape'] == '单峰密集'
    assert result['behavior_code'] in {'accumulation', 'lockup'}
    assert result['cost_percentiles']['cost_5'] < result['cost_percentiles']['cost_95']


def test_chip_peak_classifies_distribution_when_bottom_peak_collapses_at_high_price():
    bottom = pd.DataFrame({
        'open': [10.0] * 80,
        'high': [10.2] * 80,
        'low': [9.8] * 80,
        'close': [10.0] * 80,
        'vol': [1000] * 80,
        'turnover': [1.0] * 80,
    })
    markup = pd.DataFrame({
        'open': np.linspace(10.2, 15.5, 25),
        'high': np.linspace(10.5, 16.0, 25),
        'low': np.linspace(10.0, 15.0, 25),
        'close': np.linspace(10.4, 15.8, 25),
        'vol': [2500] * 25,
        'turnover': [4.0] * 25,
    })
    distribution = pd.DataFrame({
        'open': [16.0] * 12,
        'high': [16.5] * 12,
        'low': [15.4] * 12,
        'close': [15.6] * 12,
        'vol': [8000] * 12,
        'turnover': [9.0] * 12,
    })
    df = pd.concat([bottom, markup, distribution], ignore_index=True)

    result = analyze_chip_peak(df, lookback=117, bins=64, decay_coefficient=1.2)

    assert result['behavior_code'] == 'distribution'
    assert result['bottom_peak_retention_pct'] < 35
    assert result['recent_volume_ratio'] >= 1.8
    assert '派发' in result['main_force_signal'] or '抛售' in result['main_force_signal']
