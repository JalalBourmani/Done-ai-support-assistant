import pytest
from mcp_server import (
    parse_truncated_columns,
    strip_string_literals,
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
    # legitimate reporting queries (see case 46939).
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



# --- Guard: string literals must not be scanned as SQL -------------------
#
# Regression tests for 21.09.2026. The guard used to inspect the raw query
# text, which rejected ordinary reporting queries and — worse — let a write
# slip through. Every case below was measured against the live server.

@pytest.mark.parametrize("query,why", [
    ("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
     "WHERE COLUMN_NAME LIKE '%delete%'",
     "DELETE inside a literal is not a DELETE statement"),
    ("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
     "WHERE COLUMN_NAME LIKE '%update%'",
     "UPDATE inside a literal is not an UPDATE statement"),
    ("SELECT client_name FROM client WHERE client_name LIKE '%Call%'",
     "'%' is a word boundary, so \bCALL\b used to match inside the literal"),
    ("SELECT SUM(request_string LIKE '%\"stockUpdate\";b:1%') n FROM t",
     "a ';' inside a literal was read as a second statement"),
    ("SELECT LOCATE('s:11:\"stock\";', request_string) FROM t",
     "every PHP-serialised column in ProTouch is full of semicolons"),
    ("SELECT id FROM orders WHERE comment LIKE '%kl. 14:30; ferdig%'",
     "so is ordinary Norwegian prose with a time in it"),
    ("SELECT name FROM t WHERE name LIKE '%it''s%'",
     "doubled quote is an escape, not the end of the literal"),
    ("SELECT `delete` FROM t",
     "a backtick identifier is an identifier, not a statement"),
])
def test_literals_are_not_scanned_as_sql(query, why):
    assert is_safe_query(query), why


@pytest.mark.parametrize("gap", [" ", "  ", "\t", "\n", "   \n\t "])
def test_into_outfile_blocked_regardless_of_whitespace(gap):
    """INTO OUTFILE writes to the server filesystem.

    The pattern \bINTO OUTFILE\b matches one literal space, so two spaces, a
    tab or a newline used to walk straight past it. That was a write escaping
    a read-only guard.
    """
    assert not is_safe_query(
        "SELECT * FROM client INTO%sOUTFILE '/tmp/x'" % gap)
    assert not is_safe_query(
        "SELECT * FROM client INTO%sDUMPFILE '/tmp/x'" % gap)


def test_unterminated_quote_rejected():
    """An unclosed quote could hide the rest of the statement inside it."""
    assert not is_safe_query("SELECT ';DROP TABLE client")
    assert not is_safe_query('SELECT "abc')


def test_second_statement_blocked_even_next_to_a_literal():
    assert not is_safe_query("SELECT 'a'; DROP TABLE client")
    assert not is_safe_query("SELECT 1; DROP TABLE client")


def test_single_trailing_semicolon_still_allowed():
    assert is_safe_query("SELECT 1;")
    assert is_safe_query("SELECT client_id FROM client LIMIT 1 ;  ")


def test_strip_string_literals_keeps_skeleton():
    skeleton, balanced = strip_string_literals(
        "SELECT a FROM t WHERE b LIKE '%x;y%' AND c = \"q;r\"")
    assert balanced
    assert ";" not in skeleton, "literals must be blanked out"
    assert "SELECT a FROM t WHERE b LIKE" in skeleton


def test_strip_string_literals_reports_imbalance():
    _, balanced = strip_string_literals("SELECT 'abc")
    assert not balanced


# --- Zero rows is not a parse failure ------------------------------------

def test_empty_result_is_reported_as_zero_rows(monkeypatch):
    """phpMyAdmin's own wording must be recognised.

    It answers "MySQL returned an empty result set (i.e. zero rows)", which
    matched neither "0 rows" nor "Empty result" (case). Every empty result was
    therefore reported as a parse failure — "nothing found" looked exactly like
    "the tool broke". Measured 21.09.2026.
    """
    import mcp_server as M

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"success": True,
                    "message": "MySQL returned an empty result set "
                               "(i.e. zero rows). (Query took 0.0008 sec)"}

    monkeypatch.setattr(M, "get_session", lambda: (None, "tok"))
    monkeypatch.setattr(M.requests.Session, "post",
                        lambda self, *a, **k: _R(), raising=False)

    class _S:
        def post(self, *a, **k):
            return _R()

    monkeypatch.setattr(M, "get_session", lambda: (_S(), "tok"))
    ut = M.execute_query("SELECT 1 FROM client WHERE client_id = -1")
    assert "0 rows returned" in ut
    assert "could not be parsed" not in ut


def test_real_parse_failure_is_flagged_as_unknown(monkeypatch):
    """A genuinely unparseable answer must NOT be read as zero rows."""
    import mcp_server as M

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"success": True, "message": "<div>noe helt annet</div>"}

    class _S:
        def post(self, *a, **k):
            return _R()

    monkeypatch.setattr(M, "get_session", lambda: (_S(), "tok"))
    ut = M.execute_query("SELECT 1")
    assert "UNKNOWN result" in ut
    assert "0 rows returned" not in ut


# --- Cell values must be the real values ---------------------------------

def test_clean_html_decodes_entities():
    """phpMyAdmin escapes cell values; the caller wants the database value.

    A JSON column arrives as {&quot;amount&quot;:&quot;7215.85&quot;}. Without
    decoding, json.loads() fails and a 1 020 character field measures 1 900.
    Measured 21.09.2026.
    """
    assert clean_html("{&quot;amount&quot;:&quot;7215.85&quot;}") == \
        '{"amount":"7215.85"}'
    assert clean_html("Bl&aring;b&aelig;r &amp; fl&oslash;te") == "Blåbær & fløte"
    assert clean_html("a &lt; b &gt; c") == "a < b > c"


def test_parse_pma_table_returns_usable_json_column():
    html_in = """
    <table class="table_results">
    <thead><tr><th>id</th><th>payload</th></tr></thead>
    <tbody><tr>
      <td>7</td>
      <td>{&quot;syncId&quot;:131756724,&quot;isNew&quot;:true}</td>
    </tr></tbody>
    </table>
    """
    import json as _json
    rad = parse_pma_table(html_in)[0]
    assert _json.loads(rad["payload"])["syncId"] == 131756724, \
        "a JSON column must survive the round trip without manual unescaping"


def test_parse_truncated_columns_finds_clipped_cell():
    html_in = """
    <table class="table_results">
    <thead><tr><th class="print_ignore">x</th><th>id</th><th>payload</th></tr></thead>
    <tbody><tr>
      <td class="print_ignore"><input></td>
      <td class="data">7</td>
      <td class="data grid_edit truncated">abc...</td>
    </tr></tbody>
    </table>
    """
    assert parse_truncated_columns(html_in) == ["payload"]


def test_parse_truncated_columns_quiet_when_nothing_clipped():
    html_in = """
    <table class="table_results">
    <thead><tr><th>id</th></tr></thead>
    <tbody><tr><td class="data">7</td></tr></tbody>
    </table>
    """
    assert parse_truncated_columns(html_in) == []
