import unittest
from pathlib import Path


class FrontendChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index_path = Path(__file__).parents[1] / "api" / "static" / "index.html"
        cls.html = index_path.read_text(encoding="utf-8")

    def test_final_result_is_not_truncated_to_800_characters(self):
        self.assertNotIn("l.data.result.substring(0, 800)", self.html)
        self.assertIn("escapeHtml(l.data.result)", self.html)

    def test_follow_up_reuses_current_thread_id(self):
        self.assertIn("继续当前会话", self.html)
        self.assertIn("sendTask(activeSessionId)", self.html)
        self.assertIn("if (threadId) payload.thread_id = threadId", self.html)
        self.assertIn("body: JSON.stringify(payload)", self.html)

    def test_http_errors_do_not_create_an_undefined_session(self):
        self.assertIn("if (!res.ok)", self.html)
        self.assertIn("if (!data.thread_id)", self.html)


if __name__ == "__main__":
    unittest.main()
