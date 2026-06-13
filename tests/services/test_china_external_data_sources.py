import sys
import types

import pandas as pd

class _DummyMongoClient:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return self

    def __getitem__(self, name):
        return self

    def command(self, *args, **kwargs):
        return {"ok": 1}

    def close(self):
        return None


sys.modules.setdefault("bson", types.SimpleNamespace(ObjectId=str))
sys.modules.setdefault("pymongo", types.SimpleNamespace(UpdateOne=object, MongoClient=_DummyMongoClient))
sys.modules.setdefault("pymongo.database", types.SimpleNamespace(Database=object))
sys.modules.setdefault(
    "pymongo.errors",
    types.SimpleNamespace(ServerSelectionTimeoutError=Exception, ConnectionFailure=Exception),
)
sys.modules.setdefault(
    "motor.motor_asyncio",
    types.SimpleNamespace(AsyncIOMotorClient=object, AsyncIOMotorDatabase=object),
)
sys.modules.setdefault("redis.asyncio", types.SimpleNamespace(Redis=object, ConnectionPool=object))
sys.modules.setdefault("redis.exceptions", types.SimpleNamespace(ConnectionError=Exception))


def test_tencent_quote_parser_standardizes_realtime_snapshot():
    from app.services.data_sources.tencent_finance_client import TencentFinanceClient

    line = (
        'v_sz000001="51~平安银行~000001~12.34~12.10~12.20~123456~'
        '0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
        '20260612150000~0.24~1.98~12.50~12.00~12.34/123456/152345678~'
        '123456~15235~0.85~9.8~~12.10~0.00~0.00~1.2~1000.0~1100.0~'
        '2.1~0.0~12.50~12.00~1.0~0.0~0.0~0.0";'
    )

    quote = TencentFinanceClient.parse_quote_line(line)

    assert quote == {
        "code": "000001",
        "name": "平安银行",
        "close": 12.34,
        "pre_close": 12.1,
        "open": 12.2,
        "high": 12.5,
        "low": 12.0,
        "pct_chg": 1.98,
        "amount": 15235.0,
        "volume": 123456.0,
        "turnover_rate": 0.85,
        "pe_ttm": 9.8,
        "pb": 1.2,
        "total_mv": 1000.0,
        "float_mv": 1100.0,
        "limit_up": 12.5,
        "limit_down": 12.0,
        "source": "tencent_finance",
    }


def test_eastmoney_reportapi_normalizes_eps_forecast_and_pdf_url():
    from app.services.china_external_data_service import EastmoneyReportApiClient

    report = EastmoneyReportApiClient().normalize_report(
        {
            "title": "业绩稳健增长",
            "stockCode": "000001",
            "stockName": "平安银行",
            "orgSName": "测试证券",
            "emRatingName": "买入",
            "publishDate": "2026-06-12 00:00:00.000",
            "infoCode": "AP202606121234567890",
            "predictThisYearEps": "1.23",
            "predictNextYearEps": "1.45",
            "predictNextTwoYearEps": "1.67",
        }
    )

    assert report["symbol"] == "000001"
    assert report["title"] == "业绩稳健增长"
    assert report["eps_forecast"] == {
        "this_year": 1.23,
        "next_year": 1.45,
        "next_two_year": 1.67,
    }
    assert report["pdf_url"] == "https://pdf.dfcfw.com/pdf/H3_AP202606121234567890_1.pdf"
    assert report["source"] == "eastmoney_reportapi"


def test_eastmoney_reportapi_strips_jsonp_response():
    from app.services.china_external_data_service import EastmoneyReportApiClient

    data = EastmoneyReportApiClient.parse_jsonp('callback123({"hits":1,"data":[{"title":"x"}]})')

    assert data == {"hits": 1, "data": [{"title": "x"}]}


def test_iwencai_pywencai_client_passes_cookie_and_normalizes_dataframe(monkeypatch):
    from app.services.china_external_data_service import IwencaiPywencaiClient

    captured = {}

    class Pywencai:
        @staticmethod
        def get(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame([{"股票代码": "000001"}, {"股票代码": "000002"}])

    monkeypatch.setitem(sys.modules, "pywencai", Pywencai)

    client = IwencaiPywencaiClient(cookie="v=A; other=B")

    result = client.search("人形机器人 丝杠", limit=1)

    assert result["available"] is True
    assert captured == {
        "query": "人形机器人 丝杠",
        "perpage": 1,
        "loop": False,
        "cookie": "v=A; other=B",
    }
    assert result["results"] == [{"股票代码": "000001"}]


def test_ths_hotspot_service_builds_editorial_theme_query():
    from app.services.china_external_data_service import THSHotspotService

    class Client:
        def search(self, query, limit):
            return {
                "available": True,
                "results": [
                    {"股票代码": "000001", "股票简称": "平安银行", "题材": "金融科技;银行", "热点归因": "信贷政策催化"}
                ],
            }

    result = THSHotspotService(client=Client()).get_hotspots(limit=20)

    assert "同花顺 当日强势股 题材归因" in result["query"]
    assert result["items"][0]["tags"] == ["金融科技", "银行"]
    assert result["items"][0]["reason"] == "信贷政策催化"
    assert result["source"] == "ths_hotspot_pywencai"


def test_akshare_news_trio_normalizes_individual_cls_and_global(monkeypatch):
    from app.services.china_external_data_service import AkshareNewsService

    fake_ak = types.SimpleNamespace(
        stock_news_em=lambda symbol: pd.DataFrame([{"新闻标题": "个股新闻", "文章来源": "东财", "发布时间": "2026-06-12", "新闻链接": "u1"}]),
        stock_info_global_cls=lambda: pd.DataFrame([{"标题": "财联社快讯", "发布时间": "2026-06-12 10:00:00", "内容": "电报内容"}]),
        stock_info_global_em=lambda: pd.DataFrame([{"标题": "全球资讯", "发布时间": "2026-06-12 11:00:00", "链接": "u3"}]),
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    service = AkshareNewsService()

    assert service.get_stock_news("000001", limit=1)[0]["type"] == "stock_news"
    assert service.get_cls_flash(limit=1)[0]["type"] == "cls_flash"
    assert service.get_global_news(limit=1)[0]["type"] == "global_news"


def test_cninfo_announcement_service_normalizes_disclosure(monkeypatch):
    from app.services.china_external_data_service import CninfoAnnouncementService

    fake_ak = types.SimpleNamespace(
        stock_zh_a_disclosure_report_cninfo=lambda symbol, market, keyword, category, start_date, end_date: pd.DataFrame(
            [{"公告标题": "年度报告", "公告时间": "2026-06-12", "公告链接": "https://example.com/a.pdf", "公告类型": "年报"}]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    result = CninfoAnnouncementService().get_announcements("000001", limit=1)

    assert result[0] == {
        "symbol": "000001",
        "title": "年度报告",
        "publish_date": "2026-06-12",
        "url": "https://example.com/a.pdf",
        "category": "年报",
        "source": "cninfo_akshare",
    }


def test_mootdx_deep_market_service_delegates_core_calls():
    from app.services.china_external_data_service import MootdxDeepMarketService

    calls = []

    class Client:
        def quotes(self, symbols):
            calls.append(("quotes", symbols))
            return pd.DataFrame([{"code": "000001", "price": 12.3}])

        def bars(self, symbol, frequency, offset):
            calls.append(("bars", symbol, frequency, offset))
            return pd.DataFrame([{"datetime": "2026-06-12", "close": 12.3}])

        def transactions(self, symbol, start, offset):
            calls.append(("transactions", symbol, start, offset))
            return pd.DataFrame([{"time": "09:30:00", "price": 12.3, "vol": 10}])

    service = MootdxDeepMarketService(client=Client())

    assert service.get_order_book("000001")[0]["code"] == "000001"
    assert service.get_kline("000001", period="day", limit=5)[0]["close"] == 12.3
    assert service.get_transactions("000001", start=0, limit=10)[0]["price"] == 12.3
    assert calls == [
        ("quotes", [(0, "000001")]),
        ("bars", "000001", 9, 5),
        ("transactions", "000001", 0, 10),
    ]


def test_quotes_service_does_not_fallback_to_akshare_when_external_quotes_empty(monkeypatch):
    from app.services.quotes_service import QuotesService

    service = QuotesService(ttl_seconds=0)
    monkeypatch.setattr(service, "_fetch_external_quotes", lambda codes: {})
    assert not hasattr(service, "_fetch_spot_akshare")

    import asyncio

    assert asyncio.run(service.get_quotes(["000001"])) == {}


def test_quotes_ingestion_rotation_only_uses_external_quotes():
    sys.modules.setdefault("pymongo", types.SimpleNamespace(UpdateOne=object, MongoClient=object))
    sys.modules.setdefault("pymongo.database", types.SimpleNamespace(Database=object))
    sys.modules.setdefault(
        "pymongo.errors",
        types.SimpleNamespace(ServerSelectionTimeoutError=Exception, ConnectionFailure=Exception),
    )
    sys.modules.setdefault(
        "motor.motor_asyncio",
        types.SimpleNamespace(AsyncIOMotorClient=object, AsyncIOMotorDatabase=object),
    )
    sys.modules.setdefault("redis.asyncio", types.SimpleNamespace(Redis=object, ConnectionPool=object))
    sys.modules.setdefault("redis.exceptions", types.SimpleNamespace(ConnectionError=Exception))

    from app.services.quotes_ingestion_service import QuotesIngestionService

    service = QuotesIngestionService()

    assert service._rotation_sources == ["external_quotes"]
    assert service._get_next_source() == ("external_quotes", None)
    assert service._get_next_source() == ("external_quotes", None)


def test_semantic_search_reports_unavailable_without_iwencai_cookie(monkeypatch):
    from app.services import china_external_data_service

    monkeypatch.setattr(china_external_data_service.settings, "IWENCAI_COOKIE", "")
    from app.services.china_external_data_service import SemanticSearchService

    result = SemanticSearchService(client=None).search("人工智能 近5日涨幅", limit=10)

    assert result["available"] is False
    assert result["source"] == "iwencai"
    assert "IWENCAI_COOKIE" in result["reason"]


def test_theme_tag_service_extracts_concept_columns(monkeypatch):
    from app.services.china_external_data_service import ThemeTagService

    class Client:
        def search(self, query, limit):
            return {
                "available": True,
                "results": [
                    {"股票代码": "000001", "股票简称": "平安银行", "所属概念": "银行;互联金融", "题材": "金融科技"}
                ],
            }

    result = ThemeTagService(client=Client()).get_tags("000001")

    assert result["available"] is True
    assert result["symbol"] == "000001"
    assert result["tags"] == ["银行", "互联金融", "金融科技"]
    assert result["source"] == "iwencai_ths_tags"


def test_data_source_type_registers_latest_china_sources():
    from app.models.config import DataSourceType
    from tradingagents.constants.data_sources import DATA_SOURCE_REGISTRY, DataSourceCode

    assert DataSourceType.EXTERNAL_QUOTES.value == "external_quotes"
    assert DataSourceType.MOOTDX.value == "mootdx"
    assert DataSourceType.TENCENT_FINANCE.value == "tencent_finance"
    assert DataSourceType.EASTMONEY_REPORTAPI.value == "eastmoney_reportapi"
    assert DataSourceType.IWENCAI.value == "iwencai"
    assert DataSourceType.THS_HOTSPOT.value == "ths_hotspot"
    assert DataSourceType.AKSHARE_NEWS.value == "akshare_news"
    assert DataSourceType.CNINFO.value == "cninfo"
    assert DATA_SOURCE_REGISTRY[DataSourceCode.EXTERNAL_QUOTES].requires_api_key is False
    assert DATA_SOURCE_REGISTRY[DataSourceCode.IWENCAI].requires_api_key is False
    assert "Cookie" in DATA_SOURCE_REGISTRY[DataSourceCode.IWENCAI].description


def test_latest_china_data_source_configs_enable_iwencai_from_cookie():
    from app.models.config import DataSourceType, build_latest_china_data_source_configs

    without_cookie = build_latest_china_data_source_configs("")
    with_cookie = build_latest_china_data_source_configs("v=A; other=B")

    assert next(config for config in without_cookie if config.type == DataSourceType.IWENCAI).enabled is False
    iwencai = next(config for config in with_cookie if config.type == DataSourceType.IWENCAI)
    assert iwencai.enabled is True
    assert iwencai.name == "iWenCai pywencai"
    assert iwencai.endpoint == "pywencai://iwencai"


def test_favorite_formatter_preserves_latest_source_enrichment_fields():
    from app.services.favorites_service import FavoritesService

    favorite = FavoritesService()._format_favorite(
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "pe_ttm": 9.8,
            "pb": 1.2,
            "total_mv": 1000.0,
            "float_mv": 900.0,
            "turnover_rate": 0.85,
            "limit_up": 13.2,
            "limit_down": 10.8,
            "quote_source": "tencent_finance",
            "data_sources": {"quote": "tencent_finance"},
        }
    )

    assert favorite["pe_ttm"] == 9.8
    assert favorite["pb"] == 1.2
    assert favorite["total_mv"] == 1000.0
    assert favorite["float_mv"] == 900.0
    assert favorite["turnover_rate"] == 0.85
    assert favorite["limit_up"] == 13.2
    assert favorite["limit_down"] == 10.8
    assert favorite["quote_source"] == "tencent_finance"
    assert favorite["data_sources"] == {"quote": "tencent_finance"}


def test_favorites_realtime_sync_defaults_to_external_quotes():
    from app.routers.favorites import SyncFavoritesRequest

    assert SyncFavoritesRequest().data_source == "external_quotes"
