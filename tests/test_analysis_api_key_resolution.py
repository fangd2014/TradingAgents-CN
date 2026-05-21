from unittest.mock import MagicMock, patch

from app.services.simple_analysis_service import get_provider_and_url_by_model_sync


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, sort=None):
        if query == {"is_active": True}:
            return self.docs.get("system_config")
        if "name" in query:
            return self.docs.get("providers", {}).get(query["name"])
        return None


class FakeDB:
    def __init__(self, docs):
        self.system_configs = FakeCollection(docs)
        self.llm_providers = FakeCollection(docs)


class FakeMongoClient:
    def __init__(self, docs):
        self.docs = docs

    def __getitem__(self, name):
        return FakeDB(self.docs)

    def close(self):
        pass


def test_model_placeholder_api_key_falls_back_to_provider_key():
    docs = {
        "system_config": {
            "is_active": True,
            "version": 1,
            "llm_configs": [
                {
                    "provider": "qwen",
                    "model_name": "qwen-turbo",
                    "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "your_dashscope_api_key_here",
                }
            ],
        },
        "providers": {
            "qwen": {
                "name": "qwen",
                "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-valid-provider-key-123456",
            }
        },
    }

    fake_settings = MagicMock(MONGO_URI="mongodb://unused", MONGO_DB="tradingagentscn")
    with patch("pymongo.MongoClient", return_value=FakeMongoClient(docs)), patch(
        "app.core.config.settings", fake_settings
    ):
        result = get_provider_and_url_by_model_sync("qwen-turbo")

    assert result["provider"] == "qwen"
    assert result["backend_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert result["api_key"] == "sk-valid-provider-key-123456"


def test_qwen_model_falls_back_to_legacy_dashscope_provider_key():
    docs = {
        "system_config": {
            "is_active": True,
            "version": 1,
            "llm_configs": [
                {
                    "provider": "qwen",
                    "model_name": "qwen-turbo",
                    "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "your_dashscope_api_key_here",
                }
            ],
        },
        "providers": {
            "dashscope": {
                "name": "dashscope",
                "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-valid-dashscope-key-123456",
            }
        },
    }

    fake_settings = MagicMock(MONGO_URI="mongodb://unused", MONGO_DB="tradingagentscn")
    with patch("pymongo.MongoClient", return_value=FakeMongoClient(docs)), patch(
        "app.core.config.settings", fake_settings
    ):
        result = get_provider_and_url_by_model_sync("qwen-turbo")

    assert result["provider"] == "qwen"
    assert result["backend_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert result["api_key"] == "sk-valid-dashscope-key-123456"


def test_qwen_legacy_dashscope_generation_url_normalizes_to_compatible_mode():
    docs = {
        "system_config": {
            "is_active": True,
            "version": 1,
            "llm_configs": [
                {
                    "provider": "dashscope",
                    "model_name": "qwen-turbo",
                    "api_base": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                    "api_key": "your_dashscope_api_key_here",
                }
            ],
        },
        "providers": {
            "dashscope": {
                "name": "dashscope",
                "default_base_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                "api_key": "sk-valid-dashscope-key-123456",
            }
        },
    }

    fake_settings = MagicMock(MONGO_URI="mongodb://unused", MONGO_DB="tradingagentscn")
    with patch("pymongo.MongoClient", return_value=FakeMongoClient(docs)), patch(
        "app.core.config.settings", fake_settings
    ):
        result = get_provider_and_url_by_model_sync("qwen-turbo")

    assert result["provider"] == "qwen"
    assert result["backend_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
