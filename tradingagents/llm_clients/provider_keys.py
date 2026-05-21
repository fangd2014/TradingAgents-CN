from __future__ import annotations


_ALIASES = {
    "dashscope": "qwen",
    "alibaba": "qwen",
    "qwen": "qwen",
    "zhipu": "glm",
    "glm": "glm",
    "openai": "openai",
    "google": "google",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "openrouter": "openrouter",
    "aihubmix": "aihubmix",
    "ollama": "ollama",
    "qianfan": "qianfan",
    "custom_openai": "custom_openai",
    "siliconflow": "siliconflow",
}

_CANONICAL_ALIASES = {
    "qwen": ["dashscope", "alibaba", "阿里百炼", "百炼"],
    "glm": ["zhipu", "智谱", "智谱ai"],
}


def normalize_provider_key(provider: str) -> str:
    if provider is None:
        return ""

    raw = str(provider).strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if "阿里百炼" in raw or "百炼" in raw:
        return "qwen"
    if "智谱" in raw:
        return "glm"

    return _ALIASES.get(lowered, lowered)


def env_key_for_provider(provider: str) -> str:
    key = normalize_provider_key(provider)
    env_key_map = {
        "google": "GOOGLE_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "aihubmix": "AIHUBMIX_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "qianfan": "QIANFAN_API_KEY",
        "glm": "ZHIPU_API_KEY",
    }
    return env_key_map.get(key, "")


def default_backend_url(provider: str) -> str:
    key = normalize_provider_key(provider)
    default_urls = {
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "anthropic": "https://api.anthropic.com",
        "openrouter": "https://openrouter.ai/api/v1",
        "aihubmix": "https://aihubmix.com/v1",
        "ollama": "http://localhost:11434/v1",
        "qianfan": "https://qianfan.baidubce.com/v2",
        "siliconflow": "https://api.siliconflow.cn/v1",
        "glm": "https://open.bigmodel.cn/api/paas/v4/",
    }
    return default_urls.get(key, "https://dashscope.aliyuncs.com/compatible-mode/v1")


def normalize_backend_url_for_provider(provider: str, backend_url: str) -> str:
    """Normalize provider endpoint URLs to the API style expected by clients."""
    key = normalize_provider_key(provider)
    if not backend_url:
        if key in {"custom_openai", ""}:
            return ""
        return default_backend_url(key)

    normalized_url = str(backend_url).strip().rstrip("/")
    if key == "qwen":
        legacy_dashscope_paths = (
            "https://dashscope.aliyuncs.com/api/v1",
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        )
        if normalized_url in legacy_dashscope_paths or "/services/aigc/text-generation/generation" in normalized_url:
            return default_backend_url(key)

    return normalized_url


def normalize_model_name_for_provider(provider: str, model_name: str) -> str:
    """Normalize provider-specific model IDs before API calls."""
    if model_name is None:
        return model_name

    normalized = str(model_name).strip()
    if not normalized:
        return normalized

    provider_key = normalize_provider_key(provider)
    if provider_key == "qwen":
        # DashScope model IDs are case-sensitive in compatible-mode. UI labels
        # and fetched catalogs may contain Qwen3.6-Flash style names.
        if normalized.lower().startswith(("qwen", "qwq", "qvq")):
            return normalized.lower()

    return normalized


def canonical_aliases(provider: str) -> list[str]:
    key = normalize_provider_key(provider)
    return list(_CANONICAL_ALIASES.get(key, []))
