import csv
import io
import unittest

from tools.db_tools import (
    _apply_row_limit,
    _fetch_limited_csv,
    _rows_to_csv,
    _validate_read_only_query,
    _validate_table_name,
)


class ReadOnlyQueryValidationTests(unittest.TestCase):
    def test_accepts_select_and_removes_one_trailing_semicolon(self):
        self.assertEqual(_validate_read_only_query(" SELECT 1; "), "SELECT 1")

    def test_accepts_select_cte(self):
        query = "WITH totals AS (SELECT 1 AS value) SELECT value FROM totals"
        self.assertEqual(_validate_read_only_query(query), query)

    def test_keywords_inside_string_literals_are_not_treated_as_commands(self):
        query = "SELECT 'drop table orders' AS message"
        self.assertEqual(_validate_read_only_query(query), query)

    def test_rejects_mutating_statement(self):
        with self.assertRaisesRegex(ValueError, "仅允许执行 SELECT"):
            _validate_read_only_query("DELETE FROM orders")

    def test_rejects_stacked_statement(self):
        with self.assertRaisesRegex(ValueError, "只允许执行一条"):
            _validate_read_only_query("SELECT 1; DROP TABLE orders")

    def test_rejects_select_into_outfile(self):
        with self.assertRaisesRegex(ValueError, "INTO"):
            _validate_read_only_query("SELECT * INTO OUTFILE '/tmp/orders' FROM orders")

    def test_rejects_expensive_sleep_function(self):
        with self.assertRaisesRegex(ValueError, "SLEEP"):
            _validate_read_only_query("SELECT SLEEP(10)")

    def test_rejects_sql_comments(self):
        with self.assertRaisesRegex(ValueError, "不允许包含注释"):
            _validate_read_only_query("SELECT * FROM orders -- bypass")


class TableNameValidationTests(unittest.TestCase):
    def test_accepts_simple_identifier(self):
        self.assertEqual(_validate_table_name("order_items_2026"), "order_items_2026")

    def test_rejects_identifier_injection(self):
        with self.assertRaisesRegex(ValueError, "表名格式不合法"):
            _validate_table_name("orders; DROP TABLE products")


class RowLimitTests(unittest.TestCase):
    def test_appends_limit_to_unbounded_query(self):
        self.assertEqual(_apply_row_limit("SELECT * FROM orders", 100), "SELECT * FROM orders LIMIT 100")

    def test_keeps_safe_top_level_limit(self):
        query = "SELECT * FROM orders LIMIT 20 OFFSET 10"
        self.assertEqual(_apply_row_limit(query, 100), query)

    def test_nested_limit_does_not_replace_top_level_limit(self):
        query = "SELECT * FROM (SELECT * FROM orders LIMIT 5) AS recent_orders"
        self.assertEqual(_apply_row_limit(query, 100), f"{query} LIMIT 100")

    def test_rejects_excessive_limit(self):
        with self.assertRaisesRegex(ValueError, "LIMIT 不能超过 100"):
            _apply_row_limit("SELECT * FROM orders LIMIT 101", 100)


class CsvFormattingTests(unittest.TestCase):
    def test_escapes_commas_quotes_and_newlines(self):
        description = [("id",), ("name",), ("note",)]
        result = _rows_to_csv(description, [(1, 'A, "quoted"', "line1\nline2")])
        parsed = list(csv.reader(io.StringIO(result)))
        self.assertEqual(parsed, [["id", "name", "note"], ["1", 'A, "quoted"', "line1\nline2"]])

    def test_empty_result_is_explicit(self):
        class EmptyCursor:
            description = [("id",), ("customer_name",)]

            @staticmethod
            def fetchall():
                return []

        result = _fetch_limited_csv(EmptyCursor(), 100)
        self.assertEqual(result, "查询成功，共 0 条记录。\n列名：id,customer_name")


if __name__ == "__main__":
    unittest.main()
