from datetime import datetime, timedelta

import pandas as pd
import pytest


def _make_history(start_price: float = 10.0) -> pd.DataFrame:
    rows = []
    start = datetime(2026, 2, 1)

    for i in range(80):
        date = start + timedelta(days=i)
        if i < 20:
            close = start_price + i * 0.12
            volume = 2_000_000
        elif i < 45:
            close = start_price + 2.4 - (i - 20) * 0.07
            volume = 1_600_000
        elif i < 65:
            close = start_price + 0.65 + (i - 45) * 0.01
            volume = 1_400_000
        elif i < 77:
            close = start_price + 0.82 + (i - 65) * 0.015
            volume = 900_000
        elif i == 77:
            close = start_price + 1.15
            volume = 4_800_000
        elif i == 78:
            close = start_price + 1.20
            volume = 1_100_000
        else:
            close = start_price + 1.22
            volume = 1_300_000
        open_price = close - 0.08
        if i == 78:
            open_price = close + 0.05

        rows.append(
            {
                "trade_date": date.strftime("%Y-%m-%d"),
                "open": open_price,
                "high": close + 0.08,
                "low": close - 0.08,
                "close": close,
                "volume": volume,
                "amount": close * volume * 100,
                "period": "daily",
            }
        )

    return pd.DataFrame(rows)


def test_evaluate_trend_start_candidate_returns_recent_summary():
    from app.services.preset_screening_service import PresetScreeningService

    service = PresetScreeningService()
    candidate = {
        "code": "000001",
        "name": "平安银行",
        "industry": "银行",
        "board": "主板",
        "total_mv": 120,
        "circ_mv": 100,
        "turnover_rate_f": 6,
        "amount": 800_000_000,
    }

    result = service._evaluate_trend_start_candidate(candidate, _make_history())

    assert result is not None
    assert result["code"] == "000001"
    assert result["total_mv"] == 120
    assert result["board"] == "主板"
    assert result["close"] > 0
    assert result["pct_chg"] > 0
    assert result["five_day_change_pct"] > 0
    assert len(result["recent_5d"]) == 5
    assert result["matched_conditions"]["price_consolidation"] is True
    assert result["matched_conditions"]["ma_up"] is True
    assert result["matched_conditions"]["turnover_5d"] is True
    assert result["matched_conditions"]["volume_price_breakout"] is True
    assert result["matched_conditions"]["chip_control"] is True


def test_evaluate_trend_start_candidate_rejects_large_cap():
    from app.services.preset_screening_service import PresetScreeningService

    service = PresetScreeningService()
    candidate = {
        "code": "600000",
        "name": "大盘股",
        "industry": "银行",
        "board": "主板",
        "total_mv": 800,
        "circ_mv": 700,
        "turnover_rate_f": 4.2,
        "amount": 800_000_000,
    }

    assert service._evaluate_trend_start_candidate(candidate, _make_history()) is None


def test_evaluate_trend_start_candidate_trace_reports_failed_stage():
    from app.services.preset_screening_service import PresetScreeningService

    service = PresetScreeningService()
    candidate = {
        "code": "600000",
        "name": "大盘股",
        "industry": "银行",
        "board": "主板",
        "total_mv": 800,
        "circ_mv": 700,
        "turnover_rate_f": 4.2,
        "amount": 800_000_000,
    }

    result, diagnostic = service._evaluate_trend_start_candidate_with_trace(
        candidate,
        _make_history(),
    )

    assert result is None
    assert diagnostic["failed_stage"] == "price_consolidation"
    assert diagnostic["stage_results"]["price_consolidation"] is False
    assert diagnostic["metrics"]["circ_mv"] == 700


@pytest.mark.asyncio
async def test_load_recent_daily_history_falls_back_to_tushare_when_mongo_is_short(monkeypatch):
    from app.services.preset_screening_service import PresetScreeningService

    service = PresetScreeningService()
    mongo_history = _make_history().head(1)
    tushare_history = _make_history()

    async def fake_load_mongo_history(code, days):
        return mongo_history

    def fake_load_tushare_history(code, days):
        return tushare_history

    monkeypatch.setattr(service, "_load_recent_daily_history_from_mongo", fake_load_mongo_history)
    monkeypatch.setattr(service, "_load_recent_daily_history_from_tushare", fake_load_tushare_history)

    result = await service._load_recent_daily_history("000001", days=90)

    assert len(result.data) == len(tushare_history)
    assert result.source == "tushare"
    assert result.mongo_rows == 1
    assert result.tushare_rows == len(tushare_history)


@pytest.mark.asyncio
async def test_load_recent_daily_history_keeps_mongo_when_enough_rows(monkeypatch):
    from app.services.preset_screening_service import PresetScreeningService

    service = PresetScreeningService()
    mongo_history = _make_history()

    async def fake_load_mongo_history(code, days):
        return mongo_history

    def fail_if_called(code, days):
        raise AssertionError("Tushare fallback should not be called")

    monkeypatch.setattr(service, "_load_recent_daily_history_from_mongo", fake_load_mongo_history)
    monkeypatch.setattr(service, "_load_recent_daily_history_from_tushare", fail_if_called)

    result = await service._load_recent_daily_history("000001", days=90)

    assert result.data is mongo_history
    assert result.source == "mongodb"
    assert result.mongo_rows == len(mongo_history)
    assert result.tushare_rows == 0
