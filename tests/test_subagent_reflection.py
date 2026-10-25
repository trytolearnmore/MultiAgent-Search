import unittest

from agent.prompts import (
    get_main_agent_content,
    get_subagent_system_prompt,
    is_reflection_enabled,
    main_agent_content,
    sub_agents_content,
)
from agent.subagents.database_query_agent import database_query_agent
from agent.subagents.knowledge_base_agent import knowledge_base_agent
from agent.subagents.network_search_agent import network_search_agent


class SubagentReflectionPromptTests(unittest.TestCase):
    def test_every_subagent_receives_reflection_protocol(self):
        registered_agents = (
            database_query_agent,
            knowledge_base_agent,
            network_search_agent,
        )
        self.assertEqual(len(registered_agents), len(sub_agents_content))

        for agent in registered_agents:
            with self.subTest(agent_name=agent["name"]):
                prompt = agent["system_prompt"]
                self.assertIn("任务完成后的强制自检", prompt)
                self.assertIn("自检结论", prompt)
                self.assertIn("不得编造工具未提供的信息", prompt)
                self.assertIn("【任务结论】", prompt)
                self.assertIn("【关键依据】", prompt)
                self.assertIn("【限制与风险】", prompt)
                self.assertIn("核心文件或网页", prompt)
                self.assertIn("像论文引用一样简洁", prompt)

    def test_original_agent_instructions_are_preserved(self):
        for agent_key, config in sub_agents_content.items():
            with self.subTest(agent_key=agent_key):
                self.assertTrue(
                    get_subagent_system_prompt(agent_key).startswith(
                        config["system_prompt"].rstrip()
                    )
                )

    def test_main_agent_enforces_reflection_quality_gate(self):
        prompt = main_agent_content["system_prompt"]
        self.assertIn("子智能体质量门槛", prompt)
        self.assertIn("缺少自检结论", prompt)
        self.assertIn("不要重复调度同一子智能体", prompt)
        self.assertIn("基于已有结果指出缺口", prompt)
        self.assertIn("已确认子智能体的输出格式。", prompt)
        self.assertIn("基础输出格式和自检要求都通过", prompt)

    def test_reflection_can_be_disabled_without_disabling_other_safeguards(self):
        subagent_prompt = get_subagent_system_prompt("tavily", enabled=False)
        main_prompt = get_main_agent_content(enabled=False)["system_prompt"]

        self.assertNotIn("任务完成后的强制自检", subagent_prompt)
        self.assertNotIn("【自检结论】", subagent_prompt)
        self.assertNotIn("子智能体质量门槛", main_prompt)
        self.assertIn("【统一返回格式】", subagent_prompt)
        self.assertIn("【任务结论】", subagent_prompt)
        self.assertIn("【关键依据】", subagent_prompt)
        self.assertIn("【限制与风险】", subagent_prompt)
        self.assertIn("status=error", subagent_prompt)
        self.assertIn("工具失败处理", main_prompt)
        self.assertIn("子智能体输出格式验收", main_prompt)
        self.assertIn("已确认子智能体的输出格式。", main_prompt)

    def test_reflection_changes_only_the_additional_self_check_requirement(self):
        enabled_prompt = get_main_agent_content(enabled=True)["system_prompt"]
        disabled_prompt = get_main_agent_content(enabled=False)["system_prompt"]

        self.assertIn("【自检结论】", enabled_prompt)
        self.assertNotIn("【自检结论】", disabled_prompt)
        self.assertIn("【任务结论】", enabled_prompt)
        self.assertIn("【任务结论】", disabled_prompt)

    def test_reflection_switch_accepts_common_boolean_values(self):
        for value in ("true", "1", "yes", "on", True):
            with self.subTest(value=value):
                self.assertTrue(is_reflection_enabled(value))
        for value in ("false", "0", "no", "off", False):
            with self.subTest(value=value):
                self.assertFalse(is_reflection_enabled(value))

    def test_reflection_switch_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            is_reflection_enabled("sometimes")


if __name__ == "__main__":
    unittest.main()
