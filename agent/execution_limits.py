"""主智能体工具调用的任务级硬限制。"""

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from api.context import get_task_execution_limits
from api.monitor import monitor
from utils.tool_result import tool_failure


class SubagentDispatchLimitMiddleware(AgentMiddleware):
    """阻止同一用户任务重复执行同一种子智能体。"""

    @staticmethod
    def _blocked_message(tool_call: dict[str, Any], subagent_type: str) -> ToolMessage:
        content = tool_failure(
            "task",
            f"同一任务内不允许重复调度子智能体：{subagent_type}",
            error_type="DuplicateSubagentDispatch",
            retryable=False,
            guidance="请使用该子智能体第一次返回的结果完成汇总，不要再次调用它。",
        )
        return ToolMessage(
            content=content,
            tool_call_id=tool_call["id"],
            name=tool_call.get("name"),
            status="error",
        )

    @staticmethod
    def _allow(tool_call: dict[str, Any]) -> tuple[bool, str]:
        if tool_call.get("name") != "task":
            return True, ""
        subagent_type = str(tool_call.get("args", {}).get("subagent_type", "")).strip()
        limits = get_task_execution_limits()
        if not subagent_type or limits is None:
            return True, subagent_type
        return limits.try_dispatch_subagent(subagent_type), subagent_type

    def wrap_tool_call(self, request, handler):
        allowed, subagent_type = self._allow(request.tool_call)
        if not allowed:
            return self._blocked_message(request.tool_call, subagent_type)
        if request.tool_call.get("name") == "task":
            monitor.report_assistant(
                subagent_type,
                {"description": request.tool_call.get("args", {}).get("description", "")},
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        allowed, subagent_type = self._allow(request.tool_call)
        if not allowed:
            return self._blocked_message(request.tool_call, subagent_type)
        if request.tool_call.get("name") == "task":
            monitor.report_assistant(
                subagent_type,
                {"description": request.tool_call.get("args", {}).get("description", "")},
            )
        return await handler(request)
