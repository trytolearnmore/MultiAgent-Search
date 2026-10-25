import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import ToolMessage

from agent.execution_limits import SubagentDispatchLimitMiddleware
from api.context import (
    TaskExecutionLimits,
    reset_task_execution_limits,
    set_task_execution_limits,
)
from tools.tavily_tool import internet_search
from tools.db_tools import execute_sql_query


class TaskExecutionLimitsTests(unittest.TestCase):
    def test_network_search_budget_is_atomic_under_parallel_calls(self):
        limits = TaskExecutionLimits(max_network_searches=5)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: limits.try_consume_network_search()[0], range(20)))

        self.assertEqual(sum(results), 5)
        self.assertEqual(limits.network_searches, 5)

    def test_database_query_budget_is_atomic_under_parallel_calls(self):
        limits = TaskExecutionLimits(max_database_queries=5)

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: limits.try_consume_database_query()[0], range(20)))

        self.assertEqual(sum(results), 5)
        self.assertEqual(limits.database_queries, 5)

    @patch("tools.db_tools.connect")
    @patch("tools.db_tools.monitor.report_tool")
    @patch("utils.tool_result.monitor.report_tool_error")
    def test_database_query_over_limit_is_blocked_before_connection(
        self,
        report_tool_error,
        report_tool,
        connect,
    ):
        limits = TaskExecutionLimits(max_database_queries=2, database_queries=2)
        token = set_task_execution_limits(limits)
        try:
            result = json.loads(execute_sql_query.invoke({"query": "SELECT 1"}))
        finally:
            reset_task_execution_limits(token)

        connect.assert_not_called()
        report_tool.assert_not_called()
        self.assertEqual(result["error_type"], "DatabaseQueryLimitExceeded")
        self.assertFalse(result["retryable"])
        report_tool_error.assert_called_once()

    @patch("tools.tavily_tool._search_with_retry")
    @patch("tools.tavily_tool.monitor.report_tool")
    @patch("utils.tool_result.monitor.report_tool_error")
    def test_sixth_network_search_is_blocked_before_external_call(
        self,
        report_tool_error,
        report_tool,
        search,
    ):
        search.return_value = {"results": []}
        token = set_task_execution_limits(TaskExecutionLimits(max_network_searches=5))
        try:
            for index in range(5):
                internet_search.invoke({"query": f"query-{index}"})
            blocked = json.loads(internet_search.invoke({"query": "query-6"}))
        finally:
            reset_task_execution_limits(token)

        self.assertEqual(search.call_count, 5)
        self.assertEqual(report_tool.call_count, 5)
        self.assertEqual(blocked["error_type"], "SearchLimitExceeded")
        self.assertFalse(blocked["retryable"])
        report_tool_error.assert_called_once()

    @patch("tools.tavily_tool.time.sleep")
    @patch("tools.tavily_tool.tavily_client.search")
    @patch("tools.tavily_tool.monitor.report_tool")
    @patch("utils.tool_result.monitor.report_tool_error")
    def test_internal_retries_also_consume_the_hard_limit(
        self,
        report_tool_error,
        report_tool,
        tavily_search,
        sleep,
    ):
        tavily_search.side_effect = RuntimeError("temporary failure")
        token = set_task_execution_limits(TaskExecutionLimits(max_network_searches=2))
        try:
            result = json.loads(internet_search.invoke({"query": "retry-test"}))
        finally:
            reset_task_execution_limits(token)

        self.assertEqual(tavily_search.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(report_tool.call_count, 1)
        self.assertEqual(result["error_type"], "SearchLimitExceeded")
        report_tool_error.assert_called_once()


class SubagentDispatchLimitMiddlewareTests(unittest.TestCase):
    @patch("agent.execution_limits.monitor.report_assistant")
    @patch("utils.tool_result.monitor.report_tool_error")
    def test_same_subagent_is_executed_only_once(self, report_tool_error, report_assistant):
        middleware = SubagentDispatchLimitMiddleware()
        limits_token = set_task_execution_limits(TaskExecutionLimits())
        handler_calls = 0

        def handler(request):
            nonlocal handler_calls
            handler_calls += 1
            return ToolMessage(
                content="ok",
                tool_call_id=request.tool_call["id"],
                name="task",
            )

        first = SimpleNamespace(
            tool_call={
                "id": "call-1",
                "name": "task",
                "args": {"subagent_type": "市场情报助手", "description": "第一次"},
            }
        )
        second = SimpleNamespace(
            tool_call={
                "id": "call-2",
                "name": "task",
                "args": {"subagent_type": "市场情报助手", "description": "第二次"},
            }
        )

        try:
            first_result = middleware.wrap_tool_call(first, handler)
            second_result = middleware.wrap_tool_call(second, handler)
        finally:
            reset_task_execution_limits(limits_token)

        self.assertEqual(first_result.content, "ok")
        self.assertEqual(handler_calls, 1)
        self.assertEqual(report_assistant.call_count, 1)
        blocked = json.loads(second_result.content)
        self.assertEqual(blocked["error_type"], "DuplicateSubagentDispatch")
        self.assertEqual(second_result.status, "error")
        report_tool_error.assert_called_once()

    def test_different_subagents_are_each_allowed_once(self):
        limits = TaskExecutionLimits()
        self.assertTrue(limits.try_dispatch_subagent("市场情报助手"))
        self.assertTrue(limits.try_dispatch_subagent("数据分析助手"))
        self.assertFalse(limits.try_dispatch_subagent("市场情报助手"))


if __name__ == "__main__":
    unittest.main()
