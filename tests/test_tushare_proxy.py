import os

import pytest
import tushare as ts


@pytest.mark.integration
def test_tushare_direct_api_daily():
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        pytest.skip("TUSHARE_TOKEN is not configured")

    pro = ts.pro_api(token)
    df = pro.daily(ts_code="000001.SZ", start_date="20180701", end_date="20180718")

    assert df is not None
    assert not df.empty
