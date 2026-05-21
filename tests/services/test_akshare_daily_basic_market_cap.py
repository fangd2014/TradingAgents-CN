from __future__ import annotations

import sys
import types

import pandas as pd

from app.services.basics_sync.processing import add_financial_metrics
from app.services.data_sources.akshare_adapter import AKShareAdapter


def test_akshare_circ_mv_uses_float_share_times_previous_close(monkeypatch):
    class FakeAkshare(types.SimpleNamespace):
        @staticmethod
        def stock_individual_info_em(symbol: str):
            return pd.DataFrame(
                [
                    {"item": "最新", "value": 10.5},
                    {"item": "昨收", "value": 10.0},
                    {"item": "总股本", "value": 20000.0},
                    {"item": "流通股", "value": 10000.0},
                    {"item": "总市值", "value": 210000.0},
                ]
            )

    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare())

    adapter = AKShareAdapter()
    monkeypatch.setattr(
        adapter,
        "get_stock_list",
        lambda: pd.DataFrame(
            [{"symbol": "000001", "name": "平安银行", "ts_code": "000001.SZ"}]
        ),
    )

    df = adapter.get_daily_basic("20260510")

    assert df is not None
    row = df.iloc[0]
    assert row["float_share"] == 10000.0
    assert row["pre_close"] == 10.0
    assert row["circ_mv"] == 100000.0

    doc = {}
    add_financial_metrics(doc, row.to_dict())
    assert doc["circ_mv"] == 10.0
    assert doc["total_mv"] == 21.0
