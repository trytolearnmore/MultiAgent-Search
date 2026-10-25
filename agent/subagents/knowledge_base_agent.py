from agent.prompts import get_subagent_system_prompt, sub_agents_content
from tools.ragflow_tools import get_assistant_list , create_ask_delete

knowledge_base_agent = {
    "name":sub_agents_content['ragflow']['name'],
    "description":sub_agents_content['ragflow']['description'],
    "system_prompt":get_subagent_system_prompt("ragflow"),
    "tools":[get_assistant_list,create_ask_delete]
}
