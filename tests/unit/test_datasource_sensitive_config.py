from app.utils.datasource_sensitive_config import (
    CANONICAL_TUSHARE_WEB_COOKIE_KEY,
    bridge_sensitive_config_params_to_env,
    merge_sensitive_config_params_for_update,
    normalize_sensitive_config_params,
    sanitize_sensitive_config_params,
)


def test_normalize_tushare_web_cookie_to_canonical_key():
    params = normalize_sensitive_config_params(
        "tushare",
        {"tushare_web_cookie": "sessionid=abc; token=def"},
    )

    assert params == {CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessionid=abc; token=def"}


def test_sanitize_masks_tushare_web_cookie():
    params = sanitize_sensitive_config_params(
        "tushare",
        {CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessionid=abcdef1234567890; token=abcdef"},
    )

    assert params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] == "sessio...abcdef"


def test_sanitize_shows_masked_env_cookie_when_db_missing():
    params = sanitize_sensitive_config_params(
        "tushare",
        {},
        env={CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessionid=abcdef1234567890; token=abcdef"},
    )

    assert params[CANONICAL_TUSHARE_WEB_COOKIE_KEY] == "sessio...abcdef"


def test_merge_preserves_existing_cookie_for_empty_or_masked_value():
    existing = {CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessionid=abcdef1234567890; token=abcdef"}

    empty_merged = merge_sensitive_config_params_for_update(
        "tushare",
        {CANONICAL_TUSHARE_WEB_COOKIE_KEY: ""},
        existing,
    )
    masked_merged = merge_sensitive_config_params_for_update(
        "tushare",
        {CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessio...abcdef"},
        existing,
    )

    assert empty_merged[CANONICAL_TUSHARE_WEB_COOKIE_KEY] == existing[CANONICAL_TUSHARE_WEB_COOKIE_KEY]
    assert masked_merged[CANONICAL_TUSHARE_WEB_COOKIE_KEY] == existing[CANONICAL_TUSHARE_WEB_COOKIE_KEY]


def test_bridge_sensitive_config_params_to_env_sets_cookie(monkeypatch):
    monkeypatch.delenv(CANONICAL_TUSHARE_WEB_COOKIE_KEY, raising=False)

    count = bridge_sensitive_config_params_to_env(
        "tushare",
        {CANONICAL_TUSHARE_WEB_COOKIE_KEY: "sessionid=abc; token=def"},
    )

    assert count == 1
    import os

    assert os.environ[CANONICAL_TUSHARE_WEB_COOKIE_KEY] == "sessionid=abc; token=def"
