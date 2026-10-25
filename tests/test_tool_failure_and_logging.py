import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.task_logger import TaskExecutionLogger
from tools.upload_file_read_tool import read_file_content
from utils.tool_result import tool_failure


class ToolFailureTests(unittest.TestCase):
    @patch("utils.tool_result.monitor.report_tool_error")
    def test_tool_failure_has_a_machine_readable_shape(self, report_tool_error):
        result = json.loads(
            tool_failure(
                "example_tool",
                ValueError("bad input"),
                retryable=True,
            )
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["tool"], "example_tool")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["message"], "bad input")
        self.assertTrue(result["retryable"])
        report_tool_error.assert_called_once()

    @patch("utils.tool_result.monitor.report_tool_error")
    def test_real_tool_uses_the_common_failure_shape(self, report_tool_error):
        result = json.loads(
            read_file_content.invoke({"filename": "file-that-does-not-exist.txt"})
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["tool"], "read_file_content")
        self.assertEqual(result["error_type"], "FileNotFoundError")
        report_tool_error.assert_called_once()


class TaskExecutionLoggerTests(unittest.TestCase):
    def test_log_is_json_line_and_excludes_content_fields(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            log_path = Path(temp_dir) / "task.log"
            logger = TaskExecutionLogger(log_path)
            logger.write(
                "task_result",
                "任务执行完成",
                thread_id="thread-1",
                data={
                    "duration_ms": 25,
                    "reflection_enabled": False,
                    "result": "不应写入日志的完整回答",
                    "args": {"query": "不应写入日志的查询"},
                },
            )
            logger.close()

            event = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertEqual(event["thread_id"], "thread-1")
            self.assertEqual(event["event"], "task_result")
            self.assertEqual(
                event["data"],
                {"duration_ms": 25, "reflection_enabled": False},
            )
            self.assertNotIn("不应写入", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
