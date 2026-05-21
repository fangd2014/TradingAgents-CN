from bson import ObjectId

from app.services.unified_stock_service import UnifiedStockService


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return _FakeCursor(self._docs)


class _FakeDB:
    def __init__(self, docs):
        self._docs = docs

    def __getitem__(self, name):
        return _FakeCollection(self._docs)


async def test_search_stocks_returns_json_safe_documents():
    db = _FakeDB([
        {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "code": "600089",
            "name": "特变电工",
            "source": "tushare",
        }
    ])
    service = UnifiedStockService(db)

    results = await service.search_stocks("CN", "特变电工", 5)

    assert results == [
        {
            "code": "600089",
            "name": "特变电工",
            "source": "tushare",
        }
    ]
