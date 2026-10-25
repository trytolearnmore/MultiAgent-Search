import os
from pathlib import Path
from typing import Optional, Tuple

from dotenv import load_dotenv

def _load_ragflow_env() -> Tuple[Optional[str], Optional[str]]:
    """
    加载 RAGFlow 环境变量（优先读取项目根目录 .env，兼容系统环境变量）
    返回值：(api_key, base_url) → 缺失则返回 None
    """
    # rawflow/ 的上一级才是项目根目录。
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    api_key = os.getenv("RAGFLOW_API_KEY")
    base_url = os.getenv("RAGFLOW_API_URL")
    return api_key, base_url
