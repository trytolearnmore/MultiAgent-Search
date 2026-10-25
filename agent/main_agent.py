from agent.subagents.knowledge_base_agent import knowledge_base_agent
from agent.subagents.database_query_agent import database_query_agent
from agent.subagents.network_search_agent import network_search_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

# main_agent tool导入
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content

from deepagents import create_deep_agent

from agent.llm import model
from agent.prompts import main_agent_content, reflection_enabled
from agent.artifact_guard import (
    build_artifact_recovery_prompt,
    detect_requested_artifacts,
    find_missing_artifacts,
    snapshot_files,
)
from agent.execution_limits import SubagentDispatchLimitMiddleware

from api.monitor import monitor
import asyncio
import uuid
import shutil
import time
from pathlib import Path

from api.context import (
    create_task_execution_limits,
    reset_session_context,
    set_session_context,
    set_task_execution_limits,
    set_thread_context,
)

from langchain_core.messages import AIMessage

# 持久化 checkpoint：使用 SQLite 替代内存存储
# 服务重启后对话历史不丢失，支持多轮对话上下文
checkpoint_db_path = Path(__file__).parents[1] / "data" / "checkpoints.db"
checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
_conn = None
checkpointer = None
main_agent = None
_agent_init_lock = asyncio.Lock()


async def initialize_main_agent():
    """在当前事件循环中初始化异步 checkpoint 和主智能体。"""
    global _conn, checkpointer, main_agent

    if main_agent is not None:
        return main_agent

    async with _agent_init_lock:
        if main_agent is None:
            _conn = await aiosqlite.connect(str(checkpoint_db_path))
            checkpointer = AsyncSqliteSaver(_conn)
            await checkpointer.setup()
            main_agent = create_deep_agent(
                model=model,
                system_prompt=main_agent_content["system_prompt"],
                tools=[generate_markdown, convert_md_to_pdf, read_file_content],
                checkpointer=checkpointer,
                subagents=[
                    database_query_agent,
                    network_search_agent,
                    knowledge_base_agent,
                ],
                middleware=[SubagentDispatchLimitMiddleware()],
            )

    return main_agent


async def close_main_agent():
    """服务关闭时释放 SQLite 连接。"""
    global _conn, checkpointer, main_agent

    if _conn is not None:
        await _conn.close()
    _conn = None
    checkpointer = None
    main_agent = None

# 执行
"""
  1. 执行主智能体 一定选异步，原因：对应多个客户端
  2. 什么时候触发我们智能体的调用或者执行？？？
  3. 客户端 -》 api/task -> fastapi 接口 -》 异步执行 -》 main_agent的运行 （异步方法）
  4. main_agent执行stream流式处理 -》 调用工具 -》 已经埋好了点  
                                   调用子智能体 -》 结果解析 -》 name = task -> monitor -> 发送子智能体
                                   调用最终结果 -》 结果 -》 monitor -> 发送结果的方法
                                   开启调用以后 -》 当前会话 -》 文件夹地址 -》 推送到前端
"""



project_root_path = Path(__file__).parents[1].resolve() # 绝对 解析路径标识以及软连接
# project_root_path = Path(__file__).parents[1].absolute() # 绝对
# main_agent.invoke()
# main_agent.stream()
# main_agent.astream() [选他]
async def run_deep_agent(task_query,session_id):
    """
    定义流式+异步执行主智能体！！
    执行过程中，返回  会话文件化返回  调用子智能体  调用最终结果 （monitor）
    task_query: 前端提问的问题
    session_id: 每个前端会话对应的标识 （1.存储session_id ContextVars 2.session_id 给他创建对应的output输出地址）
    """
    started_at = time.perf_counter()
    print(f"当前会话的main_agent开始执行了！ 会话id:{session_id}")
    # 准备工作 【1. session_dir（前端） 2. relative_session_dir (大模型) 3. 上传的文件拼接上传文件专属提示词】
    # project_root_path / output / session_session_id(uuid)
    # 当前会话存储生成文件的专属文件夹
    session_dir = project_root_path / "output" / f"session_{session_id}"
    # 文件夹可能没有，第一次请求要创建
    session_dir.mkdir(parents=True, exist_ok=True)
    # \  \n \t -> /
    session_dir_str = str(session_dir).replace("\\","/")
    # 获取相对文件夹
    # session_dir : project_root_path / output / session_session_id(uuid)
    # project_root_path : project_root_path
    # relative_session_dir_str: / output / session_session_id(uuid)
    relative_session_dir_str = str(session_dir.relative_to(project_root_path)).replace("\\","/")

    #处理上传文件 （updated / session_session_id）
    updated_dir_path = project_root_path / "updated" / f"session_{session_id}"
    updated_info_prompt = "" # 有上传文件，拼接上传文件专属解析位置的提示词
    if updated_dir_path.exists():
        # 有
        files = [ f.name  for f in updated_dir_path.iterdir()  if f.is_file()]
        # 将上传文件统一赋值到 output_dir 方便前端统一读取 session_dir
        if files:
            for filename in files:
                # 将原文件 -》 复制 -》 目标文件中  （copy2 保留原文件修改时间和权限等元数据）
                shutil.copy2(updated_dir_path / filename, session_dir / filename)
            # 构建提示词！告诉大模型，有上传文件，你要读取上传文件！！
            updated_info_prompt = (f"\n    [已上传文件] 已加载到工作目录:\n" +
                             "\n".join([f"    - {f}" for f in files]) +
                             "\n    请优先使用工具（read_file_content）读取并参考这些文件。")

    # 继续准备 1. 当前会话的对应的session_id session_dir 存储到contextVars [后续工具获取，socket -> 推送消息] 2.调用monitor给前端推送session_dir信息
    task_limits = create_task_execution_limits()
    session_dir_token = set_session_context(session_dir_str)  # 存储的当前会话对应的文件夹地址
    session_id_token = set_thread_context(session_id)  #获取当前会话的session_id对应socket
    limits_token = set_task_execution_limits(task_limits)

    monitor.report_session_dir(session_dir_str)  # 当前会话对应的文件夹地址推送给起前端！
    monitor.report_task_started(
        len(task_query),
        reflection_enabled,
        task_limits.max_network_searches,
        task_limits.max_database_queries,
    )
    requested_artifacts = detect_requested_artifacts(task_query)
    baseline_files = snapshot_files(session_dir)

    # 执行main_agent
    config = {
        "configurable":{
            "thread_id":session_id
        }
    }

    # 构建提示词
    path_instruction = f"""
    【工作环境指令】
    工作目录: {relative_session_dir_str}
    {updated_info_prompt}

    规则：
    1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}/filename'
    2. 读取已上传的文件时，请直接将文件名（例如：'开篇.txt'）作为 filename 参数传入（read_file_content）读取工具，不要带上任何目录前缀。
    3. 使用相对路径，禁止使用绝对路径
    4. 若存在上传文件，请先分析内容
    """
    # 反馈结果
    try:
        agent = await initialize_main_agent()

        async def stream_agent(user_content: str):
            """执行一轮 Agent，并延迟上报最终结果以便先验证文件产物。"""
            final_content = None
            async for chunk in agent.astream(
                {"messages": [{"role": "user", "content": user_content}]},
                config=config,
            ):
                # {"model [大模型决定调用工具 子智能体 最终结果] / tools": {messages:[...]}}
                for node_name, state in chunk.items():
                    if not state or "messages" not in state:
                        continue
                    messages = state["messages"]
                    if not messages or not isinstance(messages, list):
                        continue
                    last_msg = messages[-1]
                    if node_name != "model":
                        continue
                    if not last_msg.tool_calls and last_msg.content:
                        final_content = last_msg.content
            return final_content

        final_content = await stream_agent(task_query + path_instruction)

        missing_artifacts = find_missing_artifacts(
            session_dir,
            baseline_files,
            requested_artifacts,
        )
        if missing_artifacts:
            monitor.report_artifact_retry(missing_artifacts)
            recovery_content = build_artifact_recovery_prompt(missing_artifacts)
            recovered_content = await stream_agent(recovery_content + path_instruction)
            final_content = recovered_content or final_content
            missing_artifacts = find_missing_artifacts(
                session_dir,
                baseline_files,
                requested_artifacts,
            )

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        if missing_artifacts:
            missing_formats = "、".join(sorted(missing_artifacts))
            monitor.report_error(
                f"任务未完成：未能生成要求的文件（{missing_formats}）",
                duration_ms,
            )
        elif final_content:
            print(f"主智能体执行结果，最终结果：{final_content[:100]}")
            monitor.report_task_result(final_content, duration_ms)
        else:
            monitor.report_error("任务未完成：主智能体没有返回最终结果", duration_ms)

    except Exception as e :
        # 报错推送错误信息给前端
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        monitor.report_error(f"执行主智能体发生异常：{str(e)}", duration_ms)
    finally:
        # 释放存储的地址和session_id
        reset_session_context(session_dir_token, session_id_token, limits_token)

