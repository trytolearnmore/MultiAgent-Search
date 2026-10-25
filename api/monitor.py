import sys
import datetime
import asyncio
from typing import Any, Dict, Optional
from fastapi import WebSocket
from api.context import get_thread_context
from api.task_logger import task_logger

# 修复 Windows GBK 编码问题
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 尝试导入全局运行时（用于脚本模式下的流式输出）
try:
    import builtins
except ImportError:
    builtins = None


class ToolMonitor:
    """
    工具监控类，用于在工具执行过程中上报进度和状态。
    设计为单例模式，可在任何工具中直接导入使用。
    兼容 FastAPI WebSocket 和 脚本运行时的 stream_writer。

    使用示例:
    from api.monitor import monitor

    def my_tool(arg1):
        monitor.report_start("my_tool", {"arg1": arg1})
        ...
        monitor.report_running("my_tool", "正在处理数据...", progress=0.5)
        ...
        monitor.report_end("my_tool", result)
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ToolMonitor, cls).__new__(cls)
            cls._instance.websocket_manager = None  # 预留给 FastAPI WebSocketManager
        return cls._instance

    def set_websocket_manager(self, manager):
        """设置 FastAPI 的 WebSocket 管理器"""
        self.websocket_manager = manager

    def _emit(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None):
        """内部发送方法"""
        thread_id = get_thread_context()
        payload = {
            "type": "monitor_event",
            "event": event_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.datetime.now().isoformat()
        }

        # 每个监控事件同时落一条轻量日志；logger 只保留白名单元数据。
        try:
            task_logger.write(
                event_type,
                message,
                thread_id=thread_id,
                data=data,
            )
        except Exception as e:
            # 日志不可写不能反过来中断用户任务。
            print(f"[Monitor] Task log write failed: {e}")

        # 1. 优先尝试通过 FastAPI WebSocket 发送 (定向推送)
        if self.websocket_manager:
            try:
                # 获取当前线程 ID
                # 确保 loop 已加载 [fastapi的事件循环]
                manager_loop = self.websocket_manager.loop

                if manager_loop:
                    if thread_id:
                        # 检查当前是否在同一个事件循环中
                        try:
                            # 当前的循环事件
                            current_loop = asyncio.get_running_loop()
                            print(f"对比是不是同一个event_loop:{manager_loop == current_loop}")
                        except RuntimeError:
                            current_loop = None

                        if current_loop and current_loop == manager_loop:
                            # 如果在同一个循环中（例如在 create_task 中运行），直接创建任务
                            current_loop.create_task(
                                self.websocket_manager.send_to_thread(payload, thread_id)
                            )
                        else:
                            #  FastAPI 的 WebSocket 依赖异步事件循环，且协程必须在创建它的循环中运行：
                            #  如果当前线程和 WebSocket 管理器在同一个循环（比如在 FastAPI 的接口 / 任务中运行）：直接 create_task 效率最高；
                            #  如果在不同循环 / 不同线程（比如同步线程调用）：必须用 asyncio.run_coroutine_threadsafe（线程安全的方式），否则会报错 “协程在错误的循环中运行”。
                            # 如果在不同线程，使用 threadsafe 方法
                            asyncio.run_coroutine_threadsafe(
                                self.websocket_manager.send_to_thread(payload, thread_id),
                                manager_loop
                            )
                    else:
                        # 如果没有 thread_id，说明可能是系统级消息，或者未上下文环境
                        pass
            except Exception as e:
                print(f"[Monitor] WebSocket send failed: {e}")

        # 2. 尝试通过全局 runtime 输出 (DeepAgents 脚本模式)
        # 这使得 simple_agents.py 中的 MockRuntime 能接收到数据
        if builtins and hasattr(builtins, 'runtime') and hasattr(builtins.runtime, 'stream_writer'):
            try:
                builtins.runtime.stream_writer(payload)
            except Exception:
                pass

        # 3. 控制台保底输出 (方便调试)
        # 加上特殊前缀，方便肉眼识别
        print(f"\n[Monitor:{event_type}] {message}")

    def report_tool(self, tool_name: str, args: Dict[str, Any] = None):
        """报告工具开始执行"""
        self._emit("tool_start", f"开始执行工具: {tool_name}", {"tool_name": tool_name, "args": args})

    def report_tool_error(
        self,
        tool_name: str,
        message: str,
        *,
        error_type: str,
        retryable: bool,
    ):
        """报告工具失败，并向日志保留可检索的错误类别。"""
        self._emit(
            "tool_error",
            f"工具执行失败: {tool_name} - {message}",
            {
                "tool_name": tool_name,
                "error_type": error_type,
                "retryable": retryable,
            },
        )

    def report_assistant(self, assistant_name: str, args: Dict[str, Any] = None):
        """报告正在调用的子智能体进度"""
        self._emit("assistant_call", f"正在调用助手: {assistant_name}",
                   {"assistant_name": assistant_name, "args": args})

    def report_task_started(
        self,
        query_length: int,
        reflection_enabled: bool,
        max_network_searches: int | None = None,
        max_database_queries: int | None = None,
    ):
        """报告任务开始，不记录用户问题正文。"""
        self._emit(
            "task_started",
            f"任务开始执行（反思机制：{'开启' if reflection_enabled else '关闭'}）",
            {
                "query_length": query_length,
                "reflection_enabled": reflection_enabled,
                "max_network_searches": max_network_searches,
                "max_database_queries": max_database_queries,
            },
        )

    def report_artifact_retry(self, missing_extensions: set[str]):
        """报告文件产物缺失后的自动纠正。"""
        formats = "、".join(sorted(missing_extensions))
        self._emit(
            "artifact_retry",
            f"未检测到要求的文件（{formats}），正在自动补充生成",
        )

    def report_task_result(self, result: str, duration_ms: int | None = None):
        """报告任务最终结果"""
        self._emit(
            "task_result",
            "任务执行完成",
            {"result": result, "duration_ms": duration_ms},
        )

    def report_error(self, message: str, duration_ms: int | None = None):
        """报告任务级错误。"""
        self._emit("error", message, {"duration_ms": duration_ms})

    def report_session_dir(self, path: str):
        """报告任务工作目录"""
        self._emit("session_created", f"工作目录已创建: {path}", {"path": path})


# 全局单例实例
monitor = ToolMonitor()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        # 延迟绑定 loop，防止初始化时 loop 不一致
        self.loop = None

    def set_loop(self, loop):
        """显式设置事件循环"""
        self.loop = loop
        monitor.set_websocket_manager(self)
        print(f"[Monitor] ConnectionManager manually bound to loop: {id(self.loop)}")

    async def connect(self, websocket: WebSocket, thread_id: str):
        await websocket.accept()
        print(f"存储当前会话id:{thread_id}对应的:{websocket}")
        self.active_connections[thread_id] = websocket
        print(f"Client connected: {thread_id}")

    def disconnect(self, websocket: WebSocket, thread_id: str):
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        print(f"Client disconnected: {thread_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def send_to_thread(self, message: dict, thread_id: str):
        if thread_id in self.active_connections:
            websocket = self.active_connections[thread_id]
            await websocket.send_json(message)


manager = ConnectionManager()
