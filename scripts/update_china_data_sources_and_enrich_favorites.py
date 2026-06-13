"""Update China data-source config and enrich favorite stocks.

This maintenance script is idempotent:
- rewrites the active system data-source config to the latest seven-module set
- refreshes datasource_groupings for A shares
- enriches every user_favorites document through Tencent/mootdx external quotes
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.core import database as database_module
from app.models.config import build_latest_china_data_source_configs
from app.services.favorites_service import FavoritesService


async def _get_db():
    if database_module.mongo_db is None:
        await database_module.db_manager.init_mongodb()
        database_module.mongo_client = database_module.db_manager.mongo_client
        database_module.mongo_db = database_module.db_manager.mongo_db
    return database_module.mongo_db


def _dump_config(config: Any) -> Dict[str, Any]:
    if hasattr(config, "model_dump"):
        return config.model_dump(mode="json")
    return dict(config)


async def update_system_data_sources() -> Dict[str, Any]:
    db = await _get_db()
    configs = build_latest_china_data_source_configs(settings.IWENCAI_COOKIE)
    config_docs = [_dump_config(config) for config in configs]
    now = datetime.now(timezone.utc)

    active_config = await db.system_configs.find_one({"is_active": True}, sort=[("version", -1)])
    if active_config:
        await db.system_configs.update_one(
            {"_id": active_config["_id"]},
            {
                "$set": {
                    "data_source_configs": config_docs,
                    "default_data_source": "External Quotes",
                    "updated_at": now,
                    "version": int(active_config.get("version", 0)) + 1,
                }
            },
        )
    else:
        await db.system_configs.insert_one(
            {
                "config_name": "默认配置",
                "config_type": "system",
                "llm_configs": [],
                "default_llm": None,
                "data_source_configs": config_docs,
                "default_data_source": "External Quotes",
                "database_configs": [],
                "system_settings": {},
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "is_active": True,
            }
        )

    for config in configs:
        await db.datasource_groupings.update_one(
            {
                "data_source_name": config.name,
                "market_category_id": "a_shares",
            },
            {
                "$set": {
                    "data_source_name": config.name,
                    "market_category_id": "a_shares",
                    "priority": config.priority,
                    "enabled": config.enabled,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    return {
        "data_source_count": len(config_docs),
        "default_data_source": "External Quotes",
        "iwencai_enabled": bool(settings.IWENCAI_COOKIE),
    }


async def enrich_all_favorites() -> Dict[str, Any]:
    db = await _get_db()
    service = FavoritesService()
    service.db = db

    docs = await db.user_favorites.find({}, {"user_id": 1}).to_list(length=None)
    results: List[Dict[str, Any]] = []
    for doc in docs:
        user_id = str(doc.get("user_id") or "")
        if not user_id:
            continue
        result = await service.enrich_user_favorites_latest_sources(user_id)
        results.append({"user_id": user_id, **result})

    return {
        "user_count": len(results),
        "favorite_total": sum(item.get("total", 0) for item in results),
        "success_total": sum(item.get("success_count", 0) for item in results),
        "failed_total": sum(item.get("failed_count", 0) for item in results),
        "users": results,
    }


async def main() -> None:
    config_result = await update_system_data_sources()
    favorites_result = await enrich_all_favorites()
    print(
        {
            "config": config_result,
            "favorites": {
                "user_count": favorites_result["user_count"],
                "favorite_total": favorites_result["favorite_total"],
                "success_total": favorites_result["success_total"],
                "failed_total": favorites_result["failed_total"],
            },
        }
    )


if __name__ == "__main__":
    asyncio.run(main())
