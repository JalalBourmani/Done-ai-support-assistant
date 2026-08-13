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

def is_safe_query(query: str) -> bool:
    """Verifies that the query is read-only (SELECT, SHOW, DESCRIBE, EXPLAIN)."""
    # Clean whitespace and comments
    clean_query = re.sub(r'/\*.*?\*/', '', query, flags=re.DOTALL)
    clean_query = re.sub(r'--.*$', '', clean_query, flags=re.MULTILINE)
    clean_query = clean_query.strip().upper()

    if not clean_query:
        return False

    # Allow a single trailing semicolon, but reject multiple statements.
    if clean_query.endswith(";"):
        clean_query = clean_query[:-1].strip()
    if ";" in clean_query:
        return False

    # Check if query starts with approved read-only commands
    allowed_commands = ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")
    if not clean_query.startswith(allowed_commands):
        return False

    blocked_keywords = (
        "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
        "GRANT", "REVOKE", "CALL", "LOAD", "LOAD_FILE", "INTO OUTFILE",
        "INTO DUMPFILE", "LOCK", "UNLOCK", "SET",
    )
    if any(re.search(rf"\b{re.escape(keyword)}\b", clean_query) for keyword in blocked_keywords):
        return False

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
    """Strips HTML tags and cleans up whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
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
def execute_query(sql_query: str) -> str:
    """
    Executes a read-only SQL query on the database.
    Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are permitted.

    Returns a JSON array of row objects.

    If the result had to be truncated, a JSON *object* is returned instead:
    {"truncated": true, "total_rows": N, "returned_rows": M, "warning": "...",
     "rows": [...]}. Treat that as an incomplete answer — narrow the query or
     aggregate in SQL rather than reasoning about the partial rows.
    """
    if not is_safe_query(sql_query):
        return "Error: Only read-only queries (SELECT, SHOW, DESCRIBE, EXPLAIN) are allowed."

    base_url = os.getenv("PMA_URL", "https://ws.tellix.no/phpmyadmin/")
    db_name = os.getenv("DB_NAME", "protouch")

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
                # Could be a successful query with 0 rows
                clean_msg = clean_html(message_html)
                if any(x in clean_msg for x in ["executed successfully", "0 rows", "Empty result"]):
                    return "Query executed successfully. 0 rows returned."
                return f"Query executed successfully, but result table could not be parsed. Message: {clean_msg}"

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
