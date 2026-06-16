
import logging
import time
import uuid
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.routers.auth_db import get_current_user

from app.services.screening_service import ScreeningService, ScreeningParams
from app.services.enhanced_screening_service import get_enhanced_screening_service
from app.services.preset_screening_service import get_preset_screening_service
from app.services.custom_strategy_screening_service import get_custom_strategy_screening_service
from app.models.screening import (
    ScreeningCondition, ScreeningRequest as NewScreeningRequest,
    ScreeningResponse as NewScreeningResponse, FieldInfo, BASIC_FIELDS_INFO
)

router = APIRouter(tags=["screening"])
logger = logging.getLogger("webapi")

# 筛选字段配置响应模型
class FieldConfigResponse(BaseModel):
    """筛选字段配置响应"""
    fields: Dict[str, FieldInfo]
    categories: Dict[str, List[str]]

# 传统的请求/响应模型（保持向后兼容）
class OrderByItem(BaseModel):
    field: str
    direction: str = Field("desc", pattern=r"^(?i)(asc|desc)$")

class ScreeningRequest(BaseModel):
    market: str = Field("CN", description="市场：CN")
    date: Optional[str] = Field(None, description="交易日YYYY-MM-DD，缺省为最新")
    adj: str = Field("qfq", description="复权口径：qfq/hfq/none（P0占位）")
    conditions: Dict[str, Any] = Field(default_factory=dict)
    order_by: Optional[List[OrderByItem]] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)

class ScreeningResponse(BaseModel):
    total: int
    items: List[dict]

class PresetTrendStartRequest(BaseModel):
    limit: int = Field(50, ge=1, le=200, description="返回数量")
    candidate_limit: int = Field(300, ge=20, le=1000, description="候选股票扫描数量")
    industries: Optional[List[str]] = Field(None, description="可选行业过滤")
    float_cap_limit: float = Field(500, gt=0, le=5000, description="流通市值上限，单位亿元")
    min_five_day_turnover: float = Field(5, ge=0, le=100, description="上一交易日 turnover_rate_f 下限，单位%")
    volume_breakout_multiplier: float = Field(4, ge=1, le=20, description="放量上涨倍数阈值")

class StrategyTaskRequest(BaseModel):
    strategy_id: str = Field(..., description="策略ID")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    title: Optional[str] = Field(None, description="任务标题")
    strategy_text: Optional[str] = Field(None, description="自定义策略文本")

# 服务实例
svc = ScreeningService()
enhanced_svc = get_enhanced_screening_service()
preset_svc = get_preset_screening_service()
custom_strategy_svc = get_custom_strategy_screening_service()


def _number_field(
    key: str,
    label: str,
    default: float,
    min_value: float,
    max_value: float,
    step: float,
    unit: str = "",
    precision: Optional[int] = None,
) -> Dict[str, Any]:
    field = {
        "key": key,
        "label": label,
        "component": "number",
        "default": default,
        "min": min_value,
        "max": max_value,
        "step": step,
        "unit": unit,
    }
    if precision is not None:
        field["precision"] = precision
    return field


SCREENING_STRATEGIES: List[Dict[str, Any]] = [
    {
        "id": "trend_start",
        "name": "中高回落+缩量横盘",
        "description": "寻找高位回落后缩量横盘，并在近期开启放量上涨的A股机会。",
        "tags": ["冲高回落", "缩量横盘", "放量启动", "筹码控盘"],
        "fields": [
            {"key": "industries", "label": "行业范围", "component": "industry-select", "multiple": True, "default": []},
            _number_field("limit", "结果数量", 100, 1, 200, 10, "只"),
            _number_field("candidate_limit", "候选扫描", 500, 20, 1000, 20, "只"),
            _number_field("float_cap_limit", "流通市值上限", 500, 50, 5000, 50, "亿元"),
            _number_field("min_five_day_turnover", "上一交易日换手", 5, 0, 100, 1, "%"),
            _number_field("volume_breakout_multiplier", "放量倍数", 4, 1, 20, 0.5, "倍", 1),
        ],
    },
    {
        "id": "positive_rubbing_line",
        "name": "缩量正揉搓线",
        "description": "最近两日先倒T后T，实体都很小，两日合成十字线，最新成交量缩至此前5日均量的7成以内。",
        "tags": ["揉搓线", "先长上影", "后长下影", "缩量", "十字线"],
        "fields": [
            {"key": "industries", "label": "行业范围", "component": "industry-select", "multiple": True, "default": []},
            _number_field("limit", "结果数量", 100, 1, 200, 10, "只"),
            _number_field("candidate_limit", "候选扫描", 1000, 20, 5000, 100, "只"),
            _number_field("body_ratio", "实体占振幅上限", 15, 1, 40, 1, "%"),
            _number_field("long_shadow_ratio", "长影线占振幅下限", 50, 20, 90, 1, "%"),
            _number_field("short_shadow_ratio", "短影线占振幅上限", 25, 0, 50, 1, "%"),
            _number_field("combined_body_ratio", "合成实体占比上限", 15, 1, 40, 1, "%"),
            _number_field("volume_ratio", "缩量比例", 70, 10, 120, 5, "%"),
        ],
    },
    {
        "id": "low_valuation_quality",
        "name": "低估值高ROE",
        "description": "以估值、ROE和市值约束筛选基本面质量较好的标的。",
        "tags": ["低估值", "高ROE", "基本面"],
        "fields": [
            {"key": "industries", "label": "行业范围", "component": "industry-select", "multiple": True, "default": []},
            _number_field("limit", "结果数量", 100, 1, 500, 10, "只"),
            _number_field("max_pe", "PE上限", 25, 0, 200, 1, "倍"),
            _number_field("max_pb", "PB上限", 3, 0, 20, 0.1, "倍", 2),
            _number_field("min_roe", "ROE下限", 10, 0, 100, 1, "%"),
            _number_field("max_total_mv", "总市值上限", 2000, 50, 10000, 50, "亿元"),
        ],
    },
    {
        "id": "active_volume",
        "name": "放量活跃股",
        "description": "从成交额、换手率和涨跌幅中筛选短线活跃标的。",
        "tags": ["成交活跃", "换手率", "短线"],
        "fields": [
            {"key": "industries", "label": "行业范围", "component": "industry-select", "multiple": True, "default": []},
            _number_field("limit", "结果数量", 100, 1, 500, 10, "只"),
            _number_field("min_amount", "成交额下限", 5, 0, 200, 1, "亿元"),
            _number_field("min_turnover", "换手率下限", 3, 0, 100, 1, "%"),
            _number_field("min_pct_chg", "涨跌幅下限", -3, -20, 20, 0.5, "%", 1),
            _number_field("max_pct_chg", "涨跌幅上限", 9.8, -20, 20, 0.5, "%", 1),
        ],
    },
    {
        "id": "custom_strategy",
        "name": "自定义策略",
        "description": "输入自然语言或公式，由 DeepSeek 转换为受控 DSL 后解释执行。",
        "tags": ["自定义", "DeepSeek生成DSL", "受控执行"],
        "fields": [
            {"key": "industries", "label": "行业范围", "component": "industry-select", "multiple": True, "default": []},
            _number_field("limit", "结果数量", 100, 1, 200, 10, "只"),
            _number_field("candidate_limit", "候选扫描", 500, 20, 1000, 20, "只"),
        ],
    },
]


def _strategy_by_id(strategy_id: str) -> Optional[Dict[str, Any]]:
    return next((strategy for strategy in SCREENING_STRATEGIES if strategy["id"] == strategy_id), None)


def _condition(field: str, op: str, value: Any) -> Dict[str, Any]:
    return {"field": field, "op": op, "value": value}


def _sanitize_for_mongo_storage(value: Any) -> Any:
    """Recursively replace Mongo-reserved field names before saving task results."""
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.startswith("$"):
                key = f"operator_{key[1:]}"
            key = key.replace(".", "_")
            sanitized[key] = _sanitize_for_mongo_storage(raw_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_mongo_storage(item) for item in value]
    return value


def _manual_task_parameters(req: ScreeningRequest) -> Dict[str, Any]:
    return {
        "market": req.market,
        "date": req.date,
        "adj": req.adj,
        "conditions": req.conditions,
        "order_by": [item.model_dump() for item in (req.order_by or [])],
        "limit": req.limit,
        "offset": req.offset,
    }


async def _execute_legacy_screening(parameters: Dict[str, Any]) -> Dict[str, Any]:
    conditions = _convert_legacy_conditions_to_new_format(parameters.get("conditions", {}))
    result = await enhanced_svc.screen_stocks(
        conditions=conditions,
        market=parameters.get("market", "CN"),
        date=parameters.get("date"),
        adj=parameters.get("adj", "qfq"),
        limit=int(parameters.get("limit") or 100),
        offset=int(parameters.get("offset") or 0),
        order_by=parameters.get("order_by") or [],
        use_database_optimization=True,
    )
    return {
        "preset": "manual_indicators",
        "title": "指标选股",
        "description": ["按页面配置的指标条件筛选股票。"],
        "total": result.get("total", 0),
        "items": result.get("items", []),
        "took_ms": result.get("took_ms"),
        "trace": {
            "parameters": parameters,
            "optimization_used": result.get("optimization_used"),
            "source": result.get("source"),
        },
    }


async def _execute_strategy(strategy_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    if strategy_id == "manual_indicators":
        return await _execute_legacy_screening(parameters)

    if strategy_id == "trend_start":
        return await preset_svc.run_trend_start_preset(
            limit=int(parameters.get("limit") or 100),
            candidate_limit=int(parameters.get("candidate_limit") or 500),
            industries=parameters.get("industries") or None,
            float_cap_limit=float(parameters.get("float_cap_limit") or 500),
            min_five_day_turnover=float(parameters.get("min_five_day_turnover") or 5),
            volume_breakout_multiplier=float(parameters.get("volume_breakout_multiplier") or 4),
        )

    if strategy_id == "positive_rubbing_line":
        return await preset_svc.run_positive_rubbing_line_preset(
            limit=int(parameters.get("limit") or 100),
            candidate_limit=int(parameters.get("candidate_limit") or 1000),
            industries=parameters.get("industries") or None,
            body_ratio=float(parameters.get("body_ratio") or 15) / 100,
            long_shadow_ratio=float(parameters.get("long_shadow_ratio") or 50) / 100,
            short_shadow_ratio=float(parameters.get("short_shadow_ratio") or 25) / 100,
            combined_body_ratio=float(parameters.get("combined_body_ratio") or 15) / 100,
            volume_ratio=float(parameters.get("volume_ratio") or 70) / 100,
        )

    if strategy_id == "custom_strategy":
        return await custom_strategy_svc.run_custom_strategy(
            strategy_text=str(parameters.get("strategy_text") or ""),
            limit=int(parameters.get("limit") or 100),
            candidate_limit=int(parameters.get("candidate_limit") or 500),
            industries=parameters.get("industries") or None,
        )

    children: List[Dict[str, Any]] = []
    industries = parameters.get("industries") or []
    if industries:
        children.append(_condition("industry", "in", industries))

    if strategy_id == "low_valuation_quality":
        children.extend([
            _condition("pe", "between", [0, float(parameters.get("max_pe") or 25)]),
            _condition("pb", "between", [0, float(parameters.get("max_pb") or 3)]),
            _condition("roe", "gte", float(parameters.get("min_roe") or 10)),
            _condition("market_cap", "between", [0, float(parameters.get("max_total_mv") or 2000) * 10000]),
        ])
        order_by = [{"field": "roe", "direction": "desc"}]
    elif strategy_id == "active_volume":
        min_amount_yi = float(parameters.get("min_amount") or 5)
        children.extend([
            _condition("amount", "gte", min_amount_yi * 100000000),
            _condition("turnover_rate", "gte", float(parameters.get("min_turnover") or 3)),
            _condition("pct_chg", "between", [
                float(parameters.get("min_pct_chg") if parameters.get("min_pct_chg") is not None else -3),
                float(parameters.get("max_pct_chg") if parameters.get("max_pct_chg") is not None else 9.8),
            ]),
        ])
        order_by = [{"field": "amount", "direction": "desc"}]
    else:
        raise ValueError(f"未知选股策略: {strategy_id}")

    result = await _execute_legacy_screening({
        "market": "CN",
        "date": None,
        "adj": "qfq",
        "conditions": {"logic": "AND", "children": children},
        "order_by": order_by,
        "limit": int(parameters.get("limit") or 100),
        "offset": 0,
    })
    strategy = _strategy_by_id(strategy_id) or {"name": strategy_id, "description": []}
    result.update({
        "preset": strategy_id,
        "title": strategy["name"],
        "description": [strategy.get("description", "")],
    })
    result["trace"]["parameters"] = parameters
    return result


def _build_saved_screening_result(
    task_id: str,
    strategy_id: str,
    strategy_name: str,
    parameters: Dict[str, Any],
    raw_result: Dict[str, Any],
    execution_time: float,
) -> Dict[str, Any]:
    total = int(raw_result.get("total") or len(raw_result.get("items", [])))
    summary = f"选股完成，命中 {total} 只股票。"
    screening_payload = _sanitize_for_mongo_storage(
        {
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "parameters": parameters,
            "total": total,
            "items": raw_result.get("items", []),
            "trace": raw_result.get("trace"),
            "description": raw_result.get("description", []),
            "took_ms": raw_result.get("took_ms"),
        }
    )
    return {
        "type": "screening",
        "analysis_id": task_id,
        "stock_symbol": "SCREENING",
        "stock_code": "SCREENING",
        "analysis_date": datetime.utcnow().isoformat(),
        "summary": summary,
        "recommendation": f"策略：{strategy_name}。结果已保存，可在任务中心随时查看。",
        "confidence_score": 0,
        "risk_level": "中等",
        "key_points": [
            f"策略：{strategy_name}",
            f"命中数量：{total}",
            f"参数：{parameters}",
        ],
        "execution_time": execution_time,
        "tokens_used": 0,
        "analysts": ["screening"],
        "research_depth": "选股",
        "reports": {},
        "screening": screening_payload,
    }


async def _run_screening_task(task_id: str, strategy_id: str, strategy_name: str, parameters: Dict[str, Any]) -> None:
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    started = time.time()
    try:
        await db.analysis_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "running",
                "progress": 20,
                "message": "正在执行选股策略",
                "current_step": "screening",
                "started_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )

        raw_result = await _execute_strategy(strategy_id, parameters)
        execution_time = round(time.time() - started, 3)
        saved_result = _build_saved_screening_result(
            task_id=task_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            parameters=parameters,
            raw_result=raw_result,
            execution_time=execution_time,
        )
        await db.analysis_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "completed",
                "progress": 100,
                "message": f"选股完成，命中 {saved_result['screening']['total']} 只股票",
                "current_step": "completed",
                "result": saved_result,
                "execution_time": execution_time,
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )
    except Exception as exc:
        logger.error("[screening_task] 任务失败: task_id=%s error=%s", task_id, exc, exc_info=True)
        await db.analysis_tasks.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "failed",
                "progress": 100,
                "message": f"选股失败: {exc}",
                "error_message": str(exc),
                "current_step": "failed",
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }},
        )


@router.get("/fields", response_model=FieldConfigResponse)
async def get_screening_fields(user: dict = Depends(get_current_user)):
    """
    获取筛选字段配置
    返回所有可用的筛选字段及其配置信息
    """
    try:
        # 字段分类
        categories = {
            "basic": ["code", "name", "industry", "area", "market"],
            "market_value": ["total_mv", "circ_mv"],
            "financial": ["pe", "pb", "pe_ttm", "pb_mrq", "roe"],
            "trading": ["turnover_rate", "volume_ratio"],
            "price": ["close", "pct_chg", "amount"],
            "technical": ["ma20", "rsi14", "kdj_k", "kdj_d", "kdj_j", "dif", "dea", "macd_hist"]
        }

        return FieldConfigResponse(
            fields=BASIC_FIELDS_INFO,
            categories=categories
        )

    except Exception as e:
        logger.error(f"[get_screening_fields] 获取字段配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies", response_model=Dict[str, Any])
async def get_screening_strategies(user: dict = Depends(get_current_user)):
    """获取可用策略选股配置。"""
    return {
        "strategies": SCREENING_STRATEGIES,
        "default_strategy_id": "trend_start",
    }


@router.post("/tasks", response_model=Dict[str, Any])
async def create_strategy_screening_task(
    req: StrategyTaskRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """创建策略选股任务，结果保存到任务中心。"""
    strategy = _strategy_by_id(req.strategy_id)
    if not strategy:
        raise HTTPException(status_code=400, detail=f"未知选股策略: {req.strategy_id}")

    task_id = str(uuid.uuid4())
    now = datetime.utcnow()
    title = req.title or f"策略选股：{strategy['name']}"
    parameters = req.parameters or {}
    if req.strategy_id == "custom_strategy":
        parameters = dict(parameters)
        parameters["strategy_text"] = req.strategy_text or parameters.get("strategy_text") or ""
        if not parameters["strategy_text"].strip():
            raise HTTPException(status_code=400, detail="自定义策略文本不能为空")

    try:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        await db.analysis_tasks.insert_one({
            "task_id": task_id,
            "user_id": user["id"],
            "task_type": "screening",
            "screening_type": "strategy",
            "strategy_id": req.strategy_id,
            "strategy_name": strategy["name"],
            "title": title,
            "stock_code": "SCREENING",
            "stock_symbol": "SCREENING",
            "stock_name": strategy["name"],
            "status": "running",
            "progress": 1,
            "message": "选股任务已创建，准备执行",
            "current_step": "queued",
            "parameters": parameters,
            "created_at": now,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("[screening_task] 创建任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建选股任务失败: {exc}")

    background_tasks.add_task(_run_screening_task, task_id, req.strategy_id, strategy["name"], parameters)
    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": "pending",
            "task_type": "screening",
            "strategy_id": req.strategy_id,
            "strategy_name": strategy["name"],
        },
        "message": "选股任务已添加到任务中心",
    }


@router.post("/tasks/indicators", response_model=Dict[str, Any])
async def create_indicator_screening_task(
    req: ScreeningRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """创建指标选股任务，结果保存到任务中心。"""
    task_id = str(uuid.uuid4())
    now = datetime.utcnow()
    parameters = _manual_task_parameters(req)
    strategy_name = "指标选股"

    try:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        await db.analysis_tasks.insert_one({
            "task_id": task_id,
            "user_id": user["id"],
            "task_type": "screening",
            "screening_type": "indicators",
            "strategy_id": "manual_indicators",
            "strategy_name": strategy_name,
            "title": strategy_name,
            "stock_code": "SCREENING",
            "stock_symbol": "SCREENING",
            "stock_name": strategy_name,
            "status": "running",
            "progress": 1,
            "message": "指标选股任务已创建，准备执行",
            "current_step": "queued",
            "parameters": parameters,
            "created_at": now,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("[screening_task] 创建指标选股任务失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建指标选股任务失败: {exc}")

    background_tasks.add_task(_run_screening_task, task_id, "manual_indicators", strategy_name, parameters)
    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "status": "pending",
            "task_type": "screening",
            "strategy_id": "manual_indicators",
            "strategy_name": strategy_name,
        },
        "message": "指标选股任务已添加到任务中心",
    }


def _convert_legacy_conditions_to_new_format(legacy_conditions: Dict[str, Any]) -> List[ScreeningCondition]:
    """
    将传统格式的筛选条件转换为新格式

    传统格式示例:
    {
        "logic": "AND",
        "children": [
            {"field": "market_cap", "op": "between", "value": [5000000, 9007199254740991]}
        ]
    }

    新格式:
    [
        ScreeningCondition(field="total_mv", operator="between", value=[50, 90071992547])
    ]
    """
    conditions = []

    # 字段名映射（前端可能使用的旧字段名 -> 统一的后端字段名）
    field_mapping = {
        "market_cap": "total_mv",      # 市值（兼容旧字段名）
        "pe_ratio": "pe",              # 市盈率（兼容旧字段名）
        "pb_ratio": "pb",              # 市净率（兼容旧字段名）
        "turnover": "turnover_rate",   # 换手率（兼容旧字段名）
        "change_percent": "pct_chg",   # 涨跌幅（兼容旧字段名）
        "price": "close",              # 价格（兼容旧字段名）
    }

    # 操作符映射
    operator_mapping = {
        "between": "between",
        "gt": ">",
        "lt": "<",
        "gte": ">=",
        "lte": "<=",
        "eq": "==",
        "ne": "!=",
        "in": "in",
        "contains": "contains"
    }

    if isinstance(legacy_conditions, dict):
        children = legacy_conditions.get("children", [])

        for child in children:
            if isinstance(child, dict):
                field = child.get("field")
                op = child.get("op")
                value = child.get("value")

                if field and op and value is not None:
                    # 映射字段名
                    mapped_field = field_mapping.get(field, field)

                    # 映射操作符
                    mapped_op = operator_mapping.get(op, op)

                    # 处理市值单位转换（前端传入的是万元，数据库存储的是亿元）
                    if mapped_field == "total_mv" and isinstance(value, list):
                        # 将万元转换为亿元
                        converted_value = [v / 10000 for v in value if isinstance(v, (int, float))]
                        logger.info(f"[screening] 市值单位转换: {value} 万元 -> {converted_value} 亿元")
                        value = converted_value
                    elif mapped_field == "total_mv" and isinstance(value, (int, float)):
                        value = value / 10000
                        logger.info(f"[screening] 市值单位转换: {child.get('value')} 万元 -> {value} 亿元")

                    # 创建筛选条件
                    condition = ScreeningCondition(
                        field=mapped_field,
                        operator=mapped_op,
                        value=value
                    )
                    conditions.append(condition)

                    logger.info(f"[screening] 转换条件: {field}({op}) -> {mapped_field}({mapped_op}), 值: {value}")

    return conditions


# 传统筛选接口（保持向后兼容，但使用增强服务）
@router.post("/run", response_model=ScreeningResponse)
async def run_screening(req: ScreeningRequest, user: dict = Depends(get_current_user)):
    try:
        logger.info(f"[screening] 请求条件: {req.conditions}")
        logger.info(f"[screening] 排序与分页: order_by={req.order_by}, limit={req.limit}, offset={req.offset}")

        # 转换传统格式的条件为新格式
        conditions = _convert_legacy_conditions_to_new_format(req.conditions)
        logger.info(f"[screening] 转换后的条件: {conditions}")

        # 使用增强筛选服务
        result = await enhanced_svc.screen_stocks(
            conditions=conditions,
            market=req.market,
            date=req.date,
            adj=req.adj,
            limit=req.limit,
            offset=req.offset,
            order_by=[{"field": o.field, "direction": o.direction} for o in (req.order_by or [])],
            use_database_optimization=True
        )

        logger.info(f"[screening] 筛选完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        if result.get('items'):
            sample = result['items'][:3]
            logger.info(f"[screening] 返回样例(前3条): {sample}")

        return ScreeningResponse(total=result["total"], items=result["items"])

    except Exception as e:
        logger.error(f"[screening] 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preset/trend-start", response_model=Dict[str, Any])
async def run_trend_start_preset(
    req: PresetTrendStartRequest,
    user: dict = Depends(get_current_user),
):
    """
    运行“横盘放量启动”预设条件选股。

    预设条件来自 docs/选股逻辑.md，聚合放量启动、上一交易日自由流通换手、
    量价健康、小市值和热点行业方向，返回最近5日基础摘要。
    """
    try:
        logger.info(
            "[preset_screening] trend_start 请求: limit=%s candidate_limit=%s industries=%s",
            req.limit,
            req.candidate_limit,
            req.industries,
        )
        result = await preset_svc.run_trend_start_preset(
            limit=req.limit,
            candidate_limit=req.candidate_limit,
            industries=req.industries,
            float_cap_limit=req.float_cap_limit,
            min_five_day_turnover=req.min_five_day_turnover,
            volume_breakout_multiplier=req.volume_breakout_multiplier,
        )
        logger.info(
            "[preset_screening] trend_start 完成: total=%s took=%sms",
            result.get("total"),
            result.get("took_ms"),
        )
        return result
    except Exception as e:
        logger.error("[preset_screening] trend_start 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"预设条件选股失败: {str(e)}")


# 新的优化筛选接口
@router.post("/enhanced", response_model=NewScreeningResponse)
async def enhanced_screening(req: NewScreeningRequest, user: dict = Depends(get_current_user)):
    """
    增强的股票筛选接口
    - 支持更丰富的筛选条件格式
    - 自动选择最优的筛选策略（数据库优化 vs 传统方法）
    - 提供详细的性能统计信息
    """
    try:
        logger.info(f"[enhanced_screening] 筛选条件: {len(req.conditions)}个")
        logger.info(f"[enhanced_screening] 排序与分页: order_by={req.order_by}, limit={req.limit}, offset={req.offset}")

        # 执行增强筛选
        result = await enhanced_svc.screen_stocks(
            conditions=req.conditions,
            market=req.market,
            date=req.date,
            adj=req.adj,
            limit=req.limit,
            offset=req.offset,
            order_by=req.order_by,
            use_database_optimization=req.use_database_optimization
        )

        logger.info(f"[enhanced_screening] 筛选完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        return NewScreeningResponse(
            total=result["total"],
            items=result["items"],
            took_ms=result.get("took_ms"),
            optimization_used=result.get("optimization_used"),
            source=result.get("source")
        )

    except Exception as e:
        logger.error(f"[enhanced_screening] 筛选失败: {e}")
        raise HTTPException(status_code=500, detail=f"增强筛选失败: {str(e)}")


# 获取支持的字段信息
@router.get("/fields", response_model=List[Dict[str, Any]])
async def get_supported_fields(user: dict = Depends(get_current_user)):
    """获取所有支持的筛选字段信息"""
    try:
        fields = await enhanced_svc.get_all_supported_fields()
        return fields
    except Exception as e:
        logger.error(f"[screening] 获取字段信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取字段信息失败: {str(e)}")


# 获取单个字段的详细信息
@router.get("/fields/{field_name}", response_model=Dict[str, Any])
async def get_field_info(field_name: str, user: dict = Depends(get_current_user)):
    """获取指定字段的详细信息"""
    try:
        field_info = await enhanced_svc.get_field_info(field_name)
        if not field_info:
            raise HTTPException(status_code=404, detail=f"字段 '{field_name}' 不存在")
        return field_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[screening] 获取字段信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取字段信息失败: {str(e)}")


# 验证筛选条件
@router.post("/validate", response_model=Dict[str, Any])
async def validate_conditions(conditions: List[ScreeningCondition], user: dict = Depends(get_current_user)):
    """验证筛选条件的有效性"""
    try:
        validation_result = await enhanced_svc.validate_conditions(conditions)
        return validation_result
    except Exception as e:
        logger.error(f"[screening] 验证条件失败: {e}")
        raise HTTPException(status_code=500, detail=f"验证条件失败: {str(e)}")

# 重复定义的旧端点移除（保留带日志的版本）


@router.get("/industries")
async def get_industries(user: dict = Depends(get_current_user)):
    """
    获取数据库中所有可用的行业列表
    根据系统配置的数据源优先级，从优先级最高的数据源获取行业分类数据
    返回按股票数量排序的行业列表
    """
    try:
        from app.core.database import get_mongo_db
        from app.core.unified_config import UnifiedConfigManager

        db = get_mongo_db()
        collection = db["stock_basic_info"]

        # 🔥 获取数据源优先级配置（使用统一配置管理器的异步方法）
        config = UnifiedConfigManager()
        data_source_configs = await config.get_data_source_configs_async()

        # 提取启用的数据源，按优先级排序（已排序）
        enabled_sources = [
            ds.type.lower() for ds in data_source_configs
            if ds.enabled and ds.type.lower() in ['tushare', 'akshare', 'baostock']
        ]

        if not enabled_sources:
            # 如果没有配置，使用默认顺序
            enabled_sources = ['tushare', 'akshare', 'baostock']

        logger.info(f"[get_industries] 数据源优先级: {enabled_sources}")

        # 🔥 按优先级查询：优先使用优先级最高的数据源
        preferred_source = enabled_sources[0] if enabled_sources else 'tushare'

        # 聚合查询：按行业分组并统计股票数量（只查询指定数据源）
        pipeline = [
            {
                "$match": {
                    "source": preferred_source,  # 🔥 只查询优先级最高的数据源
                    "industry": {"$ne": None, "$ne": ""}  # 过滤空行业
                }
            },
            {
                "$group": {
                    "_id": "$industry",
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}},  # 按股票数量降序排序
            {
                "$project": {
                    "industry": "$_id",
                    "count": 1,
                    "_id": 0
                }
            }
        ]

        industries = []
        async for doc in collection.aggregate(pipeline):
            # 清洗字段，避免 NaN/Inf 导致 JSON 序列化失败
            raw_industry = doc.get("industry")
            safe_industry = ""
            try:
                if raw_industry is None:
                    safe_industry = ""
                elif isinstance(raw_industry, float):
                    if raw_industry != raw_industry or raw_industry in (float("inf"), float("-inf")):
                        safe_industry = ""
                    else:
                        safe_industry = str(raw_industry)
                else:
                    safe_industry = str(raw_industry)
            except Exception:
                safe_industry = ""

            raw_count = doc.get("count", 0)
            safe_count = 0
            try:
                if isinstance(raw_count, float):
                    if raw_count != raw_count or raw_count in (float("inf"), float("-inf")):
                        safe_count = 0
                    else:
                        safe_count = int(raw_count)
                else:
                    safe_count = int(raw_count)
            except Exception:
                safe_count = 0

            industries.append({
                "value": safe_industry,
                "label": safe_industry,
                "count": safe_count,
            })

        logger.info(f"[get_industries] 从数据源 {preferred_source} 返回 {len(industries)} 个行业")

        return {
            "industries": industries,
            "total": len(industries),
            "source": preferred_source  # 🔥 返回数据来源
        }

    except Exception as e:
        logger.error(f"[get_industries] 获取行业列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
