from app.services.stock_detail_insight_service import (
    calculate_magic_nine,
    normalize_code6,
)


def _bars(closes):
    return [
        {"trade_date": f"202605{idx + 1:02d}", "close": close}
        for idx, close in enumerate(closes)
    ]


def test_normalize_code6_strips_suffix_and_pads():
    assert normalize_code6("688049.SH") == "688049"
    assert normalize_code6("1") == "000001"


def test_calculate_magic_nine_up_signal():
    bars = _bars([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "up"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "up"
    assert result["latest_signal"]["count"] == 9
    assert result["latest_signal"]["date"] == "20260513"


def test_calculate_magic_nine_down_signal():
    bars = _bars([20, 20, 20, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11])

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "down"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "down"


def test_calculate_magic_nine_insufficient_data():
    result = calculate_magic_nine(_bars([1, 2, 3, 4]))

    assert result["status"] == "insufficient_data"
    assert result["required_bars"] == 13


def test_calculate_magic_nine_non_zero_padded_dates_sorted_chronologically():
    bars = [
        {"trade_date": f"2026-05-{idx}", "close": close}
        for idx, close in enumerate([10, 10, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], start=1)
    ]

    result = calculate_magic_nine(bars)

    assert result["status"] == "ok"
    assert result["current_direction"] == "up"
    assert result["current_count"] == 9
    assert result["latest_signal"]["direction"] == "up"
    assert result["latest_signal"]["count"] == 9
    assert result["latest_signal"]["date"] == "2026-05-13"
