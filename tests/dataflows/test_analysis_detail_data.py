from tradingagents.dataflows.analysis_detail_data import (
    _format_financial_detail,
    _format_industry_comparison,
    _format_shareholders,
    _format_technical_factors,
    normalize_code6,
)


def test_normalize_code6_strips_exchange_suffix():
    assert normalize_code6("688049.SH") == "688049"


def test_format_financial_detail_includes_statement_tables_in_yi():
    content = _format_financial_detail(
        {
            "status": "ok",
            "summary": {"report_period": "20251231", "revenue": 1230000000, "roe": 8.5},
            "income_statement": [{"end_date": "20251231", "revenue": 1230000000, "n_income_attr_p": 200000000, "oper_profit": 300000000}],
            "balance_sheet": [{"end_date": "20251231", "total_assets": 5000000000, "total_liab": 2000000000, "money_cap": 800000000}],
            "cashflow_statement": [{"end_date": "20251231", "n_cashflow_act": 100000000, "n_cashflow_inv_act": -200000000, "n_cashflow_fin_act": 300000000}],
            "main_business": [{"end_date": "20251231", "bz_item": "产品A", "bz_sales": 900000000, "bz_profit": 100000000, "bz_cost": 800000000}],
        }
    )

    assert "## 详细财务数据" in content
    assert "12.30亿元" in content
    assert "### 利润表摘要" in content
    assert "### 资产负债表摘要" in content
    assert "### 现金流量表摘要" in content


def test_format_industry_comparison_includes_median_metrics():
    content = _format_industry_comparison(
        {
            "industry": "电气设备",
            "sample_count": 5,
            "metrics": {"pe": {"stock_value": 10, "industry_median": 12, "percentile": 40, "rank": 2}},
        }
    )

    assert "行业: 电气设备" in content
    assert "| PE | 10.00 | 12.00 | 40.00 | 2 |" in content


def test_format_shareholders_includes_change_counts_and_latest_holders():
    content = _format_shareholders(
        "前十大股东",
        {
            "status": "ok",
            "latest_period": "20251231",
            "previous_period": "20250930",
            "changes": {"new_count": 1, "exited_count": 2, "increased_count": 3, "decreased_count": 4, "rank_changed_count": 5},
            "latest": [{"rank": 1, "holder_name": "A股东", "hold_amount": 120000000, "hold_ratio": 12.5, "change_type": "increased"}],
        },
    )

    assert "新增1、退出2、增持3、减持4、排名变化5" in content
    assert "1.20亿股" in content


def test_format_technical_factors_includes_magic_nine_and_factors():
    content = _format_technical_factors(
        {
            "magic_nine": {"status": "ok", "current_direction": "up", "current_count": 6},
            "factors": {"ma_5": {"latest": 12.345, "signal": "多头"}},
        }
    )

    assert "神奇九转" in content
    assert "方向=up" in content
    assert "| MA5 | 12.35 | 多头 |" in content
