import unittest

from api.server import TaskRequest


class TaskRequestModelTests(unittest.TestCase):
    def test_new_task_can_omit_thread_id(self):
        request = TaskRequest(query="new task")
        self.assertIsNone(request.thread_id)

    def test_new_task_can_send_null_thread_id(self):
        request = TaskRequest(query="new task", thread_id=None)
        self.assertIsNone(request.thread_id)

    def test_follow_up_accepts_existing_thread_id(self):
        request = TaskRequest(query="follow up", thread_id="thread-123")
        self.assertEqual(request.thread_id, "thread-123")


if __name__ == "__main__":
    unittest.main()
