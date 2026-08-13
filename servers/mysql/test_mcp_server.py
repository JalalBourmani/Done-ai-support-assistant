import pytest
from mcp_server import (
    is_safe_query,
    clean_html,
    parse_pma_table,
    parse_total_rows,
    login_timeout,
    query_timeout,
    max_rows,
)

def test_safe_queries():
    assert is_safe_query("SELECT * FROM users") is True
    assert is_safe_query("show tables") is True
    assert is_safe_query("  DESCRIBE products;") is True
    assert is_safe_query("EXPLAIN SELECT * FROM orders") is True
    assert is_safe_query("SELECT id FROM customers -- inline comment") is True
    assert is_safe_query("/* comment */ SELECT name FROM departments") is True

def test_unsafe_queries():
    assert is_safe_query("INSERT INTO users VALUES (1)") is False
    assert is_safe_query("UPDATE users SET admin=1") is False
    assert is_safe_query("DELETE FROM logs") is False
    assert is_safe_query("DROP TABLE users") is False
    assert is_safe_query("ALTER TABLE orders ADD COLUMN test INT") is False
    assert is_safe_query("TRUNCATE TABLE active_sessions") is False

def test_replace_and_insert_allowed_as_functions():
    # These are string functions, not statements. Rejecting them blocked
    # legitimate reporting queries.
    assert is_safe_query("SELECT REPLACE(product_name, ' cm', '') FROM product") is True
    assert is_safe_query("SELECT replace(name,'a','b') FROM t") is True
    assert is_safe_query("SELECT REPLACE (name,'a','b') FROM t") is True
    assert is_safe_query("SELECT INSERT(name, 1, 2, 'x') FROM t") is True

def test_replace_and_insert_still_blocked_as_statements():
    assert is_safe_query("REPLACE INTO t VALUES (1)") is False
    assert is_safe_query("INSERT INTO t VALUES (1)") is False
    # ...and blocked even when smuggled behind a read-only prefix.
    assert is_safe_query("SELECT 1 FROM t UNION REPLACE INTO x VALUES (1)") is False

def test_load_file_blocked():
    # \bLOAD\b does not match inside LOAD_FILE, so it needed its own entry.
    assert is_safe_query("SELECT LOAD_FILE('/etc/passwd')") is False

def test_parse_total_rows_from_showing_rows():
    html = 'Showing rows 0 -  24 (38 total, Query took 0.0016 seconds.)'
    assert parse_total_rows(html) == 38

def test_parse_total_rows_handles_thousands_separator():
    html = 'Showing rows 0 -  24 (1,570 total, Query took 0.5 seconds.)'
    assert parse_total_rows(html) == 1570

def test_parse_total_rows_falls_back_to_unlim_num_rows():
    html = '<a href="export.php?sql_query=SELECT+1&amp;unlim_num_rows=60">Export</a>'
    assert parse_total_rows(html) == 60

def test_parse_total_rows_absent():
    assert parse_total_rows("<table class='table_results'></table>") is None

def test_config_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("PMA_MAX_ROWS", raising=False)
    monkeypatch.delenv("PMA_LOGIN_TIMEOUT", raising=False)
    monkeypatch.delenv("PMA_QUERY_TIMEOUT", raising=False)
    assert max_rows() == 10000
    assert login_timeout() == 120
    assert query_timeout() == 180

    monkeypatch.setenv("PMA_MAX_ROWS", "500")
    assert max_rows() == 500
    # Garbage and non-positive values must not disable the cap.
    monkeypatch.setenv("PMA_MAX_ROWS", "not-a-number")
    assert max_rows() == 10000
    monkeypatch.setenv("PMA_MAX_ROWS", "0")
    assert max_rows() == 10000

def test_clean_html():
    assert clean_html("<p>Hello <strong>World</strong></p>") == "Hello World"
    assert clean_html("   Spacing   \n  test  ") == "Spacing test"

def test_parse_pma_table_standard():
    html = """
    <table class="table_results data ajax">
        <thead>
            <tr>
                <th>test_val</th>
                <th>test_str</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>hello</td>
            </tr>
        </tbody>
    </table>
    """
    res = parse_pma_table(html)
    assert res == [{"test_val": "1", "test_str": "hello"}]

def test_parse_pma_table_with_actions():
    html = """
    <table class="table_results data ajax">
        <thead>
            <tr>
                <th class="column_action print_ignore" colspan="4"></th>
                <th>id</th>
                <th>code</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td class="center print_ignore"><input type="checkbox"/></td>
                <td class="center print_ignore">Edit</td>
                <td class="center print_ignore">Copy</td>
                <td class="center print_ignore">Delete</td>
                <td>10</td>
                <td>abc</td>
            </tr>
        </tbody>
    </table>
    """
    res = parse_pma_table(html)
    assert res == [{"id": "10", "code": "abc"}]

def test_parse_pma_table_with_null():
    html = """
    <table class="table_results data ajax">
        <thead>
            <tr>
                <th>id</th>
                <th>val</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td class="null" data-type="null"><em>NULL</em></td>
            </tr>
        </tbody>
    </table>
    """
    res = parse_pma_table(html)
    assert res == [{"id": "1", "val": None}]

def test_parse_pma_table_empty():
    assert parse_pma_table("no table here") == []
    assert parse_pma_table("<table class='table_results'></table>") == []

def test_parse_pma_table_with_sort_headers():
    html = """
    <table class="table_results data ajax">
        <thead>
            <tr>
                <th class="draggable right" data-column="id"><a href="#">id <img class="asc" /> 1</a></th>
                <th class="draggable right" data-column="val">val</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>10</td>
                <td>abc</td>
            </tr>
        </tbody>
    </table>
    """
    res = parse_pma_table(html)
    assert res == [{"id": "10", "val": "abc"}]

