"""工具失败结果的统一格式。"""

import json

from api.monitor import monitor


def tool_failure(
    tool_name: str,
    error: BaseException | str,
    *,
    error_type: str | None = None,
    retryable: bool = False,
    guidance: str = "请根据错误信息调整参数，或在最终结果中明确说明该数据暂不可用。",
) -> str:
    """返回可供 Agent 稳定识别的 JSON 错误，并同步记录失败事件。"""
    resolved_error_type = error_type or (
        type(error).__name__ if isinstance(error, BaseException) else "ToolError"
    )
    message = str(error)[:1000]
    payload = {
        "status": "error",
        "tool": tool_name,
        "error_type": resolved_error_type,
        "message": message,
        "retryable": retryable,
        "guidance": guidance,
    }
    monitor.report_tool_error(
        tool_name,
        message,
        error_type=resolved_error_type,
        retryable=retryable,
    )
    return json.dumps(payload, ensure_ascii=False)
