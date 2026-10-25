import tempfile
import unittest
from pathlib import Path

from agent.artifact_guard import (
    build_artifact_recovery_prompt,
    detect_requested_artifacts,
    find_missing_artifacts,
    snapshot_files,
)


class ArtifactGuardTests(unittest.TestCase):
    def test_detects_explicit_markdown_and_pdf_requests(self):
        self.assertEqual(
            detect_requested_artifacts("请生成 Markdown 和 PDF 文件"),
            {".md", ".pdf"},
        )

    def test_defaults_explicit_document_request_to_markdown(self):
        self.assertEqual(
            detect_requested_artifacts("请生成一份市场分析报告"),
            {".md"},
        )

    def test_does_not_require_a_file_for_plain_text_answer(self):
        self.assertEqual(detect_requested_artifacts("简单说说市场趋势"), set())

    def test_only_new_files_satisfy_the_requirement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            session_dir = Path(temp_dir)
            (session_dir / "uploaded.md").write_text("old", encoding="utf-8")
            baseline = snapshot_files(session_dir)

            self.assertEqual(
                find_missing_artifacts(session_dir, baseline, {".md"}),
                {".md"},
            )
            (session_dir / "report.md").write_text("new", encoding="utf-8")
            self.assertEqual(
                find_missing_artifacts(session_dir, baseline, {".md"}),
                set(),
            )

    def test_modified_existing_file_satisfies_the_requirement(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
            session_dir = Path(temp_dir)
            report = session_dir / "report.md"
            report.write_text("old", encoding="utf-8")
            baseline = snapshot_files(session_dir)

            report.write_text("new and longer", encoding="utf-8")
            self.assertEqual(
                find_missing_artifacts(session_dir, baseline, {".md"}),
                set(),
            )

    def test_recovery_prompt_requires_a_real_tool_call(self):
        prompt = build_artifact_recovery_prompt({".md"})
        self.assertIn("必须调用相应的文件生成工具", prompt)
        self.assertIn("不得只输出文档正文", prompt)


if __name__ == "__main__":
    unittest.main()
