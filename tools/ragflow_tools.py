"""供内部知识助手调用的 RAGFlow 工具。"""

from collections.abc import Mapping
from functools import lru_cache
from uuid import uuid4

from langchain_core.tools import tool
from ragflow_sdk import RAGFlow

from api.monitor import monitor
from rawflow.rag_config import _load_ragflow_env
from utils.tool_result import tool_failure


@lru_cache(maxsize=1)
def _get_ragflow_client() -> RAGFlow:
    """按需创建客户端，避免未配置 RAGFlow 时阻塞整个应用启动。"""
    api_key, base_url = _load_ragflow_env()
    missing = []
    if not api_key or not api_key.strip():
        missing.append("RAGFLOW_API_KEY")
    if not base_url or not base_url.strip():
        missing.append("RAGFLOW_API_URL")
    if missing:
        raise RuntimeError(f"缺少 RAGFlow 配置：{', '.join(missing)}")

    return RAGFlow(api_key=api_key.strip(), base_url=base_url.strip().rstrip("/"))


def _dataset_name(dataset: object) -> str:
    """兼容 SDK 将知识库表示为字典或对象的情况。"""
    if isinstance(dataset, Mapping):
        return str(dataset.get("name") or "").strip()
    return str(getattr(dataset, "name", "") or "").strip()



# 1. 查询现在知识库中有哪些聊天助手和对应知识库的信息 （方便我们知道rag可以给我们提供哪些数据）
@tool
def get_assistant_list() -> str:
    """
    调用此工具，可以查询ragflow服务器中有哪些助手和助手关联的知识库信息！
    供模型参考，可以从哪个助手获取对应的内部文档信息！
    强调：想向某个助手提问，必须想要调用此工具查询助手的信息和名称
    返回结果： 有-> 名称:助手名称,助手描述：xxxx,关联的知识库：知识库的名、知识库的名字、
             没有 -> 没有任何可用助手
             异常 -> 查询助手信息异常，无可用助手
    :return:
    """

    # 埋点,调用工具了告诉前端哪个工具被调用了！！
    monitor.report_tool(tool_name="ragflow聊天助手列表查询工具：get_assistant_list")

    try:
        ragflow_client = _get_ragflow_client()
        chat_list = ragflow_client.list_chats(page=1, page_size=100)
        if not chat_list:
            return "没有任何可用助手"

        chat_info = []
        for chat in chat_list:
            dataset_names = [
                name
                for dataset in (getattr(chat, "datasets", None) or [])
                if (name := _dataset_name(dataset))
            ]
            name = str(getattr(chat, "name", "") or "未命名助手")
            description = str(getattr(chat, "description", "") or "无")
            datasets = "、".join(dataset_names) or "无"
            chat_info.append(
                f"助手名称:{name};功能介绍：{description};关联的知识库：{datasets}"
            )
        return "\n".join(chat_info)
    except Exception as e:
        return tool_failure("get_assistant_list", e)

# 2. 对某个助手进行提问（创建会话 -》 提问 -》 删除会话）
@tool
def create_ask_delete(chat_name: str, question: str) -> str:
    """
    想某个助手，创建单次会话进行提问，提问完毕以后会关闭会话！
    主要查询ragflow中相关的信息！
    注意：调用此工具之前，必须先调用 get_assistant_list工具明确查询助手的名字和对应的问题
    :param chat_name: 助手的名字！上一个工具get_assistant_list告诉大模型的只有名字
    :param question: 本次提问的问题
    :return: 返回提问的结果
    """
    # 埋点,调用工具了告诉前端哪个工具被调用了！！
    monitor.report_tool(tool_name="ragflow提问助手工具：create_ask_delete",args={"chat_name":chat_name,"question":question})
    session = None
    use_chat = None
    try:
        chat_name = chat_name.strip()
        question = question.strip()
        if not chat_name:
            raise ValueError("chat_name 不能为空")
        if not question:
            raise ValueError("question 不能为空")

        ragflow_client = _get_ragflow_client()
        chats = ragflow_client.list_chats(name=chat_name)
        use_chat = next(
            (chat for chat in chats if getattr(chat, "name", None) == chat_name),
            None,
        )
        if use_chat is None:
            raise LookupError(f"未找到名称为 {chat_name!r} 的 RAGFlow 助手")

        session = use_chat.create_session(name=f"temp_session_ask_{uuid4().hex}")
        response = session.ask(question=question, stream=True)
        result = ""
        for part in response:
            content = str(getattr(part, "content", "") or "")
            if content.startswith(result):
                # RAGFlow 当前流式接口返回逐步累积的完整内容。
                result = content
            elif content and not result.endswith(content):
                # 同时兼容未来可能返回增量片段的实现。
                result += content

        if not result.strip():
            raise RuntimeError("RAGFlow 助手返回了空结果")
        return result
    except Exception as e:
        return tool_failure("create_ask_delete", e)
    finally:
        if use_chat is not None and session is not None:
            try:
                use_chat.delete_sessions(ids=[session.id])
            except Exception as cleanup_error:
                monitor.report_tool_error(
                    "create_ask_delete.cleanup",
                    str(cleanup_error),
                    error_type=type(cleanup_error).__name__,
                    retryable=True,
                )

# if __name__ == '__main__':
#     # print(get_assistant_list())
#     # print(create_ask_delete("你的助手名称", "你的问题"))
