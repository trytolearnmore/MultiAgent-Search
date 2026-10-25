# 目标： 创建网络搜索子智能体
# 方式1： dict -> deepagents  方式： compiledSubAgent -> langchain langgraph
from agent.prompts import get_subagent_system_prompt, sub_agents_content
from tools.tavily_tool import internet_search


network_search_agent = {
    "name":sub_agents_content['tavily']['name'],
    "description":sub_agents_content['tavily']['description'],
    "system_prompt":get_subagent_system_prompt("tavily"),
    "tools":[internet_search]
}
