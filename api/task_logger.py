"""轻量级任务执行日志。"""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class JsonLineFormatter(logging.Formatter):
    """把每个任务事件写成一行 JSON，便于检索和后续分析。"""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.task_event, ensure_ascii=False, default=str)


class TaskExecutionLogger:
    """记录必要的执行元数据，不保存完整问题、参数或回答内容。"""

    _SAFE_DATA_FIELDS = {
        "assistant_name",
        "duration_ms",
        "error_type",
        "max_network_searches",
        "query_length",
        "reflection_enabled",
        "retryable",
        "tool_name",
    }

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger_name = f"task_execution.{self.log_path.resolve()}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        if not self._logger.handlers:
            handler = RotatingFileHandler(
                self.log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(JsonLineFormatter())
            self._logger.addHandler(handler)

    def write(
        self,
        event: str,
        message: str,
        *,
        thread_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        safe_data = {
            key: value
            for key, value in (data or {}).items()
            if key in self._SAFE_DATA_FIELDS
        }
        task_event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": thread_id,
            "event": event,
            "message": message,
            "data": safe_data,
        }
        self._logger.info("task_event", extra={"task_event": task_event})

    def close(self) -> None:
        """释放文件句柄，主要供测试和进程关闭使用。"""
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)


task_log_path = Path(__file__).parents[1] / "data" / "task_execution.log"
task_logger = TaskExecutionLogger(task_log_path)
