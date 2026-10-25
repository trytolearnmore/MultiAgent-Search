import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.ragflow_tools import create_ask_delete, get_assistant_list


class RagflowToolTests(unittest.TestCase):
    @patch("tools.ragflow_tools.monitor")
    @patch("tools.ragflow_tools._get_ragflow_client")
    def test_lists_assistants_and_datasets(self, get_client, _monitor):
        client = get_client.return_value
        client.list_chats.return_value = [
            SimpleNamespace(
                name="helper",
                description="客服知识助手",
                datasets=[{"name": "客服制度"}, SimpleNamespace(name="售后流程")],
            )
        ]

        result = get_assistant_list.invoke({})

        self.assertIn("助手名称:helper", result)
        self.assertIn("客服制度、售后流程", result)

    @patch("tools.ragflow_tools.monitor")
    @patch("tools.ragflow_tools._get_ragflow_client")
    def test_missing_assistant_returns_structured_error(self, get_client, _monitor):
        get_client.return_value.list_chats.return_value = []

        result = json.loads(
            create_ask_delete.invoke({"chat_name": "missing", "question": "问题"})
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "LookupError")

    @patch("tools.ragflow_tools.monitor")
    @patch("tools.ragflow_tools._get_ragflow_client")
    def test_returns_last_cumulative_stream_content_and_cleans_up(
        self, get_client, _monitor
    ):
        session = SimpleNamespace(
            id="session-1",
            ask=MagicMock(
                return_value=[
                    SimpleNamespace(content="客服负责售前"),
                    SimpleNamespace(content="客服负责售前和售后"),
                ]
            ),
        )
        chat = SimpleNamespace(
            name="helper",
            create_session=MagicMock(return_value=session),
            delete_sessions=MagicMock(),
        )
        get_client.return_value.list_chats.return_value = [chat]

        result = create_ask_delete.invoke(
            {"chat_name": "helper", "question": "客服职责是什么"}
        )

        self.assertEqual(result, "客服负责售前和售后")
        chat.delete_sessions.assert_called_once_with(ids=["session-1"])

    @patch("tools.ragflow_tools.monitor")
    @patch("tools.ragflow_tools._get_ragflow_client")
    def test_cleans_up_session_when_ask_fails(self, get_client, _monitor):
        session = SimpleNamespace(
            id="session-2",
            ask=MagicMock(side_effect=TimeoutError("请求超时")),
        )
        chat = SimpleNamespace(
            name="helper",
            create_session=MagicMock(return_value=session),
            delete_sessions=MagicMock(),
        )
        get_client.return_value.list_chats.return_value = [chat]

        result = json.loads(
            create_ask_delete.invoke({"chat_name": "helper", "question": "问题"})
        )

        self.assertEqual(result["error_type"], "TimeoutError")
        chat.delete_sessions.assert_called_once_with(ids=["session-2"])


if __name__ == "__main__":
    unittest.main()
