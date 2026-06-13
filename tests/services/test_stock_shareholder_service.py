import pytest

from app.services import stock_shareholder_service as shareholder_module
from app.services.stock_shareholder_service import StockShareholderService, fetch_tushare_shareholder_rows_sync


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)
        self._limit = None

    def sort(self, field, direction=1):
        reverse = direction == -1
        self.docs.sort(key=lambda item: item.get(field) or "", reverse=reverse)
        return self

    def limit(self, limit):
        self._limit = limit
        return self

    async def to_list(self, length=None):
        docs = self.docs
        if self._limit is not None:
            docs = docs[: self._limit]
        if length is not None:
            docs = docs[:length]
        return docs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.replacements = []
        self.indexes = []

    @staticmethod
    def _matches(doc, query):
        if not query:
            return True
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                else:
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _project(doc, projection):
        if projection is None:
            return dict(doc)
        excluded = {key for key, flag in projection.items() if not flag}
        return {key: value for key, value in doc.items() if key not in excluded}

    def find(self, query=None, projection=None):
        return FakeCursor([self._project(doc, projection) for doc in self.docs if self._matches(doc, query)])

    async def replace_one(self, query, replacement, upsert=False):
        self.replacements.append((query, replacement, upsert))
        self.docs = [doc for doc in self.docs if not self._matches(doc, query)]
        self.docs.append(replacement)

    async def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))


class FakeDb(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return super().__getitem__(name)


@pytest.mark.asyncio
async def test_shareholders_uses_cache_and_computes_period_changes():
    db = FakeDb(
        {
            "stock_shareholders": FakeCollection(
                [
                    {
                        "code": "688049",
                        "holder_scope": "top10",
                        "end_date": "20251231",
                        "rank": 1,
                        "holder_name": "A股东",
                        "holder_name_normalized": "a股东",
                        "hold_amount": 120,
                        "hold_ratio": 12,
                        "source": "tushare",
                        "updated_at": "2026-05-18T20:00:00+08:00",
                    },
                    {
                        "code": "688049",
                        "holder_scope": "top10",
                        "end_date": "20251231",
                        "rank": 2,
                        "holder_name": "C股东",
                        "holder_name_normalized": "c股东",
                        "hold_amount": 30,
                        "hold_ratio": 3,
                        "source": "tushare",
                        "updated_at": "2026-05-18T20:00:00+08:00",
                    },
                    {
                        "code": "688049",
                        "holder_scope": "top10",
                        "end_date": "20250930",
                        "rank": 1,
                        "holder_name": "A股东",
                        "holder_name_normalized": "a股东",
                        "hold_amount": 100,
                        "hold_ratio": 10,
                        "source": "tushare",
                        "updated_at": "2026-05-18T19:00:00+08:00",
                    },
                    {
                        "code": "688049",
                        "holder_scope": "top10",
                        "end_date": "20250930",
                        "rank": 2,
                        "holder_name": "B股东",
                        "holder_name_normalized": "b股东",
                        "hold_amount": 50,
                        "hold_ratio": 5,
                        "source": "tushare",
                        "updated_at": "2026-05-18T19:00:00+08:00",
                    },
                ]
            )
        }
    )
    service = StockShareholderService(db=db)

    result = await service.get_shareholders("688049", scope="top10", periods=4, refresh=False)

    assert result["status"] == "ok"
    assert result["is_cached"] is True
    assert result["latest_period"] == "20251231"
    assert result["previous_period"] == "20250930"
    assert result["changes"]["increased_count"] == 1
    assert result["changes"]["new_count"] == 1
    assert result["changes"]["exited_count"] == 1
    assert {item["change_type"] for item in result["changes"]["items"]} >= {"increased", "new", "exited"}


@pytest.mark.asyncio
async def test_shareholders_skips_incomplete_latest_period():
    docs = [
        {
            "code": "001309",
            "holder_scope": "top10",
            "end_date": "20260331",
            "rank": 1,
            "holder_name": "单行股东",
            "holder_name_normalized": "单行股东",
            "hold_amount": 100,
            "hold_ratio": 10,
        }
    ]
    docs.extend(
        {
            "code": "001309",
            "holder_scope": "top10",
            "end_date": "20250630",
            "rank": rank,
            "holder_name": f"完整股东{rank}",
            "holder_name_normalized": f"完整股东{rank}",
            "hold_amount": 100 - rank,
            "hold_ratio": 10 - rank / 10,
        }
        for rank in range(1, 11)
    )
    db = FakeDb({"stock_shareholders": FakeCollection(docs)})
    service = StockShareholderService(db=db)

    result = await service.get_shareholders("001309", scope="top10", periods=4, refresh=False)

    assert result["status"] == "ok"
    assert result["latest_period"] == "20250630"
    assert len(result["latest"]) == 10


def test_normalize_tushare_holder_rows_supports_top10_and_float_scopes():
    top10_row = {
        "ts_code": "688049.SH",
        "end_date": "20251231",
        "ann_date": "20260420",
        "holder_name": "炬芯投资",
        "hold_amount": "100.5",
        "hold_ratio": "8.2",
        "hold_change": "1.5",
    }
    float_row = {
        "ts_code": "688049.SH",
        "end_date": "20251231",
        "holder_name": "流通股东A",
        "hold_amount": "80",
        "hold_ratio": "6.1",
    }

    top10 = StockShareholderService.normalize_tushare_row(top10_row, scope="top10", rank=1)
    floating = StockShareholderService.normalize_tushare_row(float_row, scope="float_top10", rank=2)

    assert top10["code"] == "688049"
    assert top10["holder_scope"] == "top10"
    assert top10["holder_name_normalized"] == "炬芯投资"
    assert top10["hold_amount"] == 100.5
    assert top10["hold_ratio"] == 8.2
    assert top10["hold_change"] == 1.5
    assert floating["holder_scope"] == "float_top10"
    assert floating["rank"] == 2


def test_tushare_shareholders_raw_http_fallback_when_sdk_returns_empty(monkeypatch):
    class EmptyDf:
        empty = True

    class FakeApi:
        @staticmethod
        def top10_holders(ts_code):
            assert ts_code == "001309.SZ"
            return EmptyDf()

    class FakeProvider:
        api = FakeApi()
        config = {"token": "token"}

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def _get_token_from_database():
            return "token"

    monkeypatch.setattr(
        "tradingagents.dataflows.providers.china.tushare.get_tushare_provider",
        lambda: FakeProvider(),
    )
    monkeypatch.setattr(
        shareholder_module,
        "_fetch_tushare_raw_rows_sync",
        lambda api_name, ts_code, token: [
            {
                "ts_code": ts_code,
                "ann_date": "20260430",
                "end_date": "20260331",
                "holder_name": "李虎",
                "hold_amount": 79410129.0,
                "hold_ratio": 35.0062,
            }
        ],
    )

    rows = fetch_tushare_shareholder_rows_sync("001309", "top10")

    assert rows[0]["code"] == "001309"
    assert rows[0]["holder_scope"] == "top10"
    assert rows[0]["holder_name"] == "李虎"
    assert rows[0]["hold_amount"] == 79410129.0


@pytest.mark.asyncio
async def test_shareholders_refresh_saves_tushare_rows_when_cache_missing():
    db = FakeDb({"stock_shareholders": FakeCollection([])})
    service = StockShareholderService(db=db)

    async def fake_tushare(code, scope):
        assert code == "688049"
        assert scope == "top10"
        return [
            {
                "code": "688049",
                "ts_code": "688049.SH",
                "holder_scope": "top10",
                "end_date": "20251231",
                "ann_date": "20260420",
                "rank": 1,
                "holder_name": "A股东",
                "holder_name_normalized": "a股东",
                "hold_amount": 100,
                "hold_ratio": 10,
                "source": "tushare",
            }
        ]

    service._fetch_tushare = fake_tushare
    service._fetch_akshare = lambda *_args, **_kwargs: []

    result = await service.get_shareholders("688049", scope="top10", periods=4, refresh=False)

    assert result["status"] == "ok"
    assert result["source"] == "tushare"
    assert result["is_cached"] is False
    assert len(db["stock_shareholders"].replacements) == 1
    assert result["latest"][0]["holder_name"] == "A股东"
