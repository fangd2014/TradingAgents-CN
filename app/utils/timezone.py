from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from app.core.config import settings


DEFAULT_TIMEZONE = "Asia/Shanghai"


def _valid_timezone_name(name: str) -> str:
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return DEFAULT_TIMEZONE


def get_tz_name() -> str:
    """Return configured timezone name, preferring DB system_settings.app_timezone if cached.
    Fallback order: DB (cached) > env (settings.TIMEZONE) > Asia/Shanghai.
    This function is sync and must not await; it relies on provider cache populated elsewhere.
    """
    try:
        # Lazy import to avoid circular imports
        from app.services.config_provider import provider as cfgprov  # type: ignore
        cached = getattr(cfgprov, "_cache_settings", None)
        if isinstance(cached, dict):
            tz = cached.get("app_timezone") or cached.get("APP_TIMEZONE")
            if isinstance(tz, str) and tz.strip():
                return tz.strip()
    except Exception:
        pass
    for env_key in ("APP_TIMEZONE", "TIMEZONE", "TA_TIMEZONE", "TZ"):
        env_value = os.getenv(env_key)
        if isinstance(env_value, str) and env_value.strip():
            return _valid_timezone_name(env_value.strip())

    configured = settings.TIMEZONE or DEFAULT_TIMEZONE
    return _valid_timezone_name(configured)


def get_timezone_name() -> str:
    """Compatibility alias used by backend callers."""
    return get_tz_name()


def get_tz() -> ZoneInfo:
    return ZoneInfo(get_tz_name())


def now_tz() -> datetime:
    """Current time in configured timezone (tz-aware)."""
    return datetime.now(get_tz())


def to_config_tz(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive as UTC by default, then convert to configured tz
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(get_tz())
    return dt.astimezone(get_tz())


def ensure_timezone(dt: Optional[datetime]) -> Optional[datetime]:
    """
    确保 datetime 对象包含时区信息
    如果没有时区信息，假定为配置的时区（默认 Asia/Shanghai）
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # 如果没有时区信息，假定为配置的时区
        return dt.replace(tzinfo=get_tz())
    return dt


def apply_process_timezone(timezone_name: Optional[str] = None) -> str:
    """Apply configured timezone to the process for naive datetime.now()."""
    tz_name = _valid_timezone_name((timezone_name or get_tz_name()).strip())
    os.environ["TZ"] = tz_name
    if hasattr(time, "tzset"):
        time.tzset()
    return tz_name
