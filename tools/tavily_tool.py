# 定义一个网络搜索的工具！
# ======================== 导入核心依赖 ========================
from typing import Literal
from langchain_core.tools import tool
from tavily import TavilyClient

import os
import time
from dotenv import load_dotenv

from api.monitor import monitor
from api.context import get_task_execution_limits
from utils.tool_result import tool_failure

# ======================== 初始化配置 ========================
load_dotenv()

# Tavily 客户端（超时 30 秒，防止网络卡死）
tavily_client = TavilyClient(
    api_key=os.getenv("TAVILY_API_KEY"),
)


# ======================== 带重试的搜索封装 ========================

class SearchLimitExceeded(RuntimeError):
    """网络搜索（含内部重试）达到单任务硬上限。"""


def _consume_retry_budget() -> None:
    """内部重试前再占用一次额度，确保真实外部请求数也不超限。"""
    limits = get_task_execution_limits()
    if limits is None:
        return
    allowed, used = limits.try_consume_network_search()
    if not allowed:
        raise SearchLimitExceeded(
            f"单任务网络搜索硬上限为 {limits.max_network_searches} 次，当前已使用 {used} 次"
        )


def _search_with_retry(
    query: str,
    topic: str,
    max_results: int,
    include_raw_content: bool,
    *,
    first_attempt_reserved: bool = False,
):
    """
    对 Tavily 搜索调用进行指数退避重试，且每次真实请求都占用任务额度。
    """
    delay = 1.0
    last_exception = None
    for attempt in range(4):
        if attempt > 0 or not first_attempt_reserved:
            _consume_retry_budget()
        try:
            return tavily_client.search(
                query=query,
                topic=topic,
                max_results=max_results,
                include_raw_content=include_raw_content,
            )
        except Exception as exc:
            last_exception = exc
            if attempt == 3:
                break
            time.sleep(delay)
            delay = min(delay * 2, 10.0)
    raise last_exception


# ======================== LangChain 工具定义 ========================

@tool
def internet_search(
    query: str,
    topic: Literal["news", "finance", "general"] = "general",
    max_results: int = 5,
    include_raw_content: bool = False,
):
    """
    根据用户问题，进行网络信息搜索！
    注意：主要搜索公开的网络信息！如果指定查询数据库或者rag不能使用此工具！
    :param query: 用户的查询信息
    :param topic: 查询的类型 (general/news/finance)
    :param max_results: 返回的最大条数
    :param include_raw_content: 是否返回原内容 False 精简 True 详细
    :return: 搜索结果
    """
    # 在真正请求外部接口前原子占用额度，确保并行搜索也不会突破硬上限。
    limits = get_task_execution_limits()
    if limits is not None:
        allowed, used = limits.try_consume_network_search()
        if not allowed:
            return tool_failure(
                "internet_search",
                f"单任务网络搜索硬上限为 {limits.max_network_searches} 次，当前已使用 {used} 次",
                error_type="SearchLimitExceeded",
                retryable=False,
                guidance="停止继续搜索，使用已有结果完成回答，并在限制与风险中说明搜索额度已用尽。",
            )

    # 每次实际调用工具，都向前端推送调用进度
    monitor.report_tool(
        tool_name="网络搜索工具",
        args={
            "query": query,
            "topic": topic,
            "max_results": max_results,
            "include_raw_content": include_raw_content,
        },
    )

    # 带重试的搜索调用（指数退避，最多 3 次）
    try:
        return _search_with_retry(
            query=query,
            topic=topic,
            max_results=max_results,
            include_raw_content=include_raw_content,
            first_attempt_reserved=True,
        )
    except Exception as e:
        return tool_failure(
            "internet_search",
            e,
            error_type=(
                "SearchLimitExceeded"
                if isinstance(e, SearchLimitExceeded)
                else None
            ),
            retryable=False,
            guidance="网络搜索已完成内部重试，请调整关键词或在最终结果中说明外部信息暂不可用。",
        )
