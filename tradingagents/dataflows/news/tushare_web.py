#!/usr/bin/env python3
"""
Tushare news web crawler fallback.

The official Tushare Pro news API is still the preferred path. This module is a
best-effort fallback for https://tushare.pro/news when the web page exposes
parseable news content, optionally with a TUSHARE_WEB_COOKIE login session.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


TUSHARE_NEWS_URL = "https://tushare.pro/news"


class TushareWebNewsError(RuntimeError):
    """Raised when the Tushare news page cannot be parsed into news items."""


def get_tushare_web_news(
    symbol: Optional[str] = None,
    limit: int = 10,
    hours_back: int = 24,
    url: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """Fetch news from the Tushare news web page as a fallback source."""
    requester = session or requests.Session()
    headers = _build_headers()
    response = requester.get(_resolve_news_url(url), headers=headers, timeout=12)
    response.raise_for_status()

    html = response.text or ""
    items = parse_tushare_news_html(html, symbol=symbol, limit=limit)
    if items:
        return items[:limit]

    if _looks_like_vue_shell(html):
        raise TushareWebNewsError(
            "tushare.pro/news 返回的是前端应用壳，未包含可解析新闻；"
            "如需抓取登录后内容，请配置 TUSHARE_WEB_COOKIE"
        )

    raise TushareWebNewsError("tushare.pro/news 页面未解析到新闻条目")


def _resolve_news_url(url: Optional[str] = None) -> str:
    """
    Return the official Tushare news page for the web crawler.

    TUSHARE_API_URL / datasource endpoint may point at a Pro API proxy, but the
    news crawler is page-oriented and must never reuse that API endpoint.
    """
    return TUSHARE_NEWS_URL


def parse_tushare_news_html(
    html: str,
    symbol: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Parse news items from static HTML or embedded JSON blocks."""
    items = []
    items.extend(_parse_embedded_json_news(html))
    items.extend(_parse_dom_news(html))

    unique_items = _deduplicate_items(items)
    if symbol:
        filtered_items = [item for item in unique_items if _matches_symbol(item, symbol)]
        if filtered_items:
            unique_items = filtered_items

    return unique_items[:limit]


def _build_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://tushare.pro/news",
    }
    cookie = os.getenv("TUSHARE_WEB_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _parse_embedded_json_news(html: str) -> List[Dict[str, Any]]:
    items = []
    for script_body in re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        script_body = script_body.strip()
        if not script_body:
            continue
        for json_text in _extract_json_candidates(script_body):
            try:
                payload = json.loads(json_text)
            except Exception:
                continue
            items.extend(_walk_json_for_news(payload))
    return items


def _extract_json_candidates(text: str) -> List[str]:
    candidates = []
    if text.startswith("{") or text.startswith("["):
        candidates.append(text)

    for pattern in (
        r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;?\s*$",
        r"window\.__NUXT__\s*=\s*({.*?})\s*;?\s*$",
        r"window\.__DATA__\s*=\s*({.*?})\s*;?\s*$",
    ):
        match = re.search(pattern, text, flags=re.S)
        if match:
            candidates.append(match.group(1))

    return candidates


def _walk_json_for_news(payload: Any) -> List[Dict[str, Any]]:
    items = []
    if isinstance(payload, list):
        for value in payload:
            items.extend(_walk_json_for_news(value))
        return items

    if not isinstance(payload, dict):
        return items

    normalized = _normalize_json_news_item(payload)
    if normalized:
        items.append(normalized)

    for value in payload.values():
        if isinstance(value, (dict, list)):
            items.extend(_walk_json_for_news(value))

    return items


def _normalize_json_news_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = _first_non_empty(raw, ("title", "news_title", "name", "subject"))
    content = _first_non_empty(raw, ("content", "summary", "brief", "description", "desc"))
    if not title:
        return None

    return {
        "title": str(title),
        "content": str(content or ""),
        "summary": str(content or "")[:200],
        "url": str(_first_non_empty(raw, ("url", "link", "href")) or ""),
        "source": "Tushare网页",
        "author": str(_first_non_empty(raw, ("author", "writer")) or ""),
        "publish_time": _parse_publish_time(
            _first_non_empty(raw, ("datetime", "time", "date", "publish_time", "created_at"))
        ),
        "category": "general",
        "sentiment": "neutral",
        "importance": "low",
        "keywords": [],
        "data_source": "tushare_web",
        "original_source": "tushare_web",
    }


def _parse_dom_news(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    selectors = [
        "article",
        ".news-item",
        ".news-list li",
        ".el-card",
        "li",
    ]
    for selector in selectors:
        candidates.extend(soup.select(selector))

    items = []
    for node in candidates:
        title_node = node.select_one("h1, h2, h3, h4, .title, a")
        title = _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        if len(title) < 6:
            continue

        content = _clean_text(node.get_text(" ", strip=True))
        href_node = node.select_one("a[href]")
        href = href_node.get("href", "") if href_node else ""
        if href.startswith("/"):
            href = f"https://tushare.pro{href}"

        items.append(
            {
                "title": title,
                "content": content,
                "summary": content[:200],
                "url": href,
                "source": "Tushare网页",
                "author": "",
                "publish_time": datetime.utcnow(),
                "category": "general",
                "sentiment": "neutral",
                "importance": "low",
                "keywords": [],
                "data_source": "tushare_web",
                "original_source": "tushare_web",
            }
        )

    return items


def _deduplicate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique_items = []
    for item in items:
        key = (item.get("title", ""), item.get("url", ""))
        if not item.get("title") or key in seen:
            continue
        seen.add(key)
        unique_items.append(item)
    return unique_items


def _matches_symbol(item: Dict[str, Any], symbol: str) -> bool:
    clean_symbol = re.sub(r"\D", "", str(symbol))
    text = f"{item.get('title', '')} {item.get('content', '')}"
    return clean_symbol in text or str(symbol).upper() in text.upper()


def _first_non_empty(raw: Dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return None


def _parse_publish_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow()

    value_str = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value_str, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _looks_like_vue_shell(html: str) -> bool:
    lower_html = html.lower()
    return '<div id="app"></div>' in lower_html and "chunk-vendors" in lower_html
