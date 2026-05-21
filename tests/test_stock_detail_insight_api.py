import pytest

from app.routers import stocks


@pytest.mark.asyncio
async def test_financial_detail_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_financial_detail(self, code, periods=8, refresh=False):
            return {"code": code, "status": "ok", "periods": ["20251231"]}

    monkeypatch.setattr(stocks, "get_stock_detail_insight_service", lambda: FakeService())

    response = await stocks.get_financial_detail(
        "688049",
        periods=8,
        refresh=False,
        current_user={"id": "u1"},
    )

    assert response["success"] is True
    assert response["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_industry_comparison_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_industry_comparison(self, code, period="latest", refresh=False):
            return {"code": code, "status": "ok", "industry": "电气设备"}

    monkeypatch.setattr(stocks, "get_stock_detail_insight_service", lambda: FakeService())

    response = await stocks.get_industry_comparison(
        "688049",
        period="latest",
        refresh=False,
        current_user={"id": "u1"},
    )

    assert response["success"] is True
    assert response["data"]["industry"] == "电气设备"


@pytest.mark.asyncio
async def test_technical_factors_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_technical_factors(self, code, limit=120, refresh=False):
            return {"code": code, "status": "ok", "magic_nine": {}}

    monkeypatch.setattr(stocks, "get_stock_detail_insight_service", lambda: FakeService())

    response = await stocks.get_technical_factors(
        "688049",
        limit=120,
        refresh=False,
        current_user={"id": "u1"},
    )

    assert response["success"] is True
    assert response["data"]["magic_nine"] == {}


@pytest.mark.asyncio
async def test_shareholders_endpoint_wraps_service(monkeypatch):
    class FakeService:
        async def get_shareholders(self, code, scope="top10", periods=4, refresh=False):
            return {
                "code": code,
                "scope": scope,
                "status": "ok",
                "latest_period": "20251231",
                "latest": [],
            }

    monkeypatch.setattr(stocks, "get_stock_shareholder_service", lambda: FakeService())

    response = await stocks.get_shareholders(
        "688049",
        scope="float_top10",
        periods=4,
        refresh=False,
        current_user={"id": "u1"},
    )

    assert response["success"] is True
    assert response["data"]["scope"] == "float_top10"
    assert response["data"]["latest_period"] == "20251231"
