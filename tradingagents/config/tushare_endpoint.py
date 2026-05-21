"""Tushare API endpoint configuration helpers."""
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_TUSHARE_API_URL = "http://api.tushare.pro"


def get_tushare_api_url() -> str:
    """Return the configured Tushare Pro data API URL without a trailing slash."""
    api_url = (os.getenv("TUSHARE_API_URL") or DEFAULT_TUSHARE_API_URL).strip().rstrip("/")
    if api_url.startswith("https://42.194.163.97:5000"):
        logger.warning(
            "TUSHARE_API_URL 使用 42.194.163.97:5000 代理时应为 http，已自动修正协议。"
        )
        return "http://" + api_url.removeprefix("https://")
    return api_url


def configure_tushare_api_endpoint(api: Optional[Any] = None) -> str:
    """
    Force the Tushare SDK to use the configured Pro data API endpoint.

    tushare 1.4.x does not expose an official URL parameter on pro_api(), so
    this patches the SDK's DataApi private URL attribute in one place.
    """
    api_url = get_tushare_api_url()

    try:
        from tushare.pro import client

        setattr(client.DataApi, "_DataApi__http_url", api_url)
    except Exception as exc:
        logger.warning("配置 Tushare SDK 默认端点失败: %s", exc)

    if api is not None:
        try:
            setattr(api, "_DataApi__http_url", api_url)
        except Exception as exc:
            logger.warning("配置 Tushare API 实例端点失败: %s", exc)

    return api_url
