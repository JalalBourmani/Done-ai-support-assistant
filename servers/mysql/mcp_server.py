import html
import os
import re
import requests
import json
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("MySQL phpMyAdmin Bridge Server")

# Global state for session caching
session = None
token_post = None

# --- Configuration -------------------------------------------------------
#
# phpMyAdmin paginates results at 25 rows by default and says nothing about it:
# the response simply contains 25 rows. Any analysis built on a larger result
# silently reasons about a quarter of the data. We therefore always send an
# explicit session_max_rows, AND verify the returned count against the total
# phpMyAdmin reports, so a cap that is still too low fails loudly.
DEFAULT_MAX_ROWS = 10000

# Login against ws.tellix.no has been measured at 30-38 seconds. The original
# 15 second timeout turned a slow-but-working server into a hard failure.
DEFAULT_LOGIN_TIMEOUT = 120
DEFAULT_QUERY_TIMEOUT = 180


def _int_env(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back on default."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def login_timeout() -> int:
    return _int_env("PMA_LOGIN_TIMEOUT", DEFAULT_LOGIN_TIMEOUT)


def query_timeout() -> int:
    return _int_env("PMA_QUERY_TIMEOUT", DEFAULT_QUERY_TIMEOUT)


def max_rows() -> int:
    return _int_env("PMA_MAX_ROWS", DEFAULT_MAX_ROWS)


def parse_total_rows(html_content: str):
    """
    Total number of rows the query matched, as reported by phpMyAdmin.

    Two independent sources, because this number is the only defence against
    silently truncated results:
      "Showing rows 0 -  24 (38 total, Query took 0.0016 seconds.)"
      "...&unlim_num_rows=38"
    Returns None when neither is present (e.g. a SHOW/DESCRIBE result).
    """
    m = re.search(r"Showing rows\s+[\d,\s]+-\s*[\d,\s]+\s*\(\s*([\d,]+)\s*total",
                  html_content, re.IGNORECASE)
    if not m:
        m = re.search(r"unlim_num_rows=(\d+)", html_content)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", "").replace(" ", ""))
    except ValueError:
        return None

def parse_truncated_columns(html_content: str) -> list:
    """Column names whose values phpMyAdmin clipped, if any.

    A clipped cell carries class="... truncated" on its <td>, and the header
    order tells us which column it belongs to. Returns [] when nothing was
    clipped, which is the normal case once pftext=F is sent.
    """
    table_match = re.search(
        r'<table[^>]*class="[^"]*table_results[^"]*"[^>]*>(.*?)</table>',
        html_content, re.DOTALL)
    if not table_match:
        return []
    table = table_match.group(1)
    if "truncated" not in table:
        return []

    # Header names, in order, skipping phpMyAdmin's own action columns.
    thead = re.search(r'<thead[^>]*>(.*?)</thead>', table, re.DOTALL)
    names = []
    if thead:
        # Capture attributes AND content: print_ignore lives in the attributes,
        # so matching on the content alone let the action column into the list
        # and shifted every index by one.
        for attrs, inner in re.findall(r'<th([^>]*)>(.*?)</th>',
                                       thead.group(1), re.DOTALL):
            if "print_ignore" in attrs:
                continue
            label = clean_html(inner)
            if label:
                names.append(label)

    ramt = set()
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL):
        idx = 0
        for td in re.findall(r'<td([^>]*)>', row):
            if "print_ignore" in td:
                continue
            if "truncated" in td:
                ramt.add(names[idx] if idx < len(names) else "kolonne %d" % idx)
            idx += 1
    return sorted(ramt)


def get_session():
    """Establishes or retrieves the cached phpMyAdmin session and token."""
    global session, token_post
    if session is not None and token_post is not None:
        return session, token_post

    base_url = os.getenv("PMA_URL", "https://ws.tellix.no/phpmyadmin/")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME", "protouch")

    if not db_user or not db_password:
        raise ValueError("DB_USER and DB_PASSWORD environment variables must be set.")

    new_session = requests.Session()

    # 1. Get CSRF token from the login page
    r = new_session.get(base_url + "index.php", timeout=login_timeout())
    token_match = re.search(r'name="token"\s+value="([^"]+)"', r.text)
    token = token_match.group(1) if token_match else None

    payload = {
        'pma_username': db_user,
        'pma_password': db_password,
        'server': '1'
    }
    if token:
        payload['token'] = token

    # Add other hidden fields from the login form
    hidden_inputs = re.findall(r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', r.text)
    for name, val in hidden_inputs:
        if name not in payload:
            payload[name] = val

    # POST login
    r_login = new_session.post(base_url + "index.php", data=payload, timeout=login_timeout())
    
    # Verify login
    logged_in = any(x in r_login.text for x in ["Logg ut", "Logout", "pma_navigation"]) or "database" in r_login.text.lower()
    if not logged_in:
        raise RuntimeError("Login to phpMyAdmin failed. Please check DB_USER and DB_PASSWORD.")

    # 2. Get db_sql.php to extract the query session token
    r_sql = new_session.get(base_url + f"db_sql.php?db={db_name}", timeout=login_timeout())
    
    # Try searching for token in the HTML inputs first, then JS
    token_post_match = re.search(r'name="token"\s+value="([^"]+)"', r_sql.text)
    if not token_post_match:
        token_post_match = re.search(r"token['\"]?\s*[:=]\s*['\"]([a-f0-9]+)['\"]", r_sql.text, re.IGNORECASE)

    if not token_post_match:
        raise RuntimeError("Could not find session query token in db_sql.php")

    session = new_session
    token_post = token_post_match.group(1)
    return session, token_post

def clear_session():
    """Clears the cached session and token."""
    global session, token_post
    session = None
    token_post = None

def strip_string_literals(query: str):
    """Blank out quoted literals and identifiers, keeping the SQL skeleton.

    Returns (skeleton, balanced). The skeleton has every `'...'`, `"..."` and
    `` `...` `` replaced by an empty pair of the same quotes, so the keyword and
    semicolon checks see only real SQL.

    This exists because scanning the raw text rejects ordinary reporting
    queries. Measured 21.09.2026, all four are harmless SELECTs:

        WHERE COLUMN_NAME LIKE '%delete%'      -> DELETE matched inside a literal
        WHERE client_name LIKE '%Call%'        -> CALL matched ('%' is a boundary)
        LIKE '%"stockUpdate";b:1%'             -> the ';' read as a 2nd statement
        WHERE comment LIKE '%kl. 14:30; ok%'   -> same

    The semicolon case is the one that hurts: every PHP-serialised column in
    ProTouch (request_string, pos_settings_string, category_settings_string) is
    full of semicolons, and those are exactly the columns worth querying.

    Blanking literals makes the guard stricter as well as less annoying — a
    keyword hidden in a literal can no longer confuse it in either direction.
    And it removes the incentive to write CONCAT('stock','Upd','ate') to get
    past the check, which is the genuinely dangerous outcome: a guard that
    teaches people to obfuscate SQL protects nothing.
    """
    out = []
    i, n = 0, len(query)
    quote = None
    while i < n:
        c = query[i]
        if quote is None:
            if c in ("'", '"', "`"):
                quote = c
                out.append(c)
            else:
                out.append(c)
            i += 1
            continue
        # inside a literal: consume until the matching close quote
        if c == "\\" and i + 1 < n:
            i += 2                      # backslash escape, e.g. \' or \\
            continue
        if c == quote:
            if i + 1 < n and query[i + 1] == quote:
                i += 2                  # doubled quote escape, e.g. '' or ""
                continue
            out.append(c)
            quote = None
            i += 1
            continue
        i += 1                          # ordinary character inside the literal
    return "".join(out), quote is None


def is_safe_query(query: str) -> bool:
    """Verifies that the query is read-only (SELECT, SHOW, DESCRIBE, EXPLAIN)."""
    # Clean whitespace and comments
    clean_query = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)
    clean_query = re.sub(r'--.*$', '', clean_query, flags=re.MULTILINE)
    clean_query = clean_query.strip().upper()

    if not clean_query:
        return False

    # Analyse the skeleton, never the literals. Execution still uses the
    # original query — only the inspection runs on this copy.
    skeleton, balanced = strip_string_literals(clean_query)
    if not balanced:
        # An unterminated quote is never a valid query, and it would let the
        # rest of the statement hide inside a literal that never closes.
        return False

    # Collapse whitespace runs. Without this, "INTO  OUTFILE" with two spaces
    # walks straight past the \bINTO OUTFILE\b pattern — as do a tab and a
    # newline. Measured 21.09.2026: INTO OUTFILE writes a file to the server
    # filesystem, so that was a write escaping a read-only guard.
    skeleton = re.sub(r"\s+", " ", skeleton).strip()

    # Allow a single trailing semicolon, but reject multiple statements.
    if skeleton.endswith(";"):
        skeleton = skeleton[:-1].strip()
    if ";" in skeleton:
        return False

    # Check if query starts with approved read-only commands
    allowed_commands = ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")
    if not skeleton.startswith(allowed_commands):
        return False

    blocked_keywords = (
        "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
        "GRANT", "REVOKE", "CALL", "LOAD", "LOAD_FILE", "INTO OUTFILE",
        "INTO DUMPFILE", "LOCK", "UNLOCK", "SET",
    )
    if any(re.search(rf"\b{re.escape(keyword)}\b", skeleton) for keyword in blocked_keywords):
        return False

    clean_query = skeleton

    # REPLACE and INSERT are DML statements *and* ordinary string functions.
    # Blocking the bare word rejects perfectly safe reporting queries such as
    # REPLACE(name, ' cm', ''). A function call is always followed by "(", and a
    # statement never is — and since the query must already start with a
    # read-only command and cannot contain a second statement, there is no way
    # to reach "REPLACE INTO" through this path.
    dml_or_function = ("INSERT", "REPLACE")
    return not any(
        re.search(rf"\b{keyword}\b(?!\s*\()", clean_query) for keyword in dml_or_function
    )

def clean_html(text: str) -> str:
    """Strips HTML tags, decodes entities and cleans up whitespace.

    The entity decoding matters more than it looks. phpMyAdmin escapes cell
    values for display, so a JSON column comes back as
    {&quot;amount&quot;:&quot;7215.85&quot;} — six characters for every quote.
    Without decoding, the caller is handed something that reads like the value
    but is not: json.loads() fails, string comparisons miss, and a 1 020
    character field measures 1 900.

    Every consumer had to remember html.unescape() on its own, and forgetting
    it failed quietly. Doing it once, here, is the only place it cannot be
    forgotten.
    """
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_pma_table(html_content: str) -> list:
    """Parses columns and rows from the phpMyAdmin results table HTML."""
    table_match = re.search(r'<table[^>]*class="[^"]*table_results[^"]*"[^>]*>(.*?)</table>', html_content, re.DOTALL)
    if not table_match:
        return []

    table_content = table_match.group(1)

    # 1. Parse Column Headers (TH)
    thead_match = re.search(r'<thead[^>]*>(.*?)</thead>', table_content, re.DOTALL)
    header_html = thead_match.group(1) if thead_match else table_content
    header_trs = re.findall(r'<tr[^>]*>(.*?)</tr>', header_html, re.DOTALL)
    if not header_trs:
        return []
    
    header_tr = header_trs[0]
    # Match both tag attributes and inner content
    ths = re.findall(r'<th([^>]*)>(.*?)</th>', header_tr, re.DOTALL)
    
    headers = []
    for attrs, content in ths:
        # Skip action headers
        if 'print_ignore' in attrs or 'column_action' in attrs:
            continue
        col_match = re.search(r'data-column=["\']([^"\']+)["\']', attrs)
        if col_match:
            headers.append(col_match.group(1))
        else:
            headers.append(clean_html(content))

    # 2. Parse Rows (TD)
    tbody_match = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_content, re.DOTALL)
    tbody_html = tbody_match.group(1) if tbody_match else table_content
    trs = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody_html, re.DOTALL)

    results = []
    for tr in trs:
        # Match both tag attributes and inner content
        tds = re.findall(r'<td([^>]*)>(.*?)</td>', tr, re.DOTALL)
        row_dict = {}
        data_col_idx = 0
        
        for attrs, content in tds:
            # Skip action checkboxes and edit/copy/delete buttons
            if 'print_ignore' in attrs:
                continue
            
            if data_col_idx >= len(headers):
                break
                
            header_name = headers[data_col_idx]
            
            # Check for NULL values
            is_null = False
            if 'data-type="null"' in attrs:
                is_null = True
            else:
                class_match = re.search(r'class=["\']([^"\']+)["\']', attrs)
                if class_match:
                    classes = class_match.group(1).split()
                    if 'null' in classes:
                        is_null = True

            if is_null:
                row_dict[header_name] = None
            else:
                row_dict[header_name] = clean_html(content)
                
            data_col_idx += 1
        if row_dict:
            results.append(row_dict)
            
    return results

@mcp.tool()
def execute_query(sql_query: str, database: str = "") -> str:
    """
    Executes a read-only SQL query on the database.
    Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are permitted.

    Args:
        sql_query: The query to run.
        database: Optional database to run it against, e.g.
            "protouch_client_569_1557578336". Defaults to DB_NAME from
            config.env. ProTouch keeps one database per client, so without
            this every client query would have to fully qualify each table
            name — and information_schema lookups would need TABLE_SCHEMA too.

    Returns a JSON array of row objects.

    EVERY VALUE IS A STRING. The results are scraped from phpMyAdmin's HTML,
    which carries no type information, so COUNT(*) returns "0" and is_active
    returns "1". Note that "0" is truthy in Python and "0" != 0, so cast with
    int()/float() before comparing or summing. Values are deliberately NOT
    coerced here: ProTouch receipt numbers and product numbers have leading
    zeros ("001000000001"), and guessing a type would destroy them.

    If the result had to be truncated, a JSON *object* is returned instead:
    {"truncated": true, "total_rows": N, "returned_rows": M, "warning": "...",
     "rows": [...]}. Treat that as an incomplete answer — narrow the query or
     aggregate in SQL rather than reasoning about the partial rows.

    The same shape with "truncated_columns" means individual values were
    clipped rather than rows dropped.
    """
    if not is_safe_query(sql_query):
        return "Error: Only read-only queries (SELECT, SHOW, DESCRIBE, EXPLAIN) are allowed."

    base_url = os.getenv("PMA_URL", "https://ws.tellix.no/phpmyadmin/")
    db_name = (database or "").strip() or os.getenv("DB_NAME", "protouch")
    # The database name goes into a phpMyAdmin POST field, not into SQL, but a
    # stray quote or slash there would still be nonsense. MySQL identifiers are
    # letters, digits, underscore and dollar.
    if not re.fullmatch(r"[A-Za-z0-9_$]+", db_name):
        return (f"Error: {db_name!r} is not a valid database name. Expected "
                "letters, digits, underscore or dollar only.")

    # Try executing the query (max 2 attempts to handle potential session expiry)
    for attempt in range(2):
        try:
            sess, tok = get_session()
        except Exception as e:
            return f"Authentication Error: {str(e)}"

        query_payload = {
            'is_js_confirmed': '0',
            'db': db_name,
            'token': tok,
            'pos': '0',
            'goto': 'db_sql.php',
            'message_to_show': 'Your SQL query has been executed successfully.',
            'sql_query': sql_query,
            'sql_delimiter': ';',
            'show_query': '1',
            'fk_checks': '1',
            'SQL': 'Go',
            'ajax_request': 'true',
            # Without this, phpMyAdmin returns its default page size of 25 rows
            # and gives no indication that anything was left out.
            'session_max_rows': str(max_rows()),
            # Full column values instead of phpMyAdmin's clipped preview.
            #
            # Measured 21.09.2026: a 1 020-character request_string came back as
            # 68 characters, ending in "..." so the value looked complete. That
            # is 93 % of the content gone, with no flag and no warning — the
            # same failure mode as the 25-row page size, one level down.
            #
            # It forced a whole chunking workaround all week: read the value in
            # 26-character slices with SUBSTRING and a numbers table, then glue
            # them back together. This one field removes all of that.
            'pftext': 'F',
            'display_options[pftext]': 'F',
        }

        try:
            r_query = sess.post(base_url + "import.php", data=query_payload,
                                timeout=query_timeout())
            if r_query.status_code != 200:
                clear_session()
                continue
                
            res = r_query.json()
            if not res.get('success', False):
                err = res.get('error', '')
                if attempt == 0:
                    clear_session()
                    continue
                return f"Database Error: {clean_html(err)} | Full response: {json.dumps(res)}"
            
            message_html = res.get('message', '')
            results = parse_pma_table(message_html)
            if not results:
                # A clean zero-row answer and a failed parse are completely
                # different facts, and this branch used to conflate them:
                # phpMyAdmin says "MySQL returned an empty result set (i.e.
                # zero rows)", which matched neither "0 rows" nor "Empty
                # result" — the latter only by case. So EVERY empty result was
                # reported as a parse failure, and "nothing found" was
                # indistinguishable from "the tool broke".
                clean_msg = clean_html(message_html)
                low = clean_msg.lower()
                empty_markers = (
                    "empty result",        # "returned an empty result set"
                    "zero rows",           # "(i.e. zero rows)"
                    "0 rows",
                    "executed successfully",
                )
                if any(x in low for x in empty_markers):
                    return "Query executed successfully. 0 rows returned."
                return (
                    "Query executed successfully, but the result table could not "
                    f"be parsed — treat this as an UNKNOWN result, not as zero "
                    f"rows. Message: {clean_msg}"
                )

            # Belt and braces on the full-text request above. If a future
            # phpMyAdmin ever ignores pftext, clipped values must not slip
            # through silently a second time.
            clipped = parse_truncated_columns(message_html)
            if clipped:
                return json.dumps({
                    "truncated": True,
                    "truncated_columns": clipped,
                    "returned_rows": len(results),
                    "warning": (
                        "INCOMPLETE VALUES: phpMyAdmin clipped these columns "
                        f"despite the full-text request: {', '.join(clipped)}. "
                        "The strings look complete but are not. Re-read the "
                        "affected column with SUBSTRING in slices, and verify "
                        "each slice against CHAR_LENGTH."
                    ),
                    "rows": results,
                }, indent=2, default=str)

            # Compare against the total phpMyAdmin reports. Returning fewer rows
            # than matched has to be impossible to overlook — a quietly clipped
            # result set reads exactly like a complete one.
            total = parse_total_rows(message_html)
            if total is not None and total > len(results):
                return json.dumps({
                    "truncated": True,
                    "total_rows": total,
                    "returned_rows": len(results),
                    "warning": (
                        f"INCOMPLETE RESULT: the query matched {total} rows but only "
                        f"{len(results)} were returned (row cap {max_rows()}). Do not draw "
                        f"conclusions from these rows. Narrow the query with WHERE, or "
                        f"aggregate with COUNT/GROUP BY, or raise PMA_MAX_ROWS."
                    ),
                    "rows": results,
                }, indent=2, default=str)

            return json.dumps(results, indent=2, default=str)

        except requests.exceptions.JSONDecodeError:
            # Response was not JSON (likely session expired and redirected to login HTML)
            clear_session()
            continue
        except Exception as e:
            return f"HTTP Error: {str(e)}"

    return "Error: Query execution failed after session retries."

if __name__ == "__main__":
    mcp.run()
