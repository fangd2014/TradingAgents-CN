"""
自选股服务
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.user import FavoriteStock


LATEST_CHINA_BASIC_SOURCES = [
    "mootdx_tencent",
    "external_quotes",
    "tencent_finance",
    "mootdx",
    "mootdx_finance",
]

LATEST_QUOTE_FIELDS = [
    "pe_ttm",
    "pb",
    "total_mv",
    "float_mv",
    "turnover_rate",
    "limit_up",
    "limit_down",
]


def _is_china_etf_code(stock_code: str) -> bool:
    try:
        from tradingagents.utils.stock_utils import StockUtils
        return StockUtils.is_china_etf(stock_code)
    except Exception:
        code = str(stock_code or "").strip()
        return len(code) == 6 and (
            code.startswith("159")
            or code.startswith("51")
            or code.startswith("56")
            or code.startswith("58")
        )


def _normalize_market(stock_code: str, market: str = "A股") -> str:
    if _is_china_etf_code(stock_code):
        return "A股ETF"
    return market or "A股"


class FavoritesService:
    """自选股服务类"""
    
    def __init__(self):
        self.db = None
    
    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _is_valid_object_id(self, user_id: str) -> bool:
        """
        检查是否是有效的ObjectId格式
        注意：这里只检查格式，不代表数据库中实际存储的是ObjectId类型
        为了兼容性，我们统一使用 user_favorites 集合存储自选股
        """
        # 强制返回 False，统一使用 user_favorites 集合
        return False

    def _format_favorite(self, favorite: Dict[str, Any]) -> Dict[str, Any]:
        """格式化收藏条目（仅基础信息，不包含实时行情）。
        行情将在 get_user_favorites 中批量富集。
        """
        added_at = favorite.get("added_at")
        if isinstance(added_at, datetime):
            added_at = added_at.isoformat()
        return {
            "stock_code": favorite.get("stock_code"),
            "stock_name": favorite.get("stock_name"),
            "market": _normalize_market(favorite.get("stock_code"), favorite.get("market", "A股")),
            "added_at": added_at,
            "tags": favorite.get("tags", []),
            "notes": favorite.get("notes", ""),
            "alert_price_high": favorite.get("alert_price_high"),
            "alert_price_low": favorite.get("alert_price_low"),
            "pe_ttm": favorite.get("pe_ttm"),
            "pb": favorite.get("pb"),
            "total_mv": favorite.get("total_mv"),
            "float_mv": favorite.get("float_mv"),
            "turnover_rate": favorite.get("turnover_rate"),
            "limit_up": favorite.get("limit_up"),
            "limit_down": favorite.get("limit_down"),
            "quote_source": favorite.get("quote_source"),
            "enriched_at": favorite.get("enriched_at"),
            "data_sources": favorite.get("data_sources", {}),
            # 行情占位，稍后填充
            "current_price": None,
            "change_percent": None,
            "volume": None,
        }

    async def get_user_favorites(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户自选股列表，并批量拉取实时行情进行富集（兼容字符串ID与ObjectId）。"""
        db = await self._get_db()

        favorites: List[Dict[str, Any]] = []
        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if user is None:
                user = await db.users.find_one({"_id": user_id})
            favorites = (user or {}).get("favorite_stocks", [])
        else:
            doc = await db.user_favorites.find_one({"user_id": user_id})
            favorites = (doc or {}).get("favorites", [])

        # 先格式化基础字段
        items = [self._format_favorite(fav) for fav in favorites]

        # 批量获取股票基础信息（板块等）
        codes = [it.get("stock_code") for it in items if it.get("stock_code")]
        if codes:
            try:
                # 优先读取最新七模块写入的基础资料，旧来源仅作为兼容兜底。
                basic_info_coll = db["stock_basic_info"]
                cursor = basic_info_coll.find(
                    {
                        "code": {"$in": codes},
                        "$or": [
                            {"source": {"$in": LATEST_CHINA_BASIC_SOURCES}},
                            {"data_source": {"$in": LATEST_CHINA_BASIC_SOURCES}},
                        ],
                    },
                    {"code": 1, "sse": 1, "market": 1, "source": 1, "data_source": 1, "_id": 0}
                )
                basic_docs = await cursor.to_list(length=None)
                basic_map = {}
                source_rank = {name: idx for idx, name in enumerate(LATEST_CHINA_BASIC_SOURCES)}
                for doc in basic_docs or []:
                    code_key = str(doc.get("code")).zfill(6)
                    source = doc.get("source") or doc.get("data_source") or ""
                    rank = source_rank.get(source, len(source_rank))
                    current = basic_map.get(code_key)
                    current_rank = current[0] if current else len(source_rank) + 1
                    if rank < current_rank:
                        basic_map[code_key] = (rank, doc)

                for it in items:
                    code = it.get("stock_code")
                    basic_entry = basic_map.get(code)
                    basic = basic_entry[1] if basic_entry else None
                    if basic:
                        # market 字段表示板块（主板、创业板、科创板等）
                        it["board"] = basic.get("market", "-")
                        # sse 字段表示交易所（上海证券交易所、深圳证券交易所等）
                        it["exchange"] = basic.get("sse", "-")
                    elif _is_china_etf_code(code):
                        it["board"] = "ETF"
                        it["exchange"] = "上海证券交易所" if str(code).startswith(("51", "56", "58")) else "深圳证券交易所"
                    else:
                        it["board"] = "-"
                        it["exchange"] = "-"
            except Exception as e:
                # 查询失败时设置默认值
                for it in items:
                    it["board"] = "-"
                    it["exchange"] = "-"

        # 批量获取行情：列表接口只读入库缓存，避免同步拉取 AKShare 全市场快照导致页面阻塞。
        # 实时刷新由 /api/favorites/sync-realtime 显式触发。
        if codes:
            try:
                coll = db["market_quotes"]
                cursor = coll.find(
                    {"code": {"$in": codes}},
                    {
                        "code": 1,
                        "name": 1,
                        "close": 1,
                        "pct_chg": 1,
                        "amount": 1,
                        "volume": 1,
                        "source": 1,
                        "data_source": 1,
                        "pe_ttm": 1,
                        "pb": 1,
                        "total_mv": 1,
                        "float_mv": 1,
                        "turnover_rate": 1,
                        "limit_up": 1,
                        "limit_down": 1,
                        "_id": 0,
                    }
                )
                docs = await cursor.to_list(length=None)
                quotes_map = {str(d.get("code")).zfill(6): d for d in (docs or [])}
                for it in items:
                    code = it.get("stock_code")
                    q = quotes_map.get(code)
                    if q:
                        if q.get("name") and not it.get("stock_name"):
                            it["stock_name"] = q.get("name")
                        it["current_price"] = q.get("close")
                        it["change_percent"] = q.get("pct_chg")
                        it["volume"] = q.get("volume")
                        it["quote_source"] = q.get("source") or q.get("data_source") or it.get("quote_source")
                        for field in LATEST_QUOTE_FIELDS:
                            if q.get(field) is not None:
                                it[field] = q.get(field)
            except Exception:
                # 查询失败时保持占位 None，避免影响基础功能
                pass

        return items

    async def enrich_user_favorites_latest_sources(self, user_id: str) -> Dict[str, Any]:
        """使用 Tencent/mootdx 最新行情通道补齐自选股信息并写入缓存。"""
        db = await self._get_db()
        doc = await db.user_favorites.find_one({"user_id": user_id})
        favorites = list((doc or {}).get("favorites", []))
        codes = sorted({str(fav.get("stock_code") or "").zfill(6) for fav in favorites if fav.get("stock_code")})

        if not codes:
            return {
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "symbols": [],
                "message": "没有自选股需要补全",
            }

        from app.services.china_external_data_service import ChinaQuoteService

        quotes = ChinaQuoteService().get_quotes(codes)
        now = datetime.utcnow()
        success_codes = set()

        for code, quote in quotes.items():
            if not quote:
                continue
            success_codes.add(code)
            quote_doc = {
                "code": code,
                "symbol": code,
                "name": quote.get("name"),
                "close": quote.get("close"),
                "price": quote.get("close"),
                "current_price": quote.get("close"),
                "pct_chg": quote.get("pct_chg"),
                "change_percent": quote.get("pct_chg"),
                "amount": quote.get("amount"),
                "volume": quote.get("volume"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "pre_close": quote.get("pre_close"),
                "source": quote.get("source") or "external_quotes",
                "data_source": quote.get("source") or "external_quotes",
                "updated_at": now,
            }
            for field in LATEST_QUOTE_FIELDS:
                if quote.get(field) is not None:
                    quote_doc[field] = quote.get(field)

            await db["market_quotes"].update_one(
                {"code": code},
                {"$set": quote_doc},
                upsert=True,
            )
            await db["stock_basic_info"].update_one(
                {"code": code, "source": "mootdx_tencent"},
                {
                    "$set": {
                        "code": code,
                        "symbol": code,
                        "name": quote.get("name"),
                        "source": "mootdx_tencent",
                        "data_source": "mootdx_tencent",
                        "sse": "上海证券交易所" if code.startswith(("60", "68", "90")) else "深圳证券交易所",
                        "market": "ETF" if _is_china_etf_code(code) else "-",
                        "updated_at": now,
                    }
                },
                upsert=True,
            )

        enriched_favorites = []
        for fav in favorites:
            code = str(fav.get("stock_code") or "").zfill(6)
            quote = quotes.get(code)
            updated = dict(fav)
            if quote:
                if quote.get("name"):
                    updated["stock_name"] = updated.get("stock_name") or quote.get("name")
                updated["quote_source"] = quote.get("source") or "external_quotes"
                updated["data_sources"] = {
                    **dict(updated.get("data_sources") or {}),
                    "quote": quote.get("source") or "external_quotes",
                    "metrics": "tencent_finance",
                    "basic": "mootdx_tencent",
                }
                updated["enriched_at"] = now.isoformat()
                for field in LATEST_QUOTE_FIELDS:
                    if quote.get(field) is not None:
                        updated[field] = quote.get(field)
            enriched_favorites.append(updated)

        await db.user_favorites.update_one(
            {"user_id": user_id},
            {"$set": {"favorites": enriched_favorites, "updated_at": now}},
            upsert=False,
        )

        failed_codes = [code for code in codes if code not in success_codes]
        return {
            "total": len(codes),
            "success_count": len(success_codes),
            "failed_count": len(failed_codes),
            "symbols": codes,
            "failed_symbols": failed_codes,
            "data_source": "external_quotes",
            "message": f"补全完成: 成功 {len(success_codes)} 只，失败 {len(failed_codes)} 只",
        }

    async def add_favorite(
        self,
        user_id: str,
        stock_code: str,
        stock_name: str,
        market: str = "A股",
        tags: List[str] = None,
        notes: str = "",
        alert_price_high: Optional[float] = None,
        alert_price_low: Optional[float] = None
    ) -> bool:
        """添加股票到自选股（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [add_favorite] 开始添加自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()
            logger.info(f"🔧 [add_favorite] 数据库连接获取成功")
            stock_code = str(stock_code).strip()
            market = _normalize_market(stock_code, market)

            favorite_stock = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "market": market,
                "added_at": datetime.utcnow(),
                "tags": tags or [],
                "notes": notes,
                "alert_price_high": alert_price_high,
                "alert_price_low": alert_price_low
            }

            logger.info(f"🔧 [add_favorite] 自选股数据构建完成: {favorite_stock}")

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [add_favorite] 用户ID类型检查: is_valid_object_id={is_oid}")

            if is_oid:
                logger.info(f"🔧 [add_favorite] 使用 ObjectId 方式添加到 users 集合")

                # 先尝试使用 ObjectId 查询
                result = await db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$push": {"favorite_stocks": favorite_stock},
                        "$setOnInsert": {"favorite_stocks": []}
                    }
                )
                logger.info(f"🔧 [add_favorite] ObjectId查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if result.matched_count == 0:
                    logger.info(f"🔧 [add_favorite] ObjectId查询失败，尝试使用字符串ID查询")
                    result = await db.users.update_one(
                        {"_id": user_id},
                        {
                            "$push": {"favorite_stocks": favorite_stock}
                        }
                    )
                    logger.info(f"🔧 [add_favorite] 字符串ID查询结果: matched_count={result.matched_count}, modified_count={result.modified_count}")

                success = result.matched_count > 0
                logger.info(f"🔧 [add_favorite] 返回结果: {success}")
                return success
            else:
                logger.info(f"🔧 [add_favorite] 使用字符串ID方式添加到 user_favorites 集合")
                result = await db.user_favorites.update_one(
                    {"user_id": user_id},
                    {
                        "$setOnInsert": {"user_id": user_id, "created_at": datetime.utcnow()},
                        "$push": {"favorites": favorite_stock},
                        "$set": {"updated_at": datetime.utcnow()}
                    },
                    upsert=True
                )
                logger.info(f"🔧 [add_favorite] 更新结果: matched_count={result.matched_count}, modified_count={result.modified_count}, upserted_id={result.upserted_id}")
                logger.info(f"🔧 [add_favorite] 返回结果: True")
                return True
        except Exception as e:
            logger.error(f"❌ [add_favorite] 添加自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def remove_favorite(self, user_id: str, stock_code: str) -> bool:
        """从自选股中移除股票（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        if self._is_valid_object_id(user_id):
            # 先尝试使用 ObjectId 查询
            result = await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
            )
            # 如果 ObjectId 查询失败，尝试使用字符串查询
            if result.matched_count == 0:
                result = await db.users.update_one(
                    {"_id": user_id},
                    {"$pull": {"favorite_stocks": {"stock_code": stock_code}}}
                )
            return result.modified_count > 0
        else:
            result = await db.user_favorites.update_one(
                {"user_id": user_id},
                {
                    "$pull": {"favorites": {"stock_code": stock_code}},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            return result.modified_count > 0

    async def update_favorite(
        self,
        user_id: str,
        stock_code: str,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        alert_price_high: Optional[float] = None,
        alert_price_low: Optional[float] = None
    ) -> bool:
        """更新自选股信息（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        # 统一构建更新字段（根据不同集合的字段路径设置前缀）
        is_oid = self._is_valid_object_id(user_id)
        prefix = "favorite_stocks.$." if is_oid else "favorites.$."
        update_fields: Dict[str, Any] = {}
        if tags is not None:
            update_fields[prefix + "tags"] = tags
        if notes is not None:
            update_fields[prefix + "notes"] = notes
        if alert_price_high is not None:
            update_fields[prefix + "alert_price_high"] = alert_price_high
        if alert_price_low is not None:
            update_fields[prefix + "alert_price_low"] = alert_price_low

        if not update_fields:
            return True

        if is_oid:
            result = await db.users.update_one(
                {
                    "_id": ObjectId(user_id),
                    "favorite_stocks.stock_code": stock_code
                },
                {"$set": update_fields}
            )
            return result.modified_count > 0
        else:
            result = await db.user_favorites.update_one(
                {
                    "user_id": user_id,
                    "favorites.stock_code": stock_code
                },
                {
                    "$set": {
                        **update_fields,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0

    async def is_favorite(self, user_id: str, stock_code: str) -> bool:
        """检查股票是否在自选股中（兼容字符串ID与ObjectId）"""
        import logging
        logger = logging.getLogger("webapi")

        try:
            logger.info(f"🔧 [is_favorite] 检查自选股: user_id={user_id}, stock_code={stock_code}")

            db = await self._get_db()

            is_oid = self._is_valid_object_id(user_id)
            logger.info(f"🔧 [is_favorite] 用户ID类型: is_valid_object_id={is_oid}")

            if is_oid:
                # 先尝试使用 ObjectId 查询
                user = await db.users.find_one(
                    {
                        "_id": ObjectId(user_id),
                        "favorite_stocks.stock_code": stock_code
                    }
                )

                # 如果 ObjectId 查询失败，尝试使用字符串查询
                if user is None:
                    logger.info(f"🔧 [is_favorite] ObjectId查询未找到，尝试使用字符串ID查询")
                    user = await db.users.find_one(
                        {
                            "_id": user_id,
                            "favorite_stocks.stock_code": stock_code
                        }
                    )

                result = user is not None
                logger.info(f"🔧 [is_favorite] 查询结果: {result}")
                return result
            else:
                doc = await db.user_favorites.find_one(
                    {
                        "user_id": user_id,
                        "favorites.stock_code": stock_code
                    }
                )
                result = doc is not None
                logger.info(f"🔧 [is_favorite] 字符串ID查询结果: {result}")
                return result
        except Exception as e:
            logger.error(f"❌ [is_favorite] 检查自选股异常: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    async def get_user_tags(self, user_id: str) -> List[str]:
        """获取用户使用的所有标签（兼容字符串ID与ObjectId）"""
        db = await self._get_db()

        if self._is_valid_object_id(user_id):
            pipeline = [
                {"$match": {"_id": ObjectId(user_id)}},
                {"$unwind": "$favorite_stocks"},
                {"$unwind": "$favorite_stocks.tags"},
                {"$group": {"_id": "$favorite_stocks.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db.users.aggregate(pipeline).to_list(None)
        else:
            pipeline = [
                {"$match": {"user_id": user_id}},
                {"$unwind": "$favorites"},
                {"$unwind": "$favorites.tags"},
                {"$group": {"_id": "$favorites.tags"}},
                {"$sort": {"_id": 1}}
            ]
            result = await db.user_favorites.aggregate(pipeline).to_list(None)

        return [item["_id"] for item in result if item.get("_id")]

    def _get_mock_price(self, stock_code: str) -> float:
        """获取模拟股价"""
        # 基于股票代码生成模拟价格
        base_price = hash(stock_code) % 100 + 10
        return round(base_price + (hash(stock_code) % 1000) / 100, 2)
    
    def _get_mock_change(self, stock_code: str) -> float:
        """获取模拟涨跌幅"""
        # 基于股票代码生成模拟涨跌幅
        change = (hash(stock_code) % 2000 - 1000) / 100
        return round(change, 2)
    
    def _get_mock_volume(self, stock_code: str) -> int:
        """获取模拟成交量"""
        # 基于股票代码生成模拟成交量
        return (hash(stock_code) % 10000 + 1000) * 100


# 创建全局实例
favorites_service = FavoritesService()
