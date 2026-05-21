#!/usr/bin/env python3
"""Migrate stock_daily_quotes from legacy tradingagents DB to app DB."""
from __future__ import annotations

import os

from pymongo import MongoClient, ReplaceOne


def main() -> None:
    uri = os.getenv("MONGODB_CONNECTION_STRING") or os.getenv("MONGO_URI")
    if not uri:
        host = os.getenv("MONGODB_HOST", "localhost")
        port = os.getenv("MONGODB_PORT", "27017")
        username = os.getenv("MONGODB_USERNAME")
        password = os.getenv("MONGODB_PASSWORD")
        auth_source = os.getenv("MONGODB_AUTH_SOURCE", "admin")
        if username and password:
            uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource={auth_source}"
        else:
            uri = f"mongodb://{host}:{port}/"

    source_db_name = os.getenv("LEGACY_STOCK_QUOTES_DB", "tradingagents")
    target_db_name = os.getenv("MONGODB_DATABASE", "") or os.getenv("MONGODB_DATABASE_NAME", "") or "tradingagentscn"

    client = MongoClient(uri)
    source = client[source_db_name].stock_daily_quotes
    target = client[target_db_name].stock_daily_quotes

    total = source.count_documents({})
    copied = 0
    operations = []
    batch_size = int(os.getenv("MIGRATE_STOCK_QUOTES_BATCH_SIZE", "1000"))

    cursor = source.find({})
    for doc in cursor:
        doc.pop("_id", None)
        filter_doc = {
            "symbol": doc.get("symbol"),
            "trade_date": doc.get("trade_date"),
            "data_source": doc.get("data_source"),
            "period": doc.get("period", "daily"),
        }
        if not all(filter_doc.values()):
            continue
        operations.append(ReplaceOne(filter_doc, doc, upsert=True))
        if len(operations) >= batch_size:
            result = target.bulk_write(operations, ordered=False)
            copied += result.upserted_count + result.modified_count
            operations = []

    if operations:
        result = target.bulk_write(operations, ordered=False)
        copied += result.upserted_count + result.modified_count

    target.create_index(
        [("symbol", 1), ("trade_date", 1), ("data_source", 1), ("period", 1)],
        unique=True,
        name="symbol_date_source_period_unique",
        background=True,
    )
    target.create_index([("symbol", 1), ("trade_date", -1)], name="symbol_date_index", background=True)
    print(f"migrated stock_daily_quotes from {source_db_name} to {target_db_name}: source_total={total}, copied_or_updated={copied}")


if __name__ == "__main__":
    main()
