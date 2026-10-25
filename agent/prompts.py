"""加载并按运行开关组装主、子智能体提示词。"""

import copy
import os
from pathlib import Path

import yaml  # yaml配置文件读取
from dotenv import load_dotenv

# 定义一个加载函数，配置文件yaml加载成字典
def load_yaml(file_path):
    """
    加载指定位置的yaml配置文件
    :param file_path:  加载的文件的地址
    :return:  返回的加载结果 本质就是字典
    """
    with open(file_path, 'r', encoding='utf-8') as f :
        # safe_load 只会加载，不会触发！
        # load 加载过程中可能无意执行内部的嵌入函数！！ 可能发生注入脚本攻击
        return yaml.safe_load(f)

# 尝试读取主和子智能体的配置文件和数据（供后续使用）
# 项目的根地址
# project_root_path  = Path(__file__).parent.parent
project_root_path  = Path(__file__).parents[1]  # prompts -> parents -> [agent, project_root]
yaml_file_path = project_root_path / "prompt" / "prompts.yml"
load_dotenv(project_root_path / ".env")

prompt_yaml_content = load_yaml(yaml_file_path)

# sub_agents_content
sub_agents_content = prompt_yaml_content["sub_agents"]

main_agent_reflection_prompt = prompt_yaml_content["main_agent_reflection_prompt"].strip()
sub_agent_output_prompt = prompt_yaml_content["sub_agent_output_prompt"].strip()
sub_agent_reflection_prompt = prompt_yaml_content["sub_agent_reflection_prompt"].strip()


def is_reflection_enabled(value: str | bool | None = None) -> bool:
    """解析反思开关；无配置时默认开启，非法值直接报错。"""
    if isinstance(value, bool):
        return value

    normalized = (value or os.getenv("ENABLE_REFLECTION", "true")).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        "ENABLE_REFLECTION 仅支持 true/false、1/0、yes/no 或 on/off"
    )


reflection_enabled = is_reflection_enabled()


def get_main_agent_content(enabled: bool | None = None) -> dict:
    """根据开关构建主智能体配置，不修改 YAML 原始对象。"""
    use_reflection = reflection_enabled if enabled is None else enabled
    content = copy.deepcopy(prompt_yaml_content["main_agent"])
    if use_reflection:
        base_prompt = content["system_prompt"].rstrip()
        content["system_prompt"] = f"{base_prompt}\n\n{main_agent_reflection_prompt}\n"
    return content


def get_subagent_system_prompt(agent_key: str, enabled: bool | None = None) -> str:
    """返回基础格式一致、反思协议可切换的子智能体提示词。"""
    use_reflection = reflection_enabled if enabled is None else enabled
    agent_prompt = sub_agents_content[agent_key]["system_prompt"].rstrip()
    prompt_parts = [agent_prompt, sub_agent_output_prompt]
    if use_reflection:
        prompt_parts.append(sub_agent_reflection_prompt)
    return "\n\n".join(prompt_parts) + "\n"


main_agent_content = get_main_agent_content()
