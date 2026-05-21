from typing import Any, Dict, Optional


def _safe_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_reports(reports_data: Any) -> Dict[str, str]:
    reports = _safe_dict(reports_data)
    validated_reports: Dict[str, str] = {}

    for report_key, report_content in reports.items():
        safe_key = _safe_string(report_key, "unknown_report")
        if report_content is None:
            validated_content = "报告内容暂无"
        elif isinstance(report_content, str):
            validated_content = report_content.strip() if report_content.strip() else "报告内容为空"
        else:
            validated_content = str(report_content).strip() if str(report_content).strip() else "报告内容格式错误"
        validated_reports[safe_key] = validated_content

    return validated_reports


def build_task_result_payload(
    result_data: Dict[str, Any],
    task_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the API result payload for analysis and screening task results."""
    task_doc = task_doc or {}

    if result_data.get("type") == "screening" or isinstance(result_data.get("screening"), dict):
        screening = _safe_dict(result_data.get("screening"))
        return {
            "type": "screening",
            "analysis_id": _safe_string(result_data.get("analysis_id") or task_doc.get("task_id"), "unknown"),
            "stock_symbol": _safe_string(result_data.get("stock_symbol"), "SCREENING"),
            "stock_code": _safe_string(result_data.get("stock_code"), "SCREENING"),
            "analysis_date": _safe_string(result_data.get("analysis_date") or task_doc.get("completed_at") or task_doc.get("created_at"), ""),
            "summary": _safe_string(result_data.get("summary"), "选股结果暂无摘要"),
            "recommendation": _safe_string(result_data.get("recommendation"), "选股结果暂无说明"),
            "confidence_score": _safe_number(result_data.get("confidence_score"), 0.0),
            "risk_level": _safe_string(result_data.get("risk_level"), "中等"),
            "key_points": _safe_list(result_data.get("key_points")),
            "execution_time": _safe_number(result_data.get("execution_time"), 0),
            "tokens_used": _safe_number(result_data.get("tokens_used"), 0),
            "analysts": _safe_list(result_data.get("analysts")),
            "research_depth": _safe_string(result_data.get("research_depth"), "选股"),
            "detailed_analysis": _safe_dict(result_data.get("detailed_analysis")),
            "state": _safe_dict(result_data.get("state")),
            "decision": _safe_dict(result_data.get("decision")),
            "reports": _normalize_reports(result_data.get("reports")),
            "screening": screening,
        }

    return {
        "analysis_id": _safe_string(result_data.get("analysis_id"), "unknown"),
        "stock_symbol": _safe_string(result_data.get("stock_symbol"), "UNKNOWN"),
        "stock_code": _safe_string(result_data.get("stock_code"), "UNKNOWN"),
        "analysis_date": _safe_string(result_data.get("analysis_date"), "2025-08-20"),
        "summary": _safe_string(result_data.get("summary"), "分析摘要暂无"),
        "recommendation": _safe_string(result_data.get("recommendation"), "投资建议暂无"),
        "confidence_score": _safe_number(result_data.get("confidence_score"), 0.0),
        "risk_level": _safe_string(result_data.get("risk_level"), "中等"),
        "key_points": _safe_list(result_data.get("key_points")),
        "execution_time": _safe_number(result_data.get("execution_time"), 0),
        "tokens_used": _safe_number(result_data.get("tokens_used"), 0),
        "analysts": _safe_list(result_data.get("analysts")),
        "research_depth": _safe_string(result_data.get("research_depth"), "快速"),
        "detailed_analysis": _safe_dict(result_data.get("detailed_analysis")),
        "state": _safe_dict(result_data.get("state")),
        "decision": _safe_dict(result_data.get("decision")),
        "reports": _normalize_reports(result_data.get("reports")),
    }
