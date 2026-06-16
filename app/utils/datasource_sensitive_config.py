"""
数据源敏感扩展配置处理。

用于把诸如 Tushare 网页 Cookie 这类不适合明文返回前端的配置，
统一做键名规范化、响应脱敏、更新保留和环境变量桥接。
"""

import os
from typing import Any, Dict, Mapping, MutableMapping, Optional


CANONICAL_TUSHARE_WEB_COOKIE_KEY = "TUSHARE_WEB_COOKIE"
TUSHARE_WEB_COOKIE_ALIASES = (
    CANONICAL_TUSHARE_WEB_COOKIE_KEY,
    "tushare_web_cookie",
    "web_cookie",
)
IWENCAI_COOKIE_ENV_KEY = "IWENCAI_COOKIE"
TUSHARE_TOKEN_ENV_KEY = "TUSHARE_TOKEN"
TUSHARE_API_URL_ENV_KEY = "TUSHARE_API_URL"
IFIND_USERNAME_ENV_KEY = "IFIND_USERNAME"
IFIND_PASSWORD_ENV_KEY = "IFIND_PASSWORD"

IFIND_CONFIG_KEYS = (
    "IFIND_BASIC_INDICATORS",
    "IFIND_BASIC_PARAMS",
    "IFIND_QUERY_TEMPLATES",
    "IFIND_INCLUDE_QUERY",
)


def source_type_to_string(source_type: Any) -> str:
    if hasattr(source_type, "value"):
        source_type = source_type.value
    return str(source_type or "").strip().lower()


def normalize_sensitive_config_params(
    source_type: Any,
    config_params: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """规范化数据源敏感配置键名。"""
    params = dict(config_params or {})
    if source_type_to_string(source_type) != "tushare":
        return params

    canonical_value = params.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY)
    for alias in TUSHARE_WEB_COOKIE_ALIASES:
        if alias == CANONICAL_TUSHARE_WEB_COOKIE_KEY:
            continue
        alias_value = params.pop(alias, None)
        if not canonical_value and alias_value:
            canonical_value = alias_value

    if canonical_value is not None:
        params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = canonical_value

    return params


def sanitize_sensitive_config_params(
    source_type: Any,
    config_params: Optional[Mapping[str, Any]],
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """脱敏响应中的数据源敏感扩展配置。"""
    params = normalize_sensitive_config_params(source_type, config_params)
    if source_type_to_string(source_type) != "tushare":
        return params

    env = env if env is not None else os.environ
    cookie = _clean_sensitive_value(params.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY))
    if cookie:
        params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = truncate_sensitive_value(cookie)
        return params

    env_cookie = _clean_sensitive_value(env.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY))
    if env_cookie:
        params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = truncate_sensitive_value(env_cookie)
    else:
        params.pop(CANONICAL_TUSHARE_WEB_COOKIE_KEY, None)

    return params


def merge_sensitive_config_params_for_update(
    source_type: Any,
    incoming_params: Optional[Mapping[str, Any]],
    existing_params: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """合并更新请求，避免空值或脱敏值覆盖已有敏感配置。"""
    params = normalize_sensitive_config_params(source_type, incoming_params)
    if source_type_to_string(source_type) != "tushare":
        return params

    existing = normalize_sensitive_config_params(source_type, existing_params)
    incoming_cookie = params.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY)
    existing_cookie = _clean_sensitive_value(existing.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY))

    if _should_preserve_sensitive_value(incoming_cookie):
        if existing_cookie:
            params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = existing_cookie
        else:
            params.pop(CANONICAL_TUSHARE_WEB_COOKIE_KEY, None)
    else:
        cleaned_cookie = _clean_sensitive_value(incoming_cookie)
        if cleaned_cookie:
            params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = cleaned_cookie
        else:
            params.pop(CANONICAL_TUSHARE_WEB_COOKIE_KEY, None)

    return params


def bridge_sensitive_config_params_to_env(
    source_type: Any,
    config_params: Optional[Mapping[str, Any]],
    env: Optional[MutableMapping[str, str]] = None,
) -> int:
    """将可运行时使用的数据源敏感配置桥接到环境变量。"""
    source = source_type_to_string(source_type)
    if source not in {"tushare", "ifind"}:
        return 0

    params = normalize_sensitive_config_params(source_type, config_params)
    if source == "ifind":
        env = env if env is not None else os.environ
        bridged = 0
        for key in IFIND_CONFIG_KEYS:
            value = _clean_sensitive_value(params.get(key))
            if value:
                env[key] = value
                bridged += 1
        return bridged

    cookie = _clean_sensitive_value(params.get(CANONICAL_TUSHARE_WEB_COOKIE_KEY))
    if not cookie or _should_preserve_sensitive_value(cookie):
        return 0

    env = env if env is not None else os.environ
    env[CANONICAL_TUSHARE_WEB_COOKIE_KEY] = cookie
    return 1


def bridge_datasource_credentials_to_env(
    source_type: Any,
    api_key: Optional[Any] = None,
    api_secret: Optional[Any] = None,
    endpoint: Optional[Any] = None,
    env: Optional[MutableMapping[str, str]] = None,
) -> int:
    """将数据源主凭据桥接到运行时环境变量。"""
    source = source_type_to_string(source_type)
    env = env if env is not None else os.environ
    bridged = 0

    cleaned_api_key = _clean_sensitive_value(api_key)
    if cleaned_api_key and not _should_preserve_sensitive_value(cleaned_api_key):
        if source == "tushare":
            env[TUSHARE_TOKEN_ENV_KEY] = cleaned_api_key
            bridged += 1
        elif source in {"iwencai", "ths_hotspot"}:
            env[IWENCAI_COOKIE_ENV_KEY] = cleaned_api_key
            bridged += 1
        elif source == "ifind":
            env[IFIND_USERNAME_ENV_KEY] = cleaned_api_key
            bridged += 1

    cleaned_api_secret = _clean_sensitive_value(api_secret)
    if source == "ifind" and cleaned_api_secret and not _should_preserve_sensitive_value(cleaned_api_secret):
        env[IFIND_PASSWORD_ENV_KEY] = cleaned_api_secret
        bridged += 1

    cleaned_endpoint = _clean_sensitive_value(endpoint)
    if source == "tushare" and cleaned_endpoint:
        env[TUSHARE_API_URL_ENV_KEY] = normalize_tushare_api_url(cleaned_endpoint)
        bridged += 1

    return bridged


def normalize_tushare_api_url(value: Optional[Any]) -> str:
    """规范化 Tushare Pro API 地址，兼容旧的 tushare.pro 页面地址配置。"""
    api_url = _clean_sensitive_value(value) or "http://api.tushare.pro"
    api_url = api_url.rstrip("/")
    if api_url in {"http://tushare.pro", "https://tushare.pro"}:
        return "http://api.tushare.pro"
    return api_url


def truncate_sensitive_value(value: Optional[str], prefix_len: int = 6, suffix_len: int = 6) -> Optional[str]:
    if not value:
        return value
    value = str(value)
    if len(value) <= prefix_len + suffix_len:
        return value
    return f"{value[:prefix_len]}...{value[-suffix_len:]}"


def _clean_sensitive_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _should_preserve_sensitive_value(value: Any) -> bool:
    value = _clean_sensitive_value(value)
    if not value:
        return True
    if "..." in value:
        return True
    if value.startswith("your_") or value.startswith("your-"):
        return True
    return False
