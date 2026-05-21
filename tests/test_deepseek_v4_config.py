from app.services.config_service import ConfigService
from app.services.simple_analysis_service import _get_default_provider_by_model
from tradingagents.llm_clients.model_catalog import get_known_models, get_model_options


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "I can read this.",
                        "content": "",
                    }
                }
            ]
        }


def test_deepseek_v4_flash_is_known_and_maps_to_deepseek():
    assert "deepseek-v4-flash" in get_known_models()["deepseek"]
    assert ("DeepSeek V4 Flash", "deepseek-v4-flash") in get_model_options("deepseek", "quick")
    assert _get_default_provider_by_model("deepseek-v4-flash") == "deepseek"


def test_deepseek_test_accepts_reasoning_content_when_final_content_is_empty(monkeypatch):
    captured_payload = {}

    def fake_post(url, json, headers, timeout):
        captured_payload.update(json)
        return FakeResponse()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    result = ConfigService()._test_deepseek_api(
        "sk-test-key-with-enough-length",
        "deepseek deepseek-v4-flash",
        "deepseek-v4-flash",
    )

    assert result["success"] is True
    assert captured_payload["model"] == "deepseek-v4-flash"
    assert captured_payload["max_tokens"] >= 200
