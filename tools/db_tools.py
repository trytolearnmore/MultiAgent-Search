import csv
import io
import os
import re

from dotenv import load_dotenv
from langchain_core.tools import tool
from mysql.connector import Error, connect

from api.context import get_task_execution_limits
from api.monitor import monitor
from utils.tool_result import tool_failure

load_dotenv()


DEFAULT_MAX_ROWS = 100
DEFAULT_MAX_EXECUTION_MS = 5_000
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FORBIDDEN_SQL_KEYWORDS = {
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DO",
    "DROP",
    "GRANT",
    "HANDLER",
    "INSERT",
    "INTO",
    "LOAD",
    "LOCK",
    "RENAME",
    "REPLACE",
    "REVOKE",
    "TRUNCATE",
    "UNLOCK",
    "UPDATE",
}
FORBIDDEN_SQL_FUNCTIONS = {
    "BENCHMARK",
    "GET_LOCK",
    "IS_FREE_LOCK",
    "IS_USED_LOCK",
    "LOAD_FILE",
    "RELEASE_ALL_LOCKS",
    "RELEASE_LOCK",
    "SLEEP",
}


def _positive_int_from_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须是正整数")
    return value


def get_db_config() -> dict:
    """从环境变量读取数据库连接配置。"""
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "collation": os.getenv("MYSQL_COLLATION", "utf8mb4_unicode_ci"),
        "autocommit": False,
        "connection_timeout": int(os.getenv("MYSQL_TIMEOUT", "10")),
        "sql_mode": os.getenv("MYSQL_SQL_MODE", "TRADITIONAL"),
    }
    config = {key: value for key, value in config.items() if value is not None}

    required_keys = ["user", "password", "database"]
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise ValueError(f"缺失数据库核心配置：{', '.join(missing_keys)}")

    return config


def _mask_sql_literals(sql: str) -> str:
    """屏蔽字符串和引用标识符，便于对 SQL 关键字做保守检查。"""
    masked = list(sql)
    quote = None
    index = 0

    while index < len(sql):
        char = sql[index]
        if quote is None:
            if char in {"'", '"', "`"}:
                quote = char
                masked[index] = " "
        else:
            masked[index] = " "
            if char == "\\":
                index += 1
                if index < len(sql):
                    masked[index] = " "
            elif char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                    masked[index] = " "
                else:
                    quote = None
        index += 1

    if quote is not None:
        raise ValueError("SQL 中存在未闭合的引号")
    return "".join(masked)


def _validate_read_only_query(query: str) -> str:
    """只允许单条 SELECT/CTE 查询，并拒绝危险关键字和函数。"""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("SQL 查询不能为空")
    if "\x00" in query:
        raise ValueError("SQL 查询包含非法字符")

    normalized = query.strip()
    masked = _mask_sql_literals(normalized)
    if masked.rstrip().endswith(";"):
        normalized = normalized[:-1].rstrip()
        masked = _mask_sql_literals(normalized)

    if ";" in masked:
        raise ValueError("只允许执行一条 SQL 查询")
    if "--" in masked or "/*" in masked or "*/" in masked or "#" in masked:
        raise ValueError("SQL 查询不允许包含注释")

    first_keyword = re.match(r"\s*([A-Za-z]+)", masked)
    if first_keyword is None or first_keyword.group(1).upper() not in {"SELECT", "WITH"}:
        raise ValueError("仅允许执行 SELECT 查询")

    tokens = {token.upper() for token in re.findall(r"\b[A-Za-z_]+\b", masked)}
    forbidden_keywords = sorted(tokens & FORBIDDEN_SQL_KEYWORDS)
    if forbidden_keywords:
        raise ValueError(f"SQL 包含禁止使用的关键字：{', '.join(forbidden_keywords)}")

    called_functions = {
        match.group(1).upper()
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", masked)
    }
    forbidden_functions = sorted(called_functions & FORBIDDEN_SQL_FUNCTIONS)
    if forbidden_functions:
        raise ValueError(f"SQL 包含禁止使用的函数：{', '.join(forbidden_functions)}")

    if re.search(r"\bFOR\s+UPDATE\b", masked, flags=re.IGNORECASE):
        raise ValueError("SQL 不允许申请写锁")

    return normalized


def _apply_row_limit(query: str, max_rows: int) -> str:
    """追加或校验顶层 LIMIT，确保数据库端限制结果集大小。"""
    masked = _mask_sql_literals(query)
    top_level_limits = []
    depth = 0

    for match in re.finditer(r"[()]|\bLIMIT\b", masked, flags=re.IGNORECASE):
        token = match.group(0).upper()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("SQL 括号不匹配")
        elif depth == 0:
            top_level_limits.append(match)

    if depth != 0:
        raise ValueError("SQL 括号不匹配")
    if not top_level_limits:
        return f"{query} LIMIT {max_rows}"
    if len(top_level_limits) > 1:
        raise ValueError("SQL 包含多个顶层 LIMIT")

    limit_match = top_level_limits[0]
    limit_clause = masked[limit_match.end() :]
    parsed_limit = re.fullmatch(
        r"\s+(\d+)(?:\s*,\s*(\d+)|\s+OFFSET\s+(\d+))?\s*",
        limit_clause,
        flags=re.IGNORECASE,
    )
    if parsed_limit is None:
        raise ValueError("LIMIT 仅支持整数形式，并且必须位于查询末尾")

    row_count = int(parsed_limit.group(2) or parsed_limit.group(1))
    if row_count > max_rows:
        raise ValueError(f"LIMIT 不能超过 {max_rows}")
    return query


def _validate_table_name(table_name: str) -> str:
    """只接受简单 MySQL 标识符，实际存在性另由元数据查询确认。"""
    if not isinstance(table_name, str) or not IDENTIFIER_PATTERN.fullmatch(table_name):
        raise ValueError("表名格式不合法")
    return table_name


def _table_exists(cursor, database: str, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = %s
          AND table_type IN ('BASE TABLE', 'VIEW')
        LIMIT 1
        """,
        (database, table_name),
    )
    return cursor.fetchone() is not None


def _rows_to_csv(description, rows) -> str:
    """使用标准 CSV 转义，正确处理逗号、引号、换行和 NULL。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([column[0] for column in description])
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _fetch_limited_csv(cursor, max_rows: int) -> str:
    if cursor.description is None:
        raise ValueError("查询未返回结果集")
    rows = cursor.fetchall()
    if len(rows) > max_rows:
        raise ValueError(f"查询结果超过 {max_rows} 行")
    if not rows:
        columns = ",".join(column[0] for column in cursor.description)
        return f"查询成功，共 0 条记录。\n列名：{columns}"
    return _rows_to_csv(cursor.description, rows)


@tool
def list_sql_tables() -> str:
    """列出当前数据库中可查询的表和视图。"""
    monitor.report_tool(tool_name="数据库表名查询工具：list_sql_tables", args={})
    try:
        config = get_db_config()
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type IN ('BASE TABLE', 'VIEW')
                    ORDER BY table_name
                    """,
                    (config["database"],),
                )
                tables = cursor.fetchall()
                if not tables:
                    return "没有可用的表"
                return f"可用的表有：{', '.join(table[0] for table in tables)}"
    except (Error, TypeError, ValueError) as error:
        return tool_failure("list_sql_tables", error)


@tool
def get_table_data(table_name: str) -> str:
    """安全地预览指定表，最多返回配置的行数。"""
    monitor.report_tool(
        tool_name="数据库表数据查询工具：get_table_data",
        args={"table_name": table_name},
    )
    try:
        safe_table_name = _validate_table_name(table_name)
        max_rows = _positive_int_from_env("MYSQL_QUERY_MAX_ROWS", DEFAULT_MAX_ROWS)
        config = get_db_config()
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                if not _table_exists(cursor, config["database"], safe_table_name):
                    raise ValueError(f"数据表不存在或不可访问：{safe_table_name}")
                cursor.execute(f"SELECT * FROM `{safe_table_name}` LIMIT {max_rows}")
                return _fetch_limited_csv(cursor, max_rows)
    except (Error, TypeError, ValueError) as error:
        return tool_failure("get_table_data", error)


@tool
def execute_sql_query(query: str) -> str:
    """在只读事务中执行单条 SELECT/CTE 查询，并限制时间和返回行数。"""
    limits = get_task_execution_limits()
    if limits is not None:
        allowed, used = limits.try_consume_database_query()
        if not allowed:
            return tool_failure(
                "execute_sql_query",
                f"单任务自定义 SQL 查询硬上限为 {limits.max_database_queries} 次，当前已使用 {used} 次",
                error_type="DatabaseQueryLimitExceeded",
                retryable=False,
                guidance="停止继续查询，使用已有结果作答；若精确查询为空，应明确告知未找到记录。",
            )

    monitor.report_tool(
        tool_name="数据库表数据查询工具：execute_sql_query",
        args={"query": query},
    )
    try:
        safe_query = _validate_read_only_query(query)
        max_rows = _positive_int_from_env("MYSQL_QUERY_MAX_ROWS", DEFAULT_MAX_ROWS)
        limited_query = _apply_row_limit(safe_query, max_rows)
        max_execution_ms = _positive_int_from_env(
            "MYSQL_QUERY_MAX_EXECUTION_MS",
            DEFAULT_MAX_EXECUTION_MS,
        )
        config = get_db_config()

        with connect(**config) as conn:
            conn.start_transaction(readonly=True)
            try:
                with conn.cursor() as cursor:
                    cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {max_execution_ms}")
                    cursor.execute(limited_query)
                    return _fetch_limited_csv(cursor, max_rows)
            finally:
                conn.rollback()
    except (Error, TypeError, ValueError) as error:
        return tool_failure("execute_sql_query", error)


if __name__ == "__main__":
    print(execute_sql_query.invoke({"query": "SELECT * FROM orders WHERE category = '数码电子'"}))
