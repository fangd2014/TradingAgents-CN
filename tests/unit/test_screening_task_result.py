from app.utils.analysis_result_payload import build_task_result_payload


def test_screening_task_result_preserves_saved_screening_payload():
    result = {
        "type": "screening",
        "summary": "选股完成，命中 2 只股票",
        "recommendation": "策略：中高回落+缩量横盘",
        "screening": {
            "strategy_id": "trend_start",
            "strategy_name": "中高回落+缩量横盘",
            "total": 2,
            "items": [
                {"code": "600519", "name": "贵州茅台"},
                {"code": "000001", "name": "平安银行"},
            ],
        },
    }

    payload = build_task_result_payload(
        result,
        task_doc={
            "task_id": "screening-task-1",
            "created_at": "2026-05-11T09:00:00",
            "completed_at": "2026-05-11T09:00:03",
        },
    )

    assert payload["type"] == "screening"
    assert payload["screening"]["strategy_id"] == "trend_start"
    assert payload["screening"]["items"][0]["code"] == "600519"
    assert payload["summary"] == "选股完成，命中 2 只股票"
    assert payload["reports"] == {}
