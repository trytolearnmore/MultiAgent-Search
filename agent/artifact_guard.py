"""检测显式文件请求，并验证 Agent 是否真正生成了对应产物。"""

import re
from pathlib import Path


def detect_requested_artifacts(task_query: str) -> set[str]:
    """从用户的显式要求中识别需要生成的文件类型。"""
    query = task_query.lower()
    requested: set[str] = set()

    if "markdown" in query or re.search(r"(?:^|\W)md(?:\W|$)", query):
        requested.add(".md")
    if "pdf" in query:
        requested.add(".pdf")

    # 未指定格式但明确要求生成文件/文档时，项目默认产出 Markdown。
    if not requested and re.search(r"(?:生成|创建|写一份).{0,12}(?:文件|文档|报告)", task_query):
        requested.add(".md")

    return requested


def snapshot_files(session_dir: Path) -> dict[Path, tuple[int, int]]:
    """记录文件路径、修改时间和大小，以识别新建或被覆盖的产物。"""
    snapshot = {}
    for path in session_dir.rglob("*"):
        if path.is_file():
            stat = path.stat()
            snapshot[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def find_missing_artifacts(
    session_dir: Path,
    baseline_files: dict[Path, tuple[int, int]],
    requested_extensions: set[str],
) -> set[str]:
    """返回尚未产生新文件的扩展名集合。"""
    current_files = snapshot_files(session_dir)
    created_or_modified_files = {
        path
        for path, metadata in current_files.items()
        if baseline_files.get(path) != metadata
    }
    created_extensions = {path.suffix.lower() for path in created_or_modified_files}
    return requested_extensions - created_extensions


def build_artifact_recovery_prompt(missing_extensions: set[str]) -> str:
    formats = "、".join(sorted(missing_extensions))
    return f"""
【产物完整性检查未通过】
用户明确要求生成 {formats} 文件，但上一轮没有在工作目录产生对应的新文件。
请继续当前任务并复用已经获得的信息，不要重复不必要的检索。现在必须调用相应的文件生成工具，确认工具返回成功后再给出最终答复。不得只输出文档正文或声称文件已经生成。
""".strip()
